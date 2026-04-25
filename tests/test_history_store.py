"""Tests for HistoryStore — round-trip, ordering, querying, atomicity."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.graph.state import Critique
from src.storage.history_store import (
    INDEX_FILENAME,
    HistoryStore,
    _atomic_write_json,
)


def _critique(critic_id: str, skill_id: str | None) -> dict:
    return Critique(
        critic_id=critic_id,
        claim_id="C-001",
        severity="P1",
        finding=f"finding from {critic_id}",
        evidence='line 1: "Mock"',
        suggested_fix="fix it",
        skill_id=skill_id,
    ).model_dump()


def _state(prd_text: str = "[001] PRD body", critiques: list[dict] | None = None) -> dict:
    return {
        "prd_text": prd_text,
        "critiques": critiques or [],
        "challenges": [],
        "final_report": {
            "executive_summary": "OK",
            "p0_blockers": [],
            "p1_concerns": ["one"],
            "p2_suggestions": [],
            "conflict_resolutions": [],
        },
    }


# ---- Round-trip ------------------------------------------------------------


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    state = _state(critiques=[_critique("engineering", "skl_001")])
    saved = store.save(state, prd_filename="prd_test.md")
    assert saved is not None

    loaded = store.load(saved.run_id)
    assert loaded is not None
    assert loaded.run_id == saved.run_id
    assert loaded.prd_filename == "prd_test.md"
    assert loaded.critiques == saved.critiques
    assert loaded.skill_hits == saved.skill_hits
    # PRD body excerpt + hash both populated.
    assert loaded.prd_text_excerpt.startswith("[001] PRD")
    assert len(loaded.prd_text_hash) == 64  # sha256 hex


# ---- list_recent ordering --------------------------------------------------


def test_list_recent_orders_newest_first(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    first = store.save(_state(prd_text="[001] first"))
    # Sleep long enough for the timestamp (second-precision) to advance.
    time.sleep(1.1)
    second = store.save(_state(prd_text="[001] second"))
    assert first is not None and second is not None

    recent = store.list_recent(n=5)
    assert [r.run_id for r in recent] == [second.run_id, first.run_id]


def test_list_recent_n_caps_results(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    for i in range(5):
        store.save(_state(prd_text=f"[001] run {i}"))
    assert len(store.list_recent(n=3)) == 3


def test_list_recent_empty_when_no_history(tmp_path: Path) -> None:
    assert HistoryStore(tmp_path).list_recent() == []


# ---- index.jsonl shape -----------------------------------------------------


def test_index_jsonl_appends_one_line_per_run(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.save(_state())
    store.save(_state())
    index_path = tmp_path / INDEX_FILENAME
    lines = [
        line for line in index_path.read_text(encoding="utf-8").splitlines() if line
    ]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    # Summary fields, NOT the full PRD text.
    for entry in parsed:
        assert "prd_text_hash" in entry
        assert "prd_text_excerpt" not in entry
        assert "critiques" not in entry
        assert "p1_count" in entry


# ---- query(only_misses=True) ----------------------------------------------


def test_query_only_misses_filters_to_unattributed(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    # Run A: every critique has a skill_id.
    store.save(_state(critiques=[_critique("engineering", "skl_001")]))
    time.sleep(1.1)
    # Run B: at least one critique with skill_id=None.
    store.save(
        _state(
            prd_text="[001] different",
            critiques=[
                _critique("engineering", "skl_001"),
                _critique("design", None),
            ],
        )
    )

    misses = store.query(only_misses=True)
    assert len(misses) == 1
    assert any(c["skill_id"] is None for c in misses[0].critiques)


def test_query_since_filters_by_timestamp(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path)
    store.save(_state(prd_text="[001] old"))
    time.sleep(1.1)
    cutoff_record = store.save(_state(prd_text="[001] cutoff"))
    assert cutoff_record is not None
    time.sleep(1.1)
    store.save(_state(prd_text="[001] new"))

    after = store.query(since=cutoff_record.timestamp)
    assert {r.prd_text_excerpt for r in after} == {"[001] cutoff", "[001] new"}


# ---- Atomic write ----------------------------------------------------------


def test_atomic_write_does_not_corrupt_on_crash(tmp_path: Path, monkeypatch) -> None:
    """If the rename step fails, the destination file must be untouched."""
    target = tmp_path / "library.yaml"
    target.write_text("good: original\n", encoding="utf-8")

    def explode(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("simulated crash mid-rename")

    monkeypatch.setattr("os.replace", explode)
    with pytest.raises(RuntimeError):
        _atomic_write_json(target, {"corrupt": "payload"})

    # Original survives, no .tmp left in the directory.
    assert target.read_text(encoding="utf-8") == "good: original\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_save_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    """`HistoryStore.save` must absorb any disk failure (returns None)."""
    store = HistoryStore(tmp_path)

    def explode(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise OSError("disk full")

    # Patch the file-write path so the save attempt fails after building the record.
    monkeypatch.setattr(
        "src.storage.history_store._atomic_write_json", explode
    )

    result = store.save(_state())
    assert result is None  # logged-and-swallowed, never raised


# ---- Skill telemetry --------------------------------------------------------


def test_skill_hits_and_misses_are_computed(tmp_path: Path) -> None:
    """Critique-attached skill_ids land in `skill_hits`; retrieved-but-not-used
    skills (here: none for this minimal PRD text) land in `skill_misses`."""
    store = HistoryStore(tmp_path)
    record = store.save(
        _state(
            prd_text="[001] integrate with Stripe API and webhook endpoint",
            critiques=[_critique("engineering", "api-dependency-enumeration")],
        )
    )
    assert record is not None
    assert "api-dependency-enumeration" in record.skill_hits
    assert "api-dependency-enumeration" in record.retrieved_skill_ids
    # No mismatch between hits and misses.
    assert set(record.skill_hits).isdisjoint(record.skill_misses)
