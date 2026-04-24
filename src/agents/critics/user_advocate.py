"""User Advocate critic system prompt — challenges user value and problem framing."""

from ...graph.state import Critique, CrossChallenge, GraphState
from ...llm.provider import LLMProvider
from ._shared import (
    LINE_CITATION_RULES,
    SKILL_CONTEXT_RULES,
    run_challenger,
    run_critic,
)


SYSTEM_PROMPT = f"""You are the User Advocate critic in a PRD stress-test panel.

Your lens: the real user. Challenge the PRD on:
1. User value — does this actually solve a real pain, or is it founder-fiction?
2. Problem evidence — is the pain point backed by data (interviews, tickets, analytics)
   or merely asserted?
3. Right problem — could the stated problem be a symptom of a deeper one?
4. User segment clarity — is the target user specific, or a vague "everyone"?
5. Behavior-change assumption — does the PRD assume users will change habits
   without justification?

RULES:
- Output JSON only, matching this schema:
  {{
    "critiques": [
      {{
        "critic_id": "user_advocate",
        "claim_id": "<PRDClaim.claim_id you are critiquing>",
        "severity": "P0" | "P1" | "P2",
        "finding": "<one sentence>",
        "evidence": "<quote PRD text or cite 'line NNN' — see INPUT FORMAT below>",
        "suggested_fix": "<concrete, actionable>",
        "skill_id": "<id from <retrieved_skills> or null — see RETRIEVED SKILLS>"
      }}
    ]
  }}
- If you find no real issue, return {{"critiques": []}}. Never pad.
- Severity: P0 = ship-blocker for users, P1 = significant UX risk, P2 = polish.

{LINE_CITATION_RULES}
{SKILL_CONTEXT_RULES}
Think like a user who will actually use this tomorrow.
"""


async def run_user_advocate(state: GraphState, llm: LLMProvider) -> list[Critique]:
    """Run the User Advocate critic over the current state."""
    return await run_critic(
        system_prompt=SYSTEM_PROMPT,
        critic_id="user_advocate",
        state=state,
        llm=llm,
    )


async def run_user_advocate_challenge(
    *,
    state: GraphState,
    llm: LLMProvider,
    previous_critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    round_n: int,
) -> list[CrossChallenge]:
    """Cross-challenge pass for the User Advocate critic."""
    return await run_challenger(
        base_system_prompt=SYSTEM_PROMPT,
        critic_id="user_advocate",
        state=state,
        llm=llm,
        previous_critiques=previous_critiques,
        prior_challenges=prior_challenges,
        round_n=round_n,
    )


__doc_design__ = """
Design notes:
- Role priming + numbered lens items keep output focused on user-facing risk
  rather than slipping into engineering or business critique territory.
- Evidence-quoting constraint is the single biggest defense against hallucinated
  findings; it forces the model to stay grounded in the PRD.
- Empty-list-is-allowed instruction prevents the classic "must find 5 things"
  padding failure mode observed in multi-critic setups.
- Line citations reference preprocessed `[NNN]` markers rather than model-
  counted line numbers — see src/graph/preprocess.py for the rationale.
- The `skill_id` field is a typed anchor for the Skill Library retriever loop:
  shared SKILL_CONTEXT_RULES govern when to emit an id vs null, and forbid
  inventing ids so the learning-loop telemetry stays trustworthy.
"""
