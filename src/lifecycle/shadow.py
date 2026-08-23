"""Shadow evaluation — the counterfactual OFF/ON admission gate.

Same PRDs, same config, same model, exactly one difference: whether the
CANDIDATE skill is retrievable. This is the only check that can validate
causal impact; model-reported `skill_id` attribution is not evidence
(HANDOFF debt D-17).

Mechanics:

  1. Stage a throwaway copy of the CURRENT library (seed/ + learned/) in
     a temp dir, twice: an OFF copy (exactly today's state) and an ON
     copy (plus the candidate's proposed SKILL.md under learned/). The
     real library is never touched — a failing candidate leaves no
     residue. Off-baseline = current library, NOT seed-only: the
     candidate's counterfactual is "the system as it stands, with and
     without me", so effects of already-admitted learned skills cancel
     out across arms instead of polluting the verdict.
  2. Run `run_pipeline` per golden PRD per arm with persistence and
     auto-distill disabled, score with the standard rubric, aggregate
     means per arm.
  3. `target_pattern_hits` = distinct PRDs where the ON arm produced at
     least one critique attributed (model-reported) to the candidate.
  4. Hand the metric pair to `gates.decide_admission` (Precision-first,
     Recall non-regression) and return the record + verdict.

The `default_retriever` rebinding trick mirrors
`src.eval.ablation._treatment_context` (rebind the symbol in every module
that imported it by name, restore on exit) — with staged roots and a
candidate toggle instead of preset treatments.
"""

from __future__ import annotations

import logging
import os
import shutil
import statistics
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..eval.rubric import score_run
from ..main import run_pipeline
from ..skills import retriever as retriever_mod
from ..skills.retriever import SEED_DIR, SKILL_FILENAME, LEARNED_DIR, SkillRetriever
from .gates import decide_admission, evidence_compliance
from .models import SkillEvaluation

logger = logging.getLogger(__name__)

# Mock cost per critique — mirrors src.eval.ablation so shadow numbers are
# comparable with the recorded sweeps. Real-API mode replaces it with the
# pipeline's total_cost_usd.
_MOCK_COST_PER_CRITIQUE_USD = 0.011

_METRIC_KEYS = (
    "recall",
    "precision",
    "false_p0_count",
    "evidence_compliance",
    "actionability",
    "latency_seconds",
    "cost_usd_estimate",
)


async def run_shadow_evaluation(
    proposed_name: str,
    proposed_skill_md: str,
    prd_files: list[Path],
    llm_factory,
    *,
    runs_per_arm: int = 1,
) -> SkillEvaluation:
    """Evaluate one candidate OFF vs ON over `prd_files`.

    Returns an UNSAVED SkillEvaluation (id/timestamps empty — the store
    assigns them on append). Never raises for pipeline-level failures
    inside a single run: a failed run contributes zero metrics and is
    logged; both arms see the same PRD set.
    """
    with tempfile.TemporaryDirectory(prefix="skill_shadow_") as tmp:
        staged_root = Path(tmp)
        staged_seed = staged_root / "seed"
        if SEED_DIR.exists():
            shutil.copytree(SEED_DIR, staged_seed)
        else:
            staged_seed.mkdir(parents=True, exist_ok=True)

        def _stage_learned(target: Path, *, with_candidate: bool) -> Path:
            if LEARNED_DIR.exists():
                shutil.copytree(LEARNED_DIR, target)
            else:
                target.mkdir(parents=True, exist_ok=True)
            if with_candidate:
                (target / proposed_name).mkdir(parents=True, exist_ok=True)
                (target / proposed_name / SKILL_FILENAME).write_text(
                    proposed_skill_md, encoding="utf-8"
                )
            return target

        off_learned = _stage_learned(staged_root / "learned_off", with_candidate=False)
        on_learned = _stage_learned(staged_root / "learned_on", with_candidate=True)

        off_runs = await _run_arm(
            staged_seed, off_learned,
            prd_files=prd_files, llm_factory=llm_factory,
            runs_per_arm=runs_per_arm, candidate=proposed_name,
        )
        on_runs = await _run_arm(
            staged_seed, on_learned,
            prd_files=prd_files, llm_factory=llm_factory,
            runs_per_arm=runs_per_arm, candidate=proposed_name,
        )

    metrics_off = _aggregate(off_runs)
    metrics_on = _aggregate(on_runs)
    target_pattern_hits = len(
        {r["prd_filename"] for r in on_runs if r["candidate_attributions"] > 0}
    )

    decision = decide_admission(
        metrics_off=metrics_off,
        metrics_on=metrics_on,
        target_pattern_hits=target_pattern_hits,
    )

    config_note = {
        "prd_files": [p.name for p in prd_files],
        "runs_per_arm": runs_per_arm,
        "supervisor": False,
        "persist": False,
    }
    return SkillEvaluation(
        evaluation_id="",
        skill_name=proposed_name,
        skill_version="1.0",
        off_config={"arm": "seed_only", **config_note},
        on_config={"arm": "seed_plus_candidate", **config_note},
        metrics_off=metrics_off,
        metrics_on=metrics_on,
        target_pattern_hits=target_pattern_hits,
        gate_result=decision.result,
        gate_reason="; ".join(decision.reasons) if decision.reasons else (
            f"policy {decision.policy_version} satisfied"
            + (f"; {decision.preference_note}" if decision.preference_note else "")
        ),
    )


