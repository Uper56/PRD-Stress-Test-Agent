"""SQLite persistence for Skill lifecycle records.

Storage decision (agreed in the 2026-08 product review, HANDOFF §5):

- Skill DEFINITIONS stay file/Git-friendly under `src/skills/seed|learned/`.
- Lifecycle RECORDS (lineage / use events / evaluations / gate reports /
  status + transitions) live in SQLite behind this repository class, so a
  later swap to PostgreSQL is a matter of re-implementing the same method
  surface — no caller above this module talks SQL.
- `runtime_stats.yaml` becomes a materialized read cache regenerated FROM
  these tables; it is no longer the source of truth (debt D-16 resolved).

Concurrency: one connection guarded by a re-entrant lock, WAL journal.
FastAPI serves sync endpoints from a threadpool; at this project's traffic
serializing writes through a lock is simpler and safer than a pool.

Failure policy: this store is governance-critical, NOT on the critic hot
path — so unlike HistoryStore/ProposalsStore it lets exceptions propagate
to the caller. Callers on request paths decide how to surface failures;
callers inside the pipeline wrap it in try/except (see wiring notes in
governance.py).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    FEEDBACK_WINDOW,
    GateReport,
    SkillEvaluation,
    SkillFeedback,
    SkillLineage,
    SkillStatus,
    SkillStatusRecord,
    SkillUseEvent,
    StatusTransition,
)

DEFAULT_DB_PATH = Path("data") / "lifecycle" / "skills.db"

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Immutable provenance: one row per (skill_name, version). Appends only.
CREATE TABLE IF NOT EXISTS skill_lineage (
    lineage_id             TEXT PRIMARY KEY,
    skill_name             TEXT NOT NULL,
    version                TEXT NOT NULL,
    created_at             TEXT,
    created_by             TEXT NOT NULL,
    source_proposal_id     TEXT,
    source_run_ids         TEXT NOT NULL DEFAULT '[]',
    source_prd_hashes      TEXT NOT NULL DEFAULT '[]',
    cited_excerpts         TEXT NOT NULL DEFAULT '[]',
    parent_skill           TEXT,
    parent_version         TEXT,
    admission_decision     TEXT,
    admission_actor        TEXT,
    admission_at           TEXT,
    validation_report_ref  TEXT,
    evaluation_ref         TEXT,
    body_snapshot          TEXT NOT NULL DEFAULT '',
    provenance             TEXT NOT NULL DEFAULT 'runtime',
    recorded_at            TEXT NOT NULL,
    UNIQUE (skill_name, version)
);
CREATE INDEX IF NOT EXISTS idx_lineage_name ON skill_lineage (skill_name);

-- Immutable per-run retrieval/application telemetry. Appends only.
CREATE TABLE IF NOT EXISTS skill_use_events (
    event_id                TEXT PRIMARY KEY,
    run_id                  TEXT NOT NULL,
    skill_name              TEXT NOT NULL,
    skill_version           TEXT NOT NULL,
    critic_id               TEXT,
    retrieval_score         REAL,
    retrieval_explanation   TEXT,
    retrieval_rank          INTEGER,
    retrieval_source        TEXT,
    applied                 INTEGER,          -- 1/0/NULL(unknown)
    attributed_critique_ids TEXT NOT NULL DEFAULT '[]',
    provider                TEXT,
    model                   TEXT,
    occurred_at             TEXT,
    provenance              TEXT NOT NULL DEFAULT 'runtime'
);
CREATE INDEX IF NOT EXISTS idx_use_events_skill ON skill_use_events (skill_name, occurred_at);
CREATE INDEX IF NOT EXISTS idx_use_events_run   ON skill_use_events (run_id);

-- Immutable counterfactual OFF/ON evaluation records. Appends only.
CREATE TABLE IF NOT EXISTS skill_evaluations (
    evaluation_id      TEXT PRIMARY KEY,
    skill_name         TEXT NOT NULL,
    skill_version      TEXT NOT NULL,
    off_config         TEXT NOT NULL DEFAULT '{}',
    on_config          TEXT NOT NULL DEFAULT '{}',
    metrics_off        TEXT NOT NULL DEFAULT '{}',
    metrics_on         TEXT NOT NULL DEFAULT '{}',
    target_pattern_hits INTEGER,
    gate_result        TEXT NOT NULL DEFAULT 'fail',
    gate_reason        TEXT,
    policy_version     TEXT NOT NULL,
    evaluator_version  TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    provenance         TEXT NOT NULL DEFAULT 'runtime'
);
CREATE INDEX IF NOT EXISTS idx_evaluations_skill ON skill_evaluations (skill_name, created_at);

-- Persisted admission-gate outputs ("persist every gate output and
-- evaluator version"). Appends only; the UI reads the latest per gate.
CREATE TABLE IF NOT EXISTS skill_gate_reports (
    report_id         TEXT PRIMARY KEY,
    proposal_id       TEXT NOT NULL,
    gate              TEXT NOT NULL,
    passed            INTEGER NOT NULL,
    detail            TEXT NOT NULL DEFAULT '{}',
    evaluator_version TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gates_proposal ON skill_gate_reports (proposal_id, created_at);

-- Mutable current lifecycle status: the source of truth the YAML cache
-- is regenerated from. One row per skill.
CREATE TABLE IF NOT EXISTS skill_status (
    skill_name           TEXT PRIMARY KEY,
    version              TEXT NOT NULL,
    status               TEXT NOT NULL,
    reason               TEXT,
    actor                TEXT,
    rollback_target      TEXT,
    probation_started_at TEXT,
    updated_at           TEXT NOT NULL
);

-- Append-only audit trail behind every status change.
CREATE TABLE IF NOT EXISTS skill_status_events (
    transition_id TEXT PRIMARY KEY,
    skill_name    TEXT NOT NULL,
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    reason        TEXT,
    actor         TEXT,
    at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_events_skill ON skill_status_events (skill_name, at);

-- Append-only HITL feedback samples — the probation evidence base.
CREATE TABLE IF NOT EXISTS skill_feedback (
    feedback_id        TEXT PRIMARY KEY,
    skill_name         TEXT NOT NULL,
    critique_uid       TEXT,
    severity           TEXT,
    accepted           INTEGER NOT NULL,
    evidence_compliant INTEGER,
    at                 TEXT NOT NULL,
    provenance         TEXT NOT NULL DEFAULT 'runtime'
);
CREATE INDEX IF NOT EXISTS idx_feedback_skill ON skill_feedback (skill_name, at);
"""


