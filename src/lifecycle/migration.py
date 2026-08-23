"""Deterministic migration — legacy artifacts → lifecycle SQLite.

Sources (all optional; missing sources just contribute nothing):

  - `src/skills/seed/*/SKILL.md`, `src/skills/learned/*/SKILL.md`
        → SkillLineage rows (name/version/created_by/body snapshot).
  - `src/skills/runtime_stats.yaml`
        → current status + the `created_at` stamp recorded at promote time.
  - `data/results/proposals/*.json`
        → proposal linkage: source_proposal_id, evidence run_ids, excerpts,
          admission_decision for approved/edited proposals.
  - `data/results/history/*.json` (via HistoryStore)
        → distinct PRD hashes per run_id (evidence dedup) and legacy
          SkillUseEvents from each run's flat retrieved/hit sets.
  - `data/results/ablation/latest.json`
        → one legacy SkillEvaluation for the single learned skill
          (seed_only = OFF, seed_plus_learned = ON), gate verdict computed
          RETROACTIVELY by the current policy and labeled as such.

Rules (HANDOFF §5 "Historical migration rule"):

  1. Only deterministic facts are backfilled. Anything the old system did
     not record stays NULL — most visibly `admission_actor` (we know a
     human approved, not WHO) and `created_at` for seed skills.
  2. Every row written here carries `provenance="legacy_import"`.
  3. Orphan stats rows with no SKILL.md folder (debt D-19 `demo-skill`)
     are skipped and reported, never imported.
  4. The migration is idempotent: guarded by a `schema_meta` key, a rerun
     returns `already_migrated=True` without touching the database.

This module never writes to the legacy files themselves — the YAML/JSON
readers keep working unchanged during (and after) migration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from ..skills.retriever import (
    LEARNED_DIR,
    RUNTIME_STATS_PATH,
    SEED_DIR,
    SKILL_FILENAME,
    parse_skill_md,
)
from ..storage import HistoryStore, ProposalsStore
from .models import (
    MigrationReport,
    SkillEvaluation,
    SkillLineage,
    SkillStatus,
    SkillUseEvent,
)
from .store import LifecycleStore, utcnow_iso

logger = logging.getLogger(__name__)

DEFAULT_ABLATION_LATEST = Path("data") / "results" / "ablation" / "latest.json"

MIGRATION_META_KEY = "legacy_migration_v1_at"


def run_migration(
    store: LifecycleStore,
    *,
    history_store: HistoryStore | None = None,
    proposals_store: ProposalsStore | None = None,
    seed_dir: Path | str | None = None,
    learned_dir: Path | str | None = None,
    runtime_stats_path: Path | str | None = None,
    ablation_latest: Path | str | None = None,
) -> MigrationReport:
    """Import legacy artifacts into `store`. Idempotent and injectable."""
    if store.get_meta(MIGRATION_META_KEY) is not None:
        return MigrationReport(already_migrated=True)

    history_store = history_store or HistoryStore()
    proposals_store = proposals_store or ProposalsStore()
    seed_dir = Path(seed_dir) if seed_dir else SEED_DIR
    learned_dir = Path(learned_dir) if learned_dir else LEARNED_DIR
    runtime_stats_path = (
        Path(runtime_stats_path) if runtime_stats_path else RUNTIME_STATS_PATH
    )
    ablation_latest = Path(ablation_latest) if ablation_latest else DEFAULT_ABLATION_LATEST

    report = MigrationReport(migrated_at=utcnow_iso())

    stats_by_name = _load_runtime_stats(runtime_stats_path)
    folders = _discover_folders(seed_dir, learned_dir)  # name -> (path, fm, body)
    proposals_by_name = {
        p.proposed_name: p for p in proposals_store.list_all()
    }

    versions_by_name: dict[str, str] = {}

    # ---- 1. lineage + status per skill folder ---------------------------
    for name, (path, fm, body) in sorted(folders.items()):
        entry = stats_by_name.get(name) or {}
        proposal = proposals_by_name.get(name)

        source_run_ids: list[str] = []
        cited_excerpts: list[str] = []
        if proposal is not None and proposal.status in ("approved", "edited"):
            source_run_ids = sorted(
                {ev.get("run_id") for ev in proposal.evidence if ev.get("run_id")}
            )
            cited_excerpts = [
                ev.get("critique_excerpt") or ""
                for ev in proposal.evidence
                if ev.get("critique_excerpt")
            ]

        source_prd_hashes = sorted(
            {
                rec.prd_text_hash
                for rid in source_run_ids
                if (rec := history_store.load(rid)) is not None
            }
        )

        version = str(fm.get("version") or "1.0")
        versions_by_name[name] = version

        lineage = store.append_lineage(
            SkillLineage(
                lineage_id="",
                skill_name=name,
                version=version,
                created_at=entry.get("created_at"),  # None for seeds — honest
                created_by=str(fm.get("created_by") or "seed"),
                source_proposal_id=(
                    proposal.proposal_id
                    if proposal is not None and proposal.status in ("approved", "edited")
                    else None
                ),
                source_run_ids=source_run_ids,
                source_prd_hashes=source_prd_hashes,
                cited_excerpts=cited_excerpts,
                parent_skill=None,
                parent_version=None,
                admission_decision=(
                    "approved"
                    if proposal is not None and proposal.status in ("approved", "edited")
                    else None
                ),
                admission_actor=None,          # unknown — never fabricated
                admission_at=entry.get("created_at") if proposal is not None else None,
                validation_report_ref=None,    # no gates existed pre-migration
                evaluation_ref=None,           # linked below if ablation imports
                body_snapshot=body,
                provenance="legacy_import",
            )
        )
        report.lineages_written.append(f"{name}@{version}")

        status_value = str(entry.get("status") or "active")
        if status_value.startswith("deprecated"):
            status = SkillStatus.DEPRECATED
            reason = f"legacy_import: runtime status was {status_value!r}"
        else:
            status = SkillStatus.ACTIVE
            reason = "legacy_import: runtime status was 'active'"
        store.set_status(
            name,
            version,
            status,
            reason=reason,
            actor="migration",
        )
        report.statuses_written.append(name)

    # ---- 2. orphan stats rows (D-19 demo-skill) --------------------------
    for name in sorted(set(stats_by_name) - set(folders)):
        report.skipped_orphans[name] = (
            "runtime_stats row has no SKILL.md folder — orphan (debt D-19), not imported"
        )
        logger.info("migration: skipping orphan stats row %r", name)

    # ---- 3. legacy use events from run history ----------------------------
    for run in history_store.list_recent(n=10_000):
        for skill_name in run.retrieved_skill_ids:
            if skill_name not in versions_by_name:
                continue
            applied = skill_name in run.skill_hits
            store.append_use_event(
                SkillUseEvent(
                    event_id="",
                    run_id=run.run_id,
                    skill_name=skill_name,
                    skill_version=versions_by_name[skill_name],
                    critic_id=None,              # flat set lost per-critic detail
                    retrieval_score=None,
                    retrieval_explanation=None,
                    retrieval_rank=None,
                    retrieval_source="legacy_flat_set",
                    applied=applied,             # model-reported then, too
                    attributed_critique_ids=[],   # legacy critiques had no ids
                    occurred_at=run.timestamp,
                    provenance="legacy_import",
                )
            )
            report.use_events_written += 1

    # ---- 4. legacy counterfactual evaluation from the ablation sweep ------
    learned_names = [n for n, (path, _fm, _b) in folders.items() if path.parent == learned_dir]
    if len(learned_names) == 1 and ablation_latest.exists():
        ev = _import_ablation_evaluation(store, ablation_latest, learned_names[0], versions_by_name)
        if ev is not None:
            report.evaluations_written.append(ev.evaluation_id)
            # Link the lineage to its evaluation (append-only table → the
            # link lives on a fresh row only if none exists; here the row
            # was just created above without one, so update-in-place is the
            # same as completing the initial insert).
            _link_evaluation(store, ev)

    store.set_meta(MIGRATION_META_KEY, report.migrated_at)
    logger.info(
        "migration: %d lineages, %d use events, %d evaluations, %d orphans skipped",
        len(report.lineages_written),
        report.use_events_written,
        len(report.evaluations_written),
        len(report.skipped_orphans),
    )
    return report


# ---- helpers -------------------------------------------------------------------


def _load_runtime_stats(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("migration: runtime_stats unreadable: %s", e)
        return {}
    skills = raw.get("skills") or {}
    return {name: (entry or {}) for name, entry in skills.items()} if isinstance(skills, dict) else {}


def _discover_folders(
    seed_dir: Path, learned_dir: Path
) -> dict[str, tuple[Path, dict, str]]:
    out: dict[str, tuple[Path, dict, str]] = {}
    for parent in (seed_dir, learned_dir):
        if not parent.exists():
            continue
        for child in sorted(parent.iterdir()):
            skill_md = child / SKILL_FILENAME
            if not (child.is_dir() and skill_md.is_file()):
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
                fm, body = parse_skill_md(text)
            except Exception as e:  # noqa: BLE001
                logger.warning("migration: skipping unparseable %s: %s", skill_md, e)
                continue
            name = str(fm.get("name") or child.name)
            out[name] = (child, fm, text)
    return out


def _import_ablation_evaluation(
    store: LifecycleStore,
    ablation_latest: Path,
    learned_name: str,
    versions_by_name: dict[str, str],
) -> SkillEvaluation | None:
    """Turn the recorded ablation sweep into one legacy OFF/ON evaluation.

    Valid only while `learned/` holds exactly ONE skill — then
    `skill_seed_only` IS the OFF arm and `skill_seed_plus_learned` the ON
    arm for that skill. The gate verdict is computed by the CURRENT policy
    over the recorded numbers and labeled retroactive; the sweep itself
    predates gates (that gap is exactly debt D-20).
    """
    try:
        with ablation_latest.open("r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning("migration: ablation latest.json unreadable: %s", e)
        return None

    agg = report.get("aggregated") or {}
    off = agg.get("skill_seed_only") or {}
    on = agg.get("skill_seed_plus_learned") or {}
    if not off or not on:
        return None

    def _cell(cell: dict, key: str) -> float:
        return float(cell.get(f"{key}_mean", 0.0) or 0.0)

    metrics_off = {
        "recall": _cell(off, "overall_recall"),
        "precision": _cell(off, "precision"),
        "false_p0_count": _cell(off, "false_positive_count"),
        "evidence_compliance": _cell(off, "structure_compliance"),
        "actionability": _cell(off, "actionability"),
        "latency_seconds": _cell(off, "latency_seconds"),
        "cost_usd_estimate": _cell(off, "cost_usd_estimate"),
    }
    metrics_on = {
        "recall": _cell(on, "overall_recall"),
        "precision": _cell(on, "precision"),
        "false_p0_count": _cell(on, "false_positive_count"),
        "evidence_compliance": _cell(on, "structure_compliance"),
        "actionability": _cell(on, "actionability"),
        "latency_seconds": _cell(on, "latency_seconds"),
        "cost_usd_estimate": _cell(on, "cost_usd_estimate"),
    }

    # Retroactive policy verdict — lazy import avoids a cycle at module load.
    from .gates import decide_admission

    decision = decide_admission(
        metrics_off=metrics_off,
        metrics_on=metrics_on,
        target_pattern_hits=None,   # not recorded per-skill in the sweep
    )

    record = SkillEvaluation(
        evaluation_id="",
        skill_name=learned_name,
        skill_version=versions_by_name.get(learned_name, "1.0"),
        off_config={
            "treatment": "skill_seed_only",
            "source": str(ablation_latest),
            "recorded": report.get("timestamp"),
            "note": "legacy ablation sweep; seed-only arm used as the OFF arm",
        },
        on_config={
            "treatment": "skill_seed_plus_learned",
            "source": str(ablation_latest),
            "recorded": report.get("timestamp"),
            "note": f"learned/ contained exactly one skill ({learned_name})",
        },
        metrics_off=metrics_off,
        metrics_on=metrics_on,
        target_pattern_hits=None,
        gate_result=decision.result,
        gate_reason=f"retroactive verdict under {decision.policy_version}: "
        f"{'; '.join(decision.reasons)}",
        provenance="legacy_import",
    )
    return store.append_evaluation(record)


def _link_evaluation(store: LifecycleStore, evaluation: SkillEvaluation) -> None:
    """Point the (just-created) lineage row at its evaluation record.

    Migration-only affordance: during initial import the lineage row and
    the evaluation are written in one breath, so completing the reference
    is part of the same append. Normal runtime flow passes the id at
    lineage-append time instead (see governance.admit_skill).
    """
    with store._lock:  # noqa: SLF001 — migration is part of this package
        store._conn.execute(
            "UPDATE skill_lineage SET evaluation_ref = ? "
            "WHERE skill_name = ? AND evaluation_ref IS NULL",
            (evaluation.evaluation_id, evaluation.skill_name),
        )
        store._conn.commit()
