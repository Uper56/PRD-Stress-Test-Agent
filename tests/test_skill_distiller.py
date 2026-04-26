"""Tests for the Skill Distiller — Day 9.

Covers:
  - Short-history guard: < min_runs_required → empty list, no LLM calls.
  - Clustering groups by critic_id (engineering misses don't cluster with design).
  - generalization_score < 0.7 → proposal dropped.
  - Evidence < 3 rows → proposal dropped.
  - Approved proposal can be promoted to a spec-compliant SKILL.md folder
    that the retriever immediately picks up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from src.agents.skill_distiller import (
    SkillProposal,
    _validate_proposal,
    run_distiller,
)
from src.llm.mock_provider import MockProvider
from src.llm.provider import LLMProvider, LLMResponse
from src.skills.retriever import SkillRetriever
from src.storage import HistoryStore, ProposalsStore


# ---- Helpers ---------------------------------------------------------------


def _mk_critique(critic_id: str, finding: str, claim_id: str = "C-001") -> dict:
    return {
        "critic_id": critic_id,
        "claim_id": claim_id,
        "severity": "P1",
        "finding": finding,
        "evidence": "line 1",
        "suggested_fix": "fix it",
        "skill_id": None,
    }


def _seed_runs(
    store: HistoryStore,
    critiques_per_run: list[list[dict]],
) -> list[str]:
    """Save N runs with the given critique sets; return their run_ids."""
    run_ids: list[str] = []
    for i, crits in enumerate(critiques_per_run):
        state = {
            "prd_text": f"[001] PRD {i}",
            "critiques": crits,
            "challenges": [],
            "final_report": {},
        }
        rec = store.save(state, prd_filename=f"prd_{i}.md")
        assert rec is not None
        run_ids.append(rec.run_id)
    return run_ids


# ---- Short history --------------------------------------------------------


async def test_returns_empty_when_history_below_min_runs(tmp_path: Path) -> None:
    """Less than 3 runs in history → distiller refuses to propose."""
    history = HistoryStore(tmp_path)
    _seed_runs(history, [[_mk_critique("engineering", "no rate limits anywhere")]])
    proposals = await run_distiller(MockProvider(), history, min_runs_required=3)
    assert proposals == []


# ---- Clustering: grouping by critic_id ------------------------------------


async def test_clustering_groups_by_critic_id(tmp_path: Path) -> None:
    """Engineering misses across 3 PRDs cluster; one unrelated design miss
    in the same runs does NOT inflate the engineering cluster."""
    history = HistoryStore(tmp_path)
    finding = "no retry budget defined for the upstream call"
    _seed_runs(
        history,
        [
            [
                _mk_critique("engineering", finding),
                _mk_critique("design", "icons need aria labels"),
            ],
            [_mk_critique("engineering", finding)],
            [_mk_critique("engineering", finding)],
        ],
    )
    proposals = await run_distiller(MockProvider(), history)
    assert proposals, "expected ≥1 proposal from a 3-PRD engineering cluster"
    # All injected_into entries should be engineering — design didn't cluster.
    for p in proposals:
        assert "engineering" in p.injected_into
        assert "design" not in p.injected_into


# ---- Validation -----------------------------------------------------------


def _base_proposal_kwargs(**overrides: Any) -> dict:
    md = (
        "---\n"
        "name: foo-bar\n"
        "description: Use this skill ANYTIME the PRD does X — it MUST happen, period.\n"
        'version: "1.0"\n'
        "created_by: distiller\n"
        "injected_into:\n  - engineering\n"
        "---\n\n"
        "# Skill\n## When to apply\nx\n## Instruction\ny\n## Rationale\nz\n## Examples\n- a\n"
    )
    base = dict(
        proposal_id="abc123",
        proposed_name="foo-bar",
        proposed_skill_md=md,
        injected_into=["engineering"],
        generalization_score=0.85,
        evidence=[
            {"run_id": "r1", "critique_excerpt": "[P1] one"},
            {"run_id": "r2", "critique_excerpt": "[P1] two"},
            {"run_id": "r3", "critique_excerpt": "[P1] three"},
        ],
        pattern_frequency=3,
        created_at="2026-04-26T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_validate_drops_low_generalization_score() -> None:
    p = SkillProposal(**_base_proposal_kwargs(generalization_score=0.6))
    assert not _validate_proposal(p)
    assert "generalization_score" in (p.rejection_reason or "")


def test_validate_drops_proposal_with_too_few_evidence_rows() -> None:
    p = SkillProposal(
        **_base_proposal_kwargs(
            evidence=[
                {"run_id": "r1", "critique_excerpt": "x"},
                {"run_id": "r2", "critique_excerpt": "y"},
            ]
        )
    )
    assert not _validate_proposal(p)
    assert "evidence" in (p.rejection_reason or "")


def test_validate_drops_evidence_missing_run_id() -> None:
    p = SkillProposal(
        **_base_proposal_kwargs(
            evidence=[
                {"critique_excerpt": "no run_id"},
                {"run_id": "r2", "critique_excerpt": "y"},
                {"run_id": "r3", "critique_excerpt": "z"},
            ]
        )
    )
    assert not _validate_proposal(p)


def test_validate_drops_non_kebab_name() -> None:
    bad_md = _base_proposal_kwargs()["proposed_skill_md"].replace(
        "name: foo-bar", "name: FooBar"
    )
    p = SkillProposal(
        **_base_proposal_kwargs(proposed_name="FooBar", proposed_skill_md=bad_md)
    )
    assert not _validate_proposal(p)


def test_validate_passes_a_well_formed_proposal() -> None:
    p = SkillProposal(**_base_proposal_kwargs())
    assert _validate_proposal(p)
    assert p.rejection_reason is None


# ---- Promotion: approved proposal lands on disk + is retrievable ----------


async def test_promote_to_skill_writes_compliant_skill_md(tmp_path: Path) -> None:
    """End-to-end: a 3-PRD cluster → distiller proposal → promote → SKILL.md
    appears under the configured learned/ dir and the retriever picks it up."""
    history = HistoryStore(tmp_path / "history")
    finding = "retry policy never bounds total attempts"
    _seed_runs(
        history,
        [
            [_mk_critique("engineering", finding)],
            [_mk_critique("engineering", finding)],
            [_mk_critique("engineering", finding)],
        ],
    )
    proposals = await run_distiller(MockProvider(), history)
    assert proposals, "expected ≥1 proposal"

    learned_dir = tmp_path / "learned"
    runtime_stats = tmp_path / "runtime_stats.yaml"
    runtime_stats.write_text("skills: {}\n", encoding="utf-8")

    store = ProposalsStore(
        base_dir=tmp_path / "proposals",
        learned_dir=learned_dir,
        runtime_stats_path=runtime_stats,
    )
    saved = store.save(proposals[0])
    assert saved is not None

    target = store.promote_to_skill(proposals[0].proposal_id)
    assert target is not None and target.exists()
    assert target.parent.parent == learned_dir, (
        "promoted SKILL.md must land under learned/<name>/"
    )

    # Validate the file via the retriever — it must be loadable.
    retriever = SkillRetriever(
        skills_root=tmp_path,
        runtime_stats_path=runtime_stats,
    )
    # SkillRetriever needs both seed/ and learned/ rooted under skills_root
    # to scan; create empty seed/ to satisfy the loader.
    (tmp_path / "seed").mkdir(exist_ok=True)
    lib = retriever.load_library()
    assert any(s.folder and Path(s.folder) == target.parent for s in lib.skills), (
        "retriever did not pick up the promoted SKILL.md"
    )


# ---- LLM-failure path: parse error → no proposal, no crash ----------------


class _BrokenProvider(LLMProvider):
    """Returns un-parseable text on every complete() call."""

    async def complete(self, system, user, *, max_tokens=None, temperature=0.7):
        return LLMResponse(text="not json at all", model_id="broken")

    async def stream(self, system, user, *, max_tokens=None, temperature=0.7) -> AsyncIterator[dict]:
        if False:
            yield {}


async def test_distiller_tolerates_unparseable_llm_response(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path)
    finding = "failure mode unhandled on the upstream API"
    _seed_runs(
        history,
        [
            [_mk_critique("engineering", finding)],
            [_mk_critique("engineering", finding)],
            [_mk_critique("engineering", finding)],
        ],
    )
    proposals = await run_distiller(_BrokenProvider(), history)
    # Cluster passes frequency filter but LLM never returns JSON →
    # we get [] without raising.
    assert proposals == []