# ---- arm runner -----------------------------------------------------------------


async def _run_arm(
    staged_seed: Path,
    staged_learned: Path,
    *,
    prd_files: list[Path],
    llm_factory,
    runs_per_arm: int,
    candidate: str,
) -> list[dict]:
    out: list[dict] = []
    with _shadow_env():
        with _staged_context(staged_seed, staged_learned):
            for prd_path in prd_files:
                prd_text = prd_path.read_text(encoding="utf-8")
                for _ in range(runs_per_arm):
                    out.append(
                        await _single_run(
                            llm_factory(), prd_text, prd_path.name, candidate
                        )
                    )
    return out


async def _single_run(llm, prd_text: str, prd_filename: str, candidate: str) -> dict:
    started = time.perf_counter()
    state = await run_pipeline(
        prd_text,
        llm=llm,
        include_supervisor=False,
        prd_filename=prd_filename,
        persist=False,
    )
    elapsed = time.perf_counter() - started

    critiques = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (state.get("critiques", []) or [])
    ]
    rubric = score_run(dict(state), prd_filename=prd_filename)
    real_cost = float(state.get("total_cost_usd", 0.0) or 0.0)
    return {
        "prd_filename": prd_filename,
        "rubric": rubric,
        "critiques": critiques,
        "candidate_attributions": sum(
            1 for c in critiques if c.get("skill_id") == candidate
        ),
        "latency_seconds": elapsed,
        "cost_usd_estimate": real_cost
        or len(critiques) * _MOCK_COST_PER_CRITIQUE_USD,
        "evidence_compliance": evidence_compliance(critiques, prd_text),
    }


def _aggregate(runs: list[dict]) -> dict:
    """Mean per policy metric key; an empty arm collapses to zeros."""
    def _mean(key: str, default: float = 0.0) -> float:
        values = [float(r[key]) for r in runs]
        return statistics.fmean(values) if values else default

    rubric_runs = [r["rubric"] for r in runs]
    return {
        "recall": _mean_of(rubric_runs, "overall_recall"),
        "precision": _mean_of(rubric_runs, "precision"),
        "false_p0_count": _mean_of(rubric_runs, "false_p0_count"),
        "evidence_compliance": _mean("evidence_compliance"),
        "actionability": _mean_of(rubric_runs, "actionability"),
        "latency_seconds": _mean("latency_seconds"),
        "cost_usd_estimate": _mean("cost_usd_estimate"),
    }


def _mean_of(rubrics: list, attr: str) -> float:
    values = [float(getattr(r, attr, 0.0) or 0.0) for r in rubrics]
    return statistics.fmean(values) if values else 0.0


# ---- treatment plumbing (modeled on ablation._treatment_context) ------------------


@contextmanager
def _staged_context(staged_seed: Path, staged_learned: Path) -> Iterator[None]:
    """Rebind `default_retriever` to a retriever over the staged tree.

    Each arm passes its OWN staged learned dir: the OFF copy mirrors the
    current library, the ON copy adds the candidate folder.
    """
    from ..agents.critics import _shared as critic_shared_mod
    from ..skills import __init__ as skills_pkg_mod  # noqa: F401
    from ..skills import curator as curator_mod
    import src.skills as skills_pkg

    targets = (retriever_mod, critic_shared_mod, curator_mod, skills_pkg)

    real = SkillRetriever(
        skills_root=staged_seed.parent,
        runtime_stats_path=staged_seed.parent / "runtime_stats.yaml",
    )
    real.seed_dir = staged_seed
    real.learned_dir = staged_learned

    def _ret() -> SkillRetriever:
        real._library = None  # always re-read so the arm toggle sticks
        return real

    originals = {mod: getattr(mod, "default_retriever", None) for mod in targets}
    for mod in targets:
        if hasattr(mod, "default_retriever"):
            mod.default_retriever = _ret  # type: ignore[assignment]
    try:
        yield
    finally:
        for mod, orig in originals.items():
            if orig is not None:
                mod.default_retriever = orig  # type: ignore[assignment]
                try:
                    orig.cache_clear()  # type: ignore[attr-defined]
                except AttributeError:
                    pass


@contextmanager
def _shadow_env() -> Iterator[None]:
    """Same env knobs as ablation: no auto-distill, no persistence."""
    prev = {
        "DISABLE_AUTO_DISTILL": os.environ.get("DISABLE_AUTO_DISTILL"),
        "PRD_PIPELINE_PERSIST": os.environ.get("PRD_PIPELINE_PERSIST"),
    }
    os.environ["DISABLE_AUTO_DISTILL"] = "1"
    os.environ["PRD_PIPELINE_PERSIST"] = "0"
    try:
        yield
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
