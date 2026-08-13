"""Shared FastAPI dependencies — LLM factories, stores, IP detection.

Everything here reuses `src/` modules; nothing is re-implemented.
"""

from __future__ import annotations

from fastapi import Request

from src.config import PROVIDER, get_critic_llm
from src.skills.curator import SkillCurator
from src.storage import HistoryStore, ProposalsStore


def detect_ip(request: Request) -> str | None:
    """Best-effort client IP from proxy headers (HF Space sets x-forwarded-for).

    Mirrors the semantics of `src/ui/rate_limit.detect_ip`, adapted from the
    Streamlit context to a plain ASGI request.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real
    return request.client.host if request.client else None


# Cached store instances. Function accessors (not module singletons) so
# tests can monkeypatch them to point at tmp dirs.
_history_store: HistoryStore | None = None
_proposals_store: ProposalsStore | None = None
_curator: SkillCurator | None = None


def get_history_store() -> HistoryStore:
    global _history_store
    if _history_store is None:
        _history_store = HistoryStore()
    return _history_store


def get_proposals_store() -> ProposalsStore:
    global _proposals_store
    if _proposals_store is None:
        _proposals_store = ProposalsStore()
    return _proposals_store


def get_curator() -> SkillCurator:
    global _curator
    if _curator is None:
        _curator = SkillCurator()
    return _curator


def get_llm():
    """The one LLM instance the API uses (critic tier — same as the old UI).

    Cached in deps so repeated calls (discuss turns, distill) reuse the
    provider and its connection pool.
    """
    return get_critic_llm()
