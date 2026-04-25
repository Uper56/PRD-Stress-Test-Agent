"""Tests for SkillCurator — Day 8 only covers `increment_usage`.

The fixtures here build a self-contained throwaway library under `tmp_path`
so the real `src/skills/library.yaml` is never mutated by the test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.skills.curator import SkillCurator


SEED_LIBRARY = {
    "skills": [
        {
            "id": "skl_a",
            "name": "Skill A",
            "description": "first",
            "trigger_keywords": ["alpha"],
            "trigger_semantic": "fires on alpha",
            "injected_into": ["engineering"],
            "prompt_fragment_path": "fragments/skl_a.md",
            "confidence": 0.5,
            "usage_count": 0,
            "acceptance_rate": None,
            "created_at": "2026-04-25",
            "created_by": "seed",
            "learned_from_prds": [],
            "status": "active",
        },
        {
            "id": "skl_b",
            "name": "Skill B",
            "description": "second",
            "trigger_keywords": ["bravo"],
            "trigger_semantic": "fires on bravo",
            "injected_into": ["business"],
            "prompt_fragment_path": "fragments/skl_b.md",
            "confidence": 0.7,
            "usage_count": 4,
            "acceptance_rate": None,
            "created_at": "2026-04-25",
            "created_by": "seed",
            "learned_from_prds": [],
            "status": "active",
        },
    ]
}


@pytest.fixture
def library_path(tmp_path: Path) -> Path:
    p = tmp_path / "library.yaml"
    p.write_text(yaml.safe_dump(SEED_LIBRARY, sort_keys=False), encoding="utf-8")
    return p


def _read(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def test_increment_single_id_bumps_only_target(library_path: Path) -> None:
    SkillCurator(library_path).increment_usage(["skl_a"])
    after = _read(library_path)["skills"]
    by_id = {s["id"]: s for s in after}
    assert by_id["skl_a"]["usage_count"] == 1  # 0 -> 1
    assert by_id["skl_b"]["usage_count"] == 4  # untouched


def test_increment_multiple_ids_independent(library_path: Path) -> None:
    SkillCurator(library_path).increment_usage(["skl_a", "skl_b"])
    after = _read(library_path)["skills"]
    by_id = {s["id"]: s for s in after}
    assert by_id["skl_a"]["usage_count"] == 1
    assert by_id["skl_b"]["usage_count"] == 5


def test_duplicate_skill_ids_dedup_to_single_increment(library_path: Path) -> None:
    """A single run that hands the same id twice should still only +1."""
    SkillCurator(library_path).increment_usage(["skl_a", "skl_a", "skl_a"])
    after = _read(library_path)["skills"]
    assert next(s for s in after if s["id"] == "skl_a")["usage_count"] == 1


def test_unknown_id_is_ignored(library_path: Path) -> None:
    SkillCurator(library_path).increment_usage(["skl_does_not_exist"])
    after = _read(library_path)
    # No mutation, no exception, file still parseable.
    assert after == SEED_LIBRARY


def test_empty_input_is_a_noop(library_path: Path) -> None:
    SkillCurator(library_path).increment_usage([])
    SkillCurator(library_path).increment_usage([None, ""])  # type: ignore[list-item]
    assert _read(library_path) == SEED_LIBRARY


def test_write_preserves_canonical_header(library_path: Path) -> None:
    SkillCurator(library_path).increment_usage(["skl_a"])
    text = library_path.read_text(encoding="utf-8")
    assert text.startswith("# Skill Library — seed entries.")


def test_write_preserves_key_order_per_skill(library_path: Path) -> None:
    """The on-disk skill keys should follow the canonical order so diffs stay tight."""
    SkillCurator(library_path).increment_usage(["skl_a"])
    raw = library_path.read_text(encoding="utf-8")
    # `id` should appear before `name`, which appears before `usage_count`.
    i_id = raw.index("id: skl_a")
    i_name = raw.index("name: Skill A")
    i_usage = raw.index("usage_count: 1")
    assert i_id < i_name < i_usage


def test_unimplemented_methods_raise(library_path: Path) -> None:
    """Day 9 stubs must announce themselves loudly until wired."""
    c = SkillCurator(library_path)
    with pytest.raises(NotImplementedError):
        c.update_acceptance("skl_a", accepted=True)
    with pytest.raises(NotImplementedError):
        c.deprecate("skl_a", reason="obsolete")
