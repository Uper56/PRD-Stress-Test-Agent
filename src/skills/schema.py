"""Pydantic models for the Skill Library.

A Skill is a reusable review heuristic: it ships with (a) metadata declaring
when and where it should be applied, and (b) a markdown `prompt_fragment`
that gets spliced into the relevant critic's system prompt at retrieval time.

Keeping metadata in YAML and fragment bodies as standalone .md files means:
- Skills are diff-reviewable — each fragment is a plain file.
- Non-engineers (PM / design / eval) can author new skills by dropping a
  .md into src/skills/fragments/ and appending a YAML entry.
- A future distiller agent can write new skills without learning the
  library's internal format.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Skill(BaseModel):
    """One reusable review heuristic."""

    id: str  # e.g. "skl_001_api_dependency_enumeration"
    name: str
    description: str
    trigger_keywords: list[str]
    trigger_semantic: str  # one-sentence description of when this applies
    injected_into: list[str]  # critic ids that should see this skill
    prompt_fragment_path: str  # relative to src/skills/, e.g. "fragments/skl_001.md"
    confidence: float  # 0.0–1.0, authored by the creator; curator can adjust
    usage_count: int = 0
    acceptance_rate: float | None = None
    created_at: str
    created_by: str  # "seed" | "distiller" | "<user>"
    learned_from_prds: list[str] = Field(default_factory=list)
    status: Literal["active", "deprecated"] = "active"

    # Populated at load time by the retriever — not part of the YAML on disk.
    prompt_fragment_content: str | None = None


class SkillLibrary(BaseModel):
    """Container holding every skill currently known to the system."""

    skills: list[Skill] = Field(default_factory=list)

    def by_id(self, skill_id: str) -> Skill | None:
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def active(self) -> list[Skill]:
        return [s for s in self.skills if s.status == "active"]
