"""voice/llm.py — Ollama LLM interface for the voice agent.

Public API:
  build_messages(brief, question) -> list   # pure, unit-tested
  answer(question, brief, model, url) -> str # HTTP, integration
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger("desk_sentinel.voice.llm")

_SYSTEM_PROMPT_TEMPLATE = """\
You are Desk Sentinel, the user's desk-health assistant. Answer their spoken \
question using ONLY the stats below. Keep your reply to 1–3 short sentences — \
it will be read aloud. If the stats don't cover the question, say \
"I don't track that yet." Be warm and concise.

{brief}"""


def build_messages(brief: str, question: str) -> list[dict]:
    """Assemble the Ollama messages payload (pure — no I/O).

    Returns a list of ``{"role": ..., "content": ...}`` dicts.

    Args:
        brief: the text stats brief from :func:`~sentinel.voice.brief.build_brief`.
        question: the user's transcribed spoken question.
    """
    system_content = _SYSTEM_PROMPT_TEMPLATE.format(brief=brief)
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]


def answer(
    question: str,
    brief: str,
    model: str = "llama3.1:8b",
    url: str = "http://localhost:11434",
) -> str:
    """Send a chat request to Ollama and return the assistant's reply.

    Non-streaming POST to ``/api/chat``.

    Args:
        question: the user's transcribed question.
        brief: text stats brief from :func:`~sentinel.voice.brief.build_brief`.
        model: Ollama model name (e.g. ``llama3.1:8b``).
        url: Ollama base URL.

    Returns:
        The assistant's reply text.

    Raises:
        RuntimeError: if the HTTP request fails or the response is malformed.
    """
    messages = build_messages(brief, question)
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        # Spoken answers are short; cap generation so it's quick.
        "options": {"num_predict": 120, "temperature": 0.4},
        # Keep the model resident so follow-up questions don't pay the
        # cold-load cost (the main source of the slow first response).
        "keep_alive": "1h",
    }).encode()

    endpoint = url.rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama unreachable at {endpoint}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned non-JSON: {exc}") from exc

    try:
        return body["message"]["content"].strip()
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Ollama response shape: {body!r}") from exc


def warm_up(model: str, url: str = "http://localhost:11434", keep_alive: str = "1h") -> None:
    """Load the model into Ollama's memory (no generation) so the first real
    question is fast. Best-effort — failures are swallowed."""
    payload = json.dumps({"model": model, "prompt": "", "keep_alive": keep_alive}).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        log.info("Warmed up Ollama model %r", model)
    except Exception as exc:  # noqa: BLE001 — warm-up is best-effort
        log.warning("Ollama warm-up failed for %r: %s", model, exc)
