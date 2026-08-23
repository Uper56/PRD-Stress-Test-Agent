"""Shared FastAPI dependencies — LLM factories, stores, IP detection.

Everything here reuses `src/` modules; nothing is re-implemented.
"""

from __future__ import annotations

import logging

from fastapi import Request

from src.config import PROVIDER, get_critic_llm
from src.lifecycle.governance import SkillGovernance
from src.lifecycle.store import DEFAULT_DB_PATH, LifecycleStore
from src.skills.curator import SkillCurator
from src.storage import HistoryStore, ProposalsStore

logger = logging.getLogger(__name__)


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
_lifecycle_store: LifecycleStore | None = None
_migration_attempted = False


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


def get_lifecycle_store() -> LifecycleStore:
    """Lifecycle store with one lazy, idempotent legacy migration.

    The migration only backfills deterministic facts (see
    src/lifecycle/migration.py); a failure is logged and the empty store
    is still returned — the review pipeline must not depend on
    governance audit to run.
    """
    global _lifecycle_store, _migration_attempted
    if _lifecycle_store is None:
        _lifecycle_store = LifecycleStore()
        if not _migration_attempted:
            _migration_attempted = True
            try:
                from src.lifecycle.migration import run_migration

                run_migration(_lifecycle_store)
            except Exception as e:  # noqa: BLE001
                logger.warning("lifecycle migration failed: %s", e)
    return _lifecycle_store


def get_governance() -> SkillGovernance:
    return SkillGovernance(
        get_lifecycle_store(),
        history_store=get_history_store(),
        proposals_store=get_proposals_store(),
        curator_factory=get_curator,
    )


def reset_lifecycle_cache() -> None:
    """Test hook — point the cached store at a fresh db (or the default)."""
    global _lifecycle_store, _migration_attempted
    if _lifecycle_store is not None:
        _lifecycle_store.close()
    _lifecycle_store = None
    _migration_attempted = False


def lifecycle_db_path():
    return DEFAULT_DB_PATH


def get_llm():
    """The one LLM instance the API uses (critic tier — same as the old UI).

    Cached in deps so repeated calls (discuss turns, distill) reuse the
    provider and its connection pool.
    """
    return get_critic_llm()
