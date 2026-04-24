"""Tests for the critique-dialog HITL module."""

from __future__ import annotations

import pytest

from src.agents.critique_dialog import (
    MAX_DIALOG_ROUNDS,
    _build_system_prompt,
    run_critique_dialog,
)
from src.graph.state import Critique
from src.llm.mock_provider import MockProvider


def _make_critique(critic_id: str = "engineering") -> Critique:
    return Critique(
        critic_id=critic_id,
        claim_id="C-001",
        severity="P1",
        finding="No rate-limit strategy is defined for the public endpoint.",
        evidence='line 1: "Mock top-line claim extracted from the PRD."',
        suggested_fix="Add a token-bucket rate limiter at the API gateway.",
    )


PRD_TEXT = "[001] Mock PRD body.\n[002] Another line.\n"


# ---- System-prompt routing -------------------------------------------------


@pytest.mark.parametrize(
    "critic_id,needle",
    [
        ("user_advocate", "user advocate"),
        ("engineering", "engineering"),
        ("business", "business"),
        ("design", "design"),
    ],
)
def test_dialog_system_prompt_includes_role(critic_id: str, needle: str) -> None:
    """Each critic id should load its own base prompt, preserving the role lens."""
    prompt = _build_system_prompt(critic_id, _make_critique(critic_id))
    assert needle in prompt.lower()
    # Dialog preamble always appended.
    assert "DIALOG MODE" in prompt
    # Critique fields echoed into the preamble so the model stays grounded.
    assert "No rate-limit strategy" in prompt


def test_unknown_critic_id_falls_back_gracefully() -> None:
    """Minimal role prompt rather than KeyError for unknown ids."""
    crit = _make_critique("made_up_critic")
    prompt = _build_system_prompt("made_up_critic", crit)
    assert "made_up_critic" in prompt
    assert "DIALOG MODE" in prompt


# ---- Streaming behaviour ---------------------------------------------------


async def test_stream_yields_at_least_one_text_delta() -> None:
    llm = MockProvider()
    deltas = []
    async for chunk in run_critique_dialog(
        critic_id="engineering",
        original_critique=_make_critique("engineering"),
        prd_text=PRD_TEXT,
        conversation_history=[{"role": "user", "content": "Why P1 and not P2?"}],
        llm=llm,
    ):
        assert chunk.get("type") == "text"
        deltas.append(chunk["delta"])

    assert deltas, "expected at least one streamed delta"
    full = "".join(deltas)
    # Engineering flavour should surface in the mock response.
    assert "Technically" in full or "systems" in full or "gateway" in full


async def test_mock_routes_dialog_by_critic_id() -> None:
    """Swapping critic_id should swap the flavour text — proves mock routing works."""
    llm = MockProvider()
    crit = _make_critique("business")

    deltas = []
    async for chunk in run_critique_dialog(
        critic_id="business",
        original_critique=crit,
        prd_text=PRD_TEXT,
        conversation_history=[{"role": "user", "content": "Why P0?"}],
        llm=llm,
    ):
        deltas.append(chunk["delta"])
    full = "".join(deltas)
    assert "commercial" in full or "OKR" in full or "baseline" in full


# ---- Round-cap enforcement -------------------------------------------------


async def test_cap_reached_appends_terminator() -> None:
    """After MAX_DIALOG_ROUNDS user turns, a terminator chunk must be emitted."""
    llm = MockProvider()

    # Build a history with exactly MAX_DIALOG_ROUNDS user turns (and the
    # matching assistant replies that would have come between them).
    history: list[dict] = []
    for i in range(MAX_DIALOG_ROUNDS):
        history.append({"role": "user", "content": f"Question {i}?"})
        if i < MAX_DIALOG_ROUNDS - 1:
            history.append({"role": "assistant", "content": f"Answer {i}."})

    chunks = []
    async for chunk in run_critique_dialog(
        critic_id="engineering",
        original_critique=_make_critique("engineering"),
        prd_text=PRD_TEXT,
        conversation_history=history,
        llm=llm,
    ):
        chunks.append(chunk["delta"])

    full = "".join(chunks)
    assert "已达上限" in full, "5-round cap terminator should be appended"


async def test_cap_not_reached_no_terminator() -> None:
    """Below the cap, no terminator should be emitted."""
    llm = MockProvider()
    history = [{"role": "user", "content": "First question."}]
    chunks = []
    async for chunk in run_critique_dialog(
        critic_id="design",
        original_critique=_make_critique("design"),
        prd_text=PRD_TEXT,
        conversation_history=history,
        llm=llm,
    ):
        chunks.append(chunk["delta"])
    full = "".join(chunks)
    assert "已达上限" not in full
