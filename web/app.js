const $ = (id) => document.getElementById(id);

const LABEL = {
  good:         "Good posture",
  forward_head: "Forward head",
  slouching:    "Slouching",
  away:         "Away",
};

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/live`);

  ws.onmessage = (ev) => {
    const d = JSON.parse(ev.data);

    document.body.dataset.posture = d.posture;

    $("posture").textContent = LABEL[d.posture] ?? d.posture.replace(/_/g, " ");
    $("fh").textContent       = d.forward_head_deg;
    $("head-drop").textContent = d.head_drop !== undefined ? Math.round(d.head_drop * 100) : "—";
    $("sitting").textContent  = Math.round(d.sitting_seconds / 60);

    const h = $("health");
    h.textContent = d.healthy ? "live" : "stream down";
    h.className   = "badge " + (d.healthy ? "ok" : "bad");

    // Mute button — reflect server-authoritative mute state + countdown
    updateMute(d.muted, d.mute_remaining_s);

    // Activity chip — only meaningful when present
    const chip = $("activity-chip");
    if (chip) {
      if (d.posture === "away") {
        chip.textContent = "—";
        chip.dataset.state = "away";
      } else if (d.active) {
        chip.textContent = "Active";
        chip.dataset.state = "active";
      } else {
        chip.textContent = "Idle";
        chip.dataset.state = "idle";
      }
    }
  };

  ws.onclose = () => setTimeout(connect, 1500);
}

connect();

// ── Mute button ─────────────────────────────────────────────────────────
function fmtRemaining(s) {
  if (!s || s <= 0) return "";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${String(m % 60).padStart(2, "0")}m`;
}

function updateMute(muted, remainingS) {
  const btn = $("mute-btn");
  const label = $("mute-label");
  if (!btn || !label) return;
  btn.dataset.muted = muted ? "true" : "false";
  btn.setAttribute("aria-pressed", muted ? "true" : "false");
  if (muted) {
    const r = fmtRemaining(remainingS);
    label.textContent = r ? `Muted · ${r}` : "Muted";
    btn.setAttribute("aria-label", "Nudges muted — click to unmute");
  } else {
    label.textContent = "Mute";
    btn.setAttribute("aria-label", "Mute nudges during meetings");
  }
}

(function () {
  const btn = $("mute-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const muted = btn.dataset.muted === "true";
    const endpoint = muted ? "/api/unmute" : "/api/mute";
    // Optimistic flip for snappy feedback; the WebSocket reconciles shortly.
    updateMute(!muted, muted ? 0 : 120 * 60);
    try {
      const r = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: muted ? null : JSON.stringify({ minutes: 120 }),
      });
      const d = await r.json();
      updateMute(d.muted, d.mute_remaining_s);
    } catch (e) {
      // Revert on failure
      updateMute(muted, 0);
    }
  });
})();

async function refreshHistory() {
  try {
    const r = await fetch("/api/history");
    const d = await r.json();
    const s = d.summary || {};
    if (s.slouch_pct !== undefined) document.getElementById("slouch-pct").textContent = s.slouch_pct + "%";
    if (s.breaks !== undefined) document.getElementById("breaks").textContent = s.breaks;
    if (s.present_samples !== undefined) document.getElementById("present-min").textContent = Math.round(s.present_samples / 60);
    const tl = document.getElementById("timeline");
    tl.innerHTML = "";
    const events = (d.events || []).slice(-12).reverse();
    if (events.length === 0) {
      const li = document.createElement("li");
      li.className = "event event-empty";
      li.textContent = "No events yet today";
      tl.appendChild(li);
      return;
    }
    events.forEach((e) => {
      const li = document.createElement("li");
      li.className = "event " + e.type;
      const t = new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const tSpan = document.createElement("span");
      tSpan.className = "t";
      tSpan.textContent = t;
      const mSpan = document.createElement("span");
      mSpan.className = "m";
      mSpan.textContent = e.message || e.type.replace(/_/g, " ");
      li.appendChild(tSpan);
      li.appendChild(mSpan);
      tl.appendChild(li);
    });
  } catch (_) { /* non-fatal */ }
}
refreshHistory();
setInterval(refreshHistory, 5000);

// ─────────────────────────────────────────────────────────────────────────────
// PRESENCE INSIGHTS
// ─────────────────────────────────────────────────────────────────────────────

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v);
  }
  return el;
}

