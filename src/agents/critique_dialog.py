"""Critique dialog — HITL follow-up conversation with a single critic.

Independent of the main LangGraph. Given a critic_id, the original Critique,
the PRD text, and a running chat history, this module streams the critic's
next reply word-by-word.

Design choices:
- Reuses each critic's full SYSTEM_PROMPT (loaded via `_CRITIC_REGISTRY`),
  appending a dialog-mode preamble so the model stays in character but
  switches to short conversational responses instead of JSON critiques.
- The whole conversation is flattened into the `user` argument on the single
  `llm.stream(system, user)` call, because the provider interface is
  stateless. This is fine at the volumes we expect (<= 5 rounds).
- Hard 5-round cap enforced in Python, not in the prompt. Once reached, we
  still stream one last reply but append a short "discussion cap reached"
  postscript so the UI can freeze the input without a mid-stream cutoff.
"""

from __future__ import annotations

from typing import AsyncIterator

from ..graph.state import Critique
from ..llm.provider import LLMProvider
from .critics.business import SYSTEM_PROMPT as BUSINESS_PROMPT
from .critics.design import SYSTEM_PROMPT as DESIGN_PROMPT
from .critics.engineering import SYSTEM_PROMPT as ENGINEERING_PROMPT
from .critics.user_advocate import SYSTEM_PROMPT as USER_ADVOCATE_PROMPT


MAX_DIALOG_ROUNDS = 5

_CRITIC_REGISTRY: dict[str, str] = {
    "user_advocate": USER_ADVOCATE_PROMPT,
    "engineering": ENGINEERING_PROMPT,
    "business": BUSINESS_PROMPT,
    "design": DESIGN_PROMPT,
}


_DIALOG_PREAMBLE_TEMPLATE = """\

---
DIALOG MODE — you are now in a follow-up discussion about an earlier critique.

You previously reviewed a PRD and produced this critique:

  critic_id:      {critic_id}
  claim_id:       {claim_id}
  severity:       {severity}
  finding:        {finding}
  evidence:       {evidence}
  suggested_fix:  {suggested_fix}

A product manager now wants to discuss this issue with you. Respond in your
role's voice (not as a generic assistant), keep each reply short — 2-4
sentences — and stay grounded in the original critique and the PRD text.

Hard rules in dialog mode:
- Do NOT invent new findings, new severities, or new evidence lines.
- Do NOT emit JSON. Plain prose only.
- If the PM pushes on severity, you may defend or concede — but explain why.
- If you genuinely don't know, say so. No fabrication.
"""


def _count_user_turns(conversation_history: list[dict]) -> int:
    return sum(1 for m in conversation_history if m.get("role") == "user")


def _build_system_prompt(critic_id: str, critique: Critique) -> str:
    """Append the dialog-mode preamble to the critic's base system prompt."""
    base = _CRITIC_REGISTRY.get(critic_id)
    if base is None:
        # Fall back to a minimal role prompt rather than raising — keeps the
        # UI resilient against typos or custom critic ids.
        base = f"You are the {critic_id} critic in a PRD stress-test panel."
    preamble = _DIALOG_PREAMBLE_TEMPLATE.format(
        critic_id=critique.critic_id,
        claim_id=critique.claim_id,
        severity=critique.severity,
        finding=critique.finding,
        evidence=critique.evidence,
        suggested_fix=critique.suggested_fix,
    )
    return base + preamble


def _build_user_message(
    prd_text: str,
    critique: Critique,
    conversation_history: list[dict],
) -> str:
    """Flatten PRD + critique + chat log into a single user-turn string.

    Format:
      PRD (line-numbered):
        ...
      Original critique: {...}
      --- conversation ---
      PM: ...
      {critic_id}: ...
      PM: ...
      (next turn is yours — reply as {critic_id})
    """
    header = (
        "PRD (line-numbered):\n\n"
        f"{prd_text}\n\n"
        "Original critique under discussion:\n"
        f"  {critique.critic_id}:{critique.claim_id} "
        f"[{critique.severity}] {critique.finding}\n\n"
    )
    lines = ["--- conversation so far ---"]
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        label = "PM" if role == "user" else critique.critic_id
        lines.append(f"{label}: {content}")
    lines.append(f"(Next turn is yours — reply as {critique.critic_id}.)")
    return header + "\n".join(lines)


async def run_critique_dialog(
    critic_id: str,
    original_critique: Critique,
    prd_text: str,
    conversation_history: list[dict],
    llm: LLMProvider,
) -> AsyncIterator[dict]:
    """Stream the critic's next reply.

    Yields `{"type": "text", "delta": str}` chunks matching the LLMProvider
    streaming contract. After the underlying stream completes, if the
    conversation has reached `MAX_DIALOG_ROUNDS` user turns (counting the
    current one just added by the UI), an additional terminator chunk is
    yielded so the UI can freeze further input.
    """
    system = _build_system_prompt(critic_id, original_critique)
    user = _build_user_message(prd_text, original_critique, conversation_history)

    async for chunk in llm.stream(system=system, user=user):
        # Forward only text deltas; the provider contract allows other chunk
        # types (e.g. thinking) which we don't surface in the dialog UI.
        if chunk.get("type") == "text":
            yield chunk

    # Round cap: count how many user turns are in history. If we've hit the
    # limit, append a short terminator note so the UI can display it and
    # disable the input.
    user_turns = _count_user_turns(conversation_history)
    if user_turns >= MAX_DIALOG_ROUNDS:
        yield {
            "type": "text",
            "delta": (
                "\n\n_本次讨论已达上限（5 轮），建议保存关键结论。_"
            ),
        }


__doc_design__ = """
Design notes:
- Dialog mode is intentionally stateless on the provider side. Flattening the
  conversation into the `user` turn means this module works identically
  against OpenAI (which has native message arrays) and MockProvider (which
  does not) — the OpenAI adapter can optionally split the flattened log
  back out into role-tagged messages if that produces better outputs.
- Reusing each critic's SYSTEM_PROMPT (rather than a generic dialog prompt)
  preserves the role lens — engineering still reasons about systems, user
  advocate still about users — even inside a follow-up exchange.
- The 5-round cap is enforced here, not in the prompt, because prompts can
  be cajoled. A hard Python cap is the correct place for a policy limit.
- The terminator is emitted AFTER the model's reply, not instead of it, so
  the last exchange still feels natural; only the next input is disabled.
"""
