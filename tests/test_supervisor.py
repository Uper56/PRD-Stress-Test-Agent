"""Tests for the supervisor agent — streaming parser and end-to-end verdict."""

from __future__ import annotations

from src.agents.supervisor import run_supervisor, run_supervisor_stream
from src.llm.mock_provider import MockProvider
from src.main import run_pipeline


SAMPLE_PRD = """# PRD-Test

## Problem
Users complain.

## Solution
Ship something.
"""


async def _state_with_critiques() -> dict:
    """Run the pipeline up to the merge node and return the state dict."""
    return await run_pipeline(
        SAMPLE_PRD, llm=MockProvider(), include_supervisor=False
    )


async def test_run_supervisor_returns_parsed_verdict():
    state = await _state_with_critiques()
    verdict = await run_supervisor(state, llm=MockProvider())
    assert isinstance(verdict, dict)
    assert verdict.get("executive_summary")
    assert isinstance(verdict.get("p0_blockers"), list)
    # Mock supervisor puts one P0 blocker in the verdict.
    assert len(verdict["p0_blockers"]) >= 1


async def test_run_supervisor_stream_yields_thinking_and_verdict_and_done():
    state = await _state_with_critiques()

    events = [ev async for ev in run_supervisor_stream(state, llm=MockProvider())]
    stages = [ev["stage"] for ev in events]

    assert "thinking" in stages
    assert "verdict" in stages
    assert stages[-1] == "done"
    # No stray content bleeds through as thinking text — the close tag wasn't emitted.
    thinking_text = "".join(ev["delta"] for ev in events if ev["stage"] == "thinking")
    assert "</thinking>" not in thinking_text
    assert "<verdict>" not in thinking_text


async def test_pipeline_populates_final_report():
    result = await run_pipeline(SAMPLE_PRD, llm=MockProvider())
    assert "final_report" in result
    final = result["final_report"]
    assert isinstance(final, dict)
    assert final.get("executive_summary")
    # supervisor_verdict slot is also filled with a Pydantic model
    assert result.get("supervisor_verdict") is not None


async def test_supervisor_stream_handles_tag_split_across_chunks():
    """Regression guard: manually feed a provider whose stream splits tags."""

    class SplitStreamProvider(MockProvider):
        async def stream(self, system, user, **_):  # type: ignore[override]
            resp = await self.complete(system, user)
            # Break into single-character chunks to stress boundary handling.
            for ch in resp.text:
                yield {"type": "text", "delta": ch}

    state = await _state_with_critiques()
    events = [
        ev async for ev in run_supervisor_stream(state, llm=SplitStreamProvider())
    ]
    stages = [ev["stage"] for ev in events]
    assert "thinking" in stages and "verdict" in stages
    assert stages[-1] == "done"
    final = events[-1]["final_verdict"]
    assert final.get("executive_summary")