// Format seconds → human-readable string
function fmtSecs(s) {
  if (s == null || s === 0) return "0 min";
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h > 0 && m > 0) return `${h}h ${m}m`;
  if (h > 0) return `${h}h`;
  return `${m} min`;
}

// Format seconds → fractional hours string for trend
function fmtHrs(s) {
  if (!s) return "0";
  const h = s / 3600;
  return h >= 1 ? h.toFixed(1) : (s / 60).toFixed(0) + "m";
}

// Format a Unix timestamp → "HH:MM" local time
function fmtTime(ts) {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Today's midnight as a Unix timestamp (local)
function todayMidnightTs() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
}

// ── Today timeline ──────────────────────────────────────────────────────────

function renderTimeline(today) {
  const svg = document.getElementById("ins-timeline-svg");
  const W = 720, H = 32, r = 4;
  const dayStart = todayMidnightTs();
  const now = Date.now() / 1000;

  // Clear previous dynamic content (preserve <defs>)
  const defs = svg.querySelector("defs");
  while (svg.lastChild && svg.lastChild !== defs) svg.removeChild(svg.lastChild);

  // Full bar background — surface colour
  svg.appendChild(svgEl("rect", {
    x: 0, y: 0, width: W, height: H, rx: r,
    style: "fill: var(--surface); stroke: var(--rim); stroke-width: 1",
  }));

  // Overlay entire bar with hatch pattern (= "untracked" default)
  svg.appendChild(svgEl("rect", {
    x: 0, y: 0, width: W, height: H, rx: r,
    fill: "url(#ins-hatch)",
  }));

  // Helper: ts → x coordinate
  const tsToX = (ts) => Math.max(0, Math.min(W, (ts - dayStart) / 86400 * W));

  // Clear hatch in tracked ranges → shows "away" (slightly lighter surface)
  const TRACKED_CLR = "rgba(255,255,255,0.04)";
  const ranges = today.tracked_ranges || [];
  for (const rng of ranges) {
    const x = tsToX(rng.start_ts);
    const x2 = tsToX(rng.end_ts);
    if (x2 > x) {
      svg.appendChild(svgEl("rect", {
        x, y: 0, width: x2 - x, height: H,
        style: `fill: var(--surface); opacity: 1`,
      }));
      // subtle "away" tint
      svg.appendChild(svgEl("rect", {
        x, y: 0, width: x2 - x, height: H,
        style: `fill: ${TRACKED_CLR}`,
      }));
    }
  }

  // Present sessions → accent fill
  const sessions = today.sessions || [];
  for (const sess of sessions) {
    const x = tsToX(sess.start_ts);
    const x2 = tsToX(sess.end_ts);
    if (x2 > x) {
      svg.appendChild(svgEl("rect", {
        x, y: 2, width: Math.max(x2 - x, 2), height: H - 4, rx: 2,
        style: "fill: var(--accent); opacity: 0.88",
      }));
    }
  }

  // "Now" needle — thin vertical line at current time
  const nowX = tsToX(now);
  if (nowX > 0 && nowX < W) {
    svg.appendChild(svgEl("line", {
      x1: nowX, y1: 0, x2: nowX, y2: H,
      style: "stroke: var(--text); stroke-width: 1; opacity: 0.4",
    }));
  }

  // Hour tick marks (every 6h)
  for (const frac of [0.25, 0.5, 0.75]) {
    const tx = frac * W;
    svg.appendChild(svgEl("line", {
      x1: tx, y1: H - 6, x2: tx, y2: H,
      style: "stroke: var(--subtle); stroke-width: 1; opacity: 0.5",
    }));
  }

  // Update stats
  const total = today.total_seconds || 0;
  document.getElementById("ins-total").textContent = fmtSecs(total);
  document.getElementById("ins-sessions").textContent = today.session_count || 0;
  document.getElementById("ins-first").textContent = fmtTime(today.first_sit_ts);
  document.getElementById("ins-last").textContent = fmtTime(today.last_leave_ts);

  const meta = document.getElementById("ins-today-meta");
  if (total > 0) {
    meta.textContent = `${fmtSecs(total)} tracked`;
  } else {
    meta.textContent = "no tracked time yet";
  }
}

// ── Hour-of-day heatmap ──────────────────────────────────────────────────────

