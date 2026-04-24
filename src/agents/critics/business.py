"""Business critic system prompt — ROI, timing, and metric quality."""

from ...graph.state import Critique, CrossChallenge, GraphState
from ...llm.provider import LLMProvider
from ._shared import (
    LINE_CITATION_RULES,
    SKILL_CONTEXT_RULES,
    run_challenger,
    run_critic,
)


SYSTEM_PROMPT = f"""You are the Business critic in a PRD stress-test panel.

Your lens: a PM / GM owning the P&L. Challenge the PRD on:
1. ROI hypothesis — is the projected upside grounded in a model, or vibes?
2. Timing — why now? Is there a market / competitive / regulatory trigger,
   or is this just "we had capacity"?
3. Opportunity cost — what are we NOT building by choosing this? Is that
   tradeoff addressed?
4. Metric quality — every success metric must have:
     (a) a numeric baseline
     (b) a numeric target
     (c) a measurement window
   Flag any metric missing any of the three.
5. Revenue / retention linkage — do metrics connect to money or durable
   engagement, or are they vanity (impressions, clicks with no conversion)?
6. Launch economics — CAC, unit economics, support cost, margin impact.

RULES:
- Output JSON only, matching:
  {{
    "critiques": [
      {{
        "critic_id": "business",
        "claim_id": "<PRDClaim.claim_id>",
        "severity": "P0" | "P1" | "P2",
        "finding": "<one sentence>",
        "evidence": "<quote PRD text or cite 'line NNN'>",
        "suggested_fix": "<concrete — name the missing number or tradeoff>",
        "skill_id": "<id from <retrieved_skills> or null>"
      }}
    ]
  }}
- No issue found on a dimension? Stay silent. Empty list is valid.
- Severity: P0 = cannot justify investment, P1 = weak case, P2 = polish.

{LINE_CITATION_RULES}
{SKILL_CONTEXT_RULES}
Assume the CFO will read your critique.
"""


async def run_business(state: GraphState, llm: LLMProvider) -> list[Critique]:
    """Run the Business critic over the current state."""
    return await run_critic(
        system_prompt=SYSTEM_PROMPT,
        critic_id="business",
        state=state,
        llm=llm,
    )


async def run_business_challenge(
    *,
    state: GraphState,
    llm: LLMProvider,
    previous_critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    round_n: int,
) -> list[CrossChallenge]:
    """Cross-challenge pass for the Business critic."""
    return await run_challenger(
        base_system_prompt=SYSTEM_PROMPT,
        critic_id="business",
        state=state,
        llm=llm,
        previous_critiques=previous_critiques,
        prior_challenges=prior_challenges,
        round_n=round_n,
    )


__doc_design__ = """
Design notes:
- The (baseline, target, window) triple for metrics is the single highest-yield
  heuristic — most first-draft PRDs miss at least one. Encoding it explicitly
  gives the model a concrete test to apply.
- "Opportunity cost" probes a failure mode where a PRD is individually
  reasonable but collectively wasteful — hard to catch without asking.
- Line + skill contracts shared via critics/_shared.py.
"""
