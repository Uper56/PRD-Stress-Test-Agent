"""Skill Library write side — runtime telemetry + curation hooks.

Day 8.5 split: telemetry lives in `runtime_stats.yaml`, NOT in SKILL.md
frontmatter. Each PRD run only mutates `runtime_stats.yaml`; SKILL.md
files stay diff-clean across runs.

Day 9 additions:
  - `update_acceptance(name, accepted)` — feeds HITL accept/reject feedback
    into a sliding-window `acceptance_rate` (window default = 20).
  - `auto_deprecate()` — flips `status` to `deprecated` on skills that have
    been used a non-trivial number of times AND have low acceptance.
  - `merge_duplicates(threshold)` — finds near-duplicate skills via
    SequenceMatcher on (description, injected_into) and demotes the
    "loser" of each pair to `status="deprecated_merged_into_<winner>"`.
    Files are NEVER deleted; only `runtime_stats.yaml` is mutated, so a
    merge is fully reversible by editing one file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from .retriever import RUNTIME_STATS_PATH, default_retriever

logger = logging.getLogger(__name__)


# --- tunables ---------------------------------------------------------------

# Sliding-window length for acceptance_rate. Stored as JSON in the
# `acceptance_history` field so we don't lose state on restart.
ACCEPTANCE_WINDOW = 20

# auto_deprecate thresholds — conservative defaults so we don't kill skills
# that just had a bad week.
AUTO_DEPRECATE_USAGE_FLOOR = 5
AUTO_DEPRECATE_ACCEPTANCE_CEILING = 0.30


_RUNTIME_HEADER = """\
# Runtime telemetry for skills, keyed by SKILL.md `name`.
#
# This file is the ONLY place runtime data lives. SKILL.md frontmatter and
# bodies (under src/skills/seed/ and src/skills/learned/) stay diff-clean
# across PRD runs; only this file is touched by the SkillCurator.
#
# Atomic writes via tempfile + os.replace; safe to read concurrently.
"""


_STATS_KEY_ORDER = [
    "usage_count",
    "acceptance_rate",
    "acceptance_history",
    "last_used",
    "status",
    "learned_from_prds",
    "created_at",
]


class SkillCurator:
    """Mutates `runtime_stats.yaml` safely. One instance per writer; no cache."""

    def __init__(self, runtime_stats_path: Path | str = RUNTIME_STATS_PATH) -> None:
        self.runtime_stats_path = Path(runtime_stats_path)

    # ---- usage telemetry -------------------------------------------------

    def increment_usage(self, skill_names: list[str]) -> None:
        """Bump `usage_count` by 1 for each skill name given (de-duplicated)."""
        unique_names = set(filter(None, skill_names))
        if not unique_names:
            return

        try:
            data = self._read()
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map
            mutated = False
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for name in unique_names:
                if name not in stats_map:
                    continue
                entry = stats_map[name] or {}
                entry["usage_count"] = int(entry.get("usage_count", 0) or 0) + 1
                entry["last_used"] = now
                stats_map[name] = entry
                mutated = True
            if mutated:
                self._write(data)
                self._bust_retriever_cache()
        except Exception as e:  # noqa: BLE001
            logger.warning("SkillCurator.increment_usage failed: %s", e)

    # ---- HITL acceptance feedback ---------------------------------------

    def update_acceptance(self, skill_name: str, accepted: bool) -> None:
        """Append an accept (1) / reject (0) sample and recompute rate.

        Sliding window of length `ACCEPTANCE_WINDOW`: oldest sample drops
        off when a new one arrives, so `acceptance_rate` reflects RECENT
        critic quality rather than ancient history. Stored alongside the
        rate so a restart doesn't reset the signal.
        """
        if not skill_name:
            return
        try:
            data = self._read()
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map
            entry = stats_map.get(skill_name)
            if entry is None:
                logger.info(
                    "update_acceptance: unknown skill %r — ignoring", skill_name
                )
                return
            history_raw = entry.get("acceptance_history") or "[]"
            try:
                history = list(json.loads(history_raw)) if isinstance(
                    history_raw, str
                ) else list(history_raw or [])
            except Exception:  # noqa: BLE001
                history = []
            history.append(1 if accepted else 0)
            if len(history) > ACCEPTANCE_WINDOW:
                history = history[-ACCEPTANCE_WINDOW:]
            entry["acceptance_history"] = json.dumps(history)
            entry["acceptance_rate"] = (
                round(sum(history) / len(history), 3) if history else None
            )
            stats_map[skill_name] = entry
            self._write(data)
            self._bust_retriever_cache()
        except Exception as e:  # noqa: BLE001
            logger.warning("SkillCurator.update_acceptance failed: %s", e)

    # ---- auto-deprecation ------------------------------------------------

    def auto_deprecate(
        self,
        *,
        usage_floor: int = AUTO_DEPRECATE_USAGE_FLOOR,
        acceptance_ceiling: float = AUTO_DEPRECATE_ACCEPTANCE_CEILING,
    ) -> list[str]:
        """Flip `status` → "deprecated" on skills with high usage + low acceptance.

        Returns the list of skill names that were just deprecated. Skills
        already deprecated (or merged) are skipped.
        """
        deprecated: list[str] = []
        try:
            data = self._read()
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map
            mutated = False
            for name, entry in stats_map.items():
                entry = entry or {}
                if not (entry.get("status") or "active").startswith("active"):
                    continue
                usage = int(entry.get("usage_count", 0) or 0)
                rate = entry.get("acceptance_rate")
                if usage < usage_floor or rate is None:
                    continue
                if float(rate) < acceptance_ceiling:
                    entry["status"] = "deprecated"
                    entry["deprecated_at"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    entry["deprecate_reason"] = (
                        f"auto: acceptance_rate {rate:.2f} < {acceptance_ceiling} "
                        f"after {usage} uses"
                    )
                    stats_map[name] = entry
                    deprecated.append(name)
                    mutated = True
            if mutated:
                self._write(data)
                self._bust_retriever_cache()
        except Exception as e:  # noqa: BLE001
            logger.warning("SkillCurator.auto_deprecate failed: %s", e)
        return deprecated

    # ---- duplicate merging ----------------------------------------------

    def merge_duplicates(self, threshold: float = 0.85) -> list[tuple[str, str]]:
        """Find near-duplicate active skills and demote the loser of each pair.

        Similarity: SequenceMatcher ratio on the (description, injected_into)
        joint string. The "winner" of a pair is whichever has higher
        usage_count (tie-break: alphabetical name). The loser keeps its
        SKILL.md on disk untouched, but its runtime_stats row gets
        `status="deprecated_merged_into_<winner>"`.

        Returns list of (loser, winner) pairs that were just merged.
        """
        try:
            retriever = default_retriever()
            retriever._library = None  # type: ignore[attr-defined]
            lib = retriever.load_library()
            data = self._read()
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map

            active = [s for s in lib.skills if s.status == "active"]
            merged: list[tuple[str, str]] = []
            visited: set[str] = set()

            for i in range(len(active)):
                a = active[i]
                if a.name in visited:
                    continue
                for j in range(i + 1, len(active)):
                    b = active[j]
                    if b.name in visited:
                        continue
                    sim = _description_similarity(a, b)
                    if sim < threshold:
                        continue
                    a_use = int((stats_map.get(a.name) or {}).get("usage_count", 0) or 0)
                    b_use = int((stats_map.get(b.name) or {}).get("usage_count", 0) or 0)
                    if (a_use, a.name) >= (b_use, b.name):
                        winner, loser = a, b
                    else:
                        winner, loser = b, a
                    entry = stats_map.get(loser.name) or {}
                    entry["status"] = f"deprecated_merged_into_{winner.name}"
                    entry["deprecated_at"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    stats_map[loser.name] = entry
                    merged.append((loser.name, winner.name))
                    visited.add(loser.name)
                    if loser.name == a.name:
                        break  # outer skill is gone; advance i

            if merged:
                self._write(data)
                self._bust_retriever_cache()
            return merged
        except Exception as e:  # noqa: BLE001
            logger.warning("SkillCurator.merge_duplicates failed: %s", e)
            return []

    # ---- back-compat stubs (kept callable; explicit no-op now) ----------

    def deprecate(self, skill_name: str, reason: str) -> None:
        """Manual deprecation — flip `status` and stamp the reason."""
        try:
            data = self._read()
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map
            entry = stats_map.get(skill_name)
            if entry is None:
                return
            entry["status"] = "deprecated"
            entry["deprecate_reason"] = reason
            entry["deprecated_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            stats_map[skill_name] = entry
            self._write(data)
            self._bust_retriever_cache()
        except Exception as e:  # noqa: BLE001
            logger.warning("SkillCurator.deprecate failed: %s", e)

    # ---- internals --------------------------------------------------------

    def _read(self) -> dict:
        if not self.runtime_stats_path.exists():
            return {"skills": {}}
        with self.runtime_stats_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"skills": {}}

    def _write(self, data: dict) -> None:
        skills_map = data.get("skills") or {}
        ordered_skills: dict = {}
        for name, entry in skills_map.items():
            entry = entry or {}
            ordered = {k: entry[k] for k in _STATS_KEY_ORDER if k in entry}
            for k in entry:
                if k not in ordered:
                    ordered[k] = entry[k]
            ordered_skills[name] = ordered
        data["skills"] = ordered_skills

        body = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )
        payload = _RUNTIME_HEADER + body

        path = self.runtime_stats_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _bust_retriever_cache() -> None:
        try:
            default_retriever()._library = None  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass


def _description_similarity(a, b) -> float:
    """SequenceMatcher ratio on description + sorted injected_into.

    Combining the two means two skills with similar descriptions but
    different role routing won't be flagged as duplicates (they're
    routed-differently variants, intentional).
    """
    routes_a = ",".join(sorted(a.injected_into))
    routes_b = ",".join(sorted(b.injected_into))
    if routes_a != routes_b:
        return 0.0
    return SequenceMatcher(
        None, (a.description or "").lower(), (b.description or "").lower()
    ).ratio()
