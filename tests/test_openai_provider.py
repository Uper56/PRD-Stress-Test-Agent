"""Tests for OpenAIProvider — focused on the streaming-fallback path.

The deployed HF Space hit `APIConnectionError` on the supervisor stream
while the critics' `complete()` calls succeeded — i.e. the endpoint
refused SSE streaming but plain completions worked. `stream()` must
detect that and fall back to a single `complete()` call, emitting the
whole response as one chunk so the supervisor's XML parser still works.

These tests construct the provider with a fake key (no network at
construction) and monkeypatch the underlying client, so they never hit
a real API.
"""

from __future__ import annotations

import types

import pytest

from src.llm.openai_provider import OpenAIProvider
from src.llm.provider import LLMError, LLMResponse


def _make_provider() -> OpenAIProvider:
    # Constructing AsyncOpenAI with a fake key makes no network call.
    return OpenAIProvider(api_key="sk-fake-test-key", model="gpt-4o-mini")


def _chunk(content: str | None):
    """Build a minimal object shaped like an OpenAI streaming chunk."""
    delta = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(delta=delta)
    return types.SimpleNamespace(choices=[choice])


async def _drain(agen) -> list[dict]:
    return [ev async for ev in agen]


async def test_stream_falls_back_to_complete_when_sse_fails(monkeypatch) -> None:
    """If establishing the stream raises, stream() must fall back to
    complete() and emit the full text as one chunk."""
    provider = _make_provider()

    async def _boom(**_kwargs):
        raise RuntimeError("Connection error.")

    # Stream establishment fails…
    monkeypatch.setattr(provider._client.chat.completions, "create", _boom)

    # …but complete() works (mimics critics succeeding in production).
    async def _fake_complete(system, user, *, max_tokens=None, temperature=0.7):
        return LLMResponse(
            text="<thinking>ok</thinking><verdict>{}</verdict>",
            model_id="gpt-4o-mini",
        )

    monkeypatch.setattr(provider, "complete", _fake_complete)

    events = await _drain(provider.stream("You are the Supervisor.", "user msg"))
    assert events == [
        {"type": "text", "delta": "<thinking>ok</thinking><verdict>{}</verdict>"}
    ]


async def test_stream_yields_chunks_on_happy_path(monkeypatch) -> None:
    """When SSE works, stream() yields each non-empty delta as a chunk."""
    provider = _make_provider()

    async def _ok_stream(**_kwargs):
        async def _gen():
            for piece in ("Hel", "lo", None, " world"):
                yield _chunk(piece)
        return _gen()

    monkeypatch.setattr(provider._client.chat.completions, "create", _ok_stream)

    events = await _drain(provider.stream("sys", "user"))
    assert events == [
        {"type": "text", "delta": "Hel"},
        {"type": "text", "delta": "lo"},
        {"type": "text", "delta": " world"},
    ]


async def test_stream_drops_gracefully_after_partial(monkeypatch) -> None:
    """If the connection dies mid-stream after content was delivered,
    stream() ends without raising (partial > crash)."""
    provider = _make_provider()

    async def _flaky_stream(**_kwargs):
        async def _gen():
            yield _chunk("partial")
            raise RuntimeError("connection reset mid-stream")
        return _gen()

    monkeypatch.setattr(provider._client.chat.completions, "create", _flaky_stream)

    # complete() should NOT be called here — we already have partial content.
    async def _should_not_run(*a, **k):  # pragma: no cover
        raise AssertionError("complete() must not be the fallback after partial output")

    monkeypatch.setattr(provider, "complete", _should_not_run)

    events = await _drain(provider.stream("sys", "user"))
    assert events == [{"type": "text", "delta": "partial"}]


async def test_stream_raises_when_both_stream_and_complete_fail(monkeypatch) -> None:
    """If the fallback complete() also fails, stream() surfaces a typed error."""
    provider = _make_provider()

    async def _boom(**_kwargs):
        raise RuntimeError("Connection error.")

    monkeypatch.setattr(provider._client.chat.completions, "create", _boom)

    async def _complete_boom(*a, **k):
        raise LLMError("still down")

    monkeypatch.setattr(provider, "complete", _complete_boom)

    with pytest.raises(LLMError):
        await _drain(provider.stream("sys", "user"))
