"""Skill governance — admission, probation, degradation, rollback.

This module separates three roles the old flow collapsed into one
endpoint (HANDOFF §5: "Separate generator from verifier and human
decision"):

  - GENERATOR  — the distiller proposes (already exists, unchanged).
  - VERIFIER   — `run_gates()` runs the four independent checks and
                 persists every output with its evaluator version.
  - DECIDER    — `approve()` / `reject()` record the HUMAN decision. An
                 approval is refused unless all four latest gates passed;
                 no code path lets the model approve itself.

Post-release governance:

  - publication starts a probation window (`probation_started_at`);
  - every HITL feedback lands as an immutable SkillFeedback row and is
    mirrored into the `runtime_stats.yaml` cache (existing readers keep
    working);
  - `check_and_degrade()` applies the agreed policy — recent acceptance
    < 40 % (with >= 3 samples), a wrong P0 attributed to the skill, or a
    failed evidence-compliance check flip the skill to DEGRADED, remove
    it from retrieval, and stamp a rollback target;
  - `rollback()` restores the previous version's SKILL.md from its
    lineage snapshot. SKILL.md files are never deleted by any of this.

Storage layering (debt D-16 resolution):

  - SQLite (`LifecycleStore`) is the source of truth for records/status;
  - `runtime_stats.yaml` is a materialized read cache — maintained
    incrementally by the existing curator writes plus status mirroring
    here, so the latency-sensitive retriever path is untouched.

Open-decision default (HANDOFF §8): gates run SYNCHRONOUSLY and persist
their reports; shadow evaluation is opt-in per request because it costs
a full OFF/ON sweep.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..skills.retriever import (
    LEARNED_DIR,
    SKILL_FILENAME,
    default_retriever,
    parse_skill_md,
)
from ..storage import HistoryStore, ProposalsStore
from ..agents.skill_distiller import SkillProposal
from . import gates as gates_mod
from .gates import evidence_quotes_prd
from .models import (
    FEEDBACK_WINDOW,
    GateReport,
    SkillFeedback,
    SkillLineage,
    SkillStatus,
    SkillStatusRecord,
)
from .shadow import run_shadow_evaluation
from .store import LifecycleStore, utcnow_iso

logger = logging.getLogger(__name__)

# ---- probation policy numbers (agreed minimum) ---------------------------------

PROBATION_TRIGGER_COUNT = 5     # "first five real triggers"
PROBATION_MIN_FEEDBACK = 3      # "collect at least three feedback samples"
DEGRADE_ACCEPTANCE_FLOOR = 0.40  # "recent acceptance falls below 40%"

GATE_ORDER = ("spec", "evidence", "novelty", "shadow")


class GovernanceError(RuntimeError):
    """Raised when a governance action is refused (gates missing/failed,
    wrong lifecycle state, …). The API maps this to 409/400."""


class SkillGovernance:
    """One reusable orchestrator over the lifecycle store + legacy stores."""

    def __init__(
        self,
        store: LifecycleStore,
        *,
        history_store: HistoryStore | None = None,
        proposals_store: ProposalsStore | None = None,
        learned_dir: Path | str | None = None,
        curator_factory=None,
    ) -> None:
        self.store = store
        self.history_store = history_store or HistoryStore()
        self.proposals_store = proposals_store or ProposalsStore()
        self.learned_dir = Path(learned_dir) if learned_dir else LEARNED_DIR
        # Callable returning a SkillCurator — injected so tests point the
        # YAML cache mirror at tmp paths instead of the repo file.
        self._curator_factory = curator_factory or (
            lambda: __import__(
                "src.skills.curator", fromlist=["SkillCurator"]
            ).SkillCurator()
        )

    # ---- verifier role ----------------------------------------------------

    async def run_gates(
        self,
        proposal: SkillProposal,
        *,
        include_shadow: bool = False,
        llm_factory=None,
        prd_files: list[Path] | None = None,
    ) -> dict[str, GateReport]:
        """Run (and persist) the admission gates for one proposal.

        Spec/evidence/novelty are deterministic and cheap; the shadow
        gate costs a full OFF/ON evaluation sweep and is opt-in.
        Returns the LATEST report per gate after this run.
        """
        # Gate 1 — spec.
        spec = gates_mod.validate_spec(
            proposal.proposed_skill_md, proposal.proposed_name
        )
        self.store.append_gate_report(
            GateReport(
                report_id="",
                proposal_id=proposal.proposal_id,
                gate="spec",
                passed=spec["passed"],
                detail=spec,
                evaluator_version=spec["evaluator_version"],
            )
        )

        # Gate 2 — evidence (PRD-hash dedup via history).
        evidence = gates_mod.validate_evidence(
            proposal.evidence, self.history_store
        )
        self.store.append_gate_report(
            GateReport(
                report_id="",
                proposal_id=proposal.proposal_id,
                gate="evidence",
                passed=evidence["passed"],
                detail=evidence,
                evaluator_version=evidence["evaluator_version"],
            )
        )

        # Gate 3 — novelty vs active skills (self excluded: a proposal may
        # legitimately edit a skill that already exists under the name).
        try:
            fm, _body = parse_skill_md(proposal.proposed_skill_md)
        except Exception:  # noqa: BLE001 — spec gate reports the detail
            fm = {}
        description = str(fm.get("description") or proposal.proposed_name)
        routes = [str(r) for r in (fm.get("injected_into") or proposal.injected_into)]
        active_skills = [
            s
            for s in default_retriever().load_library().active()
            if s.name != proposal.proposed_name
        ]
        novelty = gates_mod.validate_novelty(
            proposal.proposed_name, description, routes, active_skills
        )
        self.store.append_gate_report(
            GateReport(
                report_id="",
                proposal_id=proposal.proposal_id,
                gate="novelty",
                passed=novelty["passed"],
                detail=novelty,
                evaluator_version=novelty["evaluator_version"],
            )
        )

        # Gate 4 — shadow evaluation (opt-in: costs an OFF/ON sweep).
        if include_shadow:
            if llm_factory is None or not prd_files:
                raise GovernanceError(
                    "shadow gate requires llm_factory and prd_files"
                )
            evaluation = await run_shadow_evaluation(
                proposal.proposed_name,
                proposal.proposed_skill_md,
                prd_files,
                llm_factory,
            )
            saved = self.store.append_evaluation(evaluation)
            self.store.append_gate_report(
                GateReport(
                    report_id="",
                    proposal_id=proposal.proposal_id,
                    gate="shadow",
                    passed=saved.gate_result == "pass",
                    detail={
                        "evaluation_id": saved.evaluation_id,
                        "metrics_off": saved.metrics_off,
                        "metrics_on": saved.metrics_on,
                        "target_pattern_hits": saved.target_pattern_hits,
                        "gate_reason": saved.gate_reason,
                        "policy_version": saved.policy_version,
                    },
                    evaluator_version=saved.evaluator_version,
                )
            )

        return self.store.latest_gate_reports(proposal.proposal_id)

    # ---- decider role ------------------------------------------------------

    def approve(
        self,
        proposal_id: str,
        *,
        actor: str,
        edited_md: str | None = None,
        require_gates: bool = True,
    ) -> dict:
        """Record the human APPROVE decision and publish the skill.

        Refused unless the four latest gate reports for this proposal all
        exist and all passed (`require_gates=False` exists for tests and
        legacy migrations only — never exposed on the API).
        """
        proposal = self.proposals_store.load(proposal_id)
        if proposal is None:
            raise GovernanceError(f"unknown proposal {proposal_id}")
        if proposal.status not in ("pending", "edited"):
            raise GovernanceError(
                f"proposal is {proposal.status!r}, not reviewable"
            )

        if edited_md is not None and edited_md != proposal.proposed_skill_md:
            proposal = self.proposals_store.update_status(
                proposal_id, "edited", edited_md=edited_md
            )
            if proposal is None:
                raise GovernanceError("failed to persist edit")

        if require_gates:
            latest = self.store.latest_gate_reports(proposal_id)
            missing = [g for g in GATE_ORDER if g not in latest]
            if missing:
                raise GovernanceError(
                    f"cannot approve: gate(s) not run: {', '.join(missing)}"
                )
            failed = [g for g in GATE_ORDER if not latest[g].passed]
            if failed:
                raise GovernanceError(
                    f"cannot approve: gate(s) failed: {', '.join(failed)}"
                )

        # Publish: write the SKILL.md + flip the proposal to approved.
        path = self.proposals_store.promote_to_skill(proposal_id)
        if path is None:
            raise GovernanceError("promotion failed — see server logs")

        name = proposal.proposed_name
        fm, _body = parse_skill_md(proposal.proposed_skill_md)
        version = str(fm.get("version") or "1.0")
        now = utcnow_iso()

        # Link evidence provenance from the (possibly edited) proposal.
        source_run_ids = sorted(
            {ev.get("run_id") for ev in proposal.evidence if ev.get("run_id")}
        )
        source_prd_hashes = sorted(
            {
                rec.prd_text_hash
                for rid in source_run_ids
                if (rec := self.history_store.load(rid)) is not None
            }
        )
        cited = [
            ev.get("critique_excerpt") or ""
            for ev in proposal.evidence
            if ev.get("critique_excerpt")
        ]
        shadow_reports = self.store.latest_gate_reports(proposal_id)
        evaluation_ref = None
        if "shadow" in shadow_reports:
            evaluation_ref = shadow_reports["shadow"].detail.get("evaluation_id")

        # Previous version (if the name already existed) becomes the
        # rollback target; its snapshot stays in its own lineage row.
        previous = self.store.get_lineage(name, version=None)
        parent_version = previous.version if previous is not None else None

        lineage = self.store.append_lineage(
            SkillLineage(
                lineage_id="",
                skill_name=name,
                version=version,
                created_at=now,
                created_by="distiller",
                source_proposal_id=proposal_id,
                source_run_ids=source_run_ids,
                source_prd_hashes=source_prd_hashes,
                cited_excerpts=cited,
                parent_skill=name if parent_version else None,
                parent_version=parent_version,
                admission_decision="approved",
                admission_actor=actor,
                admission_at=now,
                validation_report_ref=f"proposal:{proposal_id}",
                evaluation_ref=evaluation_ref,
                body_snapshot=proposal.proposed_skill_md,
                provenance="runtime",
            )
        )
        self.store.set_status(
            name, version, SkillStatus.APPROVED,
            reason="human approval after gates", actor=actor,
        )
        self.store.set_status(
            name, version, SkillStatus.ACTIVE,
            reason="published to learned/", actor=actor,
            probation_started_at=now,
        )
        self._bust_retriever_cache()
        return {
            "name": name,
            "version": version,
            "path": str(path),
            "lineage_id": lineage.lineage_id,
        }

    def reject(self, proposal_id: str, *, actor: str, reason: str | None = None) -> None:
        """Record the human REJECT decision. Evidence stays in the store."""
        proposal = self.proposals_store.load(proposal_id)
        if proposal is None:
            raise GovernanceError(f"unknown proposal {proposal_id}")
        updated = self.proposals_store.update_status(proposal_id, "rejected")
        if updated is not None and reason:
            updated.rejection_reason = reason
            self.proposals_store.save(updated)

    # ---- post-release governance --------------------------------------------

    def record_feedback(
        self,
        skill_name: str,
        *,
        accepted: bool,
        critique: dict | None = None,
        prd_text: str | None = None,
        curator=None,
    ) -> SkillStatusRecord | None:
        """Persist one HITL sample, mirror it to the YAML cache, then run
        the degrade policy. Returns the (possibly new DEGRADED) status."""
        compliant = None
        if critique is not None and prd_text is not None:
            compliant = evidence_quotes_prd(
                str(critique.get("evidence") or ""), prd_text
            )
        self.store.append_feedback(
            SkillFeedback(
                feedback_id="",
                skill_name=skill_name,
                critique_uid=critique.get("uid") if critique else None,
                severity=critique.get("severity") if critique else None,
                accepted=accepted,
                evidence_compliant=compliant,
            )
        )
        if curator is not None:
            try:
                curator.update_acceptance(skill_name, accepted=accepted)
            except Exception as e:  # noqa: BLE001 — cache write must not fail feedback
                logger.warning("governance: yaml cache mirror failed: %s", e)
        return self.check_and_degrade(skill_name)

    def check_and_degrade(self, skill_name: str) -> SkillStatusRecord | None:
        """Apply the probation policy; degrade + stamp rollback target if
        any trigger fires. Returns the new DEGRADED status or None."""
        status = self.store.get_status(skill_name)
        if status is None or status.status != SkillStatus.ACTIVE:
            return None

        feedback = self.store.list_feedback(skill_name, limit=FEEDBACK_WINDOW)
        reasons: list[str] = []

        accepted_n = sum(1 for f in feedback if f.accepted)
        rate = accepted_n / len(feedback) if feedback else None

        wrong_p0 = any(
            (not f.accepted) and f.severity == "P0" for f in feedback
        )
        non_compliant = any(f.evidence_compliant is False for f in feedback)

        if wrong_p0:
            reasons.append("a wrong P0 was attributed to this skill")
        if non_compliant:
            reasons.append("an attributed critique failed evidence compliance")
        if (
            rate is not None
            and len(feedback) >= PROBATION_MIN_FEEDBACK
            and rate < DEGRADE_ACCEPTANCE_FLOOR
        ):
            reasons.append(
                f"recent acceptance {rate:.0%} < {DEGRADE_ACCEPTANCE_FLOOR:.0%} "
                f"over {len(feedback)} sample(s)"
            )

        if not reasons:
            return None

        rollback_target = self._rollback_target_for(skill_name)
        new_status = self.store.set_status(
            skill_name,
            status.version,
            SkillStatus.DEGRADED,
            reason="; ".join(reasons),
            actor="policy:auto-degrade",
            rollback_target=rollback_target,
        )
        self._mirror_status_to_yaml(skill_name, "degraded", new_status.reason)
        self._bust_retriever_cache()
        logger.warning(
            "governance: skill %s DEGRADED (%s; rollback target %s)",
            skill_name, new_status.reason, rollback_target,
        )
        return new_status

    def rollback(self, skill_name: str, *, actor: str) -> dict:
        """Restore the previous active version of a DEGRADED skill.

        The snapshot comes from the rollback target's immutable lineage
        row — the current SKILL.md is overwritten, never deleted, and the
        current (bad) version's lineage row still records what happened.
        """
        status = self.store.get_status(skill_name)
        if status is None:
            raise GovernanceError(f"unknown skill {skill_name}")
        if status.status != SkillStatus.DEGRADED:
            raise GovernanceError(
                f"skill is {status.status.value}, rollback requires degraded"
            )
        target = status.rollback_target
        if not target or "@" not in target:
            raise GovernanceError(
                "no rollback target recorded — first version cannot roll back"
            )
        t_name, t_version = target.split("@", 1)
        lineage = self.store.get_lineage(t_name, t_version)
        if lineage is None or not lineage.body_snapshot:
            raise GovernanceError(
                f"rollback snapshot missing for {target} — restore from Git"
            )

        target_dir = self.learned_dir / skill_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / SKILL_FILENAME).write_text(
            lineage.body_snapshot, encoding="utf-8"
        )

        fm, _body = parse_skill_md(lineage.body_snapshot)
        restored_version = str(fm.get("version") or t_version)
        self.store.set_status(
            skill_name,
            restored_version,
            SkillStatus.ACTIVE,
            reason=f"rollback to {target}",
            actor=actor,
        )
        self._mirror_status_to_yaml(skill_name, "active", f"rollback to {target}")
        self._bust_retriever_cache()
        return {"skill": skill_name, "restored_version": restored_version, "from": target}

    def deprecate(self, skill_name: str, *, actor: str, reason: str) -> SkillStatusRecord:
        """Human retirement. Files and history are always retained."""
        status = self.store.get_status(skill_name)
        version = status.version if status else "1.0"
        new_status = self.store.set_status(
            skill_name, version, SkillStatus.DEPRECATED,
            reason=reason, actor=actor,
        )
        self._mirror_status_to_yaml(skill_name, "deprecated", reason)
        self._bust_retriever_cache()
        return new_status

    # ---- overview assembly (used by the API/UI) ------------------------------

    def overview(self) -> dict:
        """Lifecycle counts + quality signals + intervention queue."""
        statuses = self.store.list_statuses()
        by_status: dict[str, int] = {}
        for s in statuses:
            by_status[s.status.value] = by_status.get(s.status.value, 0) + 1

        interventions: list[dict] = []
        for s in statuses:
            if s.status == SkillStatus.ACTIVE:
                feedback = self.store.list_feedback(s.skill_name, limit=FEEDBACK_WINDOW)
                applied = self.store.count_use_events(s.skill_name, applied_only=True)
                in_probation = (
                    s.probation_started_at is not None and applied < PROBATION_TRIGGER_COUNT
                )
                rate = (
                    sum(1 for f in feedback if f.accepted) / len(feedback)
                    if feedback else None
                )
                if in_probation or (rate is not None and rate < DEGRADE_ACCEPTANCE_FLOOR):
                    interventions.append(
                        {
                            "skill_name": s.skill_name,
                            "probation": in_probation,
                            "triggers": applied,
                            "feedback_samples": len(feedback),
                            "recent_acceptance": rate,
                        }
                    )

        recent_admissions = sorted(
            (
                {
                    "skill_name": t.skill_name,
                    "to_status": t.to_status,
                    "at": t.at,
                    "actor": t.actor,
                    "reason": t.reason,
                }
                for t in self.store.list_transitions()
                if t.to_status in ("active", "degraded", "deprecated")
            ),
            key=lambda t: t["at"],
            reverse=True,
        )[:10]

        return {
            "counts": by_status,
            "total_skills": len(statuses),
            "degraded": [
                {
                    "skill_name": s.skill_name,
                    "reason": s.reason,
                    "rollback_target": s.rollback_target,
                    "since": s.updated_at,
                }
                for s in statuses if s.status == SkillStatus.DEGRADED
            ],
            "intervention_queue": interventions,
            "recent_admissions": recent_admissions,
        }

    # ---- internals ------------------------------------------------------------

    def _rollback_target_for(self, skill_name: str) -> str | None:
        current = self.store.get_status(skill_name)
        rows = self.store.list_lineage(skill_name)
        if current is not None and rows:
            others = [r for r in rows if r.version != current.version]
            if others:
                latest = max(others, key=lambda r: r.recorded_at)
                return f"{latest.skill_name}@{latest.version}"
        return None

    def _mirror_status_to_yaml(self, skill_name: str, status_value: str, reason: str) -> None:
        """Keep runtime_stats.yaml (the read cache) in agreement with SQLite.

        Failures are logged, never raised: the cache regenerates on the
        next write, while SQLite already holds the authoritative row.
        """
        try:
            self._curator_factory().set_status_field(skill_name, status_value, reason)
        except Exception as e:  # noqa: BLE001
            logger.warning("governance: yaml status mirror failed: %s", e)

    @staticmethod
    def _bust_retriever_cache() -> None:
        try:
            default_retriever()._library = None  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
