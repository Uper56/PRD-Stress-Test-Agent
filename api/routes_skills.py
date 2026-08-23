"""Skill library routes — browsing, feedback, distillation, proposal review.

Reads go through the in-process `SkillRetriever` mirror (the MCP server
remains available for external consumers; the UI hot path doesn't need a
subprocess round-trip — same layering decision as the old UI).

Lifecycle change: approval/rejection/feedback/deprecation now flow through
`SkillGovernance` — the human decision is recorded against immutable
lineage/status records, and approval is REFUSED unless the four admission
gates have passed (`POST /api/lifecycle/gates/{id}/run` runs them).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents.skill_distiller import run_distiller
from src.lifecycle.governance import GovernanceError
from src.skills.mcp_client import list_skills, read_skill_md

from .deps import (
    get_curator,
    get_governance,
    get_history_store,
    get_llm,
    get_proposals_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])


class FeedbackRequest(BaseModel):
    accepted: bool
    # Optional context so the feedback becomes auditable lifecycle
    # evidence: the critique that carried the skill attribution and the
    # PRD text it was reviewed against (evidence-compliance check).
    critique: dict | None = None
    prd_text: str | None = None


class EditRequest(BaseModel):
    edited_md: str


@router.get("/skills")
def skills() -> list[dict]:
    try:
        return list_skills(status="active")
    except Exception:  # noqa: BLE001
        return []


@router.get("/skills/{name}/md")
def skill_md(name: str) -> dict:
    try:
        return {"name": name, "md": read_skill_md(name)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/skills/{name}/feedback")
def skill_feedback(name: str, payload: FeedbackRequest) -> dict:
    """Record ✓采纳 / ✗误报 — immutable SkillFeedback + YAML cache mirror,
    then run the auto-degrade probation policy."""
    status = get_governance().record_feedback(
        name,
        accepted=payload.accepted,
        critique=payload.critique,
        prd_text=payload.prd_text,
        curator=get_curator(),
    )
    return {
        "ok": True,
        "accepted": payload.accepted,
        "degraded": status is not None and status.status.value == "degraded",
    }


@router.post("/skills/{name}/deprecate")
def skill_deprecate(name: str) -> dict:
    get_governance().deprecate(name, actor="pm:ui", reason="manual: deprecated from UI")
    return {"ok": True}


@router.post("/distill")
async def distill() -> dict:
    """Run the Skill Distiller over history; save candidates as proposals."""
    history = get_history_store()
    try:
        proposals = await run_distiller(get_llm(), history)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"提炼失败：{e}") from e
    store = get_proposals_store()
    for proposal in proposals:
        store.save(proposal)
    return {"found": len(proposals)}


@router.get("/proposals")
def proposals() -> list[dict]:
    try:
        return [p.model_dump() for p in get_proposals_store().list_pending()]
    except Exception:  # noqa: BLE001
        return []


@router.post("/proposals/{proposal_id}/approve")
def proposal_approve(proposal_id: str, payload: EditRequest | None = None) -> dict:
    governance = get_governance()
    if governance.proposals_store.load(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    try:
        result = governance.approve(
            proposal_id,
            actor="pm:ui",
            edited_md=payload.edited_md if payload else None,
        )
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"ok": True, **result}


@router.post("/proposals/{proposal_id}/reject")
def proposal_reject(proposal_id: str) -> dict:
    governance = get_governance()
    if governance.proposals_store.load(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    try:
        governance.reject(proposal_id, actor="pm:ui")
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"ok": True}


@router.post("/proposals/{proposal_id}/save-edit")
def proposal_save_edit(proposal_id: str, payload: EditRequest) -> dict:
    if get_proposals_store().load(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    get_proposals_store().update_status(
        proposal_id, "edited", edited_md=payload.edited_md
    )
    return {"ok": True}
