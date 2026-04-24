"""LangGraph assembly.

Default shape:
  intake → [4 critics in parallel] → merge → cross_challenge → supervisor → END

`include_supervisor=False` shape (used by the UI for streamed supervisor):
  intake → [4 critics in parallel] → merge → cross_challenge → END

The `critiques` key on GraphState uses an `operator.add` reducer, so the four
critic nodes can write in parallel and LangGraph concatenates their outputs.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..agents.critics.business import run_business
from ..agents.critics.design import run_design
from ..agents.critics.engineering import run_engineering
from ..agents.critics.user_advocate import run_user_advocate
from ..agents.intake import run_intake
from ..agents.supervisor import run_supervisor
from ..graph.state import SupervisorVerdict
from ..llm.provider import LLMProvider
from .edges import run_cross_challenge
from .state import GraphState


def build_graph(llm: LLMProvider, *, include_supervisor: bool = True):
    """Compile and return a LangGraph app bound to the given LLM provider.

    When `include_supervisor` is False, the graph ends at the merge node, so
    the Streamlit UI can run critics to completion and then stream the
    supervisor separately.
    """

    async def intake_node(state: GraphState) -> dict:
        claims = await run_intake(state.get("prd_text", ""), llm)
        return {"prd_claims": claims}

    async def user_advocate_node(state: GraphState) -> dict:
        return {"critiques": await run_user_advocate(state, llm)}

    async def engineering_node(state: GraphState) -> dict:
        return {"critiques": await run_engineering(state, llm)}

    async def business_node(state: GraphState) -> dict:
        return {"critiques": await run_business(state, llm)}

    async def design_node(state: GraphState) -> dict:
        return {"critiques": await run_design(state, llm)}

    async def merge_node(state: GraphState) -> dict:
        # Passthrough: `critiques` already merged via operator.add reducer.
        # This node is the fan-in barrier — every downstream step (cross-
        # challenge, supervisor) is serialized against it.
        return {}

    async def cross_challenge_node(state: GraphState) -> dict:
        # Delegates to edges.run_cross_challenge which owns the round logic
        # and convergence detection.
        return await run_cross_challenge(state, llm)

    async def supervisor_node(state: GraphState) -> dict:
        verdict_dict = await run_supervisor(state, llm)
        try:
            verdict_model = SupervisorVerdict.model_validate(verdict_dict)
        except Exception:  # validation already handled inside run_supervisor
            verdict_model = None
        return {
            "supervisor_verdict": verdict_model,
            "final_report": verdict_dict,
        }

    g = StateGraph(GraphState)
    g.add_node("intake", intake_node)
    g.add_node("user_advocate", user_advocate_node)
    g.add_node("engineering", engineering_node)
    g.add_node("business", business_node)
    g.add_node("design", design_node)
    g.add_node("merge", merge_node)
    g.add_node("cross_challenge", cross_challenge_node)

    g.set_entry_point("intake")
    for critic in ("user_advocate", "engineering", "business", "design"):
        g.add_edge("intake", critic)
        g.add_edge(critic, "merge")
    g.add_edge("merge", "cross_challenge")

    if include_supervisor:
        g.add_node("supervisor", supervisor_node)
        g.add_edge("cross_challenge", "supervisor")
        g.add_edge("supervisor", END)
    else:
        g.add_edge("cross_challenge", END)

    return g.compile()
