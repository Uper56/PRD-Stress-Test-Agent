"""End-to-end pipeline entry point.

Preprocesses the raw PRD, builds the graph against the configured LLM, and
returns the final GraphState dict. The `llm` parameter is optional so tests
can inject a MockProvider instance and inspect its call_log afterwards.

`include_supervisor=False` stops after the merge node. The Streamlit UI uses
this to render critic tabs immediately, then streams the supervisor output.
"""

from __future__ import annotations

from .config import get_critic_llm
from .graph.builder import build_graph
from .graph.preprocess import number_lines
from .graph.state import GraphState
from .llm.provider import LLMProvider


async def run_pipeline(
    prd_text: str,
    llm: LLMProvider | None = None,
    *,
    include_supervisor: bool = True,
) -> GraphState:
    """Run the full stress-test pipeline over a raw PRD."""
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
    return result
