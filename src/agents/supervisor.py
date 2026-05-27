"""Supervisor agent — synthesizes critic outputs into a prioritized verdict.

Two entry points:
  * `run_supervisor_stream` — async generator yielding incremental events for
    live UI rendering. Parses the model's `<thinking>`/`<verdict>` XML stream
    on the fly, handling tag boundaries that fall mid-chunk.
  * `run_supervisor` — thin non-streaming wrapper that drains the stream and
    returns the final verdict dict. Used inside the LangGraph node.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from pydantic import ValidationError

from ..graph.state import Critique, CrossChallenge, GraphState, SupervisorVerdict
from ..llm.provider import LLMProvider
from ._language import system_with_language
from ._parsing import extract_json

logger = logging.getLogger(__name__)


SUPERVISOR_SYSTEM_PROMPT = """You are the Supervisor agent overseeing a PRD stress-test panel.

Inputs you will receive:
- The original PRD text
- The list of extracted PRDClaims
- All Critiques from the 4 critic agents (User Advocate, Engineering, Business, Design)
- Any CrossChallenges raised between critics

Your job:
1. Deduplicate critiques that describe the same underlying issue from different
   angles. Keep the sharpest formulation; note the multi-angle support.
2. Resolve conflicts where critics disagree. State the resolution and why.
3. Re-rank severity. A finding flagged P1 by three critics is effectively P0.
4. Produce a prioritized verdict grouped by severity.

OUTPUT FORMAT — you MUST use this exact XML structure:

<thinking>
Reason step-by-step about overlaps, conflicts, and severity escalation.
Cite specific critic_id + claim_id pairs.
</thinking>

<verdict>
{
  "executive_summary": "<2-3 sentences for a busy exec>",
  "p0_blockers": ["<issue 1>", "..."],
  "p1_concerns": ["<issue 1>", "..."],
  "p2_suggestions": ["<issue 1>", "..."],
  "conflict_resolutions": [
    "<statement of disagreement> -> <your resolution and rationale>"
  ]
}
</verdict>

RULES:
- Do not introduce new findings that no critic raised.
- If critics unanimously raise nothing, return empty lists — do not invent.
- Preserve claim_id references where possible so findings remain traceable.
- If any CrossChallenges are present in the input, you MUST surface them in
  `conflict_resolutions`. Each entry should name the challenger critic, the
  target critique, and your arbitration (who is right, or what compromise).
