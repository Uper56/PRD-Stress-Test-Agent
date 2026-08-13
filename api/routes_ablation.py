"""Ablation routes — latest report, background rerun, status polling.

The quick ablation takes ~1 minute with the real LLM, so reruns run as
background tasks and the client polls for completion (mirrors the old
UI's spinner behaviour without blocking a request for a minute).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.eval.ablation import (
    DEFAULT_OUTPUT_DIR,
    AblationConfig,
    list_golden_prds,
    run_ablation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ablation"])

_TREATMENTS = ["skill_off", "skill_seed_only", "skill_seed_plus_learned"]

_jobs: dict[str, dict] = {}


class AblationRunRequest(BaseModel):
    quick: bool = True


@router.get("/ablation")
def ablation_latest() -> dict | None:
    """Latest ablation report, or null when none has been generated yet."""
    latest = DEFAULT_OUTPUT_DIR / "latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"latest.json 加载失败：{e}") from e


@router.post("/ablation/run", status_code=202)
def ablation_run(payload: AblationRunRequest) -> dict:
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"status": "running", "message": None}

    async def _task() -> None:
        try:
            await run_ablation(
                prd_files=list_golden_prds(),
                treatments=[AblationConfig.preset(n) for n in _TREATMENTS],
                runs_per_treatment=1 if payload.quick else 3,
                output_dir=DEFAULT_OUTPUT_DIR,
            )
            _jobs[job_id] = {"status": "done", "message": None}
        except Exception as e:  # noqa: BLE001
            logger.exception("ablation job %s failed", job_id)
            _jobs[job_id] = {"status": "failed", "message": str(e)}

    asyncio.get_running_loop().create_task(_task())
    return {"job_id": job_id}


@router.get("/ablation/status/{job_id}")
def ablation_status(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
