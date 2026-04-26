"""End-to-end pipeline entry point.

Preprocesses the raw PRD, builds the graph against the configured LLM, and
returns the final GraphState dict. The `llm` parameter is optional so tests
can inject a MockProvider instance and inspect its call_log afterwards.

`include_supervisor=False` stops after the merge node. The Streamlit UI uses
this to render critic tabs immediately, then streams the supervisor output.

Day 8 addition: after the graph completes, the run is persisted to
`data/results/history/` and any retrieved skill_ids have their `usage_count`
bumped. Telemetry failures are logged but never break the pipeline.
"""

from __future__ import annotations

import logging
import os

from pathlib import Path

from .config import get_critic_llm
from .graph.builder import build_graph
from .graph.preprocess import number_lines
from .graph.state import GraphState
from .llm.provider import LLMProvider
from .skills.curator import SkillCurator
from .storage import HistoryStore

logger = logging.getLogger(__name__)


def _default_persist() -> bool:
    """Pytest sets PRD_PIPELINE_PERSIST=0 to keep the suite hermetic."""
    return os.getenv("PRD_PIPELINE_PERSIST", "1") != "0"


def _auto_distill_enabled() -> bool:
    """Default OFF — PMs trigger the Distiller manually from the Streamlit panel.

    Set `DISABLE_AUTO_DISTILL=0` to opt in. Tests never trigger this.
    """
    return os.getenv("DISABLE_AUTO_DISTILL", "1") == "0"


# Auto-distill cadence: only when ≥ MIN_RUNS in history AND ≥ INTERVAL new
# runs since the last distill. The marker file is best-effort (a stale
# marker just means an extra distill, not data loss).
_AUTO_DISTILL_MIN_RUNS = 5
_AUTO_DISTILL_INTERVAL = 3
_AUTO_DISTILL_MARKER = Path("data") / "results" / ".last_auto_distill"


async def run_pipeline(
    prd_text: str,
    llm: LLMProvider | None = None,
    *,
    include_supervisor: bool = True,
    prd_filename: str | None = None,
    persist: bool | None = None,
) -> GraphState:
    """Run the full stress-test pipeline over a raw PRD.

    Args:
        prd_text: raw PRD body. Will be line-numbered before the graph runs.
        llm: optional pre-built provider. Tests inject MockProvider here.
        include_supervisor: when False, the graph stops at the merge node so
            the UI can stream the supervisor separately.
        prd_filename: optional source filename for run-history attribution.
        persist: when False, skip writing to `data/results/history/` and
            skip skill-usage bumping. Tests use this to keep the suite
            hermetic.
    """
    provider = llm or get_critic_llm()
    graph = build_graph(provider, include_supervisor=include_supervisor)

    numbered = number_lines(prd_text)
    initial: GraphState = {
        "prd_text": numbered,
        "prd_claims": [],
        "critiques": [],
        "challenges": [],
        "challenge_round": 0,
    }
    result = await graph.ainvoke(initial)

    # Skip auto-persist when the caller is going to stream the supervisor
    # separately (Streamlit two-phase). The verdict isn't in `result` yet,
    # so persisting here would archive an incomplete record. The caller is
    # expected to invoke `_persist_run` itself once it has the verdict.
    if include_supervisor:
        should_persist = persist if persist is not None else _default_persist()
        if should_persist:
            _persist_run(result, prd_filename=prd_filename)

    return result


def persist_run(state: GraphState, *, prd_filename: str | None = None) -> None:
    """Public alias for `_persist_run` — used by the UI two-phase path
    (which assembles the final state from a separate supervisor stream and
    can't rely on `run_pipeline`'s auto-persist).
    """
    return _persist_run(state, prd_filename=prd_filename)


def _persist_run(state: GraphState, *, prd_filename: str | None) -> None:
    """Best-effort: archive the run, then bump skill usage counts.

    Storage and curation each catch their own exceptions internally — this
    helper exists only to keep `run_pipeline` readable.
    """
    try:
        store = HistoryStore()
        record = store.save(state, prd_filename=prd_filename)
    except Exception as e:  # noqa: BLE001
        logger.warning("history persistence failed: %s", e)
        record = None

    if record is None:
        return

    # Bump usage_count for every retrieved skill — whether or not the model
    # actually attached it to a critique. Misses still tell us the retriever
    # thought this skill was relevant.
    if record.retrieved_skill_ids:
        try:
            SkillCurator().increment_usage(record.retrieved_skill_ids)
        except Exception as e:  # noqa: BLE001
            logger.warning("skill usage increment failed: %s", e)

    # Day 9: optionally fire the Distiller in the background. Off by default.
    if _auto_distill_enabled():
        try:
            _maybe_auto_distill()
        except Exception as e:  # noqa: BLE001 — telemetry never breaks the pipeline
            logger.warning("auto-distill failed: %s", e)


def _maybe_auto_distill() -> None:
    """Trigger the Distiller if cadence conditions are met.

    Synchronous — the Streamlit caller does not await background work, and
    the volume here is small (a handful of LLM calls under MockProvider).
    Real-API mode should move this onto a worker queue.
    """
    import asyncio

    from .agents.skill_distiller import run_distiller
    from .storage.proposals_store import ProposalsStore

    history = HistoryStore()
    runs = history.list_recent(n=10_000)
    if len(runs) < _AUTO_DISTILL_MIN_RUNS:
        return

    last_count = _read_last_distill_count()
    if (len(runs) - last_count) < _AUTO_DISTILL_INTERVAL:
        return

    provider = get_critic_llm()
    proposals = asyncio.run(run_distiller(provider, history))
    store = ProposalsStore()
    for p in proposals:
        store.save(p)
    _write_last_distill_count(len(runs))
    logger.info("auto-distill: persisted %d proposal(s)", len(proposals))


def _read_last_distill_count() -> int:
    try:
        return int(_AUTO_DISTILL_MARKER.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _write_last_distill_count(count: int) -> None:
    try:
        _AUTO_DISTILL_MARKER.parent.mkdir(parents=True, exist_ok=True)
        _AUTO_DISTILL_MARKER.write_text(str(count), encoding="utf-8")
    except OSError as e:
        logger.warning("auto-distill marker write failed: %s", e)