"""


# ---- XML streaming parser ---------------------------------------------------

_OPEN_THINK = "<thinking>"
_CLOSE_THINK = "</thinking>"
_OPEN_VERD = "<verdict>"
_CLOSE_VERD = "</verdict>"

# How many trailing chars we refuse to emit while still "inside" a section,
# in case a tag boundary straddles the next chunk. Longest tag is 11 chars;
# 20 is a comfortable margin.
_TAIL_GUARD = 20


def _format_supervisor_user_message(state: GraphState) -> str:
    """Pack PRD + claims + critiques + cross-challenges into the user turn."""
    prd_text = state.get("prd_text", "")
    claims = state.get("prd_claims", []) or []
    critiques: list[Critique] = state.get("critiques", []) or []
    challenges: list[CrossChallenge] = state.get("challenges", []) or []
    convergence = state.get("convergence_signal", False)
    rounds = state.get("challenge_round", 0)

    claims_json = json.dumps(
        [c.model_dump() for c in claims], ensure_ascii=False, indent=2
    )
    critiques_json = json.dumps(
        [c.model_dump() for c in critiques], ensure_ascii=False, indent=2
    )
    challenges_json = json.dumps(
        [c.model_dump() for c in challenges], ensure_ascii=False, indent=2
    )
    return (
        "PRD (line-numbered):\n\n"
        f"{prd_text}\n\n"
        "Extracted claims:\n"
        f"{claims_json}\n\n"
        "Critic findings:\n"
        f"{critiques_json}\n\n"
        f"Cross-challenges (rounds={rounds}, converged={convergence}):\n"
        f"{challenges_json}\n\n"
        "Produce your <thinking>/<verdict> XML now."
    )


def _empty_verdict(reason: str) -> dict:
    return {
        "executive_summary": f"parse failed: {reason}",
        "p0_blockers": [],
        "p1_concerns": [],
        "p2_suggestions": [],
        "conflict_resolutions": [],
    }


def _parse_verdict_json(verdict_text: str) -> dict:
    """Parse the inner-<verdict> JSON, falling back to an empty shape on error."""
    if not verdict_text.strip():
        return _empty_verdict("empty verdict block")
    obj = extract_json(verdict_text)
    if obj is None:
        return _empty_verdict("invalid JSON")
    try:
        # Validate shape; coerce missing keys to defaults via the model.
        model = SupervisorVerdict.model_validate(obj)
        return model.model_dump()
    except ValidationError as e:
        logger.warning("supervisor verdict failed schema validation: %s", e)
        # Accept loose shape rather than erroring — UI still has fields to render.
        base = _empty_verdict("schema mismatch")
        base.update({k: v for k, v in obj.items() if k in base})
        return base


async def run_supervisor_stream(
    state: GraphState, llm: LLMProvider
) -> AsyncIterator[dict]:
    """Yield supervisor events as the model streams.

    Event shapes:
      {"stage": "thinking", "delta": str}   — one or more text chunks inside <thinking>
      {"stage": "verdict",  "delta": str}   — one or more text chunks inside <verdict>
      {"stage": "done",     "final_verdict": dict}  — always the last event
    """
    user_msg = _format_supervisor_user_message(state)
    prd_text = state.get("prd_text", "") or ""
    system_prompt = system_with_language(SUPERVISOR_SYSTEM_PROMPT, prd_text)

    buffer = ""
    mode = "scan"  # scan | thinking | verdict | post_verdict
    verdict_text = ""  # accumulated raw text inside <verdict>...</verdict>

    async for chunk in llm.stream(system=system_prompt, user=user_msg):
        if chunk.get("type") != "text":
            continue
        buffer += chunk.get("delta", "")

        # Drain as much as possible from the buffer before awaiting next chunk.
        while True:
            if mode == "scan":
                ti = buffer.find(_OPEN_THINK)
                vi = buffer.find(_OPEN_VERD)
                candidates = [
                    (i, tag, new_mode)
                    for i, tag, new_mode in (
                        (ti, _OPEN_THINK, "thinking"),
                        (vi, _OPEN_VERD, "verdict"),
                    )
                    if i != -1
                ]
                if not candidates:
                    # Maybe a partial opening tag is still arriving; keep a tail.
                    if "<" in buffer[-_TAIL_GUARD:]:
                        buffer = buffer[-_TAIL_GUARD:]
                    else:
                        buffer = ""
                    break
                candidates.sort()
                idx, tag, new_mode = candidates[0]
                buffer = buffer[idx + len(tag) :]
                mode = new_mode
                continue

            if mode in ("thinking", "verdict"):
                close_tag = _CLOSE_THINK if mode == "thinking" else _CLOSE_VERD
                close_idx = buffer.find(close_tag)
                if close_idx != -1:
                    emitted = buffer[:close_idx]
                    if emitted:
                        if mode == "verdict":
                            verdict_text += emitted
                        yield {"stage": mode, "delta": emitted}
                    buffer = buffer[close_idx + len(close_tag) :]
                    mode = "scan" if mode == "thinking" else "post_verdict"
                    continue

                # No close tag yet. Hold back the last few chars in case they
                # contain the start of a close tag straddling the next chunk.
                if len(buffer) > _TAIL_GUARD:
                    emit = buffer[:-_TAIL_GUARD]
                    if emit:
                        if mode == "verdict":
                            verdict_text += emit
                        yield {"stage": mode, "delta": emit}
                    buffer = buffer[-_TAIL_GUARD:]
                break

            # post_verdict: ignore everything after </verdict>.
            buffer = ""
            break

    # Stream ended — flush whatever is left.
    if mode == "thinking" and buffer:
        yield {"stage": "thinking", "delta": buffer}
    elif mode == "verdict" and buffer:
        verdict_text += buffer
        yield {"stage": "verdict", "delta": buffer}

    yield {"stage": "done", "final_verdict": _parse_verdict_json(verdict_text)}


async def run_supervisor(state: GraphState, llm: LLMProvider) -> dict:
    """Non-streaming supervisor runner — drains the stream and returns the verdict."""
    final: dict | None = None
    async for event in run_supervisor_stream(state, llm):
        if event.get("stage") == "done":
            final = event["final_verdict"]
    return final or _empty_verdict("stream produced no 'done' event")


__doc_design__ = """
Design notes:
- The <thinking>/<verdict> split gives a parseable machine output while
  preserving reasoning for UI display and debugging. The XML tags are easy
  to regex out and survive JSON formatting errors in either half.
- Severity re-ranking rule (3xP1 -> P0) encodes consensus as a signal — this
  is the main value-add of having a supervisor vs. just concatenating critiques.
- The streaming parser is a 3-state machine (scan/thinking/verdict/post_verdict)
  that never emits characters that could turn out to be part of a boundary tag;
  it holds back a _TAIL_GUARD (20 chars) until it sees either the close tag or
  enough text to prove those chars were plain content.
- JSON parse failures degrade to a placeholder verdict dict, so the UI always
  has something to render and downstream nodes never crash.
"""
