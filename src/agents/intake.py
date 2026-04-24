"""Intake agent — parses raw PRD into structured PRDClaim list.

NOTE: the PRD text fed to this agent MUST be preprocessed with
`src.graph.preprocess.number_lines`, which prepends each line with a literal
`[NNN] ` marker. The agent reads the marker rather than counting lines —
this is the fix for the line-number-hallucination failure mode.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from ..graph.state import PRDClaim
from ..llm.provider import LLMProvider
from ._parsing import extract_json

logger = logging.getLogger(__name__)


INTAKE_SYSTEM_PROMPT = """You are the PRD Intake agent.

Your job: read the PRD and split it into atomic claims. Do NOT evaluate quality.
Do NOT add claims that are not literally present in the text.

INPUT FORMAT
The PRD you receive has every line prefixed with a literal marker of the form
`[NNN] ` (3+ zero-padded digits, bracketed, followed by a space), for example:

    [001] # PRD Title
    [002]
    [003] ## Problem
    [004] Our support queue is overloaded.

You MUST NOT count lines yourself. When you need the line number of a claim,
read the integer inside the brackets at the start of that line and copy it.
If a claim spans multiple marked lines, use the marker of the line where the
claim begins.

For each claim emit:
- claim_id: short stable id (e.g. "C-001")
- source_line: the integer you read from the `[NNN]` marker (no counting)
- claim_text: the claim's exact sentence or bullet, WITH the `[NNN] ` marker
  stripped off and the text trimmed
- claim_type: one of "assumption" | "requirement" | "metric" | "scope"

Type rules:
- "metric" — anything stating a number, KPI, target, or measurable outcome
- "requirement" — an explicit "must / will / shall" behavior
- "scope" — statements about what IS or IS NOT included in the launch
- "assumption" — everything else the PRD asserts as true without proof

Output JSON only, no prose:
{
  "claims": [
    {"claim_id": "...", "source_line": N, "claim_text": "...", "claim_type": "..."}
  ]
}

If the PRD is empty or unparseable, return {"claims": []}.
If a line has no `[NNN]` marker, skip it — do not invent a number for it.
"""


async def run_intake(prd_text: str, llm: LLMProvider) -> list[PRDClaim]:
    """Call the LLM with INTAKE_SYSTEM_PROMPT, parse claims, graceful-degrade.

    Returns an empty list on any parse / validation failure, logging a warning.
    The caller is responsible for number-prefixing the PRD via
    `src.graph.preprocess.number_lines` before invoking this function.
    """
    user_msg = f"PRD (line-numbered):\n\n{prd_text}\n\nReturn the claims JSON now."
    response = await llm.complete(system=INTAKE_SYSTEM_PROMPT, user=user_msg)

    obj = extract_json(response.text)
    if not obj or "claims" not in obj:
        logger.warning("run_intake: no 'claims' key in response")
        return []

    claims: list[PRDClaim] = []
    for raw in obj.get("claims", []):
        try:
            claims.append(PRDClaim.model_validate(raw))
        except ValidationError as e:
            logger.warning("run_intake: dropped invalid claim %r: %s", raw, e)
    return claims


__doc_design__ = """
Design notes:
- Intake is intentionally non-judgmental; critics handle evaluation.
- Structured atomic claims let downstream critics cite claim_id in evidence,
  which keeps `Critique.evidence` grounded instead of hallucinated.
- Line-number handling: LLMs do not natively count physical lines, so the
  pipeline pre-numbers input via `src.graph.preprocess.number_lines` and the
  prompt instructs the model to COPY the bracketed integer rather than COUNT.
- Parse failures return [] rather than raising — the pipeline degrades to
  "no claims extracted" rather than crashing the entire graph run.
"""