function renderHeatmap(byHour) {
  const svg = document.getElementById("ins-heatmap-svg");
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const W = 528, H = 36;
  const cellW = W / 24;
  const maxVal = Math.max(...byHour.map((e) => e.seconds), 1);

  for (const entry of byHour) {
    const h = entry.hour;
    const intensity = entry.seconds / maxVal;   // 0..1

    if (entry.seconds === 0) {
      // Empty cell — just show track
      svg.appendChild(svgEl("rect", {
        x: h * cellW + 1, y: 0,
        width: cellW - 2, height: H, rx: 3,
        style: "fill: var(--surface); stroke: var(--rim); stroke-width: 1",
      }));
    } else {
      // Background track
      svg.appendChild(svgEl("rect", {
        x: h * cellW + 1, y: 0,
        width: cellW - 2, height: H, rx: 3,
        style: "fill: var(--surface); stroke: var(--rim); stroke-width: 1",
      }));
      // Fill — accent at varying opacity to show intensity
      svg.appendChild(svgEl("rect", {
        x: h * cellW + 1, y: 0,
        width: cellW - 2, height: H, rx: 3,
        style: `fill: var(--accent); opacity: ${(0.12 + intensity * 0.76).toFixed(3)}`,
      }));
    }
  }
}

// ── Multi-day trend ──────────────────────────────────────────────────────────

function renderTrend(byDay) {
  const svg = document.getElementById("ins-trend-svg");
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const meta = document.getElementById("ins-trend-meta");

  if (!byDay || byDay.length === 0) {
    // Empty state
    const t = svgEl("text", {
      x: 360, y: 54,
      style: "fill: var(--subtle); font-size: 13px; text-anchor: middle",
    });
    t.textContent = "no data yet";
    svg.appendChild(t);
    meta.textContent = "hours at desk per day";
    return;
  }

  const W = 720, BAR_H = 72, LABEL_H = 14, GAP = 4;
  const n = byDay.length;
  const barW = Math.max(4, (W - GAP * (n + 1)) / n);
  const maxSecs = Math.max(...byDay.map((d) => d.seconds), 3600);  // floor 1h for scale

  byDay.forEach((day, i) => {
    const barHeight = Math.max(2, (day.seconds / maxSecs) * BAR_H);
    const x = GAP + i * (barW + GAP);
    const y = BAR_H - barHeight;

    // Bar
    svg.appendChild(svgEl("rect", {
      x, y, width: barW, height: barHeight, rx: 3,
      style: day.seconds > 0
        ? "fill: var(--accent); opacity: 0.75"
        : "fill: var(--surface); stroke: var(--rim); stroke-width: 1",
    }));

    // Date label — abbreviated "M/D"
    const parts = day.date.split("-");  // YYYY-MM-DD
    const label = `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}`;
    const t = svgEl("text", {
      x: x + barW / 2,
      y: BAR_H + LABEL_H,
      style: "fill: var(--subtle); font-size: 10px; text-anchor: middle",
    });
    t.textContent = label;
    svg.appendChild(t);
  });

  const totalHrs = (byDay.reduce((s, d) => s + d.seconds, 0) / 3600).toFixed(1);
  meta.textContent = `${totalHrs}h total over ${n} days`;
}

// ── Work vs off split ────────────────────────────────────────────────────────

function renderSplit(workSplit) {
  const work = workSplit.work_seconds || 0;
  const off  = workSplit.off_seconds || 0;
  const total = work + off;
  const pct = total > 0 ? (work / total * 100).toFixed(1) : 0;

  document.getElementById("ins-split-work-fill").style.width = `${pct}%`;
  document.getElementById("ins-work-hrs").textContent = fmtHrs(work);
  document.getElementById("ins-off-hrs").textContent  = fmtHrs(off);
}


// ── Active-work breakdown ─────────────────────────────────────────────────────

function renderActivityBreakdown(today) {
  const active = today.active_seconds || 0;
  const idle   = today.idle_seconds   || 0;
  const total  = active + idle;

  $("ins-active-sec").textContent  = fmtSecs(active);
  $("ins-idle-sec").textContent    = fmtSecs(idle);

  if (total > 0) {
    const sharePct = (active / total * 100).toFixed(0);
    $("ins-active-share").textContent = sharePct + "%";
    $("ins-active-fill").style.width  = sharePct + "%";
    $("ins-active-meta").textContent  = fmtSecs(total) + " tracked desk time";
  } else {
    $("ins-active-share").textContent = "—";
    $("ins-active-fill").style.width  = "0%";
    $("ins-active-meta").textContent  = "no data yet";
  }
}

// ── Main refresh ─────────────────────────────────────────────────────────────

