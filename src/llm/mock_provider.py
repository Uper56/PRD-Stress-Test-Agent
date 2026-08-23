"""Mock LLM provider used before a real API key is wired up.

Returns deterministic canned responses keyed off keywords in the system prompt,
so downstream agents can be exercised end-to-end without network calls.

Canned payloads are intentionally shape-compatible with the real agent output
schemas (PRDClaim, Critique) so that the pipeline's JSON parsers do not have
to branch on "is this mock data". A top-level `role` field is preserved for
routing tests and debug logs.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import AsyncIterator

from .provider import LLMProvider, LLMResponse


_CANNED: dict[str, dict] = {
    "intake": {
        "role": "intake",
        "claims": [
            {
                "claim_id": "C-001",
                "source_line": 1,
                "claim_text": "Mock top-line claim extracted from the PRD.",
                "claim_type": "assumption",
            },
            {
                "claim_id": "C-002",
                "source_line": 2,
                "claim_text": "Deflect 40% of inbound tickets.",
                "claim_type": "metric",
            },
            {
                "claim_id": "C-003",
                "source_line": 3,
                "claim_text": "Ship to 100% of users on Day 1.",
                "claim_type": "scope",
            },
        ],
    },
    "user advocate": {
        "role": "user_advocate",
        "critiques": [
            {
                "critic_id": "user_advocate",
                "claim_id": "C-001",
                "severity": "P1",
                "finding": "Onboarding path for first-time users is not described.",
                "evidence": 'line 1: "Mock top-line claim extracted from the PRD."',
                "suggested_fix": "Specify the first-run experience for new accounts.",
                "skill_id": None,
            }
        ],
    },
    "engineering": {
        "role": "engineering",
        "critiques": [
            {
                "critic_id": "engineering",
                "claim_id": "C-001",
                "severity": "P1",
                "finding": "No rate-limit strategy is defined for the public endpoint.",
                "evidence": 'line 1: "Mock top-line claim extracted from the PRD."',
                "suggested_fix": "Add a token-bucket rate limiter at the API gateway.",
                "skill_id": None,
            }
        ],
    },
    "business": {
        "role": "business",
        "critiques": [
            {
                "critic_id": "business",
                "claim_id": "C-002",
                "severity": "P0",
                "finding": "Success metric lacks baseline and measurement window.",
                "evidence": 'line 2: "Deflect 40% of inbound tickets."',
                "suggested_fix": "Add current baseline volume and a 30-day window.",
                "skill_id": None,
            }
        ],
    },
    "design": {
        "role": "design",
        "critiques": [
            {
                "critic_id": "design",
                "claim_id": "C-001",
                "severity": "P2",
                "finding": "Error states are not defined for the primary flow.",
                "evidence": 'line 1: "Mock top-line claim extracted from the PRD."',
                "suggested_fix": "Add empty / loading / error / offline state specs.",
                "skill_id": None,
            }
        ],
    },
    # Supervisor is handled specially below — it returns an XML envelope, not
    # a bare JSON object — so it is keyed separately from the JSON responders.
}


_SUPERVISOR_VERDICT: dict = {
    "executive_summary": (
        "One P0 blocker on metric quality plus two P1 ops / UX concerns; "
        "ship is gated on tightening the success metric."
    ),
    "p0_blockers": ["Success metric lacks baseline and measurement window."],
    "p1_concerns": [
        "Onboarding path for first-time users is not described.",
        "No rate-limit strategy is defined for the public endpoint.",
    ],
    "p2_suggestions": ["Define non-happy UI states (empty / loading / error)."],
    "conflict_resolutions": [
        "user_advocate challenged business:C-002 — resolution: keep business's "
        "P0 on metric baseline/window, but require a paired qualitative signal.",
        "engineering challenged design:C-001 — resolution: design P2 stands; "
        "scope full state matrix as a phased follow-up.",
    ],
}

# Mock supervisor response uses the XML envelope the real model is prompted
# for. Tokens are space-separated so the word-splitting stream() emits chunks
# that are realistic and the <thinking>/<verdict> tags stay intact.
_SUPERVISOR_TEXT = (
    "<thinking>\n"
    "Four critics produced four findings. Business flagged a P0 on metric "
    "quality (C-002) which outranks the UX P1s from user_advocate and design. "
    "No direct contradictions between critics — engineering's rate-limit "
    "finding and user_advocate's onboarding finding are independent concerns. "
    "No severity escalation from consensus is needed.\n"
    "</thinking>\n"
    "<verdict>\n"
)
_SUPERVISOR_TEXT += json.dumps(_SUPERVISOR_VERDICT, ensure_ascii=False)
_SUPERVISOR_TEXT += "\n</verdict>"


# ---- Cross-challenge canned responses --------------------------------------
# Round 1: each critic pushes back on exactly one other critic's finding.
# Round 2: everyone abstains, which triggers the "empty new round" convergence
# path in edges.run_cross_challenge.

def _critic_from_prompt(system_lower: str) -> str | None:
    for keyword, critic_id in (
        ("user advocate", "user_advocate"),
        ("engineering", "engineering"),
        ("business", "business"),
        ("design", "design"),
    ):
        if keyword in system_lower:
            return critic_id
    return None


_CHALLENGES_ROUND_1: dict[str, list[dict]] = {
    "user_advocate": [
        {
            "round": 1,
            "challenger": "user_advocate",
            "target_critique_id": "business:C-002",
            "counter_finding": (
                "Quantitative baseline/window alone misses qualitative "
                "signals users give in interviews."
            ),
        }
    ],
    "engineering": [
        {
            "round": 1,
            "challenger": "engineering",
            "target_critique_id": "design:C-001",
            "counter_finding": (
                "Full non-happy state matrix exceeds the stated build budget; "
                "phase it in rather than blocking launch."
            ),
        }
    ],
    "business": [
        {
            "round": 1,
            "challenger": "business",
            "target_critique_id": "engineering:C-001",
            "counter_finding": (
                "Rate-limit spend is unjustified without a revenue-at-risk "
                "number — cheaper guardrail may suffice."
            ),
        }
    ],
    "design": [],  # nothing to challenge in round 1
}


def _match_challenge(system_lower: str) -> dict:
    """Return a canned challenges payload keyed by critic + round.

    Round 2 returns empty lists across the board, triggering the empty-new-round
    convergence branch in edges.run_cross_challenge.
    """
    round_n = 2 if "round 2" in system_lower else 1
    critic = _critic_from_prompt(system_lower)
    if critic is None:
        return {"challenges": []}
    if round_n == 1:
        return {"challenges": _CHALLENGES_ROUND_1.get(critic, [])}
    # Round 2: everyone abstains.
    return {"challenges": []}


_DIALOG_FLAVOR: dict[str, str] = {
    "user_advocate": (
        "From the user's side: this ranking is about real friction, not "
        "polish. If the onboarding path is undefined, first-run users drop "
        "off before they see any value. That's why I held it at P1 — not "
        "because it's catastrophic, but because user trust is fragile early."
    ),
    "engineering": (
        "Technically, the concern is load predictability. Without a rate-"
        "limit policy the gateway can be starved by a single noisy client, "
        "which is a systems risk, not a UX one. I'd be willing to drop the "
        "severity if there's already an upstream guard — is there?"
    ),
    "business": (
        "From a commercial lens: a metric without baseline and window can "
        "neither be measured nor defended at review. That's why I called "
        "this P0 — it blocks OKR alignment downstream, not just the launch."
    ),
    "design": (
        "Design-wise, the non-happy states are where user trust is actually "
        "built or broken. I kept this at P2 because the main flow still "
        "works, but error/empty/offline should not be deferred indefinitely "
        "— they're the polish that compounds."
    ),
}


def _dialog_flavor_for(system_lower: str) -> str:
    critic = _critic_from_prompt(system_lower)
    if critic is None:
        return (
            "Thanks for the follow-up. My original reasoning still holds, "
            "but I'm open to adjusting the severity if you can show me "
            "contradicting evidence in the PRD."
        )
    return _DIALOG_FLAVOR[critic]


# ---- Skill distillation canned response (Day 9) ----------------------------


# A library of fake distiller proposals, keyed by `critic_id`. The mock picks
# one based on the cluster the user message advertises, so different critic
# clusters produce visibly different proposals (helpful for the Streamlit
# review panel).
_DISTILLER_PROPOSALS: dict[str, dict] = {
    "engineering": {
        "proposed_name": "retry-budget-discipline",
        "injected_into": ["engineering"],
        "generalization_score": 0.84,
        "proposed_skill_md": (
            "---\n"
            "name: retry-budget-discipline\n"
            "description: Use this skill WHENEVER the PRD describes any retry, "
            "fallback, or queue without naming a per-request retry cap, total "
            "budget, or backoff schedule. Unbounded retries are how minor "
            "outages turn into stampedes — the PRD MUST state limits.\n"
            'version: "1.0"\n'
            "created_by: distiller\n"
            "injected_into:\n  - engineering\n"
            "trigger_keywords: [retry, fallback, queue, backoff, timeout]\n"
            "trigger_semantic: PRD mentions retries / fallbacks without naming a budget.\n"
            "confidence: 0.78\n"
            "---\n\n"
            "# Skill: Retry Budget Discipline\n\n"
            "## When to apply\nThe PRD describes any retry, fallback, queue, or backoff without bounds.\n\n"
            "## Instruction\nVerify per-request retry cap, total retry budget, jitter, and circuit-break threshold.\n\n"
            "## Rationale\nUnbounded retries amplify dependency outages into stampedes.\n\n"
            "## Examples of issues this catches\n- 'We will retry on failure' with no max-attempts.\n"
            "- Background queue with no DLQ.\n"
            "- Exponential backoff without jitter on a fan-in path.\n"
        ),
    },
    "business": {
        "proposed_name": "guardrail-metric-required",
        "injected_into": ["business"],
        "generalization_score": 0.81,
        "proposed_skill_md": (
            "---\n"
            "name: guardrail-metric-required\n"
            "description: Use this skill EVERY TIME the PRD names a primary "
            "success metric. The PRD MUST also name a paired guardrail metric "
            "that must NOT regress, otherwise the team can hit the target by "
            "harming an unrelated outcome. Apply firmly to all KPI / OKR claims.\n"
            'version: "1.0"\n'
            "created_by: distiller\n"
            "injected_into:\n  - business\n"
            "trigger_keywords: [target, kpi, okr, lift, increase, conversion]\n"
            "trigger_semantic: PRD names a success metric but no paired guardrail.\n"
            "confidence: 0.75\n"
            "---\n\n"
            "# Skill: Guardrail Metric Required\n\n"
            "## When to apply\nThe PRD names any success metric / KPI / OKR.\n\n"
            "## Instruction\nVerify a paired guardrail metric is named with a non-regression threshold.\n\n"
            "## Rationale\nWithout a guardrail, a metric can be hit by harming a paired outcome.\n\n"
            "## Examples of issues this catches\n- 'Lift conversion 10%' with no NPS / refund-rate guardrail.\n"
            "- 'Reduce ticket volume' gamed by hiding the help link.\n"
            "- Engagement uplift paired with retention regression.\n"
        ),
    },
    "user_advocate": {
        "proposed_name": "user-segment-recency",
        "injected_into": ["user_advocate"],
        "generalization_score": 0.79,
        "proposed_skill_md": (
            "---\n"
            "name: user-segment-recency\n"
            "description: Use this skill ANY TIME the PRD cites user "
            "evidence (interviews, tickets, analytics) without naming the "
            "cohort and the recency of the data. Stale evidence from a "
            "different cohort is weaker than no evidence — flag it.\n"
            'version: "1.0"\n'
            "created_by: distiller\n"
            "injected_into:\n  - user_advocate\n"
            "trigger_keywords: [interviews, tickets, survey, cohort, analytics]\n"
            "trigger_semantic: User evidence cited without cohort + recency.\n"
            "confidence: 0.72\n"
            "---\n\n"
            "# Skill: User Segment + Recency\n\n"
            "## When to apply\nUser evidence is cited without specifying cohort or when it was collected.\n\n"
            "## Instruction\nVerify cohort name + collection date + sample size.\n\n"
            "## Rationale\nEvidence from the wrong segment or 18 months stale is misleading.\n\n"
            "## Examples of issues this catches\n- 'Customers asked for X' with no cohort.\n"
            "- Tickets from a redesigned-since flow.\n"
            "- B2B PRD citing B2C survey.\n"
        ),
    },
    "design": {
        "proposed_name": "non-happy-state-spec",
        "injected_into": ["design"],
        "generalization_score": 0.77,
        "proposed_skill_md": (
            "---\n"
            "name: non-happy-state-spec\n"
            "description: Use this skill ANY TIME the PRD specifies a UI "
            "flow without explicitly listing empty / loading / error / "
            "offline states. The non-happy states are where trust is built "
            "or broken — flag missing specs as P1 minimum.\n"
            'version: "1.0"\n'
            "created_by: distiller\n"
            "injected_into:\n  - design\n"
            "trigger_keywords: [flow, screen, modal, list, table, error]\n"
            "trigger_semantic: UI flow specified without enumerated non-happy states.\n"
            "confidence: 0.74\n"
            "---\n\n"
            "# Skill: Non-Happy State Spec\n\n"
            "## When to apply\nThe PRD specifies a UI flow without listing empty / loading / error / offline states.\n\n"
            "## Instruction\nFor each surface, verify the four non-happy states are specified.\n\n"
            "## Rationale\nNon-happy states are where users build or lose trust.\n\n"
            "## Examples of issues this catches\n- New list with no empty state.\n"
            "- Submit flow with no error toast spec.\n"
            "- Mobile view with no offline behavior.\n"
        ),
    },
}


def _match_distiller(user: str) -> dict:
    """Pick a fake proposal based on which critic_id the cluster is from.

    The distiller's user prompt embeds `critic_id="..."` — we sniff for
    that so different clusters produce visibly different proposals.
    """
    for cid in ("engineering", "business", "user_advocate", "design"):
        if f'critic_id="{cid}"' in user:
            return _DISTILLER_PROPOSALS[cid]
    # Fallback: return the first proposal so a malformed cluster still
    # exercises the validate/persist path.
    return next(iter(_DISTILLER_PROPOSALS.values()))


# ---- Skill-on critic extensions (Day 10 ablation visibility) ---------------
#
# When a `<retrieved_skills>` block is present in the user message AND we're
# answering a plain-critic prompt, we return EXTRA critiques on top of the
# baseline canned ones. Each extra is targeted at a defect dimension common
# across the golden manifest (risk_management / dependency_identification /
# internal_contradiction / scope_ambiguity), so the rubric's recall scores
# move measurably higher under skill_on vs skill_off — exactly the ablation
# signal a real LLM would produce when given skill context.
#
# The extras are crafted to look like the golden defect notes so
# `_match_critiques_to_defects` picks them up via difflib fuzzy matching.

_SKILL_ON_EXTRAS: dict[str, list[dict]] = {
    "user_advocate": [
        {
            "critic_id": "user_advocate",
            "claim_id": "C-001",
            "severity": "P1",
            "finding": (
                "User-pain claims are not backed by named evidence — no "
                "ticket tag, interview cohort, or analytics cite."
            ),
            "evidence": 'line 1: "users feel lost / users want X / customers complain"',
            "suggested_fix": (
                "Add a citable evidence source (Zendesk tag, Amplitude cohort, "
                "or interview sample size) for every user-pain assertion."
            ),
            "skill_id": None,
        },
    ],
    "engineering": [
        {
            "critic_id": "engineering",
            "claim_id": "C-001",
            "severity": "P0",
            "finding": (
                "No kill-switch / rollback / phased rollout. 100% launch on "
                "Day 1 has no staged ramp or numeric rollback criteria."
            ),
            "evidence": 'line: "Roll out to 100% of users on launch day"',
            "suggested_fix": (
                "Specify a staged rollout (1%→10%→50%→100%) with named "
                "rollback thresholds and kill-switch owner."
            ),
            "skill_id": None,
        },
        {
            "critic_id": "engineering",
            "claim_id": "C-001",
            "severity": "P1",
            "finding": (
                "Third-party dependencies not enumerated by name; no SLA "
                "assumption, no failure-mode handling, no idempotency."
            ),
            "evidence": 'line: "integrate with payment provider / LLM provider / email service"',
            "suggested_fix": (
                "Enumerate every external dependency with SLA, failure path, "
                "and idempotency key for write-side calls."
            ),
            "skill_id": None,
        },
    ],
    "business": [
        {
            "critic_id": "business",
            "claim_id": "C-002",
            "severity": "P2",
            "finding": (
                "Scope language is ambiguous — phrases like 'phased rollout', "
                "'all major languages', 'near real-time' are not defined."
            ),
            "evidence": 'line: "phased rollout / supports all major languages / near real-time"',
            "suggested_fix": (
                "Define each ambiguous scope term with concrete numbers "
                "(percentages, latency budgets, language list)."
            ),
            "skill_id": None,
        },
    ],
    "design": [
        {
            "critic_id": "design",
            "claim_id": "C-001",
            "severity": "P1",
            "finding": (
                "UX section contradicts a Requirement — flow promises one "
                "behaviour while Requirements enforces the opposite."
            ),
            "evidence": "lines: UX vs Requirements section",
            "suggested_fix": (
                "Rewrite the conflicting section so UX and Requirements agree "
                "on enforcement semantics (skip-able vs required)."
            ),
            "skill_id": None,
        },
    ],
}


def _critique_payload_with_skill_extras(critic_key: str, user: str = "") -> dict:
    """Return the canned critique block enriched with skill-on extras.

    Extras are stamped round-robin with the skill ids parsed from the
    injected `<retrieved_skills>` block — simulating the model self-report
    contract (`skill_id` set only for skills actually present in the
    block). Baseline canned critiques keep `skill_id: None`.
    """
    base = _CANNED[critic_key]
    critic_id = base["role"]
    extras = _SKILL_ON_EXTRAS.get(critic_id, [])
    if not extras:
        return base
    ids = _parse_retrieved_skill_ids(user)
    stamped = []
    for i, extra in enumerate(extras):
        stamped.append({**extra, "skill_id": ids[i % len(ids)] if ids else None})
    return {
        "role": critic_id,
        "critiques": list(base["critiques"]) + stamped,
    }


def _parse_retrieved_skill_ids(user: str) -> list[str]:
    """Extract the `id="…"` values from a `<retrieved_skills>` block."""
    block = re.search(r"<retrieved_skills>(.*?)</retrieved_skills>", user, re.DOTALL)
    if not block:
        return []
    return re.findall(r'<skill id="([^"]+)"', block.group(1))


def _match(system: str, user: str = "") -> dict | str:
    """Pick a canned payload based on keywords in the system prompt.

    Returns a dict for JSON-shaped responders and a raw string for supervisor
    (which wraps JSON inside an XML envelope) or dialog mode (plain prose).
    """
    s = system.lower()
    if "skill distillation" in s:
        return _match_distiller(user)
    if "supervisor" in s:
        return _SUPERVISOR_TEXT
    # Dialog mode must be checked BEFORE the plain-critic fallback, because
    # the dialog system prompt is `<critic prompt> + <dialog preamble>` and
    # would otherwise match the critic branch and return JSON.
    if "dialog mode" in s or "讨论这个问题" in system or "discussion" in s:
        return _dialog_flavor_for(s)
    # Cross-challenge check runs before the plain-critic fallback because the
    # challenge prompt is the critic prompt + a suffix — both substrings match.
    if "cross-challenge" in s:
        return _match_challenge(s)
    # Order matters: "intake" first so it doesn't get shadowed by any critic.
    for key in ("intake", "user advocate", "engineering", "business", "design"):
        if key in s:
            # Day 10 ablation signal: when a `<retrieved_skills>` block was
            # injected into the user message, return the enriched critique
            # set so the rubric sees the lift skills are supposed to provide.
            if key != "intake" and "<retrieved_skills>" in user:
                return _critique_payload_with_skill_extras(key, user)
            return _CANNED[key]
    return {"role": "unknown", "note": "No canned response matched."}


class MockProvider(LLMProvider):
    """Deterministic mock implementation of LLMProvider."""

    model_id: str = "mock-1"

    def __init__(self) -> None:
        self.call_log: list[dict] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        payload = _match(system, user)
        self.call_log.append(
            {
                "method": "complete",
                "system": system,
                "user": user,
                "payload": payload,
            }
        )
        # Supervisor payload is already an XML envelope string; everyone else
        # gets JSON-serialized.
        text = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False
        )
        return LLMResponse(
            text=text,
            thinking=None,
            usage={"input_tokens": len(system) + len(user), "output_tokens": len(text)},
            model_id=self.model_id,
        )

    async def stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[dict]:
        response = await self.complete(
            system, user, max_tokens=max_tokens, temperature=temperature
        )
        self.call_log.append({"method": "stream", "system": system, "user": user})
        # Per-chunk sleep gives Streamlit's render loop something to paint
        # between deltas; tests disable it via MOCK_STREAM_DELAY=0 so they
        # stay sub-second.
        delay = float(os.getenv("MOCK_STREAM_DELAY", "0.02"))
        for word in response.text.split(" "):
            yield {"type": "text", "delta": word + " "}
            if delay > 0:
                await asyncio.sleep(delay)
