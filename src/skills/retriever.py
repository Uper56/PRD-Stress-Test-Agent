"""Skill retriever — loads the Anthropic-Agent-Skills library and ranks for a critic.

Day 8.5: switched the on-disk format from `library.yaml + fragments/` to the
**Anthropic Agent Skills SKILL.md spec** (Dec 2025). Each skill is a folder
containing one `SKILL.md` (YAML frontmatter + Markdown body). Runtime
telemetry is kept separately in `runtime_stats.yaml`. The retriever fuses
the two on load.

Layout:
    src/skills/
      ├── seed/<skill-name>/SKILL.md        # human-authored
      ├── learned/<skill-name>/SKILL.md     # distiller-authored (Day 9+)
      └── runtime_stats.yaml                # usage_count / status per name

Lifecycle addition: `retrieve_scored()` exposes the keyword/role match
components, rank, and rejected zero-hit candidates so the caller can
persist explainable retrieval telemetry (SkillUseEvent). `retrieve()`
keeps the original signature and delegates.

Public surface (`SkillRetriever.load_library`, `.retrieve`,
`format_skills_block`, `default_retriever`) is unchanged from Day 7 so
critic code keeps working without edits.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .schema import Skill, SkillDefinition, SkillLibrary, SkillRuntimeStats

logger = logging.getLogger(__name__)


SKILLS_ROOT = Path(__file__).resolve().parent
SEED_DIR = SKILLS_ROOT / "seed"
LEARNED_DIR = SKILLS_ROOT / "learned"
RUNTIME_STATS_PATH = SKILLS_ROOT / "runtime_stats.yaml"
SKILL_FILENAME = "SKILL.md"


# ---- frontmatter parsing ---------------------------------------------------


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<yaml>.*?)\n---\s*\n?(?P<body>.*)\Z",
    re.DOTALL,
)


def parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md file into (frontmatter dict, markdown body).

    Raises ValueError if the file does not begin with a `---` frontmatter
    fence — every SKILL.md is required to have one. Lightweight homegrown
    parser; no `python-frontmatter` dependency.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(
            "SKILL.md missing YAML frontmatter fence (expected leading '---')"
        )
    fm_raw = m.group("yaml")
    body = m.group("body")
    fm = yaml.safe_load(fm_raw) or {}
    if not isinstance(fm, dict):
        raise ValueError("SKILL.md frontmatter must parse to a mapping")
    return fm, body


# ---- retriever -------------------------------------------------------------


@dataclass
class ScoredSkill:
    """One retrieval result with its explainable score components.

    `explanation` names the keyword components that contributed (the
    role/`injected_into` match is implied by the query); `rejected`
    lists same-role candidates that scored zero keyword hits and were
    filtered — persisted so retrieval misses stay auditable.
    """

    skill: Skill
    score: int
    rank: int
    explanation: str
    rejected: list[str] = field(default_factory=list)


class SkillRetriever:
    """Load-once, query-many retriever over the Skill Library."""

    def __init__(
        self,
        skills_root: str | Path | None = None,
        runtime_stats_path: str | Path | None = None,
    ) -> None:
        root = Path(skills_root) if skills_root else SKILLS_ROOT
        self.skills_root = root
        self.seed_dir = root / "seed"
        self.learned_dir = root / "learned"
        self.runtime_stats_path = (
            Path(runtime_stats_path) if runtime_stats_path else root / "runtime_stats.yaml"
        )
        self._library: SkillLibrary | None = None

    # ---- loading ----------------------------------------------------------

    def load_library(self) -> SkillLibrary:
        """Scan seed/ + learned/ for SKILL.md folders, merge runtime stats."""
        if self._library is not None:
            return self._library

        stats_by_name = self._load_runtime_stats()

        skills: list[Skill] = []
        for folder in self._discover_skill_folders():
            skill_md = folder / SKILL_FILENAME
            try:
                text = skill_md.read_text(encoding="utf-8")
                fm, body = parse_skill_md(text)
                fm["body"] = body
                definition = SkillDefinition.model_validate(fm)
            except Exception as e:  # noqa: BLE001
                logger.warning("Skipping %s: %s", skill_md, e)
                continue

            stats = stats_by_name.get(definition.name)  # may be None
            skills.append(
                Skill.from_parts(definition, stats, folder=str(folder))
            )

        self._library = SkillLibrary(skills=skills)
        return self._library

    def _discover_skill_folders(self) -> list[Path]:
        """Yield every directory under seed/ + learned/ that contains SKILL.md."""
        out: list[Path] = []
        for parent in (self.seed_dir, self.learned_dir):
            if not parent.exists():
                continue
            for child in sorted(parent.iterdir()):
                if child.is_dir() and (child / SKILL_FILENAME).is_file():
                    out.append(child)
        return out

    def _load_runtime_stats(self) -> dict[str, SkillRuntimeStats]:
        if not self.runtime_stats_path.exists():
            return {}
        try:
            with self.runtime_stats_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("runtime_stats.yaml unreadable: %s", e)
            return {}
        skills_map = (raw.get("skills") or {}) if isinstance(raw, dict) else {}
        out: dict[str, SkillRuntimeStats] = {}
        for name, payload in skills_map.items():
            try:
                out[name] = SkillRuntimeStats.model_validate(payload or {})
            except Exception as e:  # noqa: BLE001
                logger.warning("runtime stats invalid for %r: %s", name, e)
        return out

    # ---- retrieval --------------------------------------------------------

    def retrieve(
        self,
        prd_text: str,
        critic_id: str,
        top_k: int = 3,
    ) -> list[Skill]:
        """Return up to `top_k` active skills relevant to `critic_id`.

        Ranking: sum of case-insensitive keyword occurrences in `prd_text`.
        Skills with zero keyword hits are filtered out — keyword-free
        injection would just noise up the prompt.
        """
        return [hit.skill for hit in self.retrieve_scored(prd_text, critic_id, top_k)]

    def retrieve_scored(
        self,
        prd_text: str,
        critic_id: str,
        top_k: int = 3,
    ) -> list[ScoredSkill]:
        """`retrieve()` plus the score components, rank, and rejects.

        The lifecycle telemetry layer persists these components verbatim
        (SkillUseEvent.retrieval_score / .retrieval_explanation / .rank)
        so every retrieval decision stays explainable after the fact.
        """
        library = self.load_library()
        candidates = [
            s for s in library.active() if critic_id in s.injected_into
        ]

        lowered = prd_text.lower()
        scored: list[tuple[int, float, Skill, list[str]]] = []
        rejected: list[str] = []
        for skill in candidates:
            components: list[str] = []
            hits = 0
            for kw in skill.trigger_keywords:
                n = _count_keyword(kw, lowered)
                if n:
                    hits += n
                    components.append(f"{kw}×{n}")
            if hits == 0:
                rejected.append(skill.name)
                continue
            scored.append((hits, skill.confidence, skill, components))

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        out: list[ScoredSkill] = []
        for rank, (hits, _conf, skill, components) in enumerate(scored[:top_k], start=1):
            explanation = (
                f"keyword components: {', '.join(components)}; "
                f"role match: {critic_id}; cutoff: top_k={top_k}"
            )
            out.append(
                ScoredSkill(
                    skill=skill,
                    score=hits,
                    rank=rank,
                    explanation=explanation,
                    rejected=sorted(rejected),
                )
            )
        return out


@lru_cache(maxsize=1)
def default_retriever() -> SkillRetriever:
    """Process-global singleton; fine because the library is read-only at runtime."""
    r = SkillRetriever()
    r.load_library()
    return r


# ---- helpers ---------------------------------------------------------------


def _count_keyword(keyword: str, lowered_text: str) -> int:
    """Count non-overlapping case-insensitive occurrences of `keyword`.

    Multi-word keywords use a simple substring count. Single-word keywords
    use a word-boundary regex so "api" doesn't match "capital".
    """
    kw = keyword.strip().lower()
    if not kw:
        return 0
    if " " in kw:
        return lowered_text.count(kw)
    return len(re.findall(rf"\b{re.escape(kw)}\b", lowered_text))


def format_skills_block(skills: list[Skill]) -> str:
    """Render retrieved skills as the `<retrieved_skills>` block critics expect.

    Matches the contract documented in `src/agents/critics/_shared.py:
    SKILL_CONTEXT_RULES` — critics use this block to decide which
    `skill_id` (if any) to emit on each critique.
    """
    if not skills:
        return ""
    parts = ["<retrieved_skills>"]
    for s in skills:
        body = (s.prompt_fragment_content or s.description).strip()
        parts.append(f'  <skill id="{s.id}" name="{s.name}">')
        parts.append(body)
        parts.append("  </skill>")
    parts.append("</retrieved_skills>")
    return "\n".join(parts)
