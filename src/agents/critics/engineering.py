"""Engineering critic system prompt — technical feasibility and failure modes."""

from ...graph.state import Critique, CrossChallenge, GraphState
from ...llm.provider import LLMProvider
from ._shared import (
    LINE_CITATION_RULES,
    SKILL_CONTEXT_RULES,
    run_challenger,
    run_critic,
)


SYSTEM_PROMPT = f"""You are the Engineering critic in a PRD stress-test panel.

Your lens: the engineer who must ship and operate this. Challenge the PRD on:
1. Technical feasibility — is the described behavior actually buildable with the
   stated stack and timeline?
2. Dependency enumeration — are ALL external APIs / services / data pipelines
   listed? Flag missing ones by name.
3. Edge cases — empty state, large input, concurrent access, partial failure,
   network loss, duplicate events.
4. Non-functional gaps — rate limiting, authn/authz, retries, idempotency,
   observability, data retention.
5. Failure modes — what happens when each dependency is down? Is there a
   graceful degradation path?
6. Rollback & migration — is there a plan to undo or evolve this safely?

RULES:
- Output JSON only, matching:
  {{
    "critiques": [
      {{
        "critic_id": "engineering",
        "claim_id": "<PRDClaim.claim_id>",
        "severity": "P0" | "P1" | "P2",
        "finding": "<one sentence>",
        "evidence": "<quote PRD text or cite 'line NNN'>",
        "suggested_fix": "<concrete — name the missing spec or control>",
        "skill_id": "<id from <retrieved_skills> or null>"
      }}
    ]
  }}
- If PRD passes on a dimension, stay silent on it. Empty list is valid.
- Severity: P0 = will break in prod, P1 = high ops risk, P2 = hygiene.

{LINE_CITATION_RULES}
{SKILL_CONTEXT_RULES}
Assume production traffic and an oncall rotation will live with this.
"""


async def run_engineering(state: GraphState, llm: LLMProvider) -> list[Critique]:
    """Run the Engineering critic over the current state."""
    return await run_critic(
        system_prompt=SYSTEM_PROMPT,
        critic_id="engineering",
        state=state,
        llm=llm,
    )


async def run_engineering_challenge(
    *,
    state: GraphState,
    llm: LLMProvider,
    previous_critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    round_n: int,
) -> list[CrossChallenge]:
    """Cross-challenge pass for the Engineering critic."""
    return await run_challenger(
        base_system_prompt=SYSTEM_PROMPT,
        critic_id="engineering",
        state=state,
        llm=llm,
        previous_critiques=previous_critiques,
        prior_challenges=prior_challenges,
        round_n=round_n,
    )


__doc_design__ = """
Design notes:
- Six-item checklist mirrors a real senior eng review. Rate limit / auth /
  idempotency / observability are called out because they are the most
  commonly missing non-functional requirements in first-draft PRDs.
- "Flag missing dependencies by name" nudges the model to produce specific,
  testable findings (e.g. "no mention of Stripe webhook idempotency key")
  rather than vague complaints.
- Line citations + skill_id semantics shared via critics/_shared.py so the
  Skill Library learning loop stays consistent across all four critics.
"""