def utcnow_iso() -> str:
    """ISO 8601 UTC with seconds precision — the codebase-wide timestamp format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _unj(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


class LifecycleStore:
    """Repository over the lifecycle SQLite database.

    All record ids (`lineage_id`, `event_id`, …) and `recorded_at` stamps
    are assigned HERE at insert time so callers never fabricate them.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, timeout=30.0
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            self._conn.commit()

    # ---- meta -----------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    # ---- immutable: lineage ----------------------------------------------

    def append_lineage(self, record: SkillLineage) -> SkillLineage:
        """Insert one provenance row. Idempotent on (name, version): if a
        row already exists it is returned unchanged — re-running an append
        (e.g. migration rerun) never duplicates or overwrites history."""
        with self._lock:
            existing = self.get_lineage(record.skill_name, record.version)
            if existing is not None:
                return existing
            row = record.model_copy(
                update={
                    "lineage_id": record.lineage_id or _new_id(),
                    "recorded_at": record.recorded_at or utcnow_iso(),
                }
            )
            self._conn.execute(
                """INSERT INTO skill_lineage (
                       lineage_id, skill_name, version, created_at, created_by,
                       source_proposal_id, source_run_ids, source_prd_hashes,
                       cited_excerpts, parent_skill, parent_version,
                       admission_decision, admission_actor, admission_at,
                       validation_report_ref, evaluation_ref, body_snapshot,
                       provenance, recorded_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.lineage_id, row.skill_name, row.version, row.created_at,
                    row.created_by, row.source_proposal_id, _j(row.source_run_ids),
                    _j(row.source_prd_hashes), _j(row.cited_excerpts),
                    row.parent_skill, row.parent_version,
                    row.admission_decision, row.admission_actor, row.admission_at,
                    row.validation_report_ref, row.evaluation_ref, row.body_snapshot,
                    row.provenance, row.recorded_at,
                ),
            )
            self._conn.commit()
            return row

    def get_lineage(self, skill_name: str, version: str | None = None) -> SkillLineage | None:
        with self._lock:
            if version is None:
                row = self._conn.execute(
                    "SELECT * FROM skill_lineage WHERE skill_name = ? "
                    "ORDER BY recorded_at DESC, rowid DESC LIMIT 1",
                    (skill_name,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT * FROM skill_lineage WHERE skill_name = ? AND version = ?",
                    (skill_name, version),
                ).fetchone()
        return _row_to_lineage(row) if row else None

    def list_lineage(self, skill_name: str | None = None) -> list[SkillLineage]:
        with self._lock:
            if skill_name is None:
                rows = self._conn.execute(
                    "SELECT * FROM skill_lineage ORDER BY skill_name, recorded_at"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM skill_lineage WHERE skill_name = ? ORDER BY recorded_at",
                    (skill_name,),
                ).fetchall()
        return [_row_to_lineage(r) for r in rows]

    # ---- immutable: use events -------------------------------------------

    def append_use_event(self, event: SkillUseEvent) -> SkillUseEvent:
        row = event.model_copy(update={"event_id": event.event_id or _new_id()})
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO skill_use_events (
                       event_id, run_id, skill_name, skill_version, critic_id,
                       retrieval_score, retrieval_explanation, retrieval_rank,
                       retrieval_source, applied, attributed_critique_ids,
                       provider, model, occurred_at, provenance
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.event_id, row.run_id, row.skill_name, row.skill_version,
                    row.critic_id, row.retrieval_score, row.retrieval_explanation,
                    row.retrieval_rank, row.retrieval_source,
                    None if row.applied is None else int(row.applied),
                    _j(row.attributed_critique_ids), row.provider, row.model,
                    row.occurred_at, row.provenance,
                ),
            )
            self._conn.commit()
        return row

    def list_use_events(
        self,
        skill_name: str | None = None,
        run_id: str | None = None,
        limit: int = 500,
    ) -> list[SkillUseEvent]:
        clauses, params = [], []
        if skill_name is not None:
            clauses.append("skill_name = ?")
            params.append(skill_name)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM skill_use_events {where} "
                f"ORDER BY occurred_at DESC, rowid DESC LIMIT ?",
                params,
            ).fetchall()
        return [_row_to_use_event(r) for r in rows]

    def count_use_events(self, skill_name: str, *, applied_only: bool = False) -> int:
        with self._lock:
            if applied_only:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM skill_use_events "
                    "WHERE skill_name = ? AND applied = 1",
                    (skill_name,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM skill_use_events WHERE skill_name = ?",
                    (skill_name,),
                ).fetchone()
        return int(row["n"])

    # ---- immutable: evaluations -------------------------------------------

    def append_evaluation(self, record: SkillEvaluation) -> SkillEvaluation:
        with self._lock:
            existing = self._conn.execute(
                "SELECT evaluation_id FROM skill_evaluations WHERE evaluation_id = ?",
                (record.evaluation_id,),
            ).fetchone()
            if existing:
                return record
            row = record.model_copy(
                update={
                    "evaluation_id": record.evaluation_id or _new_id(),
                    "created_at": record.created_at or utcnow_iso(),
                }
            )
            self._conn.execute(
                """INSERT INTO skill_evaluations (
                       evaluation_id, skill_name, skill_version, off_config,
                       on_config, metrics_off, metrics_on, target_pattern_hits,
                       gate_result, gate_reason, policy_version,
                       evaluator_version, created_at, provenance
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.evaluation_id, row.skill_name, row.skill_version,
                    _j(row.off_config), _j(row.on_config),
                    _j(row.metrics_off), _j(row.metrics_on),
                    row.target_pattern_hits, row.gate_result, row.gate_reason,
                    row.policy_version, row.evaluator_version,
                    row.created_at, row.provenance,
                ),
            )
            self._conn.commit()
            return row

    def get_evaluation(self, evaluation_id: str) -> SkillEvaluation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skill_evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        return _row_to_evaluation(row) if row else None

    def list_evaluations(self, skill_name: str | None = None) -> list[SkillEvaluation]:
        with self._lock:
            if skill_name is None:
                rows = self._conn.execute(
                    "SELECT * FROM skill_evaluations ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM skill_evaluations WHERE skill_name = ? "
                    "ORDER BY created_at DESC",
                    (skill_name,),
                ).fetchall()
        return [_row_to_evaluation(r) for r in rows]

    # ---- immutable: gate reports -------------------------------------------

    def append_gate_report(self, report: GateReport) -> GateReport:
        row = report.model_copy(
            update={
                "report_id": report.report_id or _new_id(),
                "created_at": report.created_at or utcnow_iso(),
            }
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO skill_gate_reports (
                       report_id, proposal_id, gate, passed, detail,
                       evaluator_version, created_at
                   ) VALUES (?,?,?,?,?,?,?)""",
                (
                    row.report_id, row.proposal_id, row.gate, int(row.passed),
                    _j(row.detail), row.evaluator_version, row.created_at,
                ),
            )
            self._conn.commit()
        return row

    def list_gate_reports(self, proposal_id: str | None = None) -> list[GateReport]:
        with self._lock:
            if proposal_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM skill_gate_reports ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM skill_gate_reports WHERE proposal_id = ? "
                    "ORDER BY created_at DESC",
                    (proposal_id,),
                ).fetchall()
        return [_row_to_gate_report(r) for r in rows]

    def latest_gate_reports(self, proposal_id: str) -> dict[str, GateReport]:
        """Newest report per gate name for one proposal — what the UI shows."""
        out: dict[str, GateReport] = {}
        for report in self.list_gate_reports(proposal_id):
            if report.gate not in out:  # list is newest-first
                out[report.gate] = report
        return out

    # ---- mutable: status + transitions --------------------------------------

    def set_status(
        self,
        skill_name: str,
        version: str,
        status: SkillStatus,
        *,
        reason: str | None = None,
        actor: str | None = None,
        rollback_target: str | None = None,
        probation_started_at: str | None = None,
    ) -> SkillStatusRecord:
        """Upsert the current status row and append an audit transition.

        The transition is appended only when the status actually CHANGES —
        no-op refreshes (e.g. re-asserting version) don't pollute the audit
        trail. `rollback_target`/`probation_started_at` survive refreshes
        unless explicitly overwritten.
        """
        now = utcnow_iso()
        with self._lock:
            current = self.get_status(skill_name)
            if current is not None:
                merged = SkillStatusRecord(
                    skill_name=skill_name,
                    version=version,
                    status=status,
                    reason=reason if reason is not None else current.reason,
                    actor=actor if actor is not None else current.actor,
                    rollback_target=(
                        rollback_target if rollback_target is not None
                        else current.rollback_target
                    ),
                    probation_started_at=(
                        probation_started_at
                        if probation_started_at is not None
                        else current.probation_started_at
                    ),
                    updated_at=now,
                )
            else:
                merged = SkillStatusRecord(
                    skill_name=skill_name,
                    version=version,
                    status=status,
                    reason=reason,
                    actor=actor,
                    rollback_target=rollback_target,
                    probation_started_at=probation_started_at,
                    updated_at=now,
                )
            self._conn.execute(
                """INSERT INTO skill_status (
                       skill_name, version, status, reason, actor,
                       rollback_target, probation_started_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(skill_name) DO UPDATE SET
                       version = excluded.version,
                       status = excluded.status,
                       reason = excluded.reason,
                       actor = excluded.actor,
                       rollback_target = excluded.rollback_target,
                       probation_started_at = excluded.probation_started_at,
                       updated_at = excluded.updated_at""",
                (
                    merged.skill_name, merged.version, merged.status.value,
                    merged.reason, merged.actor, merged.rollback_target,
                    merged.probation_started_at, merged.updated_at,
                ),
            )
            if current is None or current.status != status:
                self._conn.execute(
                    """INSERT INTO skill_status_events (
                           transition_id, skill_name, from_status, to_status,
                           reason, actor, at
                       ) VALUES (?,?,?,?,?,?,?)""",
                    (
                        _new_id(), skill_name,
                        current.status.value if current else None,
                        status.value, reason, actor, now,
                    ),
                )
            self._conn.commit()
            return merged

    def get_status(self, skill_name: str) -> SkillStatusRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM skill_status WHERE skill_name = ?", (skill_name,)
            ).fetchone()
        return _row_to_status(row) if row else None

    def list_statuses(self) -> list[SkillStatusRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM skill_status ORDER BY skill_name"
            ).fetchall()
        return [_row_to_status(r) for r in rows]

    def list_transitions(self, skill_name: str | None = None) -> list[StatusTransition]:
        with self._lock:
            if skill_name is None:
                rows = self._conn.execute(
                    "SELECT * FROM skill_status_events ORDER BY at, rowid"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM skill_status_events WHERE skill_name = ? "
                    "ORDER BY at, rowid",
                    (skill_name,),
                ).fetchall()
        return [_row_to_transition(r) for r in rows]

    # ---- immutable: feedback samples ---------------------------------------

    def append_feedback(self, sample: SkillFeedback) -> SkillFeedback:
        row = sample.model_copy(
            update={
                "feedback_id": sample.feedback_id or _new_id(),
                "at": sample.at or utcnow_iso(),
            }
        )
        with self._lock:
            self._conn.execute(
                """INSERT INTO skill_feedback (
                       feedback_id, skill_name, critique_uid, severity,
                       accepted, evidence_compliant, at, provenance
                   ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    row.feedback_id, row.skill_name, row.critique_uid,
                    row.severity, int(row.accepted),
                    None if row.evidence_compliant is None else int(row.evidence_compliant),
                    row.at, row.provenance,
                ),
            )
            self._conn.commit()
        return row

    def list_feedback(
        self, skill_name: str, *, limit: int = FEEDBACK_WINDOW
    ) -> list[SkillFeedback]:
        """Most recent `limit` samples for one skill, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM skill_feedback WHERE skill_name = ? "
                "ORDER BY at DESC, rowid DESC LIMIT ?",
                (skill_name, limit),
            ).fetchall()
        return [_row_to_feedback(r) for r in rows]

    # ---- lifecycle helpers ---------------------------------------------------

    def retrievable_skill_names(self) -> set[str]:
        """Names whose current status is ACTIVE — the retrieval allowlist."""
        return {s.skill_name for s in self.list_statuses() if s.status == SkillStatus.ACTIVE}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---- row mappers --------------------------------------------------------------


def _row_to_lineage(r: sqlite3.Row) -> SkillLineage:
    return SkillLineage(
        lineage_id=r["lineage_id"],
        skill_name=r["skill_name"],
        version=r["version"],
        created_at=r["created_at"],
        created_by=r["created_by"],
        source_proposal_id=r["source_proposal_id"],
        source_run_ids=_unj(r["source_run_ids"], []),
        source_prd_hashes=_unj(r["source_prd_hashes"], []),
        cited_excerpts=_unj(r["cited_excerpts"], []),
        parent_skill=r["parent_skill"],
        parent_version=r["parent_version"],
        admission_decision=r["admission_decision"],
        admission_actor=r["admission_actor"],
        admission_at=r["admission_at"],
        validation_report_ref=r["validation_report_ref"],
        evaluation_ref=r["evaluation_ref"],
        body_snapshot=r["body_snapshot"],
        provenance=r["provenance"],
        recorded_at=r["recorded_at"],
    )


def _row_to_use_event(r: sqlite3.Row) -> SkillUseEvent:
    applied = r["applied"]
    return SkillUseEvent(
        event_id=r["event_id"],
        run_id=r["run_id"],
        skill_name=r["skill_name"],
        skill_version=r["skill_version"],
        critic_id=r["critic_id"],
        retrieval_score=r["retrieval_score"],
        retrieval_explanation=r["retrieval_explanation"],
        retrieval_rank=r["retrieval_rank"],
        retrieval_source=r["retrieval_source"],
        applied=None if applied is None else bool(applied),
        attributed_critique_ids=_unj(r["attributed_critique_ids"], []),
        provider=r["provider"],
        model=r["model"],
        occurred_at=r["occurred_at"],
        provenance=r["provenance"],
    )


def _row_to_evaluation(r: sqlite3.Row) -> SkillEvaluation:
    return SkillEvaluation(
        evaluation_id=r["evaluation_id"],
        skill_name=r["skill_name"],
        skill_version=r["skill_version"],
        off_config=_unj(r["off_config"], {}),
        on_config=_unj(r["on_config"], {}),
        metrics_off=_unj(r["metrics_off"], {}),
        metrics_on=_unj(r["metrics_on"], {}),
        target_pattern_hits=r["target_pattern_hits"],
        gate_result=r["gate_result"],
        gate_reason=r["gate_reason"],
        policy_version=r["policy_version"],
        evaluator_version=r["evaluator_version"],
        created_at=r["created_at"],
        provenance=r["provenance"],
    )


def _row_to_gate_report(r: sqlite3.Row) -> GateReport:
    return GateReport(
        report_id=r["report_id"],
        proposal_id=r["proposal_id"],
        gate=r["gate"],
        passed=bool(r["passed"]),
        detail=_unj(r["detail"], {}),
        evaluator_version=r["evaluator_version"],
        created_at=r["created_at"],
    )


def _row_to_status(r: sqlite3.Row) -> SkillStatusRecord:
    return SkillStatusRecord(
        skill_name=r["skill_name"],
        version=r["version"],
        status=SkillStatus(r["status"]),
        reason=r["reason"],
        actor=r["actor"],
        rollback_target=r["rollback_target"],
        probation_started_at=r["probation_started_at"],
        updated_at=r["updated_at"],
    )


def _row_to_transition(r: sqlite3.Row) -> StatusTransition:
    return StatusTransition(
        transition_id=r["transition_id"],
        skill_name=r["skill_name"],
        from_status=r["from_status"],
        to_status=r["to_status"],
        reason=r["reason"],
        actor=r["actor"],
        at=r["at"],
    )


def _row_to_feedback(r: sqlite3.Row) -> SkillFeedback:
    compliant = r["evidence_compliant"]
    return SkillFeedback(
        feedback_id=r["feedback_id"],
        skill_name=r["skill_name"],
        critique_uid=r["critique_uid"],
        severity=r["severity"],
        accepted=bool(r["accepted"]),
        evidence_compliant=None if compliant is None else bool(compliant),
        at=r["at"],
        provenance=r["provenance"],
    )
