"""Pytest configuration.

Async handling is delegated to pytest-asyncio's auto mode (configured in
pyproject.toml via `asyncio_mode = "auto"`).

Also disables MockProvider's per-chunk stream delay so the test suite stays
fast — the delay exists to give the Streamlit render loop something to paint
between deltas, which is irrelevant during pytest.
"""

import os

os.environ.setdefault("MOCK_STREAM_DELAY", "0")
