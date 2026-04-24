"""End-to-end pipeline tests using MockProvider.

Verifies that all four critics fire, critiques merge via the operator.add
reducer, and the final state shape matches what the UI expects.
"""

from __future__ import annotations

from src.llm.mock_provider import MockProvider
from src.main import run_pipeline


SAMPLE_PRD = """# PRD-Test

## Problem
Users complain.

## Solution
Ship something.
"""


async def test_run_pipeline_returns_critiques():
    result = await run_pipeline(SAMPLE_PRD, llm=MockProvider())
    assert "critiques" in result
    assert len(result["critiques"]) > 0
    assert len(result.get("prd_claims", [])) > 0


async def test_all_four_critics_are_invoked():
    llm = MockProvider()
    await run_pipeline(SAMPLE_PRD, llm=llm)

    systems = [
        call["system"].lower()
        for call in llm.call_log
        if call["method"] == "complete"
    ]
    # Intake + 4 critics = 5 complete() calls minimum
    assert any("intake" in s for s in systems)
    assert any("user advocate" in s for s in systems)
    assert any("engineering" in s for s in systems)
    assert any("business" in s for s in systems)
    assert any("design" in s for s in systems)


async def test_critiques_span_multiple_critic_ids():
    result = await run_pipeline(SAMPLE_PRD, llm=MockProvider())
    critic_ids = {c.critic_id for c in result["critiques"]}
    assert critic_ids == {"user_advocate", "engineering", "business", "design"}


async def test_pipeline_numbers_lines_before_intake():
    """The PRD handed to agents must carry `[NNN]` markers."""
    llm = MockProvider()
    await run_pipeline(SAMPLE_PRD, llm=llm)
    intake_call = next(c for c in llm.call_log if "intake" in c["system"].lower())
    assert "[001]" in intake_call["user"]
