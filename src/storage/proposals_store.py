"""Persistence for distiller-proposed skills awaiting human review.

Layout:
    data/results/proposals/
      ├── <proposal_id>.json    # one file per proposal
      └── ...

A proposal is independently writable / queryable / promotable. Approved
proposals are PROMOTED to `src/skills/learned/<name>/SKILL.md`, after
which they participate in the regular retrieval pipeline like any seed
skill — their `runtime_stats.yaml` row is also created at promotion time.

All disk failures are absorbed (logged, not raised); the main pipeline
must never break because the proposals store broke.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

import yaml

from ..skills.retriever import LEARNED_DIR, RUNTIME_STATS_PATH, SKILL_FILENAME, parse_skill_md

if TYPE_CHECKING:
    from ..agents.skill_distiller import SkillProposal


def _SkillProposal():
    """Lazy import to break the cycle (skill_distiller imports HistoryStore,
    which lives in src.storage; src.storage.__init__ imports this module).
    Resolved by deferring the import to call time."""
    from ..agents.skill_distiller import SkillProposal as _SP

    return _SP

logger = logging.getLogger(__name__)


DEFAULT_PROPOSALS_DIR = Path("data") / "results" / "proposals"


class ProposalsStore:
    """File-backed store for `SkillProposal` records. Tolerant of disk failures."""

    def __init__(
        self,
        base_dir: Path | str = DEFAULT_PROPOSALS_DIR,
        *,
        learned_dir: Path | str | None = None,
        runtime_stats_path: Path | str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.learned_dir = Path(learned_dir) if learned_dir else LEARNED_DIR
        self.runtime_stats_path = (
            Path(runtime_stats_path) if runtime_stats_path else RUNTIME_STATS_PATH
        )

    # ---- save / list / load ------------------------------------------------

    def save(self, proposal: SkillProposal) -> Path | None:
        """Atomically persist `proposal` as `<proposal_id>.json`."""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = self.base_dir / f"{proposal.proposal_id}.json"
            _atomic_write_json(path, proposal.model_dump())
            return path
        except Exception as e:  # noqa: BLE001
            logger.warning("ProposalsStore.save failed: %s", e)
            return None

    def list_pending(self) -> list[SkillProposal]:
        """Return every proposal whose `status == 'pending'`, newest first."""
        return [p for p in self._iter_all() if p.status == "pending"]

    def list_all(self) -> list[SkillProposal]:
        return list(self._iter_all())

    def load(self, proposal_id: str) -> SkillProposal | None:
        path = self.base_dir / f"{proposal_id}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return _SkillProposal().model_validate(json.load(f))
        except Exception as e:  # noqa: BLE001
            logger.warning("ProposalsStore.load(%s) failed: %s", proposal_id, e)
            return None

    # ---- mutation ----------------------------------------------------------

    def update_status(
        self,
        proposal_id: str,
        status: str,
        *,
        edited_md: str | None = None,
    ) -> SkillProposal | None:
        """Flip status to `status` (and optionally overwrite SKILL.md text).

        `edited_md` is used by the "✏️ Edit" UI affordance — the PM can tweak
        the proposed SKILL.md before approving. We just persist the edit;
        the next promote_to_skill call uses the updated text.
        """
        proposal = self.load(proposal_id)
        if proposal is None:
            return None
        proposal.status = status  # type: ignore[assignment]
        if edited_md is not None:
            proposal.proposed_skill_md = edited_md
            if status == "pending":
                proposal.status = "edited"
        try:
            _atomic_write_json(
                self.base_dir / f"{proposal_id}.json", proposal.model_dump()
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("ProposalsStore.update_status failed: %s", e)
            return None
        return proposal

    def promote_to_skill(self, proposal_id: str) -> Path | None:
        """Write `<proposal>.proposed_skill_md` to `learned/<name>/SKILL.md`.

        Also seeds a row in `runtime_stats.yaml` so the retriever picks the
        new skill up immediately (active, usage_count=0). Marks the proposal
        as `approved` on success.

        Returns the path of the written SKILL.md, or None on failure.
        """
        proposal = self.load(proposal_id)
        if proposal is None:
            logger.warning("promote_to_skill: unknown proposal %s", proposal_id)
            return None

        try:
            fm, body = parse_skill_md(proposal.proposed_skill_md)
        except Exception as e:  # noqa: BLE001
            logger.warning("promote_to_skill: malformed SKILL.md: %s", e)
            return None
        if not body.strip():
            logger.warning("promote_to_skill: SKILL.md body empty")
            return None

        name = fm.get("name") or proposal.proposed_name
        target_dir = self.learned_dir / name
        target = target_dir / SKILL_FILENAME
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(proposal.proposed_skill_md, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("promote_to_skill: write failed: %s", e)
            return None

        # Seed runtime stats so the retriever sees status=active immediately.
        self._seed_runtime_stats(name)

        # Bust the in-process retriever cache so the new skill is visible
        # without a restart (mirrors SkillCurator behavior).
        try:
            from ..skills.retriever import default_retriever

            default_retriever()._library = None  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

        # Mark proposal approved.
        self.update_status(proposal_id, "approved")
        return target

    # ---- internals ---------------------------------------------------------

    def _iter_all(self) -> list[SkillProposal]:
        if not self.base_dir.exists():
            return []
        out: list[SkillProposal] = []
        for path in self.base_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    out.append(_SkillProposal().model_validate(json.load(f)))
            except Exception as e:  # noqa: BLE001
                logger.warning("ProposalsStore: skipping unreadable %s: %s", path, e)
        out.sort(key=lambda p: p.created_at, reverse=True)
        return out

    def _seed_runtime_stats(self, name: str) -> None:
        """Add a fresh row to `runtime_stats.yaml` for the just-promoted skill."""
        try:
            data: dict[str, Any] = {}
            if self.runtime_stats_path.exists():
                with self.runtime_stats_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            stats_map = data.setdefault("skills", {}) or {}
            data["skills"] = stats_map
            if name in stats_map:
                # Preserve existing entry if it somehow predates this promote.
                return
            stats_map[name] = {
                "usage_count": 0,
                "acceptance_rate": None,
                "last_used": None,
                "status": "active",
                "learned_from_prds": [],
            }
            stats_map[name]["created_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            self.runtime_stats_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
            self._atomic_write_text(self.runtime_stats_path, tmp_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("ProposalsStore._seed_runtime_stats failed: %s", e)

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """tempfile + os.replace — same recipe as HistoryStore."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
