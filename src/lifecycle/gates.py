"""Admission gates — the four independent checks a candidate must pass.

An LLM may PROPOSE and EXPLAIN a skill; it can never approve one. Approval
requires four independent checks (HANDOFF §5 "Admission gate"):

  1. spec      — deterministic SKILL.md shape validation (no LLM).
  2. evidence  — pattern spans >= 3 distinct PRDs, deduplicated by PRD
                 hash so reruns of the same PRD never count twice.
  3. novelty   — not a semantic duplicate of an existing active skill
                 (difflib, per debt D-15; embeddings deferred by design).
  4. shadow    — counterfactual OFF/ON evaluation over the same PRDs,
                 config, and model (see shadow.py).

Policy: **Precision-first, Recall non-regression** — minimum rules agreed
in product review:

  - Precision must not decline.
  - Recall decline must be <= 0.02.
  - Target pattern must hit >= 3 independent PRDs.
  - No extra false P0.
  - Evidence and suggested_fix compliance must not regress (ON vs OFF).
    Compliance is judged on the DELTA, not an absolute floor: how well a
    model quotes the PRD is a pipeline property; what a candidate gate
    must catch is the candidate making it WORSE.

Advisory preference (not a hard gate): candidates gaining Precision +0.03,
or Recall +0.03 at equal Precision, are preferred.

Every gate returns a plain dict ready for `GateReport.detail`; the caller
(governance.run_gates) persists it with the evaluator version so historical
gate verdicts stay interpretable after the checkers evolve.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from pydantic import BaseModel

from ..agents.skill_distiller import ALLOWED_CRITICS, KEBAB_RE
from ..eval.rubric import _content_tokens
from ..skills.retriever import parse_skill_md
from .models import (
    EVIDENCE_VALIDATOR_VERSION,
    NOVELTY_VALIDATOR_VERSION,
    POLICY_VERSION,
    SPEC_VALIDATOR_VERSION,
)

# ---- policy numbers (agreed minimum) ------------------------------------------

RECALL_DECLINE_TOLERANCE = 0.02
TARGET_PATTERN_MIN_PRDS = 3
COMPLIANCE_DECLINE_TOLERANCE = 0.02
PREFERENCE_GAIN = 0.03
_EPS = 1e-9


class AdmissionDecision(BaseModel):
    """Verdict of the shadow-evaluation admission policy."""

    result: str                      # 'pass' | 'fail'
    reasons: list[str] = []
    policy_version: str = POLICY_VERSION
    preference_met: bool | None = None
    preference_note: str | None = None


def decide_admission(
    *,
    metrics_off: dict,
    metrics_on: dict,
    target_pattern_hits: int | None,
) -> AdmissionDecision:
    """Apply the Precision-first / Recall-non-regression policy.

    Missing/unknown values fail the specific check with an explicit reason
    rather than being silently skipped — an unknown is not a pass.
    """
    reasons: list[str] = []

    precision_off = metrics_off.get("precision")
    precision_on = metrics_on.get("precision")
    recall_off = metrics_off.get("recall")
    recall_on = metrics_on.get("recall")
    false_p0_off = metrics_off.get("false_p0_count")
    false_p0_on = metrics_on.get("false_p0_count")

    if precision_off is None or precision_on is None:
        reasons.append("precision missing on OFF or ON arm")
    elif precision_on < precision_off - _EPS:
        reasons.append(
            f"precision declined {precision_off:.3f} -> {precision_on:.3f}"
        )

    if recall_off is None or recall_on is None:
        reasons.append("recall missing on OFF or ON arm")
    elif recall_off - recall_on > RECALL_DECLINE_TOLERANCE + _EPS:
        reasons.append(
            f"recall declined {recall_off:.3f} -> {recall_on:.3f} "
            f"(tolerance {RECALL_DECLINE_TOLERANCE})"
        )

    if target_pattern_hits is None:
        reasons.append("target pattern hit count unknown (never a pass)")
    elif target_pattern_hits < TARGET_PATTERN_MIN_PRDS:
        reasons.append(
            f"target pattern hit only {target_pattern_hits} PRD(s) "
            f"(< {TARGET_PATTERN_MIN_PRDS} required)"
        )

    if false_p0_off is None or false_p0_on is None:
        reasons.append("false P0 count missing on OFF or ON arm")
    elif false_p0_on - false_p0_off > _EPS:
        reasons.append(
            f"introduced {int(false_p0_on - false_p0_off)} extra false P0(s)"
        )

    for key, label in (
        ("evidence_compliance", "evidence compliance"),
        ("actionability", "suggested_fix actionability"),
    ):
        off_value = metrics_off.get(key)
        on_value = metrics_on.get(key)
        if off_value is None or on_value is None:
            reasons.append(f"{label} not measured on both arms")
        elif float(off_value) - float(on_value) > COMPLIANCE_DECLINE_TOLERANCE + _EPS:
            reasons.append(
                f"{label} regressed {float(off_value):.2f} -> {float(on_value):.2f} "
                f"(tolerance {COMPLIANCE_DECLINE_TOLERANCE})"
            )

    # Advisory preference — reported, never gates.
    preference_met = None
    preference_note = None
    if precision_off is not None and precision_on is not None:
        if precision_on - precision_off >= PREFERENCE_GAIN - _EPS:
            preference_met = True
            preference_note = (
                f"precision +{precision_on - precision_off:.3f} >= +{PREFERENCE_GAIN}"
            )
        elif (
            recall_on is not None
            and abs(precision_on - precision_off) <= _EPS
            and recall_on - recall_off >= PREFERENCE_GAIN - _EPS
        ):
            preference_met = True
            preference_note = (
                f"recall +{recall_on - recall_off:.3f} at equal precision"
            )
        else:
            preference_met = False
            preference_note = "below the +0.03 preference bar (advisory only)"

    return AdmissionDecision(
        result="pass" if not reasons else "fail",
        reasons=reasons,
        preference_met=preference_met,
        preference_note=preference_note,
    )


# ---- evidence compliance (deterministic, shared) -------------------------------

#: Minimum share of an evidence field's content tokens that must appear in
#: the PRD text for the critique to count as "quoting the PRD". Loose on
#: purpose — this is a free-invention tripwire, not a citation grader.
EVIDENCE_TOKEN_OVERLAP = 0.5


def evidence_quotes_prd(evidence: str, prd_text: str) -> bool:
    """Deterministic check that a critique's evidence is PRD-grounded.

    Shares ≥ EVIDENCE_TOKEN_OVERLAP of its content tokens with the PRD
    text. Difflib/token-based per debt D-15; an LLM judge can replace it
    later without changing call sites.
    """
    tokens = _content_tokens(evidence or "")
    if not tokens:
        return False
    lowered = (prd_text or "").lower()
    found = sum(1 for tok in tokens if tok in lowered)
    return found / len(tokens) >= EVIDENCE_TOKEN_OVERLAP


def evidence_compliance(critiques: list[dict], prd_text: str) -> float:
    """Fraction of critiques whose evidence quotes the PRD (0.0–1.0)."""
    if not critiques:
        return 0.0
    hits = sum(
        1 for c in critiques if evidence_quotes_prd(str(c.get("evidence") or ""), prd_text)
    )
    return hits / len(critiques)


# ---- gate 1: spec ---------------------------------------------------------------


def validate_spec(proposed_skill_md: str, proposed_name: str) -> dict:
    """Deterministic SKILL.md shape validation. Returns GateReport.detail.

    Mirrors the checks the distiller already applies at generation time —
    but gates run at APPROVAL time against (possibly human-edited) text,
    so they must not trust the generator.
    """
    violations: list[str] = []
    fm: dict = {}
    body = ""
    try:
        fm, body = parse_skill_md(proposed_skill_md)
    except Exception as e:  # noqa: BLE001
        violations.append(f"SKILL.md unparseable: {e}")

    if not violations:
        for required in ("name", "description", "version", "created_by", "injected_into"):
            if required not in fm:
                violations.append(f"frontmatter missing required field: {required}")
        if fm and not KEBAB_RE.match(str(fm.get("name") or "")):
            violations.append(f"frontmatter name {fm.get('name')!r} is not kebab-case")
        if fm and str(fm.get("created_by")) != "distiller":
            violations.append("frontmatter created_by must be 'distiller'")
        if not str(fm.get("version") or "").strip():
            violations.append("frontmatter version empty")
        routes = fm.get("injected_into") or []
        if not isinstance(routes, list) or not routes:
            violations.append("injected_into must be a non-empty list")
        else:
            bad = set(map(str, routes)) - ALLOWED_CRITICS
            if bad:
                violations.append(f"injected_into invalid routes: {sorted(bad)}")
        if not str(fm.get("description") or "").strip():
            violations.append("frontmatter description empty")
        if not body.strip():
            violations.append("SKILL.md body is empty")

    if not KEBAB_RE.match(proposed_name or ""):
        violations.append(f"proposed_name {proposed_name!r} is not kebab-case")
    elif fm and str(fm.get("name")) != proposed_name:
        violations.append(
            f"frontmatter name {fm.get('name')!r} != proposed_name {proposed_name!r}"
        )

    return {
        "passed": not violations,
        "violations": violations,
        "evaluator_version": SPEC_VALIDATOR_VERSION,
    }


# ---- gate 2: evidence -------------------------------------------------------------


def validate_evidence(evidence_rows: list[dict], history_store) -> dict:
    """The pattern must span >= 3 DISTINCT PRDs (PRD-hash dedup).

    Reruns of the same PRD produce different run_ids but the same
    `prd_text_hash` — dedup by hash is what makes "three distinct PRDs"
    mean three documents, not three attempts.
    """
    run_ids = sorted(
        {
            str(row.get("run_id"))
            for row in evidence_rows
            if row.get("run_id")
        }
    )
    hashes: dict[str, str] = {}  # prd_hash -> first run_id that contributed it
    missing_runs: list[str] = []
    for rid in run_ids:
        record = history_store.load(rid)
        if record is None:
            missing_runs.append(rid)
            continue
        hashes.setdefault(record.prd_text_hash, rid)

    passed = len(hashes) >= TARGET_PATTERN_MIN_PRDS and not missing_runs
    reasons = []
    if len(hashes) < TARGET_PATTERN_MIN_PRDS:
        reasons.append(
            f"pattern spans {len(hashes)} distinct PRD(s) by hash "
            f"(< {TARGET_PATTERN_MIN_PRDS} required)"
        )
    if missing_runs:
        reasons.append(f"history missing run_id(s): {missing_runs}")

    return {
        "passed": passed,
        "evaluator_version": EVIDENCE_VALIDATOR_VERSION,
        "distinct_prd_count": len(hashes),
        "distinct_prd_hashes": sorted(hashes),
        "run_ids": run_ids,
        "missing_run_ids": missing_runs,
        "reasons": reasons,
    }


# ---- gate 3: novelty --------------------------------------------------------------


def validate_novelty(
    proposed_name: str,
    proposed_description: str,
    proposed_routes: list[str],
    active_skills: list,
    *,
    threshold: float = 0.85,
) -> dict:
    """Not a semantic duplicate of an existing ACTIVE skill.

    Similarity = SequenceMatcher ratio on lowercased descriptions, but
    only between skills sharing the same routed roles — two descriptions
    that look alike but route to different critics are variants, not
    duplicates (same rule as `SkillCurator.merge_duplicates`). Difflib is
    the acknowledged D-15 debt; swap for embeddings only with measured
    retrieval-miss evidence.
    """
    prop_routes = ",".join(sorted(proposed_routes))
    scored: list[dict] = []
    for skill in active_skills:
        skill_routes = ",".join(sorted(getattr(skill, "injected_into", []) or []))
        if skill_routes != prop_routes:
            continue
        ratio = SequenceMatcher(
            None,
            (proposed_description or "").lower(),
            (getattr(skill, "description", "") or "").lower(),
        ).ratio()
        scored.append(
            {
                "skill": getattr(skill, "name", "?"),
                "similarity": round(ratio, 3),
                "same_routes": True,
            }
        )
    scored.sort(key=lambda s: s["similarity"], reverse=True)
    top = scored[0] if scored else None
    passed = top is None or top["similarity"] < threshold

    reasons = []
    if top is not None and not passed:
        reasons.append(
            f"max similarity {top['similarity']:.3f} vs active skill "
            f"{top['skill']!r} >= threshold {threshold}"
        )

    return {
        "passed": passed,
        "evaluator_version": NOVELTY_VALIDATOR_VERSION,
        "threshold": threshold,
        "compared_against": len(active_skills),
        "top_matches": scored[:3],
        "reasons": reasons,
    }
