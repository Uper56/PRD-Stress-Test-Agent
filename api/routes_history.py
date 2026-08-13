"""History routes — archived runs from the on-disk HistoryStore."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .deps import get_history_store

router = APIRouter(prefix="/api", tags=["history"])


def _verdict_counts(verdict: dict) -> dict[str, int]:
    return {
        "p0": len(verdict.get("p0_blockers", []) or []),
        "p1": len(verdict.get("p1_concerns", []) or []),
        "p2": len(verdict.get("p2_suggestions", []) or []),
    }


@router.get("/history")
def list_history(n: int = 20) -> list[dict]:
    try:
        runs = get_history_store().list_recent(n=n)
    except Exception:  # noqa: BLE001 — keep the UI alive if the disk broke
        return []
    return [
        {
            "run_id": r.run_id,
            "timestamp": r.timestamp,
            "prd_filename": r.prd_filename,
            "excerpt": r.prd_text_excerpt,
            "summary": (r.supervisor_verdict or {}).get("executive_summary"),
            **_verdict_counts(r.supervisor_verdict or {}),
            "critique_count": len(r.critiques),
            "skill_hits": len(r.skill_hits),
            "skill_misses": len(r.skill_misses),
        }
        for r in runs
    ]


@router.get("/history/{run_id}")
def get_history_run(run_id: str) -> dict:
    record = get_history_store().load(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record.model_dump()


@router.delete("/history/{run_id}")
def delete_history_run(run_id: str) -> dict:
    """Remove one archived run (file + index entry)."""
    removed = get_history_store().delete(run_id)
    if not removed:
        raise HTTPException(status_code=404, detail="run not found")
    return {"ok": True, "deleted": run_id}
