"""Skill Lifecycle Center routes — overview, library, lineage, governance.

Read paths (overview/library/lineage/events/evaluations/gates) power the
three UI views; write paths (run gates, rollback, deprecate) are the
governance actions. Everything goes through `SkillGovernance` /
`LifecycleStore` — no direct SQLite access at the route layer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.eval.ablation import list_golden_prds

from .deps import get_governance, get_lifecycle_store, get_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


# ---- request bodies -----------------------------------------------------------


class RunGatesRequest(BaseModel):
    # Shadow evaluation costs a full OFF/ON sweep — opt in per request.
    include_shadow: bool = False


class DeprecateRequest(BaseModel):
    reason: str = ""


class RejectRequest(BaseModel):
    reason: str = ""


# ---- read paths ---------------------------------------------------------------


@router.get("/overview")
def overview() -> dict:
    try:
        return get_governance().overview()
    except Exception as e:  # noqa: BLE001
        logger.warning("lifecycle overview failed: %s", e)
        return {"counts": {}, "total_skills": 0, "degraded": [],
                "intervention_queue": [], "recent_admissions": []}


@router.get("/library")
def library() -> list[dict]:
    """Library view rows — status + lineage + usage/feedback aggregates."""
    store = get_lifecycle_store()
    rows: list[dict] = []
    for status in store.list_statuses():
        lineage = store.get_lineage(status.skill_name)
        feedback = store.list_feedback(status.skill_name)
        rows.append(
            {
                **status.model_dump(),
                "status": status.status.value,
                "usage_count": store.count_use_events(status.skill_name),
                "applied_count": store.count_use_events(
                    status.skill_name, applied_only=True
                ),
                "feedback_samples": len(feedback),
                "recent_acceptance": (
                    sum(1 for f in feedback if f.accepted) / len(feedback)
                    if feedback else None
                ),
                "source": (
                    {
                        "proposal_id": lineage.source_proposal_id,
                        "prd_count": len(lineage.source_prd_hashes),
                        "created_by": lineage.created_by,
                        "provenance": lineage.provenance,
                    }
                    if lineage else None
                ),
            }
        )
    return rows


@router.get("/lineage/{skill_name}")
def lineage(skill_name: str) -> dict:
    store = get_lifecycle_store()
    rows = store.list_lineage(skill_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no lineage for {skill_name!r}")
    return {
        "skill_name": skill_name,
        "versions": [r.model_dump() for r in rows],
        "transitions": [t.model_dump() for t in store.list_transitions(skill_name)],
    }


@router.get("/events")
def events(skill_name: str | None = None, limit: int = 200) -> list[dict]:
    return [
        e.model_dump()
        for e in get_lifecycle_store().list_use_events(skill_name, limit=limit)
    ]


@router.get("/evaluations")
def evaluations(skill_name: str | None = None) -> list[dict]:
    return [
        e.model_dump()
        for e in get_lifecycle_store().list_evaluations(skill_name)
    ]


@router.get("/gates/{proposal_id}")
def gate_reports(proposal_id: str) -> list[dict]:
    return [
        r.model_dump()
        for r in get_lifecycle_store().list_gate_reports(proposal_id)
    ]


# ---- write paths ---------------------------------------------------------------


@router.post("/gates/{proposal_id}/run")
async def run_gates(proposal_id: str, payload: RunGatesRequest | None = None) -> dict:
    governance = get_governance()
    proposal = governance.proposals_store.load(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")

    include_shadow = bool(payload and payload.include_shadow)
    llm_factory = None
    prd_files = None
    if include_shadow:
        llm_factory = get_llm
        prd_files = list_golden_prds()
        if not prd_files:
            raise HTTPException(status_code=500, detail="no golden PRDs available")

    try:
        latest = await governance.run_gates(
            proposal,
            include_shadow=include_shadow,
            llm_factory=llm_factory,
            prd_files=prd_files,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("run_gates failed: %s", e)
        raise HTTPException(status_code=500, detail=f"门禁执行失败：{e}") from e

    return {
        "latest": {gate: report.model_dump() for gate, report in latest.items()},
    }


@router.post("/{skill_name}/rollback")
def rollback(skill_name: str) -> dict:
    try:
        return get_governance().rollback(skill_name, actor="pm:ui")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/{skill_name}/deprecate")
def deprecate(skill_name: str, payload: DeprecateRequest | None = None) -> dict:
    reason = (payload.reason if payload and payload.reason else None) or "manual: deprecated from Lifecycle Center"
    status = get_governance().deprecate(skill_name, actor="pm:ui", reason=reason)
    return {"ok": True, "status": status.model_dump()}
