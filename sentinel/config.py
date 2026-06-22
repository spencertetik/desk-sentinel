from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class StreamConfig(BaseModel):
    rtsp_url: str
    capture_fps: int = 8
    pose_downscale_width: int = 960


class Thresholds(BaseModel):
    forward_head_margin_deg: float = 12.0
    trunk_margin_deg: float = 10.0
    min_visibility: float = 0.5
    # Head-drop (normalized image-height units) below the calibrated neutral that
    # marks a forward lean / slouch. This is the primary seated-posture signal
    # because hips are occluded by the desk. ~0.04 ≈ a clear forward lean.
    head_drop_margin: float = 0.04
    # absolute fallbacks used when no calibration baseline exists
    abs_forward_head_deg: float = 35.0
    abs_trunk_lean_deg: float = 25.0


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8088
    stream_width: int = 960


class MorningBriefConfig(BaseModel):
    enabled: bool = True
    after_hour: float = 5.0          # don't fire before this local hour (avoids 3am trips)
    include_weather: bool = True
    include_news: bool = True
    include_recap: bool = True
    weather_location: str | None = None   # None = IP-based
    news_query: str = "artificial intelligence"
    headline_count: int = 2


class WindDownConfig(BaseModel):
    enabled: bool = True
    lead_minutes: int = 30           # fire this many minutes before work_end_hour


class NudgeConfig(BaseModel):
    enabled: bool = True
    break_after_seconds: int = 3600
    poor_posture_seconds: int = 300
    # Coach v2 — presence debounce + new event thresholds
    debounce_seconds: int = 4
    posture_slip_seconds: int = 90
    good_streak_seconds: int = 1200
    checkin_interval_seconds: int = 3600
    # Work-hours window (fractional hours, e.g. 8.5 = 8:30am, 17.5 = 5:30pm)
    work_start_hour: float = 8.5
    work_end_hour: float = 17.5
    speak_volume: int | None = 50   # set macOS output volume before speaking; None = leave untouched
    cooldown_seconds: dict[str, int] = {
        "break_due": 600,
        "poor_posture_sustained": 600,
        "returned": 300,
        "posture_slipping": 300,
        "posture_good_streak": 1800,
        "periodic_checkin": 3000,
        "morning_arrival": 3600,
        "wind_down": 3600,
    }
    default_cooldown_seconds: int = 300
    morning_brief: MorningBriefConfig = MorningBriefConfig()
    wind_down: WindDownConfig = WindDownConfig()


class PresenceConfig(BaseModel):
    work_start_hour: float = 8.5
    work_end_hour: float = 17.5
    gap_merge_seconds: int = 20
    min_session_seconds: int = 30
    trend_days: int = 14
    history_days: int = 30
    # Seat-zone gate: only count a person as "present" when their shoulder is
    # inside the zone where you actually sit, so the camera ignores other
    # furniture in view (an empty chair across the room, etc.).
    gate_enabled: bool = True
    # Manual override of the seat zone (normalized [x0, y0, x1, y1]). When null,
    # the zone learned during `--calibrate` (stored in baseline.json) is used.
    seat_roi: list[float] | None = None


class VoiceConfig(BaseModel):
    hotkey: str = "<cmd>+<alt>+d"
    whisper_model: str = "base.en"
    ollama_model: str = "llama3.1:8b"
    ollama_url: str = "http://localhost:11434"
    max_record_seconds: float = 15.0
    silence_timeout: float = 1.2



class ActivityConfig(BaseModel):
    enabled: bool = True
    # Normalised keyboard/desk ROI [x0, y0, x1, y1]; controller tunes live via overlay.
    roi: list[float] = [0.15, 0.78, 0.95, 1.0]
    # Motion thresholds (mean abs pixel diff on grayscale ROI crop).
    # enter > exit ensures hysteresis; controller tunes against the real feed.
    enter_threshold: float = 3.0
    exit_threshold: float = 1.5
    idle_grace_seconds: float = 8.0   # seconds below exit before flipping idle
    ema_alpha: float = 0.3            # EMA smoothing (0=no response, 1=no smoothing)

class BackupConfig(BaseModel):
    enabled: bool = True
    dest_dir: str = "~/desk-sentinel-backups"  # point at an external drive/NAS if you have one
    keep: int = 14
    interval_hours: float = 24.0


class Config(BaseModel):
    stream: StreamConfig
    thresholds: Thresholds = Thresholds()
    server: ServerConfig = ServerConfig()
    nudges: NudgeConfig = NudgeConfig()
    presence: PresenceConfig = PresenceConfig()
    voice: VoiceConfig = VoiceConfig()
    activity: ActivityConfig = ActivityConfig()
    db_path: str = "~/.desk-sentinel/desk_sentinel.db"
    baseline_path: str = "baseline.json"
    backup: BackupConfig = BackupConfig()


def load_config(path: str | Path) -> Config:
    data = yaml.safe_load(Path(path).read_text())
    return Config(**data)
