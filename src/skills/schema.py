"""Pydantic models for the Skill Library.

Conforms to the **Anthropic Agent Skills SKILL.md spec** (Dec 2025): each
skill is a folder containing a single `SKILL.md` file with YAML frontmatter
plus a Markdown body. Runtime telemetry (usage_count, acceptance_rate,
status …) is kept in a separate `runtime_stats.yaml` so the design-time
content of a skill stays diff-clean across runs.

Three models:
  - `SkillDefinition`   — what lives on disk in SKILL.md (frontmatter + body)
  - `SkillRuntimeStats` — what lives on disk in runtime_stats.yaml
  - `Skill`             — the merged view returned by the retriever; exposes
                          a flat field surface so existing callers and the
                          MCP transport keep working without per-call merges.

Backward-compat: `Skill.id` is preserved as a field equal to `name`, so
historical RunRecord payloads (which carry `retrieved_skill_ids` /
`skill_hits` keyed on what was then `skill.id`) keep their semantics.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---- on-disk: SKILL.md frontmatter + body ---------------------------------


class SkillDefinition(BaseModel):
    """The design-time half of a skill — sourced from `SKILL.md`.

    `name` is the kebab-case unique identifier. `body` is the full Markdown
    body (everything after the closing `---` of the YAML frontmatter).
    """

    name: str  # e.g. "api-dependency-enumeration"
    description: str  # pushy one-paragraph trigger description
    version: str = "1.0"
    created_by: Literal["seed", "distiller"] = "seed"
    injected_into: list[str] = Field(default_factory=list)

    # Optional retrieval metadata kept in frontmatter for ranking transparency.
    trigger_keywords: list[str] = Field(default_factory=list)
    trigger_semantic: str | None = None
    confidence: float = 0.8

    # The Markdown body following the frontmatter (populated by the loader).
    body: str = ""


# ---- on-disk: runtime_stats.yaml ------------------------------------------


class SkillRuntimeStats(BaseModel):
    """The runtime half — sourced from `runtime_stats.yaml`, keyed by name."""

    usage_count: int = 0
    acceptance_rate: float | None = None
    last_used: str | None = None
    status: Literal["active", "deprecated"] = "active"
    learned_from_prds: list[str] = Field(default_factory=list)


# ---- merged view used by retriever / MCP / UI -----------------------------


class Skill(BaseModel):
    """Combined skill definition + runtime stats.

    Flat shape so existing callers (`mcp_client.list_skills`, the
    `<retrieved_skills>` formatter, the Streamlit sidebar) keep their
    field accesses working unchanged from the pre-Day-8.5 layout.
    """

    # Identity (id == name; kept as a separate field for back-compat with
    # historical RunRecord payloads that referenced `skill.id`).
    id: str
    name: str

    # From SkillDefinition
    description: str
    version: str = "1.0"
    created_by: str = "seed"
    injected_into: list[str] = Field(default_factory=list)
    trigger_keywords: list[str] = Field(default_factory=list)
    trigger_semantic: str | None = None
    confidence: float = 0.8

    # The full Markdown body of SKILL.md (everything after frontmatter).
    # Kept under the legacy field name so the existing
    # `format_skills_block()` and Streamlit "Show fragment" code path keep
    # rendering without changes.
    prompt_fragment_content: str = ""

    # From SkillRuntimeStats
    usage_count: int = 0
    acceptance_rate: float | None = None
    last_used: str | None = None
    status: Literal["active", "deprecated"] = "active"
    learned_from_prds: list[str] = Field(default_factory=list)

    # Filesystem provenance — set by the retriever, not on disk.
    folder: str | None = None  # absolute path to the SKILL.md folder

    @classmethod
    def from_parts(
        cls,
        definition: SkillDefinition,
        stats: SkillRuntimeStats | None = None,
        *,
        folder: str | None = None,
    ) -> "Skill":
        """Merge a definition with its runtime stats (defaulted if missing)."""
        s = stats or SkillRuntimeStats()
        return cls(
            id=definition.name,
            name=definition.name,
            description=definition.description,
            version=definition.version,
            created_by=definition.created_by,
            injected_into=definition.injected_into,
            trigger_keywords=definition.trigger_keywords,
            trigger_semantic=definition.trigger_semantic,
            confidence=definition.confidence,
            prompt_fragment_content=definition.body,
            usage_count=s.usage_count,
            acceptance_rate=s.acceptance_rate,
            last_used=s.last_used,
            status=s.status,
            learned_from_prds=s.learned_from_prds,
            folder=folder,
        )


class SkillLibrary(BaseModel):
    """Container holding every skill currently known to the system."""

    skills: list[Skill] = Field(default_factory=list)

    def by_id(self, skill_id: str) -> Skill | None:
        for s in self.skills:
            if s.id == skill_id or s.name == skill_id:
                return s
        return None

    def active(self) -> list[Skill]:
        return [s for s in self.skills if s.status == "active"]
