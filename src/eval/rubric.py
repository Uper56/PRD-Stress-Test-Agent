"""Evaluation rubric — 5 dimensions for scoring stress-test runs against golden PRDs.

Scoring functions here are stubs; implementations land alongside the eval harness.
Every function takes the full set of critiques produced by one run plus the
manifest entry for the golden PRD, and returns a float in [0, 1] (or None if
not applicable).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RubricScore(BaseModel):
    """Per-run score across the five rubric dimensions."""

    structure_compliance: float = Field(
        ..., ge=0, le=1, description="1 iff every critique parses against schema."
    )
    dependency_recall: float = Field(
        ..., ge=0, le=1, description="Recall of explicit dependency-identification defects."
    )
    contradiction_detection: float = Field(
        ..., ge=0, le=1, description="Hit rate on internal-contradiction defects."
    )
    severity_classification_f1: float = Field(
        ..., ge=0, le=1, description="Macro-F1 over P0/P1/P2 vs golden severity."
    )
    actionability: float = Field(
        ..., ge=0, le=1, description="Fraction of critiques that include a concrete fix."
    )


def score_structure_compliance(critiques: list[dict]) -> float | None:
    """Return 1.0 iff every critique validates against the Critique pydantic schema,
    else the fraction that do.

    TODO: implement alongside the eval harness.
    """
    return None


def score_dependency_recall(critiques: list[dict], manifest_entry: dict) -> float | None:
    """Recall over defects tagged dimension='dependency_identification'.

    Matches a critique to a defect if the critique's evidence quote overlaps
    the defect's source line range.

    TODO: implement alongside the eval harness.
    """
    return None


def score_contradiction_detection(critiques: list[dict], manifest_entry: dict) -> float | None:
    """Hit rate over defects tagged dimension='internal_contradiction'.

    TODO: implement alongside the eval harness.
    """
    return None


def score_severity_classification_f1(critiques: list[dict], manifest_entry: dict) -> float | None:
    """Macro-F1 of predicted P0/P1/P2 against each defect's labeled severity,
    restricted to critiques that were matched to a known defect.

    TODO: implement alongside the eval harness.
    """
    return None


def score_actionability(critiques: list[dict]) -> float | None:
    """Fraction of critiques whose suggested_fix is non-empty and concrete
    (length >= N chars, contains an imperative verb).

    TODO: implement alongside the eval harness.
    """
    return None
