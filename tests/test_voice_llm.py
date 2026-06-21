"""Unit tests for sentinel.voice.llm.build_messages (pure — no HTTP)."""
from __future__ import annotations

import pytest

from sentinel.voice.llm import build_messages, _SYSTEM_PROMPT_TEMPLATE

SAMPLE_BRIEF = """\
=== Desk Sentinel Stats Brief — 2026-06-17 10:00 ===

TODAY (so far):
  Desk time: 2h 30m
  Sessions: 3
  Posture: 80.0% good, 20.0% poor"""

SAMPLE_QUESTION = "How much time did I spend at my desk today?"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_build_messages_returns_list():
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    assert isinstance(msgs, list)


def test_build_messages_has_two_entries():
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    assert len(msgs) == 2


def test_build_messages_roles():
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


# ---------------------------------------------------------------------------
# System prompt content
# ---------------------------------------------------------------------------

def test_build_messages_system_contains_brief():
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    assert SAMPLE_BRIEF in msgs[0]["content"]


def test_build_messages_system_constrains_to_brief():
    """System prompt must instruct the model to answer ONLY from the brief."""
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    sys_content = msgs[0]["content"].lower()
    assert "only" in sys_content


def test_build_messages_system_requests_short_answer():
    """System prompt must request short / spoken-friendly output."""
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    sys_content = msgs[0]["content"].lower()
    # Any of these phrases indicate brevity is requested
    assert any(
        phrase in sys_content
        for phrase in ("1–3", "1-3", "short", "aloud", "spoken")
    )


def test_build_messages_system_fallback_phrase():
    """System prompt must tell the model what to say when data is absent."""
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    sys_content = msgs[0]["content"].lower()
    assert "don't track" in sys_content or "i don't track" in sys_content


def test_build_messages_user_content_is_question():
    msgs = build_messages(SAMPLE_BRIEF, SAMPLE_QUESTION)
    assert msgs[1]["content"] == SAMPLE_QUESTION


# ---------------------------------------------------------------------------
# Brief injection
# ---------------------------------------------------------------------------

def test_build_messages_different_brief_changes_system():
    brief_a = "Brief A content"
    brief_b = "Brief B content"
    msgs_a = build_messages(brief_a, SAMPLE_QUESTION)
    msgs_b = build_messages(brief_b, SAMPLE_QUESTION)
    assert msgs_a[0]["content"] != msgs_b[0]["content"]
    assert brief_a in msgs_a[0]["content"]
    assert brief_b in msgs_b[0]["content"]


def test_build_messages_different_question_changes_user():
    q1 = "Question one?"
    q2 = "Question two?"
    msgs_1 = build_messages(SAMPLE_BRIEF, q1)
    msgs_2 = build_messages(SAMPLE_BRIEF, q2)
    assert msgs_1[1]["content"] == q1
    assert msgs_2[1]["content"] == q2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_build_messages_empty_brief():
    msgs = build_messages("", SAMPLE_QUESTION)
    assert isinstance(msgs, list)
    assert len(msgs) == 2


def test_build_messages_empty_question():
    msgs = build_messages(SAMPLE_BRIEF, "")
    assert msgs[1]["content"] == ""
