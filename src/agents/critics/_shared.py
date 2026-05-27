"""Shared prompt fragments + run helper used across all critic agents.

Keeping these in one place means the Skill Library contract and the line-marker
contract evolve in lockstep across critics, instead of drifting per-file.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from ...graph.state import Critique, CrossChallenge, GraphState, PRDClaim
from ...llm.provider import LLMProvider
from ...skills import Skill, default_retriever, format_skills_block
from .._language import system_with_language
from .._parsing import extract_json

logger = logging.getLogger(__name__)


LINE_CITATION_RULES = """\
INPUT FORMAT
The PRD and every claim you see has been preprocessed: each PRD line is
prefixed with a literal `[NNN] ` marker, and each PRDClaim carries a
`source_line` that matches one of those markers. You MUST use those markers
when citing evidence — do NOT count lines yourself.

Accepted evidence formats:
  - A direct quote from the PRD enclosed in double quotes.
  - An explicit line reference of the form `line NNN` matching an existing
    `[NNN]` marker.
  - Ideally both — e.g. `line 042: "Retry up to 3 times over 24 hours"`.

If you cannot cite the PRD verbatim, do not emit the critique.
"""

SKILL_CONTEXT_RULES = """\
RETRIEVED SKILLS (dynamic context)
Before your critique you MAY receive a `<retrieved_skills>` block, placed by
the Skill Library retriever. Its shape is:

  <retrieved_skills>
    <skill id="SK-042" name="metric-triple-check">
      A metric is incomplete unless it states (baseline, target, window).
    </skill>
    <skill id="SK-017" name="stripe-idempotency-key">
      Retried Stripe charges must carry an Idempotency-Key header.
    </skill>
  </retrieved_skills>

Rules for using skills:
1. If a retrieved skill directly informed a finding, set `skill_id` on that
   critique to the skill's id (e.g. "SK-042"). One skill per critique.
2. If no retrieved skill applies to a critique, set `skill_id` to null.
3. NEVER emit a `skill_id` that is not present in the `<retrieved_skills>`
   block. Do not invent ids. Do not reuse ids you remember from training.
4. If no `<retrieved_skills>` block is provided, treat it as empty and set
   every `skill_id` to null.
5. A skill is a heuristic, not a mandate — if a retrieved skill does not
   actually apply to this PRD, ignore it rather than forcing a finding.

This `skill_id` field is the telemetry that closes the skill-learning loop;
emitting accurate ids (or honest nulls) is load-bearing for the eval harness.
"""


def _format_user_message(
    prd_text: str,
    claims: list[PRDClaim],
    skills_block: str = "",
) -> str:
    """Shape the user-turn payload given to every critic.

    If `skills_block` is non-empty, it is prepended as a `<retrieved_skills>`
    XML section — critics' SKILL_CONTEXT_RULES instruct them to cite those
    ids (and only those ids) on any critique the skill informed.
    """
    claims_json = json.dumps(
        [c.model_dump() for c in claims], ensure_ascii=False, indent=2
    )
    prefix = f"{skills_block}\n\n" if skills_block else ""
    return (
        f"{prefix}"
        "PRD (line-numbered):\n\n"
        f"{prd_text}\n\n"
        "Extracted claims:\n"
        f"{claims_json}\n\n"
        "Produce your critique JSON now."
    )


async def run_critic(
    *,
    system_prompt: str,
    critic_id: str,
    state: GraphState,
    llm: LLMProvider,
) -> list[Critique]:
    """Generic critic runner — shared by user_advocate / engineering / business / design.

    Calls the LLM, parses the JSON envelope, validates each critique, forces the
    `critic_id` field to the caller's identity (even if the model emits a
    different value). Returns [] on any parse / validation failure.
    """
    prd_text = state.get("prd_text", "")
    claims = state.get("prd_claims", []) or []

    # Retrieve relevant skills for this critic — injected as <retrieved_skills>
    # in the user message. Graceful fallback: on any retrieval error we proceed
    # without skills rather than blocking the critique.
    retrieved: list[Skill] = []
    try:
        retrieved = default_retriever().retrieve(prd_text, critic_id)
    except Exception as e:  # pragma: no cover — retriever is defensive
        logger.warning("run_critic[%s]: skill retrieval failed: %s", critic_id, e)
    skills_block = format_skills_block(retrieved)
    retrieved_ids = [s.id for s in retrieved]

    user_msg = _format_user_message(prd_text, claims, skills_block)
    # Append a Chinese-output directive to the system prompt iff the PRD
    # is Chinese — keeps the human-readable fields in the PRD's language
    # while leaving JSON keys / severity enum / skill_ids in English so
    # parsers don't break.
    response = await llm.complete(
        system=system_with_language(system_prompt, prd_text),
        user=user_msg,
    )

    obj = extract_json(response.text)
    if not obj or "critiques" not in obj:
        logger.warning("run_critic[%s]: no 'critiques' key in response", critic_id)
        return []

    out: list[Critique] = []
    for raw in obj.get("critiques", []):
        if isinstance(raw, dict):
            raw["critic_id"] = critic_id  # trust the caller, not the model
            # If the model didn't name a skill but a skill was retrieved,
            # tag the first retrieved skill so we still emit telemetry
            # linking critiques back to the library. Callers can tell the
            # difference from model-attributed skill_ids via the call_log.
            if not raw.get("skill_id") and retrieved_ids:
                raw["skill_id"] = retrieved_ids[0]
            # Guardrail: never let a hallucinated skill id through.
            if raw.get("skill_id") and raw["skill_id"] not in retrieved_ids:
                logger.warning(
                    "run_critic[%s]: dropping hallucinated skill_id %r",
                    critic_id,
                    raw["skill_id"],
                )
                raw["skill_id"] = None
        try:
            out.append(Critique.model_validate(raw))
        except ValidationError as e:
            logger.warning(
                "run_critic[%s]: dropped invalid critique %r: %s", critic_id, raw, e
            )
    return out


# ---- Cross-challenge support -----------------------------------------------

CHALLENGE_INSTRUCTION_TEMPLATE = """\