async function refreshPresence() {
  try {
    const r = await fetch("/api/presence");
    if (!r.ok) return;
    const d = await r.json();

    renderTimeline(d.today || {});
    renderActivityBreakdown(d.today || {});
    renderHeatmap(d.by_hour || []);
    renderTrend(d.by_day || []);
    renderSplit(d.work_split || {});
  } catch (_) { /* non-fatal */ }
}

refreshPresence();
setInterval(refreshPresence, 30_000);

// ─────────────────────────────────────────────────────────────────────────────
// TALK BUTTON — click-to-talk mic → /api/ask → speechSynthesis
// ─────────────────────────────────────────────────────────────────────────────

(function () {
  const micBtn     = document.getElementById("mic-btn");
  const micLabel   = document.getElementById("mic-label");
  const askPanel   = document.getElementById("ask-panel");
  const askQuestion = document.getElementById("ask-question");
  const askAnswer  = document.getElementById("ask-answer");
  const askDismiss = document.getElementById("ask-dismiss");

  if (!micBtn) return; // guard in case HTML isn't updated yet

  let _recorder = null;
  let _chunks   = [];
  let _autoStopTimer = null;

  // ── State helpers ──────────────────────────────────────────────────────────

  const LABELS = {
    idle:      "Ask",
    recording: "Stop",
    thinking:  "…",
  };

  const ARIA = {
    idle:      "Ask Desk Sentinel",
    recording: "Stop recording",
    thinking:  "Thinking…",
  };

  function setMicState(s) {
    micBtn.dataset.state = s;
    micLabel.textContent = LABELS[s] ?? "Ask";
    micBtn.setAttribute("aria-label", ARIA[s] ?? "Ask Desk Sentinel");
    micBtn.disabled = (s === "thinking");
  }

  // ── Answer card ───────────────────────────────────────────────────────────

  function showAnswer(question, answer) {
    askQuestion.textContent = question || "";
    askAnswer.textContent   = answer;
    askPanel.classList.remove("ask-panel--hidden");
    // The server speaks the answer via macOS `say` (the nice system voice),
    // so we don't use the browser's robotic speechSynthesis here.
  }

  function showError(msg) {
    askQuestion.textContent = "";
    askAnswer.textContent   = msg;
    askPanel.classList.remove("ask-panel--hidden");
  }

  function dismissAsk() {
    askPanel.classList.add("ask-panel--hidden");
    "speechSynthesis" in window && window.speechSynthesis.cancel();
  }

  askDismiss.addEventListener("click", dismissAsk);

  // ── Recording flow ────────────────────────────────────────────────────────

  async function startRecording() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_) {
      setMicState("idle");
      showError("Microphone access denied — check your browser settings.");
      return;
    }

    setMicState("recording");
    _chunks = [];

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "";
    _recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

    _recorder.ondataavailable = (ev) => {
      if (ev.data.size > 0) _chunks.push(ev.data);
    };

    _recorder.onstop = async () => {
      // Release mic tracks immediately so the browser indicator clears
      stream.getTracks().forEach((t) => t.stop());

      const blob = new Blob(_chunks, { type: _recorder.mimeType || "audio/webm" });
      const form = new FormData();
      form.append("audio", blob, "recording.webm");

      try {
        const r = await fetch("/api/ask", { method: "POST", body: form });
        const d = await r.json();
        setMicState("idle");
        if (d.error) showError(d.error);
        else         showAnswer(d.question, d.answer);
      } catch (_) {
        setMicState("idle");
        showError("Network error — couldn't reach the server.");
      }
    };

    _recorder.start();

    // Auto-stop at 15 s
    _autoStopTimer = setTimeout(() => {
      if (_recorder && _recorder.state === "recording") {
        clearAutoStop();
        _recorder.stop();
        setMicState("thinking");
      }
    }, 15_000);
  }

  function clearAutoStop() {
    if (_autoStopTimer) { clearTimeout(_autoStopTimer); _autoStopTimer = null; }
  }

  function stopRecording() {
    clearAutoStop();
    if (_recorder && _recorder.state === "recording") {
      _recorder.stop();
      setMicState("thinking");
    }
  }

  // ── Button click ──────────────────────────────────────────────────────────

  micBtn.addEventListener("click", () => {
    const s = micBtn.dataset.state || "idle";

    if (s === "recording") {
      stopRecording();
      return;
    }
    if (s === "thinking") return; // already waiting

    // idle → start
    dismissAsk();
    startRecording();
  });

  // ── Keyboard shortcut: Escape dismisses the panel ─────────────────────────

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") dismissAsk();
  });
})();
