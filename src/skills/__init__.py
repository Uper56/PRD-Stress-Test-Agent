"""Skill Library — reusable review heuristics shared across critics.

Public surface:
  - Skill, SkillLibrary         (src/skills/schema.py)
  - SkillRetriever              (src/skills/retriever.py)
  - default_retriever()         (module-level singleton)
  - format_skills_block(skills) (render to `<retrieved_skills>` XML)
"""

from .retriever import SkillRetriever, default_retriever, format_skills_block
from .schema import Skill, SkillLibrary

__all__ = [
    "Skill",
    "SkillLibrary",
    "SkillRetriever",
    "default_retriever",
    "format_skills_block",
]
