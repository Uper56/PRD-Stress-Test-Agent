"""Pytest configuration.

Async handling is delegated to pytest-asyncio's auto mode (configured in
pyproject.toml via `asyncio_mode = "auto"`).

Also disables MockProvider's per-chunk stream delay so the test suite stays
fast — the delay exists to give the Streamlit render loop something to paint
between deltas, which is irrelevant during pytest.
"""

import os

os.environ.setdefault("MOCK_STREAM_DELAY", "0")
# Day 8: existing tests don't expect run history or skill-usage side effects.
# `src/main.py:run_pipeline` reads this env var as the default for `persist`.
os.environ.setdefault("PRD_PIPELINE_PERSIST", "0")
