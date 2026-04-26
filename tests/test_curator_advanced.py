"""Tests for the Day-9 SkillCurator additions.

Covers:
  - `update_acceptance` sliding window math.
  - `auto_deprecate` triggers only above usage floor + below acceptance ceiling.
  - `merge_duplicates` flips status without deleting any SKILL.md file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.skills.curator import (
    ACCEPTANCE_WINDOW,
    AUTO_DEPRECATE_ACCEPTANCE_CEILING,
    AUTO_DEPRECATE_USAGE_FLOOR,
    SkillCurator,
)


SEED_STATS = {
    "skills": {
        "skl-a": {
            "usage_count": 0,
            "acceptance_rate": None,
            "last_used": None,
            "status": "active",
            "learned_from_prds": [],
        },
        "skl-b": {
            "usage_count": 10,
            "acceptance_rate": 0.5,  # mid-range; not auto-deprecated
            "last_used": None,
            "status": "active",
            "learned_from_prds": [],
        },
    }
}


@pytest.fixture
def stats_path(tmp_path: Path) -> Path:
    p = tmp_path / "runtime_stats.yaml"
    p.write_text(yaml.safe_dump(SEED_STATS, sort_keys=False), encoding="utf-8")
    return p


def _read(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---- update_acceptance ----------------------------------------------------


def test_update_acceptance_appends_sample_and_recomputes(stats_path: Path) -> None:
    c = SkillCurator(stats_path)
    c.update_acceptance("skl-a", accepted=True)
    after = _read(stats_path)["skills"]["skl-a"]
    assert after["acceptance_rate"] == 1.0
    history = json.loads(after["acceptance_history"])
    assert history == [1]


def test_update_acceptance_sliding_window_caps_at_window_size(stats_path: Path) -> None:
    c = SkillCurator(stats_path)
    # Record a long string of accepts followed by enough rejects to roll
    # past the window edge.
    for _ in range(ACCEPTANCE_WINDOW):
        c.update_acceptance("skl-a", accepted=True)
    # Now overflow with rejects.
    for _ in range(ACCEPTANCE_WINDOW // 2):
        c.update_acceptance("skl-a", accepted=False)
    after = _read(stats_path)["skills"]["skl-a"]
    history = json.loads(after["acceptance_history"])
    assert len(history) == ACCEPTANCE_WINDOW
    expected_rate = sum(history) / len(history)
    assert abs(after["acceptance_rate"] - round(expected_rate, 3)) < 1e-9


def test_update_acceptance_unknown_name_is_noop(stats_path: Path) -> None:
    SkillCurator(stats_path).update_acceptance("does-not-exist", accepted=True)
    assert _read(stats_path) == SEED_STATS


# ---- auto_deprecate -------------------------------------------------------


def test_auto_deprecate_flips_only_low_acceptance_high_usage(stats_path: Path) -> None:
    """Skill with usage ≥ floor AND acceptance < ceiling gets deprecated;
    skills missing one or both conditions are untouched."""
    # Mutate skl-a to satisfy both conditions for deprecation.
    data = _read(stats_path)
    data["skills"]["skl-a"]["usage_count"] = AUTO_DEPRECATE_USAGE_FLOOR + 2
    data["skills"]["skl-a"]["acceptance_rate"] = AUTO_DEPRECATE_ACCEPTANCE_CEILING - 0.1
    stats_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    deprecated = SkillCurator(stats_path).auto_deprecate()
    assert deprecated == ["skl-a"]
    after = _read(stats_path)["skills"]
    assert after["skl-a"]["status"] == "deprecated"
    assert "deprecate_reason" in after["skl-a"]
    # skl-b had acceptance ≥ ceiling — stays active.
    assert after["skl-b"]["status"] == "active"


def test_auto_deprecate_skips_skills_below_usage_floor(stats_path: Path) -> None:
    data = _read(stats_path)
    data["skills"]["skl-a"]["usage_count"] = AUTO_DEPRECATE_USAGE_FLOOR - 1
    data["skills"]["skl-a"]["acceptance_rate"] = 0.05
    stats_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert SkillCurator(stats_path).auto_deprecate() == []
    assert _read(stats_path)["skills"]["skl-a"]["status"] == "active"


def test_auto_deprecate_skips_skills_with_no_acceptance_data(stats_path: Path) -> None:
    """A skill that has been used but never received feedback can't be judged."""
    data = _read(stats_path)
    data["skills"]["skl-a"]["usage_count"] = AUTO_DEPRECATE_USAGE_FLOOR + 5
    data["skills"]["skl-a"]["acceptance_rate"] = None
    stats_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert SkillCurator(stats_path).auto_deprecate() == []
    assert _read(stats_path)["skills"]["skl-a"]["status"] == "active"


