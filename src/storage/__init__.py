"""Run-history persistence layer.

Public surface:
  - HistoryStore       (src/storage/history_store.py)
  - RunRecord          (src/storage/history_store.py)
"""

from .history_store import HistoryStore, RunRecord

__all__ = ["HistoryStore", "RunRecord"]
