"""Evaluation rubric — 5 dimensions for scoring stress-test runs against golden PRDs.

Each scoring function compares one run's output against the corresponding
manifest entry in `src/eval/golden_prds/manifest.yaml`. Matching from
critique → golden defect uses `difflib.SequenceMatcher` ratio ≥ 0.5
(TODO: upgrade to embeddings — see HANDOFF debt D-10/D-12).

Every function fails closed: on schema or input weirdness it returns 0.0
and logs a warning rather than raising, so an ablation sweep over many
runs never gets killed by one malformed critique.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from ..graph.state import Critique

logger = logging.getLogger(__name__)


# Threshold used at the call sites. We score with `max(SequenceMatcher,
# token_jaccard)` so a critique only needs to win on ONE of the two:
# verbatim-ish wording OR shared key terms ("rollback", "baseline" …).
# Calibrated against the 5 golden PRDs so each defect's right critique
# clears the bar but unrelated critiques (different dimension) do not.
MATCH_THRESHOLD = 0.35

# Tokens too generic to count toward overlap — they show up in nearly
# every PRD critique and would inflate Jaccard similarity for everyone.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "of", "to", "and", "or", "for",
        "in", "on", "with", "by", "be", "no", "not", "at", "as", "this",
        "that", "it", "its", "but", "if", "any", "all", "from", "into",
        "out", "up", "down", "we", "our", "you", "your", "they", "their",
        "every", "there", "than", "then", "so", "do", "does", "has",
        "have", "had", "will", "would", "should", "could", "can",
        "prd", "prds", "section", "sections", "users", "user",
    }
)

DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "golden_prds" / "manifest.yaml"
)


# ---- Schema ---------------------------------------------------------------


class RubricScore(BaseModel):
    """Per-run score across the five rubric dimensions plus aggregate stats."""

    structure_compliance: float = Field(0.0, ge=0, le=1)
    dependency_recall: float = Field(0.0, ge=0, le=1)
    contradiction_detection: float = Field(0.0, ge=0, le=1)
    severity_classification_f1: float = Field(0.0, ge=0, le=1)
    actionability: float = Field(0.0, ge=0, le=1)
    overall_recall: float = Field(0.0, ge=0, le=1)
    precision: float = Field(0.0, ge=0, le=1)
    matched_defect_ids: list[str] = Field(default_factory=list)
    false_positive_count: int = 0
    # Unmatched critiques at P0 severity — the "extra false P0" signal the
    # lifecycle admission policy gates on (see src/lifecycle/gates.py).
    false_p0_count: int = 0


# ---- Manifest helpers ------------------------------------------------------


def load_manifest(path: Path | str | None = None) -> dict:
    """Read manifest.yaml and return `{filename: entry}` for fast lookup."""
    p = Path(path) if path else DEFAULT_MANIFEST_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {entry["file"]: entry for entry in raw.get("prds", []) or []}


def manifest_for(filename: str | None, manifest: dict | None = None) -> dict | None:
    """Return the manifest entry matching `filename`, or None if missing."""
    if not filename:
        return None
    m = manifest or load_manifest()
    return m.get(filename)


# ---- The five rubric scorers ----------------------------------------------


def score_structure_compliance(critiques: list[dict]) -> float:
    """Fraction of critiques that validate against the `Critique` pydantic schema.

    Returns `0.0` on an empty list — the pipeline produced nothing parseable,
    which is the worst possible structure outcome.
    """
    if not critiques:
        return 0.0
    ok = 0
    for c in critiques:
        try:
            Critique.model_validate(c)
            ok += 1
        except (ValidationError, TypeError):
            continue
    return ok / len(critiques)


def score_dependency_recall(critiques: list[dict], manifest_entry: dict) -> float:
    """Recall over `dimension == 'dependency_identification'` defects."""
    return _recall_for_dimension(critiques, manifest_entry, "dependency_identification")


def score_contradiction_detection(critiques: list[dict], manifest_entry: dict) -> float:
    """Recall over `dimension == 'internal_contradiction'` defects."""
    return _recall_for_dimension(critiques, manifest_entry, "internal_contradiction")


def score_severity_classification_f1(
    critiques: list[dict], manifest_entry: dict
) -> float:
    """Macro-F1 of predicted P0/P1/P2 against each MATCHED defect's labeled severity.

    Defects with no matching critique don't contribute (no prediction =
    no label pair). When zero defects are matched, return 0.0.
    """
    matches = _match_critiques_to_defects(critiques, manifest_entry)
    if not matches:
        return 0.0

    labels = {"P0", "P1", "P2"}
    f1s: list[float] = []
    for label in labels:
        tp = sum(
            1 for crit, defect in matches if crit.get("severity") == label
            and defect.get("severity") == label
        )
        fp = sum(
            1 for crit, defect in matches if crit.get("severity") == label
            and defect.get("severity") != label
        )
        fn = sum(
            1 for crit, defect in matches if crit.get("severity") != label
            and defect.get("severity") == label
        )
        if tp + fp + fn == 0:
            continue  # label absent from this batch
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        if precision + recall == 0:
            f1s.append(0.0)
        else:
            f1s.append(2 * precision * recall / (precision + recall))
    return sum(f1s) / len(f1s) if f1s else 0.0


def score_actionability(critiques: list[dict]) -> float:
    """Fraction of critiques whose `suggested_fix` is non-empty and concrete.

    "Concrete" = ≥ 12 characters AND contains at least one imperative-style
    verb. Both checks are intentionally loose; on real OpenAI output this
    becomes a much stricter LLM-judged classifier.
    """
    if not critiques:
        return 0.0
    imperatives = (
        "add", "remove", "specify", "include", "define", "set",
        "limit", "cap", "enforce", "split", "rewrite", "drop",
        "introduce", "decouple", "guard", "log", "instrument",
        "rename", "validate", "publish", "expose", "track", "store",
    )
    ok = 0
    for c in critiques:
        fix = (c.get("suggested_fix") or "").strip().lower()
        if len(fix) < 12:
            continue
        if any(verb in fix for verb in imperatives):
            ok += 1
    return ok / len(critiques)


# ---- Composite ------------------------------------------------------------


def score_run(
    state: dict,
    *,
    prd_filename: str | None = None,
    manifest_path: Path | str | None = None,
) -> RubricScore:
    """Compute every rubric dimension + overall recall / precision for one run.

    Robust to missing manifest entries: if `prd_filename` isn't in the
    manifest (custom PRD), per-defect scorers return 0.0 but
    `structure_compliance` and `actionability` stay meaningful.
    """
    try:
        critiques: list[dict] = []
        for c in state.get("critiques", []) or []:
            critiques.append(c.model_dump() if hasattr(c, "model_dump") else dict(c))

        manifest = load_manifest(manifest_path)
        entry = manifest_for(prd_filename, manifest) or {"defects": []}

        matches = _match_critiques_to_defects(critiques, entry)
        matched_ids = sorted({d.get("id") for _, d in matches if d.get("id")})

        total_defects = len(entry.get("defects") or [])
        overall_recall = len(matched_ids) / total_defects if total_defects else 0.0

        critique_count = len(critiques)
        # Identity-based dedup so two critiques mapped to the same defect
        # don't both count toward precision (they won't — see _match_*).
        matched_refs = {id(c) for c, _ in matches}
        matched_critique_count = len(matched_refs)
        precision = (
            matched_critique_count / critique_count if critique_count else 0.0
        )
        false_positive_count = max(critique_count - matched_critique_count, 0)
        false_p0_count = sum(
            1
            for c in critiques
            if c.get("severity") == "P0" and id(c) not in matched_refs
        )

        return RubricScore(
            structure_compliance=score_structure_compliance(critiques),
            dependency_recall=score_dependency_recall(critiques, entry),
            contradiction_detection=score_contradiction_detection(critiques, entry),
            severity_classification_f1=score_severity_classification_f1(
                critiques, entry
            ),
            actionability=score_actionability(critiques),
            overall_recall=overall_recall,
            precision=precision,
            matched_defect_ids=matched_ids,
            false_positive_count=false_positive_count,
            false_p0_count=false_p0_count,
        )
    except Exception as e:  # noqa: BLE001 — fail closed
        logger.warning("score_run failed for %s: %s", prd_filename, e)
        return RubricScore()


# ---- Internals ------------------------------------------------------------


def _recall_for_dimension(
    critiques: list[dict], manifest_entry: dict, dimension: str
) -> float:
    """Fraction of defects on `dimension` that have at least one matching critique.

    A PRD with zero defects on a dimension → vacuous full recall (1.0),
    so the dimension score stays comparable across PRDs that don't all
    exercise every defect type.
    """
    defects = [
        d for d in (manifest_entry.get("defects") or [])
        if d.get("dimension") == dimension
    ]
    if not defects:
        return 1.0
    matches = _match_critiques_to_defects(critiques, manifest_entry)
    matched_defect_ids = {d.get("id") for _, d in matches}
    hit = sum(1 for d in defects if d.get("id") in matched_defect_ids)
    return hit / len(defects)


def _match_critiques_to_defects(
    critiques: list[dict], manifest_entry: dict
) -> list[tuple[dict, dict]]:
    """Greedy 1:1 fuzzy match between critique findings and golden defect notes.

    Each defect matches at most ONE critique (so two critiques piling
    onto the same defect don't double-count recall). Each critique
    matches at most one defect.
    """
    defects = manifest_entry.get("defects") or []
    matches: list[tuple[dict, dict]] = []
    used_critiques: set[int] = set()
    used_defects: set[str] = set()

    for defect in defects:
        defect_id = defect.get("id")
        if defect_id in used_defects:
            continue
        note = (defect.get("note") or "").strip().lower()
        if not note:
            continue

        best_idx = -1
        best_ratio = MATCH_THRESHOLD
        note_tokens = _content_tokens(note)
        for i, crit in enumerate(critiques):
            if i in used_critiques:
                continue
            # Score against EACH critique field individually and take the
            # max — concatenating finding+evidence+fix would dilute both
            # SequenceMatcher and Jaccard with mismatched-length text.
            ratio = 0.0
            for field in ("finding", "evidence", "suggested_fix"):
                text = str(crit.get(field, "")).lower()
                if not text.strip():
                    continue
                pair = max(
                    SequenceMatcher(None, note, text).ratio(),
                    _jaccard(note_tokens, _content_tokens(text)),
                )
                if pair > ratio:
                    ratio = pair
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
        if best_idx >= 0:
            matches.append((critiques[best_idx], defect))
            used_critiques.add(best_idx)
            if defect_id:
                used_defects.add(defect_id)
    return matches


def _content_tokens(text: str) -> set[str]:
    """Lowercase content-word set after stopword + punctuation strip."""
    out: set[str] = set()
    for raw in text.lower().replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 3 and token not in _STOPWORDS:
            out.add(token)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---- Back-compat aliases ---------------------------------------------------
# Earlier callers used the names without the `score_` prefix.

structure_compliance = score_structure_compliance
dependency_recall = score_dependency_recall
contradiction_detection = score_contradiction_detection
severity_classification_f1 = score_severity_classification_f1
actionability = score_actionability
