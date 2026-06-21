"""briefing.py — Daily bookend content assembly for Desk Sentinel.

Provides:
  fetch_weather     — wttr.in one-line forecast (best-effort, timeout-guarded)
  fetch_ai_headlines — Google News RSS top-N titles (best-effort)
  compose_morning   — pure: builds the morning spoken brief string
  compose_wind_down — pure: builds the wind-down spoken string
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx


# ---------------------------------------------------------------------------
# Network fetchers (best-effort; None / [] on any failure)
# ---------------------------------------------------------------------------

def fetch_weather(location: str | None = None, timeout: float = 4.0) -> str | None:
    """Fetch a one-line weather summary from wttr.in.

    Args:
        location: city / location string, or None for IP-based lookup.
        timeout:  request timeout in seconds.

    Returns:
        A short string like "Partly cloudy, +72F, feels +68F", or None on failure.
    """
    loc = quote(location) if location else ""
    url = f"https://wttr.in/{loc}?format=%C,+%t,+feels+%f"
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text.strip()
        return text if text else None
    except Exception:
        return None


def fetch_ai_headlines(
    query: str = "artificial intelligence",
    n: int = 2,
    timeout: float = 4.0,
) -> list[str]:
    """Fetch top-N headline titles from Google News RSS.

    Args:
        query:   search query string (default: "artificial intelligence").
        n:       number of headlines to return.
        timeout: request timeout in seconds.

    Returns:
        List of up to n cleaned headline strings, or [] on any failure.
    """
    encoded = quote(query)
    url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        titles: list[str] = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                # Google News titles include " - Source Name" suffix; strip it
                raw = title_el.text.strip()
                # Strip trailing " - Publisher" attribution
                if " - " in raw:
                    raw = raw.rsplit(" - ", 1)[0].strip()
                if raw:
                    titles.append(raw)
            if len(titles) >= n:
                break
        return titles
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Pure composers
# ---------------------------------------------------------------------------

def compose_morning(
    weather: str | None,
    headlines: list[str],
    recap: dict | None,
) -> str:
    """Compose the morning spoken briefing string.

    Args:
        weather:   weather summary string, or None to skip.
        headlines: list of AI-news headline strings (may be empty).
        recap:     dict with optional keys:
                     desk_hours  — float, hours at desk yesterday
                     good_pct    — float, posture-good percentage yesterday
                   Pass None or empty dict to skip the recap section.

    Returns:
        A natural spoken string ready for ``say``.
    """
    parts: list[str] = ["Good morning."]

    if weather:
        parts.append(weather + ".")

    if recap:
        desk_hours = recap.get("desk_hours")
        good_pct = recap.get("good_pct")
        if desk_hours is not None and good_pct is not None:
            h = round(float(desk_hours), 1)
            p = round(float(good_pct))
            parts.append(
                f"Yesterday you were at your desk about {h} hours, "
                f"posture good {p}%."
            )
        elif desk_hours is not None:
            h = round(float(desk_hours), 1)
            parts.append(f"Yesterday you were at your desk about {h} hours.")
        elif good_pct is not None:
            p = round(float(good_pct))
            parts.append(f"Yesterday your posture was good {p}% of the time.")

    if headlines:
        intro = "In AI news:"
        joined = "; ".join(headlines)
        if not joined.endswith((".", "!", "?")):
            joined += "."
        parts.append(f"{intro} {joined}")

    return " ".join(parts)


def compose_wind_down() -> str:
    """Compose the end-of-day wind-down spoken string.

    Returns:
        A natural spoken string ready for ``say``.
    """
    return (
        "It's getting close to the end of your day "
        "— a good time to start wrapping up."
    )
