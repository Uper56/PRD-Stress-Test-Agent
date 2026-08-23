"""FastAPI app — API routers + SPA static hosting (single-origin deployment).

For local dev, run the Vite dev server (`npm run dev` in `web/`) which
proxies `/api` to this app on :8000. In production (Docker / HF Space),
the built `web/dist` is served by this same process — one container,
no CORS headaches.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.config import PROVIDER
from src.ui.rate_limit import check as rate_check
from src.ui.rate_limit import GLOBAL_PER_DAY as RATE_GLOBAL_PER_DAY
from src.ui.rate_limit import PER_IP_PER_HOUR as RATE_PER_IP_PER_HOUR

from .deps import detect_ip
from .routes_ablation import router as ablation_router
from .routes_history import router as history_router
from .routes_lifecycle import router as lifecycle_router
from .routes_review import router as review_router
from .routes_skills import router as skills_router

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="PRD Stress Test API", version="2.0")

# Local dev: the Vite dev server runs on :5173 and needs API access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)
app.include_router(history_router)
app.include_router(skills_router)
app.include_router(ablation_router)
app.include_router(lifecycle_router)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta(request: Request) -> dict:
    """Provider / model / quota state for the top-bar status chip."""
    model = (
        os.getenv("OPENAI_CRITIC_MODEL", "gpt-4o-mini")
        if PROVIDER == "openai"
        else "MockProvider"
    )
    decision = rate_check(detect_ip(request))
    return {
        "provider": PROVIDER,
        "model": model,
        "rate": {
            "disabled": decision.reason == "ok"
            and decision.remaining_global == RATE_GLOBAL_PER_DAY
            and decision.remaining_ip == RATE_PER_IP_PER_HOUR,
            "remaining_global": decision.remaining_global,
            "remaining_ip": decision.remaining_ip,
            "per_day": RATE_GLOBAL_PER_DAY,
            "per_hour": RATE_PER_IP_PER_HOUR,
        },
    }


# ---------------------------------------------------------------------------
# SPA hosting (production). Registered last so /api/* always wins.
# ---------------------------------------------------------------------------


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    candidate = WEB_DIST / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": "前端尚未构建 —— 在 web/ 下运行 `npm install && npm run build`"
    }
