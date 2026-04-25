"""Skill Library write side — runtime telemetry + future curation hooks.

Day 8.5 split: telemetry now lives in `runtime_stats.yaml`, NOT in the
`SKILL.md` frontmatter. This means:

  - Each PRD run only mutates `runtime_stats.yaml`. SKILL.md files (the
    design-time content of each skill) stay diff-clean across runs.
  - Distiller-authored skills (Day 9) drop their stats row in here at
    creation time, sidestepping any race with usage bumping.

`update_acceptance` and `deprecate` remain stubs; Day 9 fills them in.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .retriever import RUNTIME_STATS_PATH, default_retriever

logger = logging.getLogger(__name__)


_RUNTIME_HEADER = """\
# Runtime telemetry for skills, keyed by SKILL.md `name`.
#
# This file is the ONLY place runtime data lives. SKILL.md frontmatter and
# bodies (under src/skills/seed/ and src/skills/learned/) stay diff-clean
# across PRD runs; only this file is touched by the SkillCurator.
#
# Atomic writes via tempfile + os.replace; safe to read concurrently.
"""


# Canonical key order for each skill's stats block. Matches runtime_stats.yaml
# so diffs stay tight and reviewable.
_STATS_KEY_ORDER = [
    "usage_count",
    "acceptance_rate",
    "last_used",
    "status",
    "learned_from_prds",
]


class SkillCurator:
    """Mutates `runtime_stats.yaml` safely. One instance per writer; no cache."""

    def __init__(self, runtime_stats_path: Path | str = RUNTIME_STATS_PATH) -> None:
        self.runtime_stats_path = Path(runtime_stats_path)

    # ---- the only Day-8 mutator ------------------------------------------

    def increment_usage(self, skill_names: list[str]) -> None:
        """Bump `usage_count` by 1 for each skill name given (de-duplicated).

        A single call with `["foo", "foo"]` increments by 1, not 2 — a
        single PRD run that retrieves the same skill for multiple critics
        should still count as one use. Also stamps `last_used` to now.

        Unknown names are silently ignored (logged at debug). Empty input
        is a no-op.
        """
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
                    # Silently skip unknown — keeps test_unknown_id_is_ignored
                    # semantics. A future Day can choose to register stubs.
                    continue
                entry = stats_map[name] or {}
                entry["usage_count"] = int(entry.get("usage_count", 0) or 0) + 1
                entry["last_used"] = now
                stats_map[name] = entry
                mutated = True
            if mutated:
                self._write(data)
                # Bust the retriever's in-memory cache so the next read sees
                # the fresh counts (Streamlit sidebar rerender).
                try:
                    default_retriever()._library = None  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
        except Exception as e:  # noqa: BLE001 — telemetry failures are non-fatal
            logger.warning("SkillCurator.increment_usage failed: %s", e)

    # ---- placeholders wired by Day 9 -------------------------------------

    def update_acceptance(
        self,
        skill_name: str,  # noqa: ARG002 — Day 9 will use these
        accepted: bool,  # noqa: ARG002
    ) -> None:
        """Update `acceptance_rate` after a HITL accept/reject decision.

        Stub — implemented in Day 9 alongside the curator UI.
        """
        raise NotImplementedError("update_acceptance lands in Day 9")

    def deprecate(
        self,
        skill_name: str,  # noqa: ARG002
        reason: str,  # noqa: ARG002
    ) -> None:
        """Flip `status` to `"deprecated"` and stamp the reason. Stub for Day 9."""
        raise NotImplementedError("deprecate lands in Day 9")

    # ---- internals --------------------------------------------------------

    def _read(self) -> dict:
        if not self.runtime_stats_path.exists():
            return {"skills": {}}
        with self.runtime_stats_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"skills": {}}

    def _write(self, data: dict) -> None:
        """Atomic write: tempfile → fsync → rename. Header re-prepended."""
        # Reorder each skill's stat keys so the diff stays human-friendly.
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
