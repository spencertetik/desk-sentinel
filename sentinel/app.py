from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import threading
import time

import cv2
import uvicorn

from sentinel.activity import ActivityDetector, roi_motion
from sentinel.backup import backup_db
from sentinel.briefing import (
    compose_morning,
    compose_wind_down,
    fetch_ai_headlines,
    fetch_weather,
)
from sentinel.calibration import aggregate_baseline, load_baseline, save_baseline
from sentinel.capture import RtspCapture
from sentinel.classify import Posture, Status, classify
from sentinel.config import load_config
from sentinel.events import Event, EventEngine
from sentinel.feedback import compose_status_message
from sentinel.metrics import compute_posture, RawPosture
from sentinel.nudges import Nudger
from sentinel.overlay import draw_overlay
from sentinel.pose import PoseEstimator
from sentinel.server import create_app
from sentinel.state import SharedState
from sentinel.store import Store

log = logging.getLogger("desk_sentinel.app")


def _encode(frame, width: int) -> bytes:
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, int(h * width / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def run_calibration(cap, pose, cfg, seconds: float = 3.0):
    print(f"Calibration: sit up straight for {seconds:.0f}s...")
    samples, end = [], time.time() + seconds
    while time.time() < end:
        frame = cap.get_latest()
        if frame is not None:
            lms = pose.estimate(frame)
            if lms is not None:
                samples.append(compute_posture(lms, cfg.thresholds.min_visibility))
        time.sleep(0.1)
    baseline = aggregate_baseline(samples)
    save_baseline(cfg.baseline_path, baseline)
    print(f"Saved baseline: {baseline}")


def _yesterday_range(now: float) -> tuple[float, float]:
    """Return (start_ts, end_ts) for yesterday in local time."""
    lt = time.localtime(now)
    today_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    yesterday_start = today_start - 86400
    return yesterday_start, today_start


def _fired_today(store: Store, now: float, event_type: str) -> bool:
    """True if an event of this type was already logged today (local) — a
    restart-proof once-per-day guard backed by the events table."""
    lt = time.localtime(now)
    today_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    try:
        return any(e.get("type") == event_type for e in store.recent_events(today_start))
    except Exception:
        return False


def _dispatch_morning_briefing(store: Store, cfg, nudger, now: float) -> None:
    """Gather stats, fetch network data, compose, and speak the morning brief.

    Runs in a worker thread so the ~1Hz main loop is not blocked.
    Network fetches are best-effort: missing pieces are gracefully omitted.
    """
    mb = cfg.nudges.morning_brief

    # --- Yesterday's desk stats ---
    recap = None
    if mb.include_recap:
        ystart, yend = _yesterday_range(now)
        try:
            summary = store.daily_summary(since_ts=ystart)
            pq = store.posture_quality(since_ts=ystart)
            present_s = summary["present_samples"]
            good_pct = pq["good_pct"] if pq["samples"] > 0 else None
            recap = {
                "desk_hours": present_s / 3600.0,
                "good_pct": good_pct,
            }
        except Exception as exc:
            log.warning("morning_briefing: recap gather failed: %s", exc)

    # --- Weather ---
    weather = None
    if mb.include_weather:
        try:
            weather = fetch_weather(location=mb.weather_location, timeout=4.0)
        except Exception as exc:
            log.warning("morning_briefing: weather fetch failed: %s", exc)

    # --- AI headlines ---
    headlines: list[str] = []
    if mb.include_news:
        try:
            headlines = fetch_ai_headlines(
                query=mb.news_query,
                n=mb.headline_count,
                timeout=4.0,
            )
        except Exception as exc:
            log.warning("morning_briefing: headlines fetch failed: %s", exc)

    message = compose_morning(weather=weather, headlines=headlines, recap=recap)
    if not message.strip() or message.strip() == "Good morning.":
        pass

    brief_event = Event("morning_arrival", now, message)
    store.add_event(brief_event)
    if nudger is not None:
        nudger.dispatch(brief_event, now)


def processing_loop(cap, pose, store, state, cfg, stop: threading.Event, engine, nudger):
    baseline = load_baseline(cfg.baseline_path)
    interval = 1.0 / max(cfg.stream.capture_fps, 1)
    sit_start = None
    last_log = 0.0

    # ── Seat-zone gate ────────────────────────────────────────────────────
    # Resolve the zone the user actually sits in: an explicit config override
    # wins, else the zone learned during --calibrate. Without one, the gate is
    # off and any pose anywhere in the frame counts (legacy behavior).
    seat_roi = None
    if cfg.presence.gate_enabled:
        if cfg.presence.seat_roi:
            seat_roi = tuple(cfg.presence.seat_roi)
        elif baseline is not None and baseline.seat_roi:
            seat_roi = tuple(baseline.seat_roi)
    if seat_roi:
        log.info("Presence seat-zone gate active: %s", seat_roi)
    else:
        log.warning(
            "Presence seat-zone gate OFF — no seat_roi configured or calibrated. "
            "Recalibrate (python -m sentinel.app --calibrate) or set presence.seat_roi."
        )
    _prev_present = None

    # ── Activity detection state ──────────────────────────────────────────
    # prev_roi_gray: grayscale crop of the ORIGINAL frame (not pose-downscaled)
    # so that ROI pixel coordinates are consistent with cfg.activity.roi.
    prev_roi_gray = None
    last_activity_ts = 0.0
    active = False
    # Sample activity motion over a ~0.4s window (not per-frame): at 15fps a
    # consecutive-frame diff is too short — typing barely registers and ambient
    # body motion dominates. Over ~0.4s, typing motion clearly exceeds idle.
    _ACTIVITY_SAMPLE_S = 0.4
    detector = None
    _roi_warned = False
    if cfg.activity.enabled:
        detector = ActivityDetector(
            enter=cfg.activity.enter_threshold,
            exit=cfg.activity.exit_threshold,
            idle_grace_s=cfg.activity.idle_grace_seconds,
            ema_alpha=cfg.activity.ema_alpha,
        )

    while not stop.is_set():
        frame = cap.get_latest()
        if frame is None:
            state.update(b"", classify_away(), cap.is_healthy(), 0.0)
            time.sleep(interval)
            continue

        # Pose estimation uses a downscaled copy; motion detection uses original.
        w = cfg.stream.pose_downscale_width
        h_orig, w_orig = frame.shape[:2]
        if w_orig > w:
            pose_frame = cv2.resize(frame, (w, int(h_orig * w / w_orig)))
        else:
            pose_frame = frame

        lms = pose.estimate(pose_frame)
        raw = compute_posture(lms, cfg.thresholds.min_visibility, seat_roi=seat_roi) if lms else _absent()
        status = classify(raw, baseline, cfg.thresholds)

        # Log presence transitions (low-volume) so the gate is auditable: when
        # someone appears we record where their shoulder sat in the frame.
        if raw.present != _prev_present:
            log.info(
                "presence -> %s (shoulder_x=%.2f)",
                "PRESENT" if raw.present else "absent", raw.shoulder_x,
            )
            _prev_present = raw.present

        now = time.time()
        sit_start, sitting = advance_sit_timer(sit_start, status.posture, now)

        # ── Activity detection ────────────────────────────────────────────
        if detector is not None:
            try:
                if status.posture is Posture.AWAY:
                    # Reset on every away tick so stale grace-timer state
                    # does not carry forward to the next presence session.
                    detector.reset()
                    prev_roi_gray = None
                    last_activity_ts = 0.0
                    active = False
                elif now - last_activity_ts >= _ACTIVITY_SAMPLE_S:
                    # Sample at ~0.4s intervals: compare to the frame from the
                    # previous sample, not the consecutive 66ms frame.
                    cur_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    motion = (
                        roi_motion(prev_roi_gray, cur_gray, cfg.activity.roi)
                        if prev_roi_gray is not None
                        else 0.0
                    )
                    prev_roi_gray = cur_gray
                    last_activity_ts = now
                    active = detector.update(motion, now)
                # between samples: keep the previous `active` value
                status = dataclasses.replace(status, active=active)
            except Exception as exc:
                if not _roi_warned:
                    log.warning("Activity detection error (suppressing further): %s", exc)
                    _roi_warned = True

        # Overlay: draw ROI rectangle when activity is enabled
        roi_for_overlay = cfg.activity.roi if cfg.activity.enabled else None
        annotated = draw_overlay(frame, lms, status, roi=roi_for_overlay)
        state.update(_encode(annotated, cfg.server.stream_width), status, cap.is_healthy(), sitting)

        if now - last_log >= 1.0:  # downsample to ~1 Hz
            store.add_sample(now, status)
            last_log = now

        for event in engine.update(status, now):
            # Enrich message for stats-based events before storing/speaking
            if event.type in ("returned", "periodic_checkin"):
                t = time.localtime(now)
                today_start = time.mktime(
                    (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)
                )
                pq = store.posture_quality(since_ts=today_start)
                summary = store.daily_summary(since_ts=today_start)
                stats = {
                    "desk_minutes": summary["present_samples"] // 60,
                    "good_pct": pq["good_pct"] if pq["samples"] > 0 else None,
                    "breaks": summary["breaks"],
                }
                event = Event(
                    event.type, event.ts, compose_status_message(event.type, stats)
                )
                store.add_event(event)
                if nudger is not None:
                    nudger.dispatch(event, now)

            elif event.type == "morning_arrival":
                # Persistent once-per-day guard: the engine's guard is in-memory
                # and resets on restart, so check the events table too.
                if cfg.nudges.morning_brief.enabled and not _fired_today(store, now, "morning_arrival"):
                    threading.Thread(
                        target=_dispatch_morning_briefing,
                        args=(store, cfg, nudger, now),
                        daemon=True,
                    ).start()

            elif event.type == "wind_down":
                if cfg.nudges.wind_down.enabled and not _fired_today(store, now, "wind_down"):
                    message = compose_wind_down()
                    wd_event = Event("wind_down", event.ts, message)
                    store.add_event(wd_event)
                    if nudger is not None:
                        nudger.dispatch(wd_event, now)

            else:
                store.add_event(event)
                if nudger is not None:
                    nudger.dispatch(event, now)

        time.sleep(interval)


def advance_sit_timer(sit_start, posture: Posture, now: float) -> tuple:
    """Update the continuous-sitting timer. Returns (new_sit_start, sitting_seconds)."""
    if posture is Posture.AWAY:
        return None, 0.0
    if sit_start is None:
        sit_start = now
    return sit_start, now - sit_start


def _absent():
    return RawPosture(0.0, 0.0, 0.0, present=False, side="none")


def classify_away():
    return Status(Posture.AWAY, 0.0, 0.0, 0.0)


def main():
    # Surface our own INFO logs (gate status, presence transitions) to the
    # launchd log without enabling noisy third-party INFO output.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("desk_sentinel").setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cap = RtspCapture(cfg.stream.rtsp_url, cfg.stream.capture_fps).start()
    pose = PoseEstimator()
    time.sleep(3)  # let the stream warm up

    if args.calibrate:
        run_calibration(cap, pose, cfg)

    # ------------------------------------------------------------------
    # DB path resolution + legacy auto-move
    # ------------------------------------------------------------------
    db_path = os.path.expanduser(cfg.db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    legacy_path = "desk_sentinel.db"
    if not os.path.exists(db_path) and os.path.exists(legacy_path):
        log.info(
            "Legacy DB found at %s — moving to %s", legacy_path, db_path
        )
        try:
            shutil.move(legacy_path, db_path)
        except OSError as exc:
            log.warning("Could not move legacy DB: %s", exc)

    store = Store(db_path)
    state = SharedState()
    stop = threading.Event()

    engine = EventEngine(
        break_after_seconds=cfg.nudges.break_after_seconds,
        poor_posture_seconds=cfg.nudges.poor_posture_seconds,
        debounce_seconds=cfg.nudges.debounce_seconds,
        posture_slip_seconds=cfg.nudges.posture_slip_seconds,
        good_streak_seconds=cfg.nudges.good_streak_seconds,
        checkin_interval_seconds=cfg.nudges.checkin_interval_seconds,
        morning_after_hour=cfg.nudges.morning_brief.after_hour,
        work_end_hour=cfg.nudges.work_end_hour,
        wind_down_lead_minutes=cfg.nudges.wind_down.lead_minutes,
    )
    nudger = Nudger(
        work_start_hour=cfg.nudges.work_start_hour,
        work_end_hour=cfg.nudges.work_end_hour,
        cooldown_seconds=cfg.nudges.cooldown_seconds,
        default_cooldown_seconds=cfg.nudges.default_cooldown_seconds,
        speak_volume=cfg.nudges.speak_volume,
    ) if cfg.nudges.enabled else None

    worker = threading.Thread(
        target=processing_loop,
        args=(cap, pose, store, state, cfg, stop, engine, nudger),
        daemon=True,
    )
    worker.start()

    from sentinel.voice.llm import warm_up

    def _warm_loop():
        # Re-warm every 20 min (< the 1h keep-alive) so the voice model stays
        # resident and questions never pay the ~40s cold-load after idle.
        while not stop.is_set():
            warm_up(cfg.voice.ollama_model, cfg.voice.ollama_url)
            stop.wait(1200)

    threading.Thread(target=_warm_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Capture watchdog: if the feed wedges and the in-thread reconnect can't
    # recover it within the grace window, exit so the supervisor (launchd
    # KeepAlive) restarts a clean process. KeepAlive only catches a *dead*
    # process, not a hung-but-serving one — this turns a wedge into an exit.
    # ------------------------------------------------------------------
    def _capture_watchdog(grace: float = 45.0):
        while not stop.wait(10.0):
            age = cap.frame_age()
            if age > grace:
                log.error("capture stale %.0fs (>%.0fs) — exiting for supervised restart", age, grace)
                os._exit(1)

    threading.Thread(target=_capture_watchdog, daemon=True).start()

    # ------------------------------------------------------------------
    # Backup daemon loop
    # ------------------------------------------------------------------
    if cfg.backup.enabled:
        def _backup_loop():
            # Run immediately on startup, then every interval_hours
            backup_db(db_path, cfg.backup.dest_dir, keep=cfg.backup.keep)
            interval_s = cfg.backup.interval_hours * 3600
            while not stop.is_set():
                stop.wait(interval_s)
                if not stop.is_set():
                    backup_db(db_path, cfg.backup.dest_dir, keep=cfg.backup.keep)

        threading.Thread(target=_backup_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Rollup daemon — back-fill past days + midnight ticker
    # ------------------------------------------------------------------
    def _rollup_loop():
        work_start = cfg.nudges.work_start_hour
        work_end = cfg.nudges.work_end_hour

        def _yesterday_date_str() -> str:
            lt = time.localtime()
            # yesterday = today_start - 1 day
            today_start = time.mktime(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)
            )
            return time.strftime("%Y-%m-%d", time.localtime(today_start - 86400))

        def _today_date_str() -> str:
            return time.strftime("%Y-%m-%d")

        def _date_range(start: str, end_exclusive: str) -> list[str]:
            """All YYYY-MM-DD strings in [start, end_exclusive)."""
            dates = []
            t = time.strptime(start, "%Y-%m-%d")
            current_ts = time.mktime(
                (t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)
            )
            end_t = time.strptime(end_exclusive, "%Y-%m-%d")
            end_ts = time.mktime(
                (end_t.tm_year, end_t.tm_mon, end_t.tm_mday, 0, 0, 0, 0, 0, -1)
            )
            while current_ts < end_ts:
                dates.append(time.strftime("%Y-%m-%d", time.localtime(current_ts)))
                current_ts += 86400
            return dates

        # Back-fill: roll up every complete past day that has data
        try:
            earliest = store.earliest_data_date()
            today = _today_date_str()
            if earliest and earliest < today:
                for date_str in _date_range(earliest, today):
                    try:
                        store.rollup_day(date_str, work_start, work_end)
                    except Exception as exc:
                        log.warning("rollup back-fill failed for %s: %s", date_str, exc)
        except Exception as exc:
            log.warning("rollup back-fill error: %s", exc)

        # Midnight ticker: once "yesterday" rolls over, rollup it
        while not stop.is_set():
            # Sleep until ~1 minute past next local midnight
            lt = time.localtime()
            today_start = time.mktime(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)
            )
            next_midnight = today_start + 86400 + 60  # 00:01 tomorrow
            sleep_s = max(60.0, next_midnight - time.time())
            stop.wait(sleep_s)
            if not stop.is_set():
                ydate = _yesterday_date_str()
                try:
                    store.rollup_day(ydate, work_start, work_end)
                    log.info("rollup: rolled up %s", ydate)
                except Exception as exc:
                    log.warning("rollup midnight tick failed for %s: %s", ydate, exc)

    threading.Thread(target=_rollup_loop, daemon=True).start()

    app = create_app(state, static_dir="web", store=store, presence_cfg=cfg.presence, voice_cfg=cfg.voice)
    print(f"Dashboard: http://{cfg.server.host}:{cfg.server.port}")
    try:
        uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="warning")
    finally:
        stop.set()
        cap.stop()
        pose.close()
        store.close()


if __name__ == "__main__":
    main()
