"""Tests for the cross-challenge module — rounds, convergence, graph wiring."""

from __future__ import annotations

import json

from src.graph import edges
from src.graph.edges import run_cross_challenge
from src.graph.state import Critique, GraphState
from src.llm.mock_provider import MockProvider
from src.llm.provider import LLMResponse
from src.main import run_pipeline


SAMPLE_PRD = """# PRD-Test

## Problem
Users complain.

## Solution
Ship something.
"""


def _seed_state() -> GraphState:
    """A minimal state with 4 critiques so challengers have something to target."""
    critiques = [
        Critique(
            critic_id=cid,
            claim_id="C-001",
            severity="P1",
            finding=f"Mock finding from {cid}",
            evidence='line 1: "mock"',
            suggested_fix="Fix it.",
        )
        for cid in ("user_advocate", "engineering", "business", "design")
    ]
    return {
        "prd_text": "[001] Mock PRD",
        "prd_claims": [],
        "critiques": critiques,
        "challenges": [],
        "challenge_round": 0,
    }


# ---- Custom providers for round-control tests ------------------------------


class _EmptyChallengeProvider(MockProvider):
    """Forces every challenge call to return an empty list."""

    async def complete(self, system, user, **kw):
        if "cross-challenge" in system.lower():
            text = json.dumps({"challenges": []})
            self.call_log.append(
                {"method": "complete", "system": system, "user": user, "payload": text}
            )
            return LLMResponse(text=text, usage={}, model_id=self.model_id)
        return await super().complete(system, user, **kw)


class _RepeatingChallengeProvider(MockProvider):
    """Returns the same one-item challenge list every call — rounds look identical."""

    async def complete(self, system, user, **kw):
        if "cross-challenge" in system.lower():
            round_n = 2 if "round 2" in system.lower() else 1
            text = json.dumps(
                {
                    "challenges": [
                        {
                            "round": round_n,
                            "challenger": "engineering",
                            "target_critique_id": "design:C-001",
                            "counter_finding": "Identical content across rounds.",
                        }
                    ]
                }
            )
            self.call_log.append(
                {"method": "complete", "system": system, "user": user, "payload": text}
            )
            return LLMResponse(text=text, usage={}, model_id=self.model_id)
        return await super().complete(system, user, **kw)


_DIVERGENT_PAYLOADS = {
    1: {
        "round": 1,
        "challenger": "engineering",
        "target_critique_id": "design:C-001",
        "counter_finding": (
            "Alpha bravo charlie delta — rate-limit policy is absent and the "
            "event storm scenario is uncovered."
        ),
    },
    2: {
        "round": 2,
        "challenger": "business",
        "target_critique_id": "user_advocate:C-777",
        "counter_finding": (
            "Zulu yankee xray — revenue model assumptions ignore tiered pricing "
            "and enterprise procurement lag of six months."
        ),
    },
}


class _AlwaysDivergentProvider(MockProvider):
    """Returns non-empty, lexically distinct challenges — should not converge."""

    async def complete(self, system, user, **kw):
        if "cross-challenge" in system.lower():
            round_n = 2 if "round 2" in system.lower() else 1
            text = json.dumps({"challenges": [_DIVERGENT_PAYLOADS[round_n]]})
            self.call_log.append(
                {"method": "complete", "system": system, "user": user, "payload": text}
            )
            return LLMResponse(text=text, usage={}, model_id=self.model_id)
        return await super().complete(system, user, **kw)


# ---- Tests ------------------------------------------------------------------


async def test_round1_empty_skips_round2():
    llm = _EmptyChallengeProvider()
    result = await run_cross_challenge(_seed_state(), llm)
    assert result["challenge_round"] == 1
    assert result["convergence_signal"] is True
    assert result["challenges"] == []

    # Nothing from round 2 should have been asked for.
    assert not any(
        "round 2" in call["system"].lower() for call in llm.call_log
    )


async def test_max_rounds_cap_is_enforced():
    llm = _AlwaysDivergentProvider()
    result = await run_cross_challenge(_seed_state(), llm)
    assert result["challenge_round"] == edges.MAX_CROSS_CHALLENGE_ROUNDS
    assert result["convergence_signal"] is False
    # Must not have asked for a round 3.
    assert not any(
        "round 3" in call["system"].lower() for call in llm.call_log
    )


async def test_convergence_flagged_when_rounds_match():
    llm = _RepeatingChallengeProvider()
    result = await run_cross_challenge(_seed_state(), llm)
    assert result["challenge_round"] == 2
    assert result["convergence_signal"] is True
    # Both rounds ran and both produced content.
    rounds_seen = {c.round for c in result["challenges"]}
    assert rounds_seen == {1, 2}


async def test_pipeline_exposes_challenges_field():
    result = await run_pipeline(SAMPLE_PRD, llm=MockProvider())
    assert "challenges" in result
    assert isinstance(result["challenges"], list)
    # Default mock: round 1 non-empty, round 2 empty → converged at round 2.
    assert result.get("convergence_signal") is True
    # Supervisor should now surface the challenges in conflict_resolutions.
    final = result.get("final_report") or {}
    assert final.get("conflict_resolutions"), "supervisor verdict should cite challenges"
