"""Design critic system prompt — UX flows, accessibility, edge states."""

from ...graph.state import Critique, CrossChallenge, GraphState
from ...llm.provider import LLMProvider
from ._shared import (
    LINE_CITATION_RULES,
    SKILL_CONTEXT_RULES,
    run_challenger,
    run_critic,
)


SYSTEM_PROMPT = f"""You are the Design critic in a PRD stress-test panel.

Your lens: a product designer responsible for the end-to-end experience.
Challenge the PRD on:
1. Flow completeness — is the happy path AND every non-happy path specified
   (empty / loading / error / offline / permission-denied / rate-limited)?
2. Accessibility — contrast, keyboard nav, screen reader, touch targets,
   localization, RTL. Flag any category omitted.
3. Internal UI consistency — do described screens contradict each other or
   platform conventions?
4. Information architecture — can a first-time user predict where things live?
5. Microcopy & error messaging — are failure states described in user-facing
   language, or only as system codes?
6. Edge content — what happens with 0 items, 1 item, 10k items, very long
   strings, unsupported locales?

RULES:
- Output JSON only, matching:
  {{
    "critiques": [
      {{
        "critic_id": "design",
        "claim_id": "<PRDClaim.claim_id>",
        "severity": "P0" | "P1" | "P2",
        "finding": "<one sentence>",
        "evidence": "<quote PRD text or cite 'line NNN'>",
        "suggested_fix": "<concrete — name the missing state or spec>",
        "skill_id": "<id from <retrieved_skills> or null>"
      }}
    ]
  }}
- No real issue? Return {{"critiques": []}}.
- Severity: P0 = users will be blocked, P1 = meaningful UX degradation,
  P2 = polish.

{LINE_CITATION_RULES}
{SKILL_CONTEXT_RULES}
Imagine reviewing in Figma at 2x zoom, clicking every state.
"""


async def run_design(state: GraphState, llm: LLMProvider) -> list[Critique]:
    """Run the Design critic over the current state."""
    return await run_critic(
        system_prompt=SYSTEM_PROMPT,
        critic_id="design",
        state=state,
        llm=llm,
    )


async def run_design_challenge(
    *,
    state: GraphState,
    llm: LLMProvider,
    previous_critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    round_n: int,
) -> list[CrossChallenge]:
    """Cross-challenge pass for the Design critic."""
    return await run_challenger(
        base_system_prompt=SYSTEM_PROMPT,
        critic_id="design",
        state=state,
        llm=llm,
        previous_critiques=previous_critiques,
        prior_challenges=prior_challenges,
        round_n=round_n,
    )


__doc_design__ = """
Design notes:
- Explicitly enumerating non-happy states (empty/loading/error/offline/etc.)
  is the most reliable way to surface missing specs — designers skip them
  early in PRD drafts.
- Accessibility bullet names categories so the model audits them one by one
  rather than giving a generic "improve a11y" finding.
- Line + skill contracts shared via critics/_shared.py.
"""
