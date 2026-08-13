"""In-memory run registry for the review API.

`POST /api/reviews` spawns a background pipeline task; the SSE endpoint
serves its events. Every event is appended to an in-memory log with an
incrementing id, so a reconnect (SSE `Last-Event-ID`) can replay what it
missed. Finished runs are pruned from memory after `_RUN_TTL_SECONDS` —
anything older is recoverable from the on-disk HistoryStore.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_RUN_TTL_SECONDS = 3600


class Run:
    """One in-flight (or recently finished) review run."""

    def __init__(self, run_id: str, prd_text: str, prd_filename: str | None) -> None:
        self.run_id = run_id
        self.prd_text = prd_text
        self.prd_filename = prd_filename
        # Append-only log: [(event_id, event_type, data_dict), ...]
        self.events: list[tuple[int, str, dict[str, Any]]] = []
        self.finished = False
        self.finished_at: float | None = None
        self.state: dict[str, Any] | None = None
        self.verdict: dict[str, Any] | None = None
        self.error: str | None = None
        self.history_run_id: str | None = None
        self._cond = asyncio.Condition()
        self._next_id = 0

    async def push(self, event_type: str, data: dict[str, Any]) -> None:
        """Append an event and wake any SSE subscribers."""
        async with self._cond:
            self._next_id += 1
            self.events.append((self._next_id, event_type, data))
            self._cond.notify_all()


class RunHub:
    """Registry of active runs, keyed by run_id."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, prd_text: str, prd_filename: str | None) -> Run:
        run = Run(uuid.uuid4().hex[:12], prd_text, prd_filename)
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def prune(self) -> None:
        """Drop finished runs past the TTL (called opportunistically)."""
        now = time.time()
        stale = [
            run_id
            for run_id, run in self._runs.items()
            if run.finished
            and run.finished_at is not None
            and now - run.finished_at > _RUN_TTL_SECONDS
        ]
        for run_id in stale:
            self._runs.pop(run_id, None)
        if stale:
            logger.info("run hub pruned %d finished runs", len(stale))
