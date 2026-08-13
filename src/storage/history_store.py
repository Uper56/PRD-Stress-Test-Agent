"""Run-history persistence.

Each completed pipeline run is written as a standalone JSON file under
`data/results/history/`, plus a one-line summary appended to `index.jsonl`.
The split exists so:

- Listing recent runs (sidebar, Day 9 distiller) reads only the index — small
  and append-only, never rewritten.
- Loading a single run (drilldown, evidence cite) reads only that file.
- The PRD body is stored once in the run JSON and only excerpted into the
  index, so `index.jsonl` doesn't grow into a multi-MB file.

Failures are absorbed: if disk is full, permissions are bad, or the JSON is
malformed, `save()` returns `None` and logs a warning. The pipeline never
breaks because telemetry storage broke.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..graph.state import Critique, CrossChallenge, GraphState

logger = logging.getLogger(__name__)


DEFAULT_HISTORY_DIR = Path("data") / "results" / "history"
INDEX_FILENAME = "index.jsonl"


class RunRecord(BaseModel):
    """One archived pipeline run."""

    run_id: str
    timestamp: str  # ISO 8601, UTC
    prd_filename: str | None = None
    prd_text_hash: str
    prd_text_excerpt: str  # first 500 chars
    critiques: list[dict] = Field(default_factory=list)
    challenges: list[dict] = Field(default_factory=list)
    supervisor_verdict: dict = Field(default_factory=dict)
    retrieved_skill_ids: list[str] = Field(default_factory=list)
    skill_hits: list[str] = Field(default_factory=list)
    skill_misses: list[str] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class HistoryStore:
    """File-backed run history. Tolerant of disk failures by design."""

    def __init__(self, base_dir: Path | str = DEFAULT_HISTORY_DIR) -> None:
        self.base_dir = Path(base_dir)

    # ---- save -------------------------------------------------------------

    def save(
        self,
        state: GraphState,
        *,
        prd_filename: str | None = None,
    ) -> RunRecord | None:
        """Build a `RunRecord` from `state` and persist it.

        Computes:
        - `retrieved_skill_ids` by re-running the skill retriever per critic
          present in the state (re-derived rather than threaded through the
          graph — avoids touching every critic node + reducer wiring).
        - `skill_hits` = ids actually attached to a critique.
        - `skill_misses` = retrieved minus hits.

        Returns the saved record on success, or None on any failure (logged).
        """
        try:
            return self._save_unchecked(state, prd_filename=prd_filename)
        except Exception as e:  # noqa: BLE001 — telemetry must never crash the pipeline
            logger.warning("HistoryStore.save failed: %s", e)
            return None

    def _save_unchecked(
        self,
        state: GraphState,
        *,
        prd_filename: str | None,
    ) -> RunRecord:
        prd_text = state.get("prd_text", "") or ""
        critiques_raw = state.get("critiques", []) or []
        challenges_raw = state.get("challenges", []) or []
        verdict = state.get("final_report") or {}

        critiques = [
            c.model_dump() if hasattr(c, "model_dump") else dict(c)
            for c in critiques_raw
        ]
        challenges = [
            c.model_dump() if hasattr(c, "model_dump") else dict(c)
            for c in challenges_raw
        ]

        # Skill telemetry — recomputed at save time, not threaded through
        # the graph. See module docstring for the trade-off.
        retrieved, hits, misses = _compute_skill_telemetry(prd_text, critiques)

        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        record = RunRecord(
            run_id=run_id,
            timestamp=now.isoformat(timespec="seconds"),
            prd_filename=prd_filename,
            prd_text_hash=hashlib.sha256(prd_text.encode("utf-8")).hexdigest(),
            prd_text_excerpt=prd_text[:500],
            critiques=critiques,
            challenges=challenges,
            supervisor_verdict=verdict,
            retrieved_skill_ids=sorted(retrieved),
            skill_hits=sorted(hits),
            skill_misses=sorted(misses),
            total_tokens=int(state.get("total_tokens", 0) or 0),
            total_cost_usd=float(state.get("total_cost_usd", 0.0) or 0.0),
        )

        self.base_dir.mkdir(parents=True, exist_ok=True)
        run_path = self.base_dir / _run_filename(now, run_id)
        _atomic_write_json(run_path, record.model_dump())
        self._append_index(record)
        return record

    # ---- read -------------------------------------------------------------

    def list_recent(self, n: int = 20) -> list[RunRecord]:
        """Return the most recent `n` runs, newest first.

        Reads only `index.jsonl`. Indexed-but-deleted run files are skipped
        with a warning so a missing JSON doesn't take down the sidebar.
        """
        index_path = self.base_dir / INDEX_FILENAME
        if not index_path.exists():
            return []

        summaries: list[dict] = []
        with index_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    summaries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("Skipping malformed index line: %s", e)
        # Newest first.
        summaries.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        out: list[RunRecord] = []
        for entry in summaries[:n]:
            run_id = entry.get("run_id")
            if not run_id:
                continue
            rec = self.load(run_id)
            if rec is not None:
                out.append(rec)
        return out

    def load(self, run_id: str) -> RunRecord | None:
        """Look up a run by `run_id`. Returns None if the file is gone or unreadable."""
        # Search by suffix so callers don't need to know the timestamp.
        if not self.base_dir.exists():
            return None
        for path in self.base_dir.glob(f"run_*_{run_id[:8]}.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                return RunRecord.model_validate(data)
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load %s: %s", path, e)
                return None
        return None

    def query(
        self,
        *,
        only_misses: bool = False,
        since: str | None = None,
    ) -> list[RunRecord]:
        """Filter recent runs.

        Args:
            only_misses: when True, return runs that produced at least one
                critique with `skill_id is None`. The Day 9 distiller will
                use this to find pattern repeats across PRDs.
            since: ISO 8601 lower bound on `timestamp` (inclusive).
        """
        all_runs = self.list_recent(n=10_000)
        out: list[RunRecord] = []
        for r in all_runs:
            if since and r.timestamp < since:
                continue
            if only_misses and not _has_unattributed_critique(r):
                continue
            out.append(r)
        return out

    # ---- delete ------------------------------------------------------------

    def delete(self, run_id: str) -> bool:
        """Remove a run's JSON file and its index entry.

        Files are NEVER resurrectable through this API — the call site is
        responsible for a confirm step. Returns True if a run file was
        actually removed. Tolerant of a missing file (already gone) and of
        index write failures (logged, not raised).
        """
        removed = False
        if self.base_dir.exists():
            for path in self.base_dir.glob(f"run_*_{run_id[:8]}.json"):
                try:
                    path.unlink()
                    removed = True
                except OSError as e:  # noqa: BLE001
                    logger.warning("HistoryStore.delete: unlink %s failed: %s", path, e)

        index_path = self.base_dir / INDEX_FILENAME
        if index_path.exists():
            try:
                kept: list[str] = []
                for line in index_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        if json.loads(line).get("run_id") == run_id:
                            continue
                    except json.JSONDecodeError:
                        pass  # keep malformed lines — never silently drop data
                    kept.append(line)
                _atomic_write_text(index_path, "\n".join(kept) + ("\n" if kept else ""))
            except OSError as e:  # noqa: BLE001
                logger.warning("HistoryStore.delete: index rewrite failed: %s", e)
        return removed

    # ---- internals --------------------------------------------------------

    def _append_index(self, record: RunRecord) -> None:
        """Append a one-line summary to `index.jsonl`. Never rewrites the file."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        index_path = self.base_dir / INDEX_FILENAME
        summary = {
            "run_id": record.run_id,
            "timestamp": record.timestamp,
            "prd_filename": record.prd_filename,
            "prd_text_hash": record.prd_text_hash,
            "p0_count": len(record.supervisor_verdict.get("p0_blockers", []) or []),
            "p1_count": len(record.supervisor_verdict.get("p1_concerns", []) or []),
            "p2_count": len(record.supervisor_verdict.get("p2_suggestions", []) or []),
            "critique_count": len(record.critiques),
            "skill_hit_count": len(record.skill_hits),
        }
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")


