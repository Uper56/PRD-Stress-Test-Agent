"""Verify every SKILL.md on disk conforms to the Anthropic Agent Skills spec.

The spec requires a YAML frontmatter fence with at minimum:
  - name (kebab-case, unique, matches the folder name)
  - description (non-empty, pushy trigger description)
  - version
  - created_by   ("seed" or "distiller")
  - injected_into (non-empty list of critic_ids)

Plus a non-empty Markdown body following the closing `---` fence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.skills.retriever import (
    LEARNED_DIR,
    SEED_DIR,
    SKILL_FILENAME,
    parse_skill_md,
)


KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
ALLOWED_CRITICS = {"engineering", "business", "user_advocate", "design"}


def _all_skill_md_paths() -> list[Path]:
    out: list[Path] = []
    for parent in (SEED_DIR, LEARNED_DIR):
        if not parent.exists():
            continue
        for child in parent.iterdir():
            if child.is_dir() and (child / SKILL_FILENAME).is_file():
                out.append(child / SKILL_FILENAME)
    return out


def test_at_least_one_skill_md_exists() -> None:
    """Sanity: the seed library was migrated and is discoverable."""
    paths = _all_skill_md_paths()
    assert len(paths) >= 6, f"expected ≥6 SKILL.md files, found {len(paths)}"


@pytest.mark.parametrize("skill_md", _all_skill_md_paths(), ids=lambda p: p.parent.name)
def test_skill_md_frontmatter_required_fields(skill_md: Path) -> None:
    text = skill_md.read_text(encoding="utf-8")
    fm, body = parse_skill_md(text)

    # Required fields
    for field in ("name", "description", "version", "created_by", "injected_into"):
        assert field in fm, f"{skill_md}: missing required frontmatter field {field!r}"

    # name must match folder, be kebab-case
    assert fm["name"] == skill_md.parent.name, (
        f"{skill_md}: name {fm['name']!r} doesn't match folder name {skill_md.parent.name!r}"
    )
    assert KEBAB.match(fm["name"]), f"{skill_md}: name not kebab-case"

    # description must be non-trivially long (pushy, not a one-liner)
    assert isinstance(fm["description"], str) and len(fm["description"]) > 40

    # created_by: only seed/distiller allowed
    assert fm["created_by"] in {"seed", "distiller"}

    # injected_into: non-empty list of allowed critic ids
    routes = fm["injected_into"]
    assert isinstance(routes, list) and routes, f"{skill_md}: injected_into must be a non-empty list"
    bad = set(routes) - ALLOWED_CRITICS
    assert not bad, f"{skill_md}: unknown critic_ids in injected_into: {bad}"

    # body must be non-empty
    assert body.strip(), f"{skill_md}: markdown body is empty"
