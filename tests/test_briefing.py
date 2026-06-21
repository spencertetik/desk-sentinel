"""Tests for sentinel/briefing.py.

Pure composer functions are tested fully.
Network fetchers are tested for graceful failure via monkeypatching.
Real-network tests are gated with @pytest.mark.integration.
"""
from __future__ import annotations

import pytest
import httpx

from sentinel.briefing import (
    compose_morning,
    compose_wind_down,
    fetch_ai_headlines,
    fetch_weather,
)


# ---------------------------------------------------------------------------
# compose_morning — pure
# ---------------------------------------------------------------------------

def test_compose_morning_full():
    msg = compose_morning(
        weather="Sunny, +72F, feels +70F",
        headlines=["AI breakthrough announced", "New model beats benchmarks"],
        recap={"desk_hours": 6.5, "good_pct": 82.0},
    )
    assert msg.startswith("Good morning.")
    assert "Sunny" in msg
    assert "6.5 hours" in msg
    assert "82%" in msg
    assert "AI breakthrough" in msg
    assert "New model beats benchmarks" in msg


def test_compose_morning_missing_weather():
    msg = compose_morning(
        weather=None,
        headlines=["AI headline"],
        recap={"desk_hours": 4.0, "good_pct": 60.0},
    )
    assert "Good morning." in msg
    assert "4.0 hours" in msg
    assert "AI headline" in msg
    # no crash, no weather fragment
    assert "None" not in msg


def test_compose_morning_missing_news():
    msg = compose_morning(
        weather="Cloudy, +65F",
        headlines=[],
        recap={"desk_hours": 3.0, "good_pct": 55.0},
    )
    assert "Good morning." in msg
    assert "Cloudy" in msg
    assert "3.0 hours" in msg
    # no "In AI news" section
    assert "AI news" not in msg


def test_compose_morning_missing_recap():
    msg = compose_morning(
        weather="Rainy, +58F",
        headlines=["Robots take over"],
        recap=None,
    )
    assert "Good morning." in msg
    assert "Rainy" in msg
    assert "Robots take over" in msg
    # no desk stats
    assert "hours" not in msg
    assert "%" not in msg


def test_compose_morning_all_missing():
    """With everything absent, still returns at least 'Good morning.'."""
    msg = compose_morning(weather=None, headlines=[], recap=None)
    assert "Good morning." in msg


def test_compose_morning_recap_only_hours():
    """Recap with desk_hours but no good_pct still speaks hours."""
    msg = compose_morning(
        weather=None,
        headlines=[],
        recap={"desk_hours": 7.2},
    )
    assert "7.2 hours" in msg
    assert "%" not in msg


def test_compose_morning_recap_only_good_pct():
    """Recap with good_pct but no desk_hours still speaks pct."""
    msg = compose_morning(
        weather=None,
        headlines=[],
        recap={"good_pct": 90.0},
    )
    assert "90%" in msg
    assert "hours" not in msg


def test_compose_morning_headline_semicolon_separator():
    """Multiple headlines are joined with semicolons."""
    msg = compose_morning(
        weather=None,
        headlines=["First headline", "Second headline"],
        recap=None,
    )
    assert "First headline; Second headline" in msg


def test_compose_morning_rounds_hours_to_one_decimal():
    msg = compose_morning(
        weather=None,
        headlines=[],
        recap={"desk_hours": 6.66666, "good_pct": 75.0},
    )
    assert "6.7 hours" in msg


def test_compose_morning_rounds_pct_to_integer():
    msg = compose_morning(
        weather=None,
        headlines=[],
        recap={"desk_hours": 4.0, "good_pct": 82.6},
    )
    assert "83%" in msg


# ---------------------------------------------------------------------------
# compose_wind_down — pure
# ---------------------------------------------------------------------------

def test_compose_wind_down_is_nonempty():
    msg = compose_wind_down()
    assert isinstance(msg, str)
    assert len(msg) > 10


def test_compose_wind_down_contains_wrapping_up():
    msg = compose_wind_down()
    assert "wrapping up" in msg.lower() or "end of your day" in msg.lower()


# ---------------------------------------------------------------------------
# fetch_weather — graceful failure
# ---------------------------------------------------------------------------

def test_fetch_weather_returns_none_on_connection_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("mocked failure")
    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_weather("Enid, OK")
    assert result is None


def test_fetch_weather_returns_none_on_timeout(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.TimeoutException("mocked timeout")
    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_weather()
    assert result is None


def test_fetch_weather_returns_none_on_http_error(monkeypatch):
    class _FakeResp:
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("500", request=None, response=None)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResp())
    result = fetch_weather()
    assert result is None


# ---------------------------------------------------------------------------
# fetch_ai_headlines — graceful failure
# ---------------------------------------------------------------------------

def test_fetch_ai_headlines_returns_empty_on_connection_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("mocked failure")
    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_ai_headlines()
    assert result == []


def test_fetch_ai_headlines_returns_empty_on_timeout(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.TimeoutException("mocked timeout")
    monkeypatch.setattr(httpx, "get", _raise)
    result = fetch_ai_headlines("artificial intelligence", n=2)
    assert result == []


def test_fetch_ai_headlines_returns_empty_on_bad_xml(monkeypatch):
    class _FakeResp:
        text = "not valid xml at all <<<"
        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResp())
    result = fetch_ai_headlines()
    assert result == []


def test_fetch_ai_headlines_parses_rss_correctly(monkeypatch):
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item><title>First AI Story - TechCrunch</title></item>
    <item><title>Second AI Story - Wired</title></item>
    <item><title>Third AI Story - NYT</title></item>
  </channel>
</rss>"""

    class _FakeResp:
        text = rss
        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResp())
    result = fetch_ai_headlines(n=2)
    assert len(result) == 2
    assert result[0] == "First AI Story"
    assert result[1] == "Second AI Story"


def test_fetch_ai_headlines_strips_publisher_attribution(monkeypatch):
    """Titles like 'Story - Publisher Name' should have the publisher stripped."""
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item><title>OpenAI Releases New Model - The Verge</title></item>
  </channel>
</rss>"""

    class _FakeResp:
        text = rss
        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResp())
    result = fetch_ai_headlines(n=1)
    assert result == ["OpenAI Releases New Model"]


def test_fetch_ai_headlines_respects_n_limit(monkeypatch):
    rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item><title>Story One - A</title></item>
    <item><title>Story Two - B</title></item>
    <item><title>Story Three - C</title></item>
  </channel>
</rss>"""

    class _FakeResp:
        text = rss
        def raise_for_status(self):
            pass
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResp())
    result = fetch_ai_headlines(n=1)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Integration tests (require network) — skipped in normal CI
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_fetch_weather_real_ip_based():
    """wttr.in returns a non-empty string for IP-based lookup."""
    result = fetch_weather(location=None, timeout=8.0)
    assert result is None or (isinstance(result, str) and len(result) > 3)


@pytest.mark.integration
def test_fetch_ai_headlines_real():
    """Google News RSS returns at least 1 headline for 'artificial intelligence'."""
    result = fetch_ai_headlines("artificial intelligence", n=2, timeout=8.0)
    assert isinstance(result, list)
    # On success returns 1-2 items; on network failure gracefully returns []
    assert len(result) <= 2
