"""Tests for SkillCurator on the Day-8.5 runtime_stats.yaml format.

Each test builds a self-contained `runtime_stats.yaml` under `tmp_path`
so the real `src/skills/runtime_stats.yaml` is never mutated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.skills.curator import SkillCurator


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
            "usage_count": 4,
            "acceptance_rate": None,
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


def test_increment_single_name_bumps_only_target(stats_path: Path) -> None:
    SkillCurator(stats_path).increment_usage(["skl-a"])
    after = _read(stats_path)["skills"]
    assert after["skl-a"]["usage_count"] == 1
    assert after["skl-b"]["usage_count"] == 4
    # last_used is stamped on bumped entries only.
    assert after["skl-a"]["last_used"] is not None
    assert after["skl-b"]["last_used"] is None


def test_increment_multiple_names_independent(stats_path: Path) -> None:
    SkillCurator(stats_path).increment_usage(["skl-a", "skl-b"])
    after = _read(stats_path)["skills"]
    assert after["skl-a"]["usage_count"] == 1
    assert after["skl-b"]["usage_count"] == 5


def test_duplicate_names_dedup_to_single_increment(stats_path: Path) -> None:
    """One run handing the same name 3× still increments by 1."""
    SkillCurator(stats_path).increment_usage(["skl-a", "skl-a", "skl-a"])
    after = _read(stats_path)["skills"]
    assert after["skl-a"]["usage_count"] == 1


def test_unknown_name_is_ignored(stats_path: Path) -> None:
    SkillCurator(stats_path).increment_usage(["does-not-exist"])
    after = _read(stats_path)
    assert after == SEED_STATS  # untouched


def test_empty_input_is_a_noop(stats_path: Path) -> None:
    SkillCurator(stats_path).increment_usage([])
    SkillCurator(stats_path).increment_usage([None, ""])  # type: ignore[list-item]
    assert _read(stats_path) == SEED_STATS


def test_write_preserves_canonical_header(stats_path: Path) -> None:
    SkillCurator(stats_path).increment_usage(["skl-a"])
    text = stats_path.read_text(encoding="utf-8")
    assert text.startswith("# Runtime telemetry for skills")


def test_write_preserves_key_order_per_skill(stats_path: Path) -> None:
    """Each entry's keys should follow the canonical order so diffs stay tight."""
    SkillCurator(stats_path).increment_usage(["skl-a"])
    raw = stats_path.read_text(encoding="utf-8")
    i_usage = raw.index("usage_count: 1")
    i_status = raw.index("status: active")
    # usage_count appears before status per canonical _STATS_KEY_ORDER.
    assert i_usage < i_status


def test_manual_deprecate_flips_status_and_stamps_reason(stats_path: Path) -> None:
    """Day 9: `deprecate` is now wired (no longer NotImplementedError)."""
    c = SkillCurator(stats_path)
    c.deprecate("skl-a", reason="obsolete")
    after = _read(stats_path)["skills"]
    assert after["skl-a"]["status"] == "deprecated"
    assert after["skl-a"].get("deprecate_reason") == "obsolete"
    # Untouched neighbour stays active.
    assert after["skl-b"]["status"] == "active"
