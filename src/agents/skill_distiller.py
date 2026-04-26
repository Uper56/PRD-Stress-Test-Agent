"""Skill Distiller — propose new SKILL.md candidates from cross-PRD history.

Pipeline:

  1. Pull every run with ≥1 unattributed critique  (`HistoryStore.query(only_misses=True)`).
  2. Group misses by `critic_id`.
  3. Within each group, cluster findings by textual similarity
     (difflib.SequenceMatcher; TODO: upgrade to sentence-transformers).
  4. Keep clusters that:
       - span ≥ `min_pattern_frequency` distinct PRDs (run_ids), AND
       - have ≥ 3 evidence rows.
  5. For each surviving cluster, ask the LLM for a SkillProposal
     (kebab name, full SKILL.md text, generalization_score).
  6. Drop proposals where `generalization_score < 0.7` or evidence is malformed.
  7. Validate the proposed SKILL.md frontmatter against the Day-8.5 spec
     (kebab name, required fields, allowed `created_by`, body non-empty).

The distiller never writes to disk itself — proposals are returned in memory.
The Streamlit "🧪 Skill Distillation" panel persists them via
`ProposalsStore.save` after a human review.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field

from ..agents._parsing import extract_json
from ..llm.provider import LLMProvider
from ..skills.retriever import parse_skill_md
from ..storage import HistoryStore

logger = logging.getLogger(__name__)


# Tunables — exposed via run_distiller args, but defaults captured here.
DEFAULT_MIN_PATTERN_FREQUENCY = 3
DEFAULT_MIN_RUNS_REQUIRED = 3
GENERALIZATION_THRESHOLD = 0.7
SIMILARITY_THRESHOLD = 0.6  # difflib SequenceMatcher; TODO: upgrade to embeddings
ALLOWED_CRITICS = {"engineering", "business", "user_advocate", "design"}
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


SKILL_DISTILLATION_SYSTEM_PROMPT = """\
You are the **Skill Distillation** officer for a multi-agent PRD reviewer.

Your job: read a cluster of recurring critic findings (from real PRD reviews
where the existing Skill Library produced NO matching skill) and propose ONE
new reusable skill in Anthropic Agent Skills SKILL.md format.

Hard rules — output is REJECTED if any are violated:

1. Never propose a skill from a single finding. The cluster you receive
   already passed a frequency filter (≥3 distinct PRDs); your proposed
   skill must capture what is COMMON across those PRDs, not what is
   specific to any one of them.
2. The skill `description` MUST be pushy: tell the agent in 1–2 sentences
   when it MUST trigger. "Soft" or vague descriptions are rejected.
