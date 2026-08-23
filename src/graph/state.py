"""LangGraph state schema.

Defines the Pydantic models exchanged between nodes and the TypedDict state
container that LangGraph reduces across the graph. Lists that are written to
by parallel nodes (e.g. critiques) use `Annotated[..., operator.add]` so
LangGraph merges them instead of overwriting.
"""

from __future__ import annotations

import hashlib
import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


def critique_uid(critique: dict) -> str:
    """Stable per-critique id — hashes (critic_id, claim_id, finding).

    Shared by the API layer (follow-up dialogs, feedback) and the
    lifecycle telemetry (attributed_critique_ids) so both sides derive
    the same id from the same critique dict.
    """
    raw = (
        f"{critique.get('critic_id', '?')}|"
        f"{critique.get('claim_id', '?')}|{critique.get('finding', '')}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


Severity = Literal["P0", "P1", "P2"]
ClaimType = Literal["assumption", "requirement", "metric", "scope", "dependency"]


class PRDClaim(BaseModel):
    """A single atomic claim extracted from the PRD by the intake agent."""

    claim_id: str
    source_line: int
    claim_text: str
    claim_type: ClaimType


class Critique(BaseModel):
    """One finding produced by a critic agent against a specific claim."""

    critic_id: str
    claim_id: str
    severity: Severity
    finding: str
    evidence: str = Field(
        ..., description="Must quote or line-reference the PRD — no free invention."
    )
    suggested_fix: str
    skill_id: str | None = None


class CrossChallenge(BaseModel):
    """A critic's challenge to another critic's critique, across rounds."""

    round: int
    challenger: str
    target_critique_id: str
    counter_finding: str


class SupervisorVerdict(BaseModel):
    """Final synthesized decision from the supervisor agent."""

    executive_summary: str
    p0_blockers: list[str] = Field(default_factory=list)
    p1_concerns: list[str] = Field(default_factory=list)
    p2_suggestions: list[str] = Field(default_factory=list)
    conflict_resolutions: list[str] = Field(default_factory=list)


class GraphState(TypedDict, total=False):
    """LangGraph-managed state. Parallel critic writes are merged via operator.add."""

    prd_text: str
    prd_claims: list[PRDClaim]
    retrieved_skills: list[dict]
    critiques: Annotated[list[Critique], operator.add]
    challenges: Annotated[list[CrossChallenge], operator.add]
    challenge_round: int
    convergence_signal: bool
    supervisor_verdict: SupervisorVerdict | None
    final_report: dict
    run_id: str
    total_tokens: int
    total_cost_usd: float
