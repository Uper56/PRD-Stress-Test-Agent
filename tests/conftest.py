"""Pytest configuration.

Async handling is delegated to pytest-asyncio's auto mode (configured in
pyproject.toml via `asyncio_mode = "auto"`).

Also disables MockProvider's per-chunk stream delay so the test suite stays
fast — the delay exists to give the Streamlit render loop something to paint
between deltas, which is irrelevant during pytest.

Lifecycle telemetry: HistoryStore.save() records SkillUseEvents through a
process-wide LifecycleStore singleton. This autouse fixture redirects that
singleton (and closes it) per test so (a) runs stay hermetic — no writes
into the repo's data/lifecycle — and (b) sqlite connections are closed
deterministically instead of being GC'd (which -W error turns into
PytestUnraisableExceptionWarning failures).
"""

import os

import pytest

os.environ.setdefault("MOCK_STREAM_DELAY", "0")
# Day 8: existing tests don't expect run history or skill-usage side effects.
# `src/main.py:run_pipeline` reads this env var as the default for `persist`.
os.environ.setdefault("PRD_PIPELINE_PERSIST", "0")


@pytest.fixture(autouse=True)
def _hermetic_lifecycle_store(tmp_path, monkeypatch):
    from src.lifecycle.store import LifecycleStore
    from src.storage import history_store as history_store_mod

    store = LifecycleStore(tmp_path / "lifecycle" / "skills.db")
    monkeypatch.setattr(
        history_store_mod, "_lifecycle_store_singleton", store
    )
    yield store
    store.close()