3. The skill must be GENERAL. Reject (low generalization_score) anything
   that names a specific business term ("MyCo's pricing tier", "the X
   feature") rather than a reusable PRD-review pattern.
4. Required SKILL.md frontmatter fields: name (kebab-case), description,
   version: "1.0", created_by: "distiller", injected_into (non-empty
   list of {"engineering","business","user_advocate","design"}).
5. The Markdown body must follow the canonical structure:
   ## When to apply / ## Instruction / ## Rationale / ## Examples of issues this catches.

Output strictly the following JSON, nothing else:

{
  "proposed_name": "kebab-case-name",
  "proposed_skill_md": "---\\nname: kebab-case-name\\n... (full SKILL.md text)",
  "injected_into": ["engineering"],
  "generalization_score": 0.0
}

generalization_score (0–1):
  ≥0.85 — captures a clearly reusable PRD-review heuristic.
  0.70–0.85 — reusable but borderline; risk of overfitting to recent PRDs.
  <0.70 — too specific to be a skill. The orchestrator drops these.
"""


# ---- Schema ---------------------------------------------------------------


class SkillProposal(BaseModel):
    """A candidate skill awaiting human review."""

    proposal_id: str
    proposed_name: str
    proposed_skill_md: str
    injected_into: list[str]
    generalization_score: float
    evidence: list[dict] = Field(default_factory=list)
    pattern_frequency: int  # number of distinct PRDs the pattern was seen in
    created_at: str
    status: Literal["pending", "approved", "rejected", "edited"] = "pending"
    rejection_reason: str | None = None


# ---- Public entry point ---------------------------------------------------


async def run_distiller(
    llm: LLMProvider,
    history_store: HistoryStore,
    min_pattern_frequency: int = DEFAULT_MIN_PATTERN_FREQUENCY,
    min_runs_required: int = DEFAULT_MIN_RUNS_REQUIRED,
) -> list[SkillProposal]:
    """Return zero-or-more `SkillProposal`s mined from PRD-review history.

    Empty list is an OK answer — short history, no clusters that cleared
    threshold, or every proposal failed validation. The caller (UI / cron)
    decides what to do with an empty result.
    """
    miss_runs = history_store.query(only_misses=True)
    total_runs = len(history_store.list_recent(n=10_000))
    if total_runs < min_runs_required:
        logger.warning(
            "skill_distiller: only %d run(s) in history (< %d required); skipping.",
            total_runs,
            min_runs_required,
        )
        return []

    clusters = _cluster_misses(miss_runs, min_pattern_frequency=min_pattern_frequency)
    if not clusters:
        logger.info("skill_distiller: no clusters cleared frequency threshold.")
        return []

    proposals: list[SkillProposal] = []
    for cluster in clusters:
        proposal = await _draft_proposal(llm, cluster)
        if proposal is None:
            continue
        if not _validate_proposal(proposal):
            continue
        proposals.append(proposal)
    return proposals


# ---- Clustering ------------------------------------------------------------


def _cluster_misses(
    miss_runs,
    *,
    min_pattern_frequency: int,
) -> list[dict]:
    """Build clusters from runs containing skill_id=None critiques.

    Returns a list of dicts shaped:
      {
        "critic_id": str,
        "evidence": [{"run_id": str, "critique_excerpt": str}, ...],
        "pattern_frequency": int,        # distinct run_ids
        "exemplar_finding": str,         # representative critique text
        "exemplar_runs": list[str],      # for the LLM prompt
      }
    """
    # Flatten: per-critic_id list of (run_id, critique).
    by_critic: dict[str, list[tuple[str, dict]]] = {}
    for run in miss_runs:
        for crit in run.critiques:
            if crit.get("skill_id"):
                continue
            critic_id = crit.get("critic_id") or "unknown"
            by_critic.setdefault(critic_id, []).append((run.run_id, crit))

    clusters: list[dict] = []
    for critic_id, items in by_critic.items():
        clusters.extend(
            _cluster_within_critic(critic_id, items, min_pattern_frequency)
        )
    return clusters


def _cluster_within_critic(
    critic_id: str,
    items: list[tuple[str, dict]],
    min_pattern_frequency: int,
) -> list[dict]:
    """Greedy single-pass clustering by SequenceMatcher similarity."""
    clusters: list[list[tuple[str, dict]]] = []
    for run_id, crit in items:
        finding = (crit.get("finding") or "").strip()
        if not finding:
            continue
        placed = False
        for cluster in clusters:
            ref_finding = (cluster[0][1].get("finding") or "").strip()
            ratio = SequenceMatcher(None, finding.lower(), ref_finding.lower()).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                cluster.append((run_id, crit))
                placed = True
                break
        if not placed:
            clusters.append([(run_id, crit)])

    out: list[dict] = []
    for cluster in clusters:
        distinct_runs = {run_id for run_id, _ in cluster}
        if len(distinct_runs) < min_pattern_frequency:
            continue
        evidence = [
            {
                "run_id": run_id,
                "critique_excerpt": _excerpt(crit),
            }
            for run_id, crit in cluster
        ]
        # Pick the longest finding as the exemplar — usually richest signal.
        exemplar_finding = max(
            (c.get("finding") or "" for _, c in cluster),
            key=len,
            default="",
        )
        out.append(
            {
                "critic_id": critic_id,
                "evidence": evidence,
                "pattern_frequency": len(distinct_runs),
                "exemplar_finding": exemplar_finding,
                "exemplar_runs": sorted(distinct_runs),
            }
        )
    return out


def _excerpt(crit: dict) -> str:
    """Compact one-line representation of a critique for evidence rows."""
    severity = crit.get("severity", "?")
    finding = (crit.get("finding") or "").strip()
    if len(finding) > 200:
        finding = finding[:197] + "…"
    return f"[{severity}] {finding}"


# ---- LLM call --------------------------------------------------------------


async def _draft_proposal(llm: LLMProvider, cluster: dict) -> SkillProposal | None:
    """Ask the LLM for one proposal per cluster. Returns None on parse failure."""
    user_msg = _format_cluster_for_llm(cluster)
    try:
        resp = await llm.complete(
            system=SKILL_DISTILLATION_SYSTEM_PROMPT,
            user=user_msg,
            temperature=0.5,
        )
        raw = extract_json(resp.text)
    except Exception as e:  # noqa: BLE001
        logger.warning("skill_distiller: LLM call/parse failed: %s", e)
        return None

    if not isinstance(raw, dict):
        logger.warning("skill_distiller: model returned non-dict: %r", raw)
        return None

    proposed_name = (raw.get("proposed_name") or "").strip()
    proposed_md = raw.get("proposed_skill_md") or ""
    injected_into = raw.get("injected_into") or [cluster["critic_id"]]
    score = float(raw.get("generalization_score", 0.0) or 0.0)

    return SkillProposal(
        proposal_id=uuid.uuid4().hex,
        proposed_name=proposed_name,
        proposed_skill_md=proposed_md,
        injected_into=list(injected_into),
        generalization_score=score,
        evidence=cluster["evidence"],
        pattern_frequency=cluster["pattern_frequency"],
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _format_cluster_for_llm(cluster: dict) -> str:
    """Render the cluster into a structured prompt the LLM can reason over."""
    lines = [
        f"<cluster critic_id=\"{cluster['critic_id']}\" "
        f"pattern_frequency=\"{cluster['pattern_frequency']}\">",
        f"<exemplar_finding>{cluster['exemplar_finding']}</exemplar_finding>",
        "<evidence>",
    ]
    for ev in cluster["evidence"]:
        lines.append(
            f'  <row run_id="{ev["run_id"]}">{ev["critique_excerpt"]}</row>'
        )
    lines.append("</evidence>")
    lines.append("</cluster>")
    lines.append("")
    lines.append(
        "Propose ONE skill. Output valid JSON only — no commentary, no fences."
    )
    return "\n".join(lines)


# ---- Validation ------------------------------------------------------------


def _validate_proposal(proposal: SkillProposal) -> bool:
    """Drop proposals whose evidence/score/SKILL.md fail spec compliance.

    Logs the reason and returns False on the first failure. Side-effect:
    stamps `rejection_reason` on the proposal so the UI can show why a
    proposal would have been auto-dropped (helpful for debugging the
    distiller, not used in the happy path).
    """
    if proposal.generalization_score < GENERALIZATION_THRESHOLD:
        proposal.rejection_reason = (
            f"generalization_score {proposal.generalization_score:.2f} "
            f"< {GENERALIZATION_THRESHOLD}"
        )
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    if not proposal.evidence or len(proposal.evidence) < 3:
        proposal.rejection_reason = "evidence list has fewer than 3 rows"
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    for ev in proposal.evidence:
        if not isinstance(ev, dict) or "run_id" not in ev:
            proposal.rejection_reason = "evidence rows missing run_id"
            logger.info("skill_distiller: %s", proposal.rejection_reason)
            return False

    if not KEBAB_RE.match(proposal.proposed_name):
        proposal.rejection_reason = (
            f"proposed_name {proposal.proposed_name!r} is not kebab-case"
        )
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    bad_routes = set(proposal.injected_into) - ALLOWED_CRITICS
    if bad_routes or not proposal.injected_into:
        proposal.rejection_reason = f"injected_into invalid: {proposal.injected_into}"
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    # Frontmatter / body shape must match the Day-8.5 spec or the retriever
    # will refuse to load the promoted skill.
    try:
        fm, body = parse_skill_md(proposal.proposed_skill_md)
    except Exception as e:  # noqa: BLE001
        proposal.rejection_reason = f"SKILL.md unparseable: {e}"
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    for required in ("name", "description", "version", "created_by", "injected_into"):
        if required not in fm:
            proposal.rejection_reason = (
                f"SKILL.md frontmatter missing required field: {required}"
            )
            logger.info("skill_distiller: %s", proposal.rejection_reason)
            return False

    if fm.get("created_by") != "distiller":
        proposal.rejection_reason = "frontmatter created_by must be 'distiller'"
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    if fm.get("name") != proposal.proposed_name:
        proposal.rejection_reason = (
            f"frontmatter name {fm.get('name')!r} != proposed_name "
            f"{proposal.proposed_name!r}"
        )
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    if not body.strip():
        proposal.rejection_reason = "SKILL.md body is empty"
        logger.info("skill_distiller: %s", proposal.rejection_reason)
        return False

    return True
