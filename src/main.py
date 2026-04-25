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
