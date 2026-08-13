"""Skill library routes — browsing, feedback, distillation, proposal review.

Reads go through the in-process `SkillRetriever` mirror (the MCP server
remains available for external consumers; the UI hot path doesn't need a
subprocess round-trip — same layering decision as the old UI).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agents.skill_distiller import run_distiller
from src.skills.mcp_client import list_skills, read_skill_md

from .deps import get_curator, get_history_store, get_llm, get_proposals_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["skills"])


class FeedbackRequest(BaseModel):
    accepted: bool


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
    """Record ✓采纳 / ✗误报 — feeds the SkillCurator's acceptance window."""
    get_curator().update_acceptance(name, accepted=payload.accepted)
    return {"ok": True, "accepted": payload.accepted}


@router.post("/skills/{name}/deprecate")
def skill_deprecate(name: str) -> dict:
    get_curator().deprecate(name, reason="manual: deprecated from UI")
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
    store = get_proposals_store()
    proposal = store.load(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    if payload and payload.edited_md and payload.edited_md != proposal.proposed_skill_md:
        store.update_status(proposal_id, "edited", edited_md=payload.edited_md)
    path = store.promote_to_skill(proposal_id)
    if path is None:
        raise HTTPException(status_code=500, detail="采纳失败 —— 请查看日志")
    return {"ok": True, "name": proposal.proposed_name, "path": str(path)}


@router.post("/proposals/{proposal_id}/reject")
def proposal_reject(proposal_id: str) -> dict:
    if get_proposals_store().load(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    get_proposals_store().update_status(proposal_id, "rejected")
    return {"ok": True}


@router.post("/proposals/{proposal_id}/save-edit")
def proposal_save_edit(proposal_id: str, payload: EditRequest) -> dict:
    if get_proposals_store().load(proposal_id) is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    get_proposals_store().update_status(
        proposal_id, "edited", edited_md=payload.edited_md
    )
    return {"ok": True}
