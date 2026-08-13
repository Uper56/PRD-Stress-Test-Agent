"""Review routes — submit PRD, stream the pipeline over SSE, discuss critiques.

The two-phase pattern mirrors the battle-tested Streamlit flow
(`src/ui/streamlit_app.py`): run the graph through the merge node first
(`include_supervisor=False`), push critic findings + cross-challenges to
the client immediately, then stream the supervisor separately and persist
the complete record at the end.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agents.critique_dialog import MAX_DIALOG_ROUNDS, run_critique_dialog
from src.agents.supervisor import run_supervisor_stream
from src.agents._language import force_language
from src.eval.ablation import list_golden_prds
from src.graph.state import Critique
from src.main import run_pipeline
from src.ui.prd_loader import (
    EmptyExtractionError,
    FileTooLargeError,
    PRDLoaderError,
    UnsupportedFileType,
    extract_text as extract_prd_text,
)
from src.ui.rate_limit import consume as rate_consume

from .deps import detect_ip, get_curator, get_history_store, get_llm
from .runs import Run, RunHub
from .sse import SSE_HEADERS, sse_frame

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reviews"])

hub = RunHub()

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # matches the old Streamlit upload cap


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    prd_text: str = Field(min_length=1)
    prd_filename: str | None = None
    # "auto" (default) detects from the PRD; "zh"/"en" force the verdict
    # language regardless of the PRD's language. Evidence quotes are always
    # kept verbatim in the PRD's original language (see the directive in
    # src/agents/_language.py).
    language: str = "auto"


class DiscussRequest(BaseModel):
    critique_uid: str
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


def _critique_uid(c: dict) -> str:
    """Same stable id as the old UI — hashes (critic_id, claim_id, finding)."""
    raw = f"{c.get('critic_id','?')}|{c.get('claim_id','?')}|{c.get('finding','')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


async def _execute_run(run: Run, llm) -> None:
    """Run the two-phase pipeline and stream every milestone into `run`.

    The language context (when forced) is set here so every agent prompt
    built during this run inherits it — contextvars propagate into the
    asyncio task tree.
    """
    token = force_language(run.language) if run.language else None
    try:
        await run.push("phase", {"name": "graph"})
        state = await run_pipeline(
            run.prd_text,
            llm=llm,
            include_supervisor=False,
            prd_filename=run.prd_filename,
        )
        critiques = [
            c.model_dump() if hasattr(c, "model_dump") else dict(c)
            for c in (state.get("critiques", []) or [])
        ]
        # Stable per-critique uid, computed server-side — the client uses it
        # verbatim when opening a follow-up dialog (no hash drift between sides).
        for c in critiques:
            c["uid"] = _critique_uid(c)
        challenges = [
            c.model_dump() if hasattr(c, "model_dump") else dict(c)
            for c in (state.get("challenges", []) or [])
        ]
        await run.push("critiques", {"critiques": critiques})
        await run.push(
            "challenges",
            {
                "challenges": challenges,
                "rounds": state.get("challenge_round", 0) or 0,
                "converged": bool(state.get("convergence_signal", False)),
            },
        )

        await run.push("phase", {"name": "supervisor"})
        verdict: dict = {}
        async for event in run_supervisor_stream(dict(state), llm):
            stage = event.get("stage")
            if stage == "thinking":
                await run.push("thinking", {"delta": event.get("delta", "")})
            elif stage == "done":
                verdict = event.get("final_verdict", {}) or {}
        await run.push("verdict", {"verdict": verdict})

        final_state = dict(state)
        final_state["final_report"] = verdict
        # Persist via the injected stores (mirrors src.main._persist_run, but
        # we need the returned record: HistoryStore mints its own canonical
        # run_id, which is what /api/history lists. The hub id stays the
        # streaming id; both are handed to the client in the done event.
        record = None
        try:
            record = get_history_store().save(
                final_state, prd_filename=run.prd_filename
            )
            if record is not None and record.retrieved_skill_ids:
                get_curator().increment_usage(record.retrieved_skill_ids)
        except Exception as e:  # noqa: BLE001 — archive failure must not kill the stream
            logger.warning("history persistence failed for %s: %s", run.run_id, e)
            await run.push(
                "error",
                {"message": f"历史记录保存失败：{e}", "retryable": False},
            )

        run.state = final_state
        run.verdict = verdict
        run.history_run_id = record.run_id if record else None
        await run.push(
            "done",
            {
                "run_id": run.run_id,
                "history_run_id": run.history_run_id,
                "verdict": verdict,
            },
        )
    except Exception as e:  # noqa: BLE001 — surface as an in-stream error event
        logger.exception("run %s failed", run.run_id)
        run.error = str(e)
        await run.push("error", {"message": str(e), "retryable": False})
    finally:
        if token is not None:
            token.var.reset(token)
        run.finished = True
        run.finished_at = time.time()
        hub.prune()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/reviews", status_code=202)
async def start_review(payload: ReviewRequest, request: Request) -> dict:
    """Start a review: debit quota, spawn the pipeline, hand back a stream URL."""
    if not payload.prd_text.strip():
        raise HTTPException(status_code=422, detail="PRD 内容为空")

    decision = rate_consume(detect_ip(request))
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "reason": decision.reason,
                "remaining_global": decision.remaining_global,
                "remaining_ip": decision.remaining_ip,
            },
        )

    run = hub.create(payload.prd_text, payload.prd_filename)
    run.language = payload.language if payload.language in ("zh", "en") else None
    asyncio.get_running_loop().create_task(_execute_run(run, get_llm()))
    return {
        "run_id": run.run_id,
        "stream_url": f"/api/reviews/{run.run_id}/stream",
    }


@router.get("/reviews/{run_id}/stream")
async def stream_review(run_id: str, request: Request) -> StreamingResponse:
    """SSE stream of one run. Replays missed events on reconnect via Last-Event-ID."""
    run = hub.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    try:
        last_seen = int(request.headers.get("last-event-id", "0") or "0")
    except ValueError:
        last_seen = 0

    async def gen():
        cursor = 0
        while True:
            # 1) Drain backlog from the cursor (or replay from last_seen).
            with_run = hub.get(run_id)
            if with_run is None:
                yield sse_frame(0, "error", {"message": "run not found", "retryable": False})
                return
            events = with_run.events
            while cursor < len(events):
                event_id, event_type, data = events[cursor]
                cursor += 1
                if event_id <= last_seen:
                    continue
                yield sse_frame(event_id, event_type, data)
            if with_run.finished:
                return
            # 2) Wait for new events.
            async with with_run._cond:
                if not with_run.finished and cursor >= len(with_run.events):
                    await with_run._cond.wait()

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/reviews/{run_id}")
async def get_review(run_id: str) -> dict:
    """Final state of a run (in-memory while fresh; 404 once pruned)."""
    run = hub.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run.run_id,
        "history_run_id": run.history_run_id,
        "finished": run.finished,
        "verdict": run.verdict,
        "state": run.state,
        "error": run.error,
    }


@router.post("/reviews/{run_id}/discuss")
async def discuss(run_id: str, payload: DiscussRequest) -> StreamingResponse:
    """Stream a critic's reply to a follow-up question over SSE.

    The critique is resolved server-side from the run's findings (by the
    same stable uid the UI uses), so clients can't inject arbitrary PRDs.
    """
    run = hub.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    if len(payload.messages) >= MAX_DIALOG_ROUNDS * 2:
        raise HTTPException(
            status_code=400,
            detail=f"已达到追问上限（{MAX_DIALOG_ROUNDS} 轮）",
        )

    critique_dict = None
    for c in (run.state or {}).get("critiques", []) or []:
        candidate = c.model_dump() if hasattr(c, "model_dump") else dict(c)
        if _critique_uid(candidate) == payload.critique_uid:
            critique_dict = candidate
            break
    if critique_dict is None:
        raise HTTPException(status_code=404, detail="critique not found")

    critique_obj = Critique.model_validate(
        {k: v for k, v in critique_dict.items() if k in Critique.model_fields}
    )
    history = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in payload.messages
        if m.get("role") in {"user", "assistant"}
    ]

    async def gen():
        token = force_language(run.language) if run.language else None
        try:
            async for event in run_critique_dialog(
                critic_id=critique_dict["critic_id"],
                original_critique=critique_obj,
                prd_text=run.prd_text,
                conversation_history=history,
                llm=get_llm(),
            ):
                if event.get("type") == "text":
                    yield sse_frame(0, "delta", {"delta": event.get("delta", "")})
            yield sse_frame(0, "done", {})
        except Exception as e:  # noqa: BLE001
            yield sse_frame(0, "error", {"message": str(e), "retryable": False})
        finally:
            if token is not None:
                token.var.reset(token)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/golden-prds")
def golden_prds() -> list[dict]:
    """Built-in sample PRDs for the composer's「选择内置 PRD」mode."""
    return [
        {"filename": p.name, "content": p.read_text(encoding="utf-8")}
        for p in sorted(list_golden_prds())
    ]


@router.post("/uploads")
async def upload_prd(file: UploadFile) -> dict:
    """Parse a PDF/Word/Markdown/TXT PRD upload into plain text."""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 2 MB 上限")
    try:
        text = extract_prd_text(file.filename or "upload", raw)
    except (UnsupportedFileType, FileTooLargeError, EmptyExtractionError, PRDLoaderError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"filename": file.filename, "chars": len(text), "text": text}