# ---- helpers ---------------------------------------------------------------


def _run_filename(when: datetime, run_id: str) -> str:
    """`run_<YYYYMMDD_HHMMSS>_<run_id8>.json` — lex-sortable by time."""
    stamp = when.strftime("%Y%m%d_%H%M%S")
    return f"run_{stamp}_{run_id[:8]}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to a tempfile, then `os.replace` into place.

    Crash between write and rename leaves the destination untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; swallow secondary errors.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to a tempfile, then `os.replace` into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _compute_skill_telemetry(
    prd_text: str,
    critiques: list[dict],
) -> tuple[set[str], set[str], set[str]]:
    """Return (retrieved_ids, hit_ids, miss_ids).

    Re-runs the retriever per critic_id present in the critiques list. Lazy
    import avoids a circular dependency at module init.
    """
    from ..skills.retriever import default_retriever

    retriever = default_retriever()
    critic_ids = {c.get("critic_id") for c in critiques if c.get("critic_id")}
    retrieved: set[str] = set()
    for critic_id in critic_ids:
        try:
            for s in retriever.retrieve(prd_text, critic_id=str(critic_id)):
                retrieved.add(s.id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "telemetry: retrieval failed for critic_id=%s: %s", critic_id, e
            )
    hits = {c["skill_id"] for c in critiques if c.get("skill_id")}
    misses = retrieved - hits
    return retrieved, hits, misses


def _has_unattributed_critique(record: RunRecord) -> bool:
    """True if any critique on this run has `skill_id` null/empty."""
    return any(not c.get("skill_id") for c in record.critiques)