---
CROSS-CHALLENGE MODE — Round {round}

You have already produced your own critiques. You now see the OTHER critics'
findings and any prior cross-challenges. Your task here is NOT to add new
independent findings but to:
  1. Disagree with another critic's finding where you believe they are wrong.
  2. Add an angle they missed that only your lens would catch.
  3. Abstain — return an empty list — if you have nothing sharp to add.

Output JSON only:
{{
  "challenges": [
    {{
      "round": {round},
      "challenger": "{critic_id}",
      "target_critique_id": "<critic_id>:<claim_id> you are challenging",
      "counter_finding": "<one concrete sentence>"
    }}
  ]
}}

An empty `challenges` list is a valid and often correct answer. Do NOT pad.
"""


def _format_challenger_user_message(
    prd_text: str,
    critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    self_critic_id: str,
) -> str:
    others = [c for c in critiques if c.critic_id != self_critic_id]
    others_json = json.dumps(
        [c.model_dump() for c in others], ensure_ascii=False, indent=2
    )
    priors_json = json.dumps(
        [c.model_dump() for c in prior_challenges], ensure_ascii=False, indent=2
    )
    return (
        "PRD (line-numbered):\n\n"
        f"{prd_text}\n\n"
        "Other critics' findings:\n"
        f"{others_json}\n\n"
        "Prior cross-challenges (earlier rounds):\n"
        f"{priors_json}\n\n"
        "Produce your challenges JSON now."
    )


async def run_challenger(
    *,
    base_system_prompt: str,
    critic_id: str,
    state: GraphState,
    llm: LLMProvider,
    previous_critiques: list[Critique],
    prior_challenges: list[CrossChallenge],
    round_n: int,
) -> list[CrossChallenge]:
    """Generic cross-challenge runner shared by all four critics.

    Returns an empty list on parse / validation failure (graceful degrade).
    Forces `challenger = critic_id` and `round = round_n` post-parse so a
    misbehaving model cannot spoof either field.
    """
    system_prompt = base_system_prompt + CHALLENGE_INSTRUCTION_TEMPLATE.format(
        round=round_n, critic_id=critic_id
    )
    prd_text = state.get("prd_text", "")
    user_msg = _format_challenger_user_message(
        prd_text, previous_critiques, prior_challenges, critic_id
    )

    response = await llm.complete(
        system=system_with_language(system_prompt, prd_text),
        user=user_msg,
    )
    obj = extract_json(response.text)
    if not obj or "challenges" not in obj:
        logger.warning(
            "run_challenger[%s, round=%d]: no 'challenges' key in response",
            critic_id,
            round_n,
        )
        return []

    out: list[CrossChallenge] = []
    for raw in obj.get("challenges", []):
        if isinstance(raw, dict):
            raw["challenger"] = critic_id
            raw["round"] = round_n
        try:
            out.append(CrossChallenge.model_validate(raw))
        except ValidationError as e:
            logger.warning(
                "run_challenger[%s, round=%d]: dropped invalid challenge %r: %s",
                critic_id,
                round_n,
                raw,
                e,
            )
    return out
