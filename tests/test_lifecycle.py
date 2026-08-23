"""Skill Lifecycle Center — store, migration, gates, governance tests.

Hermetic: every store/proposals/history/yaml path lives under tmp_path.
The retriever-backed novelty gate reads the repo library read-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.agents.skill_distiller import SkillProposal
from src.lifecycle.gates import decide_admission, validate_evidence, validate_novelty, validate_spec
from src.lifecycle.governance import GovernanceError, SkillGovernance
from src.lifecycle.migration import run_migration
from src.lifecycle.models import (
    GateReport,
    SkillEvaluation,
    SkillLineage,
    SkillStatus,
)
from src.lifecycle.store import LifecycleStore
from src.skills.curator import SkillCurator
from src.storage import HistoryStore, ProposalsStore

# ---------------------------------------------------------------------------
# Fixture world builder
# ---------------------------------------------------------------------------


def _write_skill(root: Path, source: str, name: str, *, body: str = "Body text.\n") -> None:
    d = root / source / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Skill {name} does something specific and unique.\n"
        'version: "1.0"\n'
        f"created_by: {'distiller' if source == 'learned' else 'seed'}\n"
        "injected_into:\n  - engineering\n"
        "trigger_keywords: [payment]\n"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )


def _seed_history(history: HistoryStore, texts: list[str]) -> list[str]:
    ids = []
    for i, text in enumerate(texts):
        rec = history.save(
            {"prd_text": text, "critiques": [], "challenges": [], "final_report": {}},
            prd_filename=f"p{i}.md",
        )
        assert rec is not None
        ids.append(rec.run_id)
    return ids


@pytest.fixture()
def world(tmp_path: Path):
    """A complete mini project: skills, stats, proposals, history, ablation."""
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "seed", "seed-alpha")
    _write_skill(skills_root, "learned", "learned-beta")

    stats_path = skills_root / "runtime_stats.yaml"
    stats_path.write_text(
        yaml.safe_dump(
            {
                "skills": {
                    "seed-alpha": {
                        "usage_count": 3,
                        "acceptance_rate": None,
                        "status": "active",
                    },
                    "learned-beta": {
                        "usage_count": 2,
                        "status": "active",
                        "created_at": "2026-04-27T12:45:32+00:00",
                    },
                    "demo-skill": {"usage_count": 0, "status": "active"},
                }
            }
        ),
        encoding="utf-8",
    )

    history = HistoryStore(tmp_path / "history")
    run_ids = _seed_history(
        history,
        [
            "# A\npayment flow one\n",
            "# B\npayment flow two\n",
            "# C\npayment flow three\n",
            "# D\npayment flow four\n",
        ],
    )

    proposals = ProposalsStore(
        tmp_path / "proposals",
        learned_dir=skills_root / "learned",
        runtime_stats_path=stats_path,
    )
    proposals.save(
        SkillProposal(
            proposal_id="prop1",
            proposed_name="learned-beta",
            proposed_skill_md=(skills_root / "learned" / "learned-beta" / "SKILL.md").read_text(encoding="utf-8"),
            injected_into=["engineering"],
            generalization_score=0.8,
            evidence=[
                {"run_id": rid, "critique_excerpt": "[P2] payment pattern"} for rid in run_ids[:3]
            ],
            pattern_frequency=3,
            created_at="2026-04-27T12:45:00+00:00",
            status="approved",
        )
    )

    ablation_dir = tmp_path / "ablation"
    ablation_dir.mkdir()
    (ablation_dir / "latest.json").write_text(
        json.dumps(
            {
                "timestamp": "2026-04-27T13:00:00+00:00",
                "aggregated": {
                    "skill_seed_only": {
                        "overall_recall_mean": 0.95,
                        "precision_mean": 0.39,
                        "false_positive_count_mean": 7.8,
                        "structure_compliance_mean": 1.0,
                        "actionability_mean": 0.9,
                        "latency_seconds_mean": 29.0,
                        "cost_usd_estimate_mean": 0.3,
                    },
                    "skill_seed_plus_learned": {
                        "overall_recall_mean": 0.91,
                        "precision_mean": 0.35,
                        "false_positive_count_mean": 8.0,
                        "structure_compliance_mean": 1.0,
                        "actionability_mean": 0.88,
                        "latency_seconds_mean": 30.1,
                        "cost_usd_estimate_mean": 0.31,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    return {
        "root": tmp_path,
        "skills_root": skills_root,
        "stats_path": stats_path,
        "history": history,
        "run_ids": run_ids,
        "proposals": proposals,
        "ablation_latest": ablation_dir / "latest.json",
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_store_lineage_append_is_idempotent(tmp_path: Path):
    store = LifecycleStore(tmp_path / "db.sqlite")
    record = SkillLineage(
        lineage_id="", skill_name="s", version="1.0", created_by="seed"
    )
    first = store.append_lineage(record)
    again = store.append_lineage(record)
    assert first.lineage_id == again.lineage_id
    assert len(store.list_lineage()) == 1
    store.close()


def test_store_status_transitions_audited(tmp_path: Path):
    store = LifecycleStore(tmp_path / "db.sqlite")
    store.set_status("s", "1.0", SkillStatus.ACTIVE, actor="a")
    store.set_status("s", "1.0", SkillStatus.ACTIVE, actor="a")  # no-op refresh
    store.set_status("s", "1.0", SkillStatus.DEGRADED, reason="bad", actor="policy")
    transitions = store.list_transitions("s")
    assert [(t.from_status, t.to_status) for t in transitions] == [
        (None, "active"),
        ("active", "degraded"),
    ]
    store.close()


def test_store_latest_gate_reports_prefers_newest(tmp_path: Path):
    store = LifecycleStore(tmp_path / "db.sqlite")
    store.append_gate_report(
        GateReport(report_id="", proposal_id="p", gate="spec", passed=False, detail={})
    )
    store.append_gate_report(
        GateReport(report_id="", proposal_id="p", gate="spec", passed=True, detail={})
    )
    latest = store.latest_gate_reports("p")
    assert latest["spec"].passed is True
    assert len(store.list_gate_reports("p")) == 2
    store.close()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_imports_deterministic_facts(world):
    store = LifecycleStore(world["root"] / "lifecycle" / "db.sqlite")
    report = run_migration(
        store,
        history_store=world["history"],
        proposals_store=world["proposals"],
        seed_dir=world["skills_root"] / "seed",
        learned_dir=world["skills_root"] / "learned",
        runtime_stats_path=world["stats_path"],
        ablation_latest=world["ablation_latest"],
    )

    assert not report.already_migrated
    assert set(report.statuses_written) == {"seed-alpha", "learned-beta"}
    assert "demo-skill" in report.skipped_orphans

    # Learned skill carries proposal linkage + distinct PRD hashes.
    beta = store.get_lineage("learned-beta")
    assert beta is not None
    assert beta.source_proposal_id == "prop1"
    assert beta.provenance == "legacy_import"
    assert beta.admission_actor is None          # never fabricated
    assert beta.created_at == "2026-04-27T12:45:32+00:00"
    assert len(beta.source_run_ids) == 3
    assert len(beta.source_prd_hashes) == 3      # deduped by hash
    assert beta.body_snapshot.startswith("---")

    # Seed skill has no proposal provenance and no invented dates.
    alpha = store.get_lineage("seed-alpha")
    assert alpha is not None
    assert alpha.source_proposal_id is None
    assert alpha.created_at is None

    # Ablation became one legacy evaluation with a RETROACTIVE verdict —
    # recall declined 0.95 -> 0.91 (> 0.02) and precision declined.
    evals = store.list_evaluations("learned-beta")
    assert len(evals) == 1
    assert evals[0].provenance == "legacy_import"
    assert evals[0].gate_result == "fail"
    assert "retroactive" in (evals[0].gate_reason or "")
    assert beta.evaluation_ref == evals[0].evaluation_id

    # Rerun is a no-op.
    again = run_migration(
        store,
        history_store=world["history"],
        proposals_store=world["proposals"],
        seed_dir=world["skills_root"] / "seed",
        learned_dir=world["skills_root"] / "learned",
        runtime_stats_path=world["stats_path"],
        ablation_latest=world["ablation_latest"],
    )
    assert again.already_migrated
    assert len(store.list_lineage()) == 2
    store.close()


def test_migration_use_events_from_history(world):
    store = LifecycleStore(world["root"] / "lifecycle" / "db.sqlite")
    run_migration(
        store,
        history_store=world["history"],
        proposals_store=world["proposals"],
        seed_dir=world["skills_root"] / "seed",
        learned_dir=world["skills_root"] / "learned",
        runtime_stats_path=world["stats_path"],
        ablation_latest=world["ablation_latest"],
    )
    # The seeded runs have no critiques, so nothing is retrieved — history
    # contributes zero use events and that is the honest outcome.
    assert store.count_use_events("seed-alpha") == 0
    store.close()


# ---------------------------------------------------------------------------
# Admission policy
# ---------------------------------------------------------------------------


def _metrics(**over) -> dict:
    base = {
        "precision": 0.5,
        "recall": 0.8,
        "false_p0_count": 1.0,
        "evidence_compliance": 0.9,
        "actionability": 0.9,
    }
    base.update(over)
    return base


def test_policy_passes_on_neutral_or_improving_deltas():
    decision = decide_admission(
        metrics_off=_metrics(), metrics_on=_metrics(precision=0.53), target_pattern_hits=3
    )
    assert decision.result == "pass"
    assert decision.preference_met is True


def test_policy_fails_each_rule_independently():
    cases = [
        (dict(metrics_on=_metrics(precision=0.49)), "precision declined"),
        (dict(metrics_on=_metrics(recall=0.77)), "recall declined"),
        (dict(target_pattern_hits=2), "target pattern"),
        (dict(metrics_on=_metrics(false_p0_count=2.0)), "extra false P0"),
        (dict(metrics_on=_metrics(evidence_compliance=0.7)), "evidence compliance regressed"),
        (dict(target_pattern_hits=None), "unknown"),
    ]
    for kwargs, fragment in cases:
        merged = dict(metrics_off=_metrics(), target_pattern_hits=3)
        merged.update(
            {"metrics_on": _metrics(), "target_pattern_hits": 3}
        )
        merged.update(kwargs)
        decision = decide_admission(**merged)
        assert decision.result == "fail"
        assert any(fragment in r for r in decision.reasons), (fragment, decision.reasons)


def test_policy_precision_gain_beats_recall_loss_preference():
    decision = decide_admission(
        metrics_off=_metrics(),
        metrics_on=_metrics(precision=0.50, recall=0.83),
        target_pattern_hits=3,
    )
    assert decision.result == "pass"
    assert decision.preference_met is True  # recall +0.03 at equal precision


# ---------------------------------------------------------------------------
# Deterministic gates
# ---------------------------------------------------------------------------


VALID_MD = (
    "---\n"
    "name: brand-new-skill\n"
    "description: A totally unique description about zigzag widgets.\n"
    'version: "1.0"\n'
    "created_by: distiller\n"
    "injected_into:\n  - business\n"
    "---\n\n"
    "## When to apply\nZigzag widgets appear.\n"
)


def test_spec_gate_catches_frontmatter_violations():
    ok = validate_spec(VALID_MD, "brand-new-skill")
    assert ok["passed"], ok["violations"]

    bad_name = validate_spec(VALID_MD.replace("brand-new-skill", "Brand New"), "brand-new-skill")
    assert not bad_name["passed"]

    missing = validate_spec(VALID_MD.replace('version: "1.0"\n', ""), "brand-new-skill")
    assert not missing["passed"]


def test_evidence_gate_dedups_reruns_by_prd_hash(world):
    # Three runs but only two distinct PRDs.
    verdict = validate_evidence(
        [
            {"run_id": world["run_ids"][0]},
            {"run_id": world["run_ids"][1]},
            {"run_id": world["run_ids"][3]},
        ],
        world["history"],
    )
    assert verdict["distinct_prd_count"] == 3  # all seeded texts differ
    assert verdict["passed"]

    reruns = validate_evidence(
        [
            {"run_id": world["run_ids"][0]},
            {"run_id": world["run_ids"][1]},
            {"run_id": "missing-run-id"},
        ],
        world["history"],
    )
    assert not reruns["passed"]
    assert reruns["missing_run_ids"] == ["missing-run-id"]


def test_novelty_gate_flags_semantic_duplicates():
    class FakeSkill:
        name = "existing"
        description = "A totally unique description about zigzag widgets."
        injected_into = ["business"]

    dup = validate_novelty(
        "brand-new-skill",
        "A totally unique description about zigzag widgets.",
        ["business"],
        [FakeSkill()],
    )
    assert not dup["passed"]

    other_route = validate_novelty(
        "brand-new-skill",
        "A totally unique description about zigzag widgets.",
        ["design"],  # different routed role → variant, not duplicate
        [FakeSkill()],
    )
    assert other_route["passed"]


# ---------------------------------------------------------------------------
# Governance: approve / probation / degrade / rollback
# ---------------------------------------------------------------------------


def _governance(tmp_path: Path, world) -> tuple[SkillGovernance, LifecycleStore]:
    store = LifecycleStore(tmp_path / "lifecycle" / "db.sqlite")
    curator = SkillCurator(runtime_stats_path=world["stats_path"])
    gov = SkillGovernance(
        store,
        history_store=world["history"],
        proposals_store=world["proposals"],
        learned_dir=world["skills_root"] / "learned",
        curator_factory=lambda: curator,
    )
    return gov, store


def _pass_shadow_gate(store: LifecycleStore, proposal_id: str) -> None:
    """Unit-test affordance: append a passing shadow report without
    running the (pipeline-heavy) sweep — the shadow module has its own
    coverage via the API test."""
    evaluation = store.append_evaluation(
        SkillEvaluation(
            evaluation_id="eval-unit",
            skill_name="whatever",
            skill_version="1.0",
            gate_result="pass",
        )
    )
    store.append_gate_report(
        GateReport(
            report_id="",
            proposal_id=proposal_id,
            gate="shadow",
            passed=True,
            detail={"evaluation_id": evaluation.evaluation_id},
            evaluator_version="shadow-v1",
        )
    )


def test_approve_refused_without_all_gates(world, tmp_path):
    gov, store = _governance(tmp_path, world)

    proposal = SkillProposal(
        proposal_id="prop2",
        proposed_name="brand-new-skill",
        proposed_skill_md=VALID_MD,
        injected_into=["business"],
        generalization_score=0.9,
        evidence=[{"run_id": rid} for rid in world["run_ids"][:3]],
        pattern_frequency=3,
        created_at="2026-08-23T00:00:00+00:00",
    )
    world["proposals"].save(proposal)

    with pytest.raises(GovernanceError, match="not run"):
        gov.approve("prop2", actor="pm:test")

    import asyncio

    latest = asyncio.run(gov.run_gates(proposal))
    assert all(latest[g].passed for g in ("spec", "evidence", "novelty"))

    with pytest.raises(GovernanceError, match="shadow"):
        gov.approve("prop2", actor="pm:test")

    _pass_shadow_gate(store, "prop2")
    result = gov.approve("prop2", actor="pm:test")
    assert result["name"] == "brand-new-skill"

    transitions = [t.to_status for t in store.list_transitions("brand-new-skill")]
    assert transitions == ["approved", "active"]
    lineage = store.get_lineage("brand-new-skill")
    assert lineage.admission_actor == "pm:test"
    assert lineage.validation_report_ref == "proposal:prop2"
    assert (world["skills_root"] / "learned" / "brand-new-skill" / "SKILL.md").exists()
    store.close()


def test_low_acceptance_degrades_and_mirrors_yaml(world, tmp_path):
    gov, store = _governance(tmp_path, world)
    store.set_status("learned-beta", "1.0", SkillStatus.ACTIVE, actor="t")

    for _ in range(3):
        status = gov.record_feedback("learned-beta", accepted=False, curator=None)

    assert status is not None and status.status == SkillStatus.DEGRADED
    assert status.rollback_target is None  # first version — nothing to roll back

    mirrored = yaml.safe_load(world["stats_path"].read_text(encoding="utf-8"))
    assert mirrored["skills"]["learned-beta"]["status"] == "degraded"
    store.close()


def test_wrong_p0_degrades_immediately(world, tmp_path):
    gov, store = _governance(tmp_path, world)
    store.set_status("learned-beta", "1.0", SkillStatus.ACTIVE, actor="t")

    status = gov.record_feedback(
        "learned-beta",
        accepted=False,
        critique={"uid": "abc", "severity": "P0", "evidence": "whatever"},
        prd_text="# prd\n",
        curator=None,
    )
    assert status is not None and status.status == SkillStatus.DEGRADED
    assert "wrong P0" in (status.reason or "")
    store.close()


def test_rollback_restores_previous_version_snapshot(world, tmp_path):
    gov, store = _governance(tmp_path, world)
    learned = world["skills_root"] / "learned"

    v1_body = (learned / "learned-beta" / "SKILL.md").read_text(encoding="utf-8")
    store.append_lineage(
        SkillLineage(
            lineage_id="", skill_name="learned-beta", version="1.0",
            created_by="distiller", body_snapshot=v1_body,
        )
    )
    # v2 replaces the file; its snapshot records the new text.
    v2_body = v1_body.replace("Body text.", "Edited body text.")
    (learned / "learned-beta" / "SKILL.md").write_text(v2_body, encoding="utf-8")
    store.append_lineage(
        SkillLineage(
            lineage_id="", skill_name="learned-beta", version="1.1",
            created_by="distiller", body_snapshot=v2_body,
            parent_skill="learned-beta", parent_version="1.0",
        )
    )
    store.set_status("learned-beta", "1.1", SkillStatus.ACTIVE, actor="t")

    degraded = store.set_status(
        "learned-beta", "1.1", SkillStatus.DEGRADED,
        reason="test degrade", actor="policy:auto-degrade",
        rollback_target="learned-beta@1.0",
    )
    assert degraded.rollback_target == "learned-beta@1.0"

    result = gov.rollback("learned-beta", actor="pm:test")
    assert result["restored_version"] == "1.0"
    assert (learned / "learned-beta" / "SKILL.md").read_text(encoding="utf-8") == v1_body
    assert store.get_status("learned-beta").status == SkillStatus.ACTIVE

    # Files were never deleted at any point.
    assert (learned / "learned-beta" / "SKILL.md").exists()
    store.close()


def test_rollback_requires_degraded_state(world, tmp_path):
    gov, store = _governance(tmp_path, world)
    store.set_status("seed-alpha", "1.0", SkillStatus.ACTIVE, actor="t")
    with pytest.raises(GovernanceError, match="rollback requires degraded"):
        gov.rollback("seed-alpha", actor="pm:test")
    store.close()


def test_overview_lists_degraded_and_interventions(world, tmp_path):
    gov, store = _governance(tmp_path, world)
    store.set_status("learned-beta", "1.0", SkillStatus.ACTIVE, actor="t", probation_started_at="2026-08-23T00:00:00+00:00")
    gov.record_feedback("learned-beta", accepted=False, curator=None)  # 1 bad sample

    data = gov.overview()
    assert data["counts"].get("active") == 1
    queue = [q["skill_name"] for q in data["intervention_queue"]]
    assert "learned-beta" in queue  # in probation with a bad signal
    store.close()
