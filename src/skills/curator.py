"""Skill Library write side — usage tracking + future curation hooks.

Day 8 implements only `increment_usage`. `update_acceptance` and
`deprecate` are placeholders so Day 9 (Distiller + Curator UI) can wire
them up without a second round of imports/threading.

Persistence
-----------
We rewrite `library.yaml` via PyYAML. PyYAML drops comments and re-orders
keys to its own sort order (we mitigate the ordering loss by setting
`sort_keys=False`, but the leading file-header comment block IS lost on
the first write).

To preserve the human-authored top comment, we hardcode the canonical header
in `_LIBRARY_HEADER` and re-prepend it on every write. The comment is part
of the persisted contract, not metadata maintained by the YAML library.

If a future Day requires preserving inline comments on individual skills,
swap PyYAML for `ruamel.yaml` (round-trip mode) — at the cost of a heavier
dependency. See HANDOFF.md technical-debt ledger.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml

from .retriever import DEFAULT_LIBRARY_PATH, default_retriever

logger = logging.getLogger(__name__)


_LIBRARY_HEADER = """\
# Skill Library — seed entries.
#
# Metadata only. The authoritative content of each skill lives in the file
# referenced by `prompt_fragment_path` (relative to src/skills/), which is
# spliced into the relevant critic's system prompt at retrieval time.
#
# To add a skill: drop a new .md into fragments/, then append an entry here.
"""


# Canonical key order on the disk format. Anything not listed appears after
# in insertion order. Matches the seed file so diffs stay minimal.
_KEY_ORDER = [
    "id",
    "name",
    "description",
    "trigger_keywords",
    "trigger_semantic",
    "injected_into",
    "prompt_fragment_path",
    "confidence",
    "usage_count",
    "acceptance_rate",
    "created_at",
    "created_by",
    "learned_from_prds",
    "status",
]


class SkillCurator:
    """Mutates `library.yaml` safely. One instance per writer; no in-memory cache."""

    def __init__(self, library_path: Path | str = DEFAULT_LIBRARY_PATH) -> None:
        self.library_path = Path(library_path)

    # ---- the only Day-8 mutator ------------------------------------------

    def increment_usage(self, skill_ids: list[str]) -> None:
        """Bump `usage_count` by 1 for each id given (de-duplicated).

        A single call with `["skl_001", "skl_001"]` increments by 1, not 2 —
        a single PRD run that retrieves the same skill for multiple critics
        should still count as one use.
        """
        unique_ids = set(filter(None, skill_ids))
        if not unique_ids:
            return

        try:
            data = self._read()
            mutated = False
            for entry in data.get("skills", []):
                if entry.get("id") in unique_ids:
                    entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
                    mutated = True
            if mutated:
                self._write(data)
                # Bust the retriever's in-memory cache so the next read sees
                # the new counts (matters for the Streamlit sidebar).
                try:
                    default_retriever()._library = None  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
        except Exception as e:  # noqa: BLE001 — telemetry failures are non-fatal
            logger.warning("SkillCurator.increment_usage failed: %s", e)

    # ---- placeholders wired by Day 9 -------------------------------------

    def update_acceptance(
        self,
        skill_id: str,  # noqa: ARG002 — Day 9 will use these
        accepted: bool,  # noqa: ARG002
    ) -> None:
        """Update `acceptance_rate` after a HITL accept/reject decision.

        Stub — implemented in Day 9 alongside the curator UI. Defined here
        so callers can import the API surface today.
        """
        raise NotImplementedError("update_acceptance lands in Day 9")

    def deprecate(
        self,
        skill_id: str,  # noqa: ARG002
        reason: str,  # noqa: ARG002
    ) -> None:
        """Flip `status` to `"deprecated"` and stamp the reason.

        Stub — implemented in Day 9.
        """
        raise NotImplementedError("deprecate lands in Day 9")

    # ---- internals --------------------------------------------------------

    def _read(self) -> dict:
        with self.library_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _write(self, data: dict) -> None:
        """Atomic write: tempfile → fsync → rename. Yaml header re-prepended."""
        # Reorder each skill's keys so the diff stays small / human-friendly.
        for skill in data.get("skills", []) or []:
            ordered = {k: skill[k] for k in _KEY_ORDER if k in skill}
            for k in skill:
                if k not in ordered:
                    ordered[k] = skill[k]
            skill.clear()
            skill.update(ordered)

        body = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )
        payload = _LIBRARY_HEADER + "\n" + body

        path = self.library_path
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
                    # Some filesystems don't support fsync on Windows; not fatal.
                    pass
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
