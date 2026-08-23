"""Skill lifecycle domain models.

The Skill Lifecycle Center separates three concerns that previously all
lived in `runtime_stats.yaml` (HANDOFF debt D-16):

1. **Immutable records** — append-only facts that never change once
   written. This module defines the three agreed in the product review:
     - `SkillLineage`    — permanent provenance of a (skill, version).
     - `SkillUseEvent`   — per-run retrieval/application telemetry.
     - `SkillEvaluation` — counterfactual OFF/ON quality record.
   Plus `GateReport` — the persisted output of one admission-gate run
   ("persist every gate output and evaluator version").

2. **Mutable current state** — `SkillStatusRecord`, the authoritative
   lifecycle pointer per skill. Every change also appends a
   `StatusTransition` so the status table itself stays auditable.

3. **Provenance labeling** — `Provenance` distinguishes facts recorded
   by the live system (`runtime`) from facts backfilled by the
   deterministic migration (`legacy_import`). Migration never fabricates
   proposal/evaluation/approval provenance; where a fact is unknown it
   stays `None` and the row is labeled `legacy_import`.

Lifecycle (simplified, agreed 2026-08 product review):

    Candidate -> Approved -> Active -> Degraded -> Deprecated
         |
         +-> Rejected

`Degraded` and `Deprecated` are both excluded from retrieval; the
difference is intent — degraded is an automatic quality intervention
with a rollback target, deprecated is a human retirement decision.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---- lifecycle vocabulary ---------------------------------------------------


class SkillStatus(str, Enum):
    """Lifecycle states a skill can occupy. Strings are persisted."""

    CANDIDATE = "candidate"    # generated, not admitted
    APPROVED = "approved"      # human-approved, awaiting publication
    ACTIVE = "active"          # eligible for retrieval
    DEGRADED = "degraded"      # auto-removed after quality failure; kept for rollback
    DEPRECATED = "deprecated"  # intentionally retired or merged; file/history kept
    REJECTED = "rejected"      # proposal not admitted; rejection evidence kept


#: Statuses eligible for retrieval by the critic hot path.
RETRIEVABLE_STATUSES = frozenset({SkillStatus.ACTIVE})

#: Terminal-ish statuses from which the skill folder is retained read-only.
RETAINED_STATUSES = frozenset(
    {SkillStatus.DEGRADED, SkillStatus.DEPRECATED, SkillStatus.REJECTED}
)


Provenance = Literal["runtime", "legacy_import"]

#: Version tag of the deterministic spec/novelty gate checkers. Bumped when
#: the validation logic changes so historical gate reports stay interpretable.
SPEC_VALIDATOR_VERSION = "spec-v1"
NOVELTY_VALIDATOR_VERSION = "novelty-difflib-v1"
EVIDENCE_VALIDATOR_VERSION = "evidence-v1"

#: Version tag of the shadow-evaluation admission policy (see gates.py).
POLICY_VERSION = "precision-first-v1"


# ---- immutable record 1: provenance ------------------------------------------


class SkillLineage(BaseModel):
    """Permanent provenance row for one (skill_name, version).

    Append-only: editing or merging a skill writes a NEW row whose
    `parent_skill`/`parent_version` point at the predecessor, never an
    UPDATE. `created_at` is nullable because legacy seed skills have no
    deterministic creation timestamp — leaving it NULL beats inventing one.
    """

    lineage_id: str                       # uuid4 hex, assigned by the store
    skill_name: str
    version: str
    created_at: str | None = None         # ISO 8601 UTC; None = unknown (legacy)
    created_by: str                       # 'seed' | 'distiller' | actor string

    # Proposal linkage (learned skills only).
    source_proposal_id: str | None = None
    source_run_ids: list[str] = Field(default_factory=list)
    source_prd_hashes: list[str] = Field(default_factory=list)  # distinct, deduped
    cited_excerpts: list[str] = Field(default_factory=list)

    # Edit / merge chain.
    parent_skill: str | None = None
    parent_version: str | None = None

    # Admission (human decision — an LLM may propose but never approve).
    admission_decision: str | None = None   # 'approved' | 'rejected' | None
    admission_actor: str | None = None      # unknown for legacy_import rows
    admission_at: str | None = None

    # Governance artifact references.
    validation_report_ref: str | None = None  # gate report set id
    evaluation_ref: str | None = None         # SkillEvaluation.evaluation_id

    # Full SKILL.md text captured at admission — the rollback source.
    body_snapshot: str = ""

    provenance: Provenance = "runtime"
    recorded_at: str = ""                    # ISO 8601 UTC; set by the store


# ---- immutable record 2: per-run telemetry -----------------------------------


class SkillUseEvent(BaseModel):
    """One (run, skill) retrieval observation.

    Attribution honesty rules (HANDOFF §3):
    - `applied` is MODEL-REPORTED (`critique.skill_id == skill_name`), not
      causally validated impact.
    - `attributed_critique_ids` are server-assigned stable ids; empty for
      legacy_import events where critiques had no ids.
    - legacy events have null score/rank/provider — the flat
      `retrieved_skill_ids` set in old RunRecords carried no per-critic
      detail, and we do not backfill guesses.
    """

    event_id: str                         # uuid4 hex, assigned by the store
    run_id: str
    skill_name: str
    skill_version: str
    critic_id: str | None = None

    # Retrieval explanation (keyword/role components — see retriever).
    retrieval_score: float | None = None
    retrieval_explanation: str | None = None
    retrieval_rank: int | None = None
    retrieval_source: str | None = None   # 'in_process_retriever' | 'legacy_flat_set'

    applied: bool | None = None           # model-reported; None = unknown
    attributed_critique_ids: list[str] = Field(default_factory=list)

    provider: str | None = None
    model: str | None = None
    occurred_at: str | None = None

    provenance: Provenance = "runtime"


# ---- immutable record 3: counterfactual evaluation ---------------------------


class SkillEvaluation(BaseModel):
    """OFF/ON counterfactual record for one candidate skill version.

    `metrics_off` / `metrics_on` hold the same key set (precision, recall,
    false_p0_count, evidence_compliance, actionability, latency_seconds,
    cost_usd_estimate, …) so deltas are computable by the reader.
    `gate_result` is the admission-policy verdict over those deltas —
    computed by `src.lifecycle.gates.decide_admission`, never by hand.
    """

    evaluation_id: str                    # uuid4 hex, assigned by the store
    skill_name: str
    skill_version: str

    off_config: dict = Field(default_factory=dict)   # runs/config/model description
    on_config: dict = Field(default_factory=dict)
    metrics_off: dict = Field(default_factory=dict)
    metrics_on: dict = Field(default_factory=dict)

    target_pattern_hits: int | None = None  # ON-side runs hitting the target pattern
    gate_result: str = "fail"               # 'pass' | 'fail' | 'error'
    gate_reason: str | None = None
    policy_version: str = POLICY_VERSION
    evaluator_version: str = "shadow-v1"

    created_at: str = ""
    provenance: Provenance = "runtime"


# ---- persisted gate output ----------------------------------------------------


class GateReport(BaseModel):
    """Output of one admission-gate execution over one proposal.

    Gates: 'spec' | 'evidence' | 'novelty' | 'shadow'. `passed` is boolean;
    `detail` carries machine-readable evidence (violations, similarities,
    PRD hashes, metric deltas) so the UI can show WHY a gate failed before
    any approval action becomes available.
    """

    report_id: str                        # uuid4 hex, assigned by the store
    proposal_id: str
    gate: str                             # 'spec' | 'evidence' | 'novelty' | 'shadow'
    passed: bool
    detail: dict = Field(default_factory=dict)
    evaluator_version: str = ""
    created_at: str = ""


# ---- immutable: HITL feedback samples ------------------------------------------

#: Sliding window for "recent acceptance" in probation checks. Matches the
#: curator's ACCEPTANCE_WINDOW so both views of the same signal agree.
FEEDBACK_WINDOW = 20


class SkillFeedback(BaseModel):
    """One human accept/reject sample on a critique attributed to a skill.

    Append-only. This is the evidence base for probation decisions
    ("collect at least three feedback samples in the first five
    triggers"), so it lives with the other immutable records rather than
    only in the YAML cache. `evidence_compliance` is a deterministic
    check of the critique's evidence against the PRD text, recorded at
    feedback time — failing samples feed the degrade policy.
    """

    feedback_id: str                      # uuid4 hex, assigned by the store
    skill_name: str
    critique_uid: str | None = None
    severity: str | None = None
    accepted: bool
    evidence_compliant: bool | None = None
    at: str = ""
    provenance: Provenance = "runtime"


# ---- mutable current state + its audit trail ---------------------------------


class SkillStatusRecord(BaseModel):
    """Authoritative lifecycle pointer for one skill (mutable).

    SQLite (`skill_status` table) is the source of truth;
    `runtime_stats.yaml` is a materialized read cache regenerated from
    this row so the latency-sensitive retriever path stays unchanged.
    """

    skill_name: str
    version: str
    status: SkillStatus = SkillStatus.ACTIVE
    reason: str | None = None
    actor: str | None = None
    rollback_target: str | None = None    # '<name>@<version>' set on degrade
    probation_started_at: str | None = None
    updated_at: str = ""


class StatusTransition(BaseModel):
    """Append-only audit row for one lifecycle status change."""

    transition_id: str
    skill_name: str
    from_status: str | None
    to_status: str
    reason: str | None = None
    actor: str | None = None
    at: str = ""


# ---- migration accounting -----------------------------------------------------


class MigrationReport(BaseModel):
    """Deterministic-migration accounting — what was imported and what was
    deliberately NOT (with reasons), so the run is reproducible and
    auditable. Rerunning the migration is a no-op that returns this same
    shape with `already_migrated=True`."""

    already_migrated: bool = False
    lineages_written: list[str] = Field(default_factory=list)      # name@version
    use_events_written: int = 0
    evaluations_written: list[str] = Field(default_factory=list)   # evaluation_ids
    statuses_written: list[str] = Field(default_factory=list)      # skill names
    skipped_orphans: dict[str, str] = Field(default_factory=dict)  # name -> reason
    migrated_at: str = ""
