"""Skill retriever — loads the library and picks relevant skills for a critic.

Day 7 implementation is intentionally simple:
- Load YAML metadata + each referenced .md fragment.
- Filter by `injected_into` (does this skill apply to the given critic?).
- Rank the remaining skills by case-insensitive keyword-hit count in the PRD.
- Return the top-K, each carrying its fully-loaded `prompt_fragment_content`.

Day 9+ can swap the keyword ranker for embedding similarity without changing
this module's public surface.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .schema import Skill, SkillLibrary


DEFAULT_LIBRARY_PATH = Path(__file__).resolve().parent / "library.yaml"


class SkillRetriever:
    """Load-once, query-many retriever over the Skill Library."""

    def __init__(self, library_path: str | Path = DEFAULT_LIBRARY_PATH) -> None:
        self.library_path = Path(library_path)
        self._library: SkillLibrary | None = None

    # ---- loading ----------------------------------------------------------

    def load_library(self) -> SkillLibrary:
        """Read library.yaml + every fragment file. Caches after first call."""
        if self._library is not None:
            return self._library

        with self.library_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        skills_root = self.library_path.parent
        skills: list[Skill] = []
        for entry in raw.get("skills", []):
            skill = Skill.model_validate(entry)
            frag_path = skills_root / skill.prompt_fragment_path
            try:
                skill.prompt_fragment_content = frag_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                skill.prompt_fragment_content = None
            skills.append(skill)

        self._library = SkillLibrary(skills=skills)
        return self._library

    # ---- retrieval --------------------------------------------------------

    def retrieve(
        self,
        prd_text: str,
        critic_id: str,
        top_k: int = 3,
    ) -> list[Skill]:
        """Return up to `top_k` active skills relevant to `critic_id`.

        Ranking: sum of case-insensitive keyword occurrences in `prd_text`.
        Skills with zero keyword hits are still candidates (they return last),
        but only if the caller has room — we don't force-inject a skill that
        the PRD gave us no reason to care about.
        """
        library = self.load_library()
        candidates = [
            s
            for s in library.active()
            if critic_id in s.injected_into
        ]

        lowered = prd_text.lower()
        scored: list[tuple[int, float, Skill]] = []
        for skill in candidates:
            hits = sum(_count_keyword(kw, lowered) for kw in skill.trigger_keywords)
            # Tie-break by confidence so the better-trusted skill wins on draws.
            scored.append((hits, skill.confidence, skill))

        # Only return skills with at least one keyword hit. If none match, we
        # return []; keyword-free injection would just noise up the prompt.
        scored = [row for row in scored if row[0] > 0]
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [row[2] for row in scored[:top_k]]


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
    # Escape for regex and require word boundaries on both sides.
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
