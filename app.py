"""HuggingFace Space entry point.

HF Spaces look for `app.py` at the repository root by default. The real
implementation lives in `src/ui/streamlit_app.py`; this file just
arranges the import path and invokes `main()`.

For local development, `streamlit run app.py` and
`streamlit run src/ui/streamlit_app.py` are equivalent.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src.*` importable when Streamlit launches this file directly.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui.streamlit_app import main  # noqa: E402 — must follow sys.path tweak


# Streamlit runs the script top-to-bottom on every rerun; calling main()
# unconditionally is the canonical pattern for both `streamlit run app.py`
# and the HF Space's auto-launch.
main()
