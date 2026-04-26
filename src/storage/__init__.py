"""Run-history + proposals persistence layer.

Public surface:
  - HistoryStore, RunRecord       (src/storage/history_store.py)
  - ProposalsStore                (src/storage/proposals_store.py)
"""

from .history_store import HistoryStore, RunRecord
from .proposals_store import ProposalsStore

__all__ = ["HistoryStore", "RunRecord", "ProposalsStore"]
