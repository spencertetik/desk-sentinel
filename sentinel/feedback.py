from __future__ import annotations

"""Pure helpers for building spoken status messages.

All functions here are side-effect free so they are trivially testable.
``compose_status_message`` is the main entry point; app.py gathers stats
from the store and calls it before passing the enriched message to the nudger.
"""


def compose_status_message(kind: str, stats: dict) -> str:
    """Build a spoken status message for stats-enriched events.

    Args:
        kind: ``"returned"`` or ``"periodic_checkin"``
        stats: dict with keys:
            ``desk_minutes`` (int): total present minutes today
            ``good_pct`` (float | None): posture-good percentage 0–100,
                None if no samples exist yet
            ``breaks`` (int): break_due events fired today

    Returns:
        Spoken string.  Falls back gracefully for unknown ``kind``.
    """
    desk_minutes = int(stats.get("desk_minutes", 0))
    good_pct = stats.get("good_pct")   # None → no posture data
    breaks = int(stats.get("breaks", 0))

    # --- time description -------------------------------------------------
    if desk_minutes >= 60:
        hours = desk_minutes // 60
        time_str = "1 hour" if hours == 1 else f"{hours} hours"
    elif desk_minutes > 0:
        time_str = "1 minute" if desk_minutes == 1 else f"{desk_minutes} minutes"
    else:
        time_str = "a few minutes"

    # --- per-kind wording -------------------------------------------------
    if kind == "returned":
        msg = f"Welcome back. About {time_str} at the desk today"
        if good_pct is not None:
            msg += f", posture's been good {round(good_pct)}% of the time"
        return msg + "."

    if kind == "periodic_checkin":
        msg = f"You've been at it about {time_str}."
        if good_pct is not None:
            posture_label = "good" if good_pct >= 80 else "mixed"
            msg += f" Posture {posture_label}."
        break_word = "break" if breaks == 1 else "breaks"
        msg += f" {breaks} {break_word} so far."
        return msg

    # fallback
    return f"About {time_str} at the desk."