# ---- merge_duplicates -----------------------------------------------------


def test_merge_duplicates_does_not_delete_skill_files(tmp_path: Path) -> None:
    """Two near-identical SKILL.md files — merging must leave both files
    on disk. Only the loser's runtime_stats status changes."""
    seed_dir = tmp_path / "seed"
    (seed_dir / "alpha-skill").mkdir(parents=True)
    (seed_dir / "alpha-twin").mkdir(parents=True)

    common_body = (
        "# X\n## When to apply\nx\n## Instruction\ny\n## Rationale\nz\n## Examples\n- a\n"
    )
    (seed_dir / "alpha-skill" / "SKILL.md").write_text(
        "---\n"
        "name: alpha-skill\n"
        "description: Use this skill ANY TIME the PRD does X without enumerating dependencies SLAs failure modes\n"
        'version: "1.0"\n'
        "created_by: seed\n"
        "injected_into:\n  - engineering\n"
        "---\n\n" + common_body,
        encoding="utf-8",
    )
    (seed_dir / "alpha-twin" / "SKILL.md").write_text(
        "---\n"
        "name: alpha-twin\n"
        "description: Use this skill ANY TIME the PRD does X without enumerating dependencies SLAs failure modes\n"
        'version: "1.0"\n'
        "created_by: seed\n"
        "injected_into:\n  - engineering\n"
        "---\n\n" + common_body,
        encoding="utf-8",
    )

    runtime_stats = tmp_path / "runtime_stats.yaml"
    runtime_stats.write_text(
        yaml.safe_dump(
            {
                "skills": {
                    "alpha-skill": {"usage_count": 5, "status": "active"},
                    "alpha-twin": {"usage_count": 1, "status": "active"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # Point the retriever singleton at our fake tree, swapping out
    # `default_retriever` in both modules so neither touches the real
    # src/skills/ directory.
    from src.skills import curator as curator_mod
    from src.skills import retriever as retriever_mod

    real_retriever = retriever_mod.SkillRetriever(
        skills_root=tmp_path, runtime_stats_path=runtime_stats
    )

    def _stub_default():
        # Always return the same instance; bust its internal cache so
        # repeat calls re-read from disk like the production retriever.
        real_retriever._library = None
        return real_retriever

    orig_retriever_default = retriever_mod.default_retriever
    orig_curator_default = curator_mod.default_retriever
    retriever_mod.default_retriever = _stub_default  # type: ignore[assignment]
    curator_mod.default_retriever = _stub_default  # type: ignore[assignment]
    try:
        merged = SkillCurator(runtime_stats).merge_duplicates(threshold=0.85)
        assert merged, "expected the twin pair to merge"
        loser, winner = merged[0]
        # Higher usage wins (alpha-skill has 5, alpha-twin has 1).
        assert winner == "alpha-skill"
        assert loser == "alpha-twin"

        after = _read(runtime_stats)["skills"]
        assert after["alpha-twin"]["status"] == f"deprecated_merged_into_{winner}"
        assert after["alpha-skill"]["status"] == "active"

        # Both SKILL.md files still on disk.
        assert (seed_dir / "alpha-skill" / "SKILL.md").exists()
        assert (seed_dir / "alpha-twin" / "SKILL.md").exists()
    finally:
        retriever_mod.default_retriever = orig_retriever_default  # type: ignore[assignment]
        curator_mod.default_retriever = orig_curator_default  # type: ignore[assignment]
        # The original is an lru_cache wrapper; clear it so any cached
        # retriever pointing at tmp_path is forgotten.
        try:
            orig_retriever_default.cache_clear()  # type: ignore[attr-defined]
        except AttributeError:
            pass
