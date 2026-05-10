"""Ablation study runner — quantify the contribution of the Skill Library.

Compares N treatments (skill_off / skill_seed_only / skill_seed_plus_learned)
across the same set of PRDs, scores each run via `src.eval.rubric.score_run`,
aggregates per treatment, and writes both a JSON record and a human-readable
Markdown report under `data/results/ablation/`.

Treatment switching uses dependency injection on the `SkillRetriever`:
- `skill_retrieval_enabled=False` → a stub retriever returning `[]`.
- `skill_sources=["seed"]` → only `src/skills/seed/` is scanned.
- `skill_sources=["seed", "learned"]` → both `seed/` and `learned/`.

Auto-distill is force-disabled (`DISABLE_AUTO_DISTILL=1`) for the duration
of the sweep so each PRD run is independent. History persistence is also
disabled (`PRD_PIPELINE_PERSIST=0`) — ablation runs shouldn't pollute the
HITL queue.

MockProvider numbers are pipeline validation only; rerun against the real
LLM for headline numbers (see HANDOFF debt D-12).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

from ..config import get_critic_llm
from ..llm.mock_provider import MockProvider
from ..llm.provider import LLMProvider
from ..main import run_pipeline
from ..skills import retriever as retriever_mod
from ..skills.retriever import SkillRetriever
from .rubric import RubricScore, score_run

logger = logging.getLogger(__name__)


DEFAULT_OUTPUT_DIR = Path("data") / "results" / "ablation"
DEFAULT_GOLDEN_DIR = Path(__file__).resolve().parent / "golden_prds"


# ---- Schema ----------------------------------------------------------------


class AblationConfig(BaseModel):
    """One treatment cell in the ablation grid."""

    treatment_name: str
    skill_retrieval_enabled: bool = True
    skill_sources: list[Literal["seed", "learned"]] = Field(
        default_factory=lambda: ["seed", "learned"]
    )

    @classmethod
    def preset(cls, name: str) -> "AblationConfig":
        """Convenience constructor for the named treatments."""
        if name == "skill_off":
            return cls(
                treatment_name="skill_off",
                skill_retrieval_enabled=False,
                skill_sources=[],
            )
        if name == "skill_seed_only":
            return cls(
                treatment_name="skill_seed_only",
                skill_retrieval_enabled=True,
                skill_sources=["seed"],
            )
        if name == "skill_seed_plus_learned":
            return cls(
                treatment_name="skill_seed_plus_learned",
                skill_retrieval_enabled=True,
                skill_sources=["seed", "learned"],
            )
        raise ValueError(f"Unknown ablation preset: {name!r}")


class AblationRunResult(BaseModel):
    """One completed run inside an ablation cell."""

    treatment: str
    prd_filename: str
    run_id: str
    metrics: dict[str, float] = Field(default_factory=dict)
    matched_defect_ids: list[str] = Field(default_factory=list)
    false_positive_count: int = 0
    critique_count: int = 0
    latency_seconds: float = 0.0
    cost_usd_estimate: float = 0.0
    state_summary: dict[str, Any] = Field(default_factory=dict)


class AblationReport(BaseModel):
    """Aggregated result across all (treatment × PRD × repeat) runs."""

    timestamp: str
    treatments: list[str]
    runs_per_treatment: int
    prds_used: list[str]
    aggregated: dict[str, dict[str, float]] = Field(default_factory=dict)
    delta: dict[str, dict[str, float]] = Field(default_factory=dict)
    raw_runs: list[AblationRunResult] = Field(default_factory=list)


# ---- Treatment switching ---------------------------------------------------


class _EmptyRetriever:
    """Drop-in retriever stub that always returns no skills.

    Used when `skill_retrieval_enabled=False`. We monkey-patch
    `src.skills.retriever.default_retriever` to return this instead of
    the real singleton, so every critic that asks for skills receives
    an empty list and the prompt never gets a `<retrieved_skills>` block.
    """

    def __init__(self) -> None:
        self._library = None  # mirrored attribute the curator pokes at

    def load_library(self):  # noqa: D401
        return _StubLibrary()

    def retrieve(self, *_args, **_kwargs):
        return []


class _StubLibrary:
    skills: list = []

    def by_id(self, _):
        return None

    def active(self) -> list:
        return []


@contextmanager
def _treatment_context(config: AblationConfig) -> Iterator[None]:
    """Apply the treatment by rebinding `default_retriever` everywhere it's
    been imported by name.

    Just patching `src.skills.retriever.default_retriever` is NOT enough
    because callers do `from ...skills import default_retriever` at
    module load — those copies of the name are bound to the original
    `lru_cache` wrapper. We rebind the symbol in every module that
    imported it, then restore on exit.
    """
    # Lazy imports so we don't add to module-load time when ablation isn't
    # being used. They do, however, register the symbol in each module's
    # globals — that's what makes the rebind effective.
    from ..agents.critics import _shared as critic_shared_mod
    from ..skills import __init__ as skills_pkg_mod  # noqa: F401
    from ..skills import curator as curator_mod
    import src.skills as skills_pkg

    targets = (
        retriever_mod,
        critic_shared_mod,
        curator_mod,
        skills_pkg,
    )

    if not config.skill_retrieval_enabled:
        stub = _EmptyRetriever()

        def _ret():
            return stub

    else:
        sources = set(config.skill_sources or [])
        real = SkillRetriever()
        real._library = None
        # Rebind source dirs on THIS instance only — leaves the real
        # singleton's view of the on-disk tree untouched.
        real.seed_dir = real.seed_dir if "seed" in sources else Path("/__nonexistent__")
        real.learned_dir = (
            real.learned_dir if "learned" in sources else Path("/__nonexistent__")
        )

        def _ret():
            real._library = None  # always re-read so per-call sources stick
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
def _ablation_env() -> Iterator[None]:
    """Force the env knobs the ablation requires for clean results."""
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


# ---- Cost estimate ---------------------------------------------------------


# Mock cost per critique — keeps the report column populated without
# pretending we have real token counts under MockProvider. Real-API mode
# replaces this with `total_cost_usd` from the GraphState.
_MOCK_COST_PER_CRITIQUE_USD = 0.011


# ---- Runner ----------------------------------------------------------------


async def run_ablation(
    prd_files: list[Path],
    treatments: list[AblationConfig],
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    runs_per_treatment: int = 1,
    *,
    llm_factory=None,
    progress=None,
) -> AblationReport:
    """Run the full ablation grid and persist the report.

    Args:
      prd_files: list of golden PRD paths to evaluate.
      treatments: list of AblationConfig — usually 2-3 cells.
      output_dir: where to write the JSON record + markdown report.
      runs_per_treatment: how many times to run EACH (treatment, PRD)
        pair. Mock numbers are deterministic so >1 just multiplies cost
        for no signal. Real-API mode benefits from 3+ for variance.
      llm_factory: callable returning a fresh LLMProvider per run. When
        omitted we honour the `LLM_PROVIDER` env var via `get_critic_llm()`
        — so flipping `.env` to `LLM_PROVIDER=openai` makes the ablation
        run against the real LLM with no code change. Tests still pin
        `MockProvider` explicitly.
      progress: optional `(done, total) -> None` callback for a UI bar.
    """
    factory = llm_factory or get_critic_llm
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runs: list[AblationRunResult] = []
    total_runs = len(treatments) * len(prd_files) * runs_per_treatment
    done = 0

    with _ablation_env():
        for treatment in treatments:
            with _treatment_context(treatment):
                for prd_path in prd_files:
                    prd_text = prd_path.read_text(encoding="utf-8")
                    for _ in range(runs_per_treatment):
                        result = await _single_run(
                            factory(), prd_text, prd_path.name, treatment.treatment_name
                        )
                        runs.append(result)
                        done += 1
                        if progress is not None:
                            try:
                                progress(done, total_runs)
                            except Exception:  # pragma: no cover
                                pass
                        else:
                            print(
                                f"  [{done:>3}/{total_runs}] {treatment.treatment_name:<25} "
                                f"{prd_path.name:<40} recall={result.metrics.get('overall_recall', 0):.2f}"
                            )

    aggregated = _aggregate(runs)
    delta = _compute_deltas(aggregated, [t.treatment_name for t in treatments])

    report = AblationReport(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        treatments=[t.treatment_name for t in treatments],
        runs_per_treatment=runs_per_treatment,
        prds_used=[p.name for p in prd_files],
        aggregated=aggregated,
        delta=delta,
        raw_runs=runs,
    )

    _persist(report, output_dir)
    return report


async def _single_run(
    llm: LLMProvider, prd_text: str, prd_filename: str, treatment_name: str
) -> AblationRunResult:
    started = time.perf_counter()
    state = await run_pipeline(
        prd_text,
        llm=llm,
        include_supervisor=True,
        prd_filename=prd_filename,
        persist=False,
    )
    elapsed = time.perf_counter() - started

    rubric = score_run(dict(state), prd_filename=prd_filename)
    critique_count = len(state.get("critiques", []) or [])
    metrics = {
        "structure_compliance": rubric.structure_compliance,
        "dependency_recall": rubric.dependency_recall,
        "contradiction_detection": rubric.contradiction_detection,
        "severity_classification_f1": rubric.severity_classification_f1,
        "actionability": rubric.actionability,
        "overall_recall": rubric.overall_recall,
        "precision": rubric.precision,
        "latency_seconds": elapsed,
        "cost_usd_estimate": critique_count * _MOCK_COST_PER_CRITIQUE_USD,
        "critique_count": float(critique_count),
        "false_positive_count": float(rubric.false_positive_count),
    }

    return AblationRunResult(
        treatment=treatment_name,
        prd_filename=prd_filename,
        run_id=uuid.uuid4().hex[:12],
        metrics=metrics,
        matched_defect_ids=rubric.matched_defect_ids,
        false_positive_count=rubric.false_positive_count,
        critique_count=critique_count,
        latency_seconds=elapsed,
        cost_usd_estimate=metrics["cost_usd_estimate"],
        state_summary={
            "challenge_round": state.get("challenge_round", 0),
            "convergence_signal": bool(state.get("convergence_signal", False)),
            "verdict_p0_count": len(
                (state.get("final_report") or {}).get("p0_blockers", []) or []
            ),
            "verdict_p1_count": len(
                (state.get("final_report") or {}).get("p1_concerns", []) or []
            ),
            "verdict_p2_count": len(
                (state.get("final_report") or {}).get("p2_suggestions", []) or []
            ),
        },
    )


# ---- Aggregation -----------------------------------------------------------


_HEADLINE_METRICS = (
    "overall_recall",
    "precision",
    "structure_compliance",
    "dependency_recall",
    "contradiction_detection",
    "severity_classification_f1",
    "actionability",
    "latency_seconds",
    "cost_usd_estimate",
    "critique_count",
    "false_positive_count",
)


def _aggregate(runs: list[AblationRunResult]) -> dict[str, dict[str, float]]:
    """Mean / std / min / max per (treatment, metric)."""
    by_treatment: dict[str, list[AblationRunResult]] = {}
    for r in runs:
        by_treatment.setdefault(r.treatment, []).append(r)

    out: dict[str, dict[str, float]] = {}
    for treatment, group in by_treatment.items():
        agg: dict[str, float] = {}
        for metric in _HEADLINE_METRICS:
            values = [
                float(r.metrics.get(metric, 0.0) or 0.0) for r in group
            ]
            if not values:
                continue
            agg[f"{metric}_mean"] = statistics.fmean(values)
            agg[f"{metric}_min"] = min(values)
            agg[f"{metric}_max"] = max(values)
            agg[f"{metric}_std"] = (
                statistics.pstdev(values) if len(values) > 1 else 0.0
            )
        out[treatment] = agg
    return out


def _compute_deltas(
    aggregated: dict[str, dict[str, float]], treatment_order: list[str]
) -> dict[str, dict[str, float]]:
    """Compute per-metric % delta of every other treatment vs the first.

    The first treatment in `treatment_order` is the baseline; for each
    other treatment we record `(other - baseline) / baseline` per
    headline metric. Baselines of 0 collapse to a flat 0.0 delta to
    avoid divide-by-zero artefacts.
    """
    if not treatment_order:
        return {}
    baseline = aggregated.get(treatment_order[0], {})
    out: dict[str, dict[str, float]] = {}
    for tname in treatment_order[1:]:
        cell = aggregated.get(tname, {})
        deltas: dict[str, float] = {}
        for metric in _HEADLINE_METRICS:
            base = baseline.get(f"{metric}_mean", 0.0)
            other = cell.get(f"{metric}_mean", 0.0)
            if base == 0:
                deltas[metric] = 0.0
            else:
                deltas[metric] = (other - base) / base
        out[tname] = deltas
    return out


# ---- Persistence + report --------------------------------------------------


def _persist(report: AblationReport, output_dir: Path) -> None:
    stamp = report.timestamp.replace(":", "").replace("-", "").replace("+0000", "Z")
    json_path = output_dir / f"ablation_{stamp}.json"
    md_path = output_dir / f"ablation_{stamp}_report.md"
    latest_json = output_dir / "latest.json"

    json_path.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    # `latest.json` symlink-style copy so the Streamlit page can always
    # find the most recent run without globbing.
    latest_json.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---- Markdown report -------------------------------------------------------


def render_markdown_report(report: AblationReport) -> str:
    """Build the human-readable report from an `AblationReport`."""
    lines: list[str] = []
    lines.append("# Ablation Study Report")
    lines.append("")
    lines.append(f"Generated: {report.timestamp}")
    lines.append(f"PRDs tested: {len(report.prds_used)}")
    lines.append(f"Treatments compared: {', '.join(report.treatments)}")
    lines.append(f"Runs per treatment: {report.runs_per_treatment}")
    lines.append("")
    lines.append("## Headline Metrics")
    lines.append("")
    lines.append(_render_headline_table(report))
    lines.append("")
    lines.append("## Trade-off Analysis")
    lines.append("")
    lines.append(_render_tradeoff_paragraph(report))
    lines.append("")
    lines.append("## Per-PRD Breakdown")
    lines.append("")
    lines.append(_render_per_prd_tables(report))
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Data source: MockProvider (pipeline validation only).")
    lines.append("- Difflib-based fuzzy matching at threshold 0.5; upgrade to embeddings is HANDOFF debt D-12.")
    lines.append("- TODO: rerun with the real LLM provider when the university API key arrives (HANDOFF debt D-12).")
    return "\n".join(lines)


def _render_headline_table(report: AblationReport) -> str:
    treatments = report.treatments
    rows = [
        ("Defect Recall", "overall_recall", "{:.2f}"),
        ("Precision", "precision", "{:.2f}"),
        ("Structure Compliance", "structure_compliance", "{:.2f}"),
        ("Dependency Recall", "dependency_recall", "{:.2f}"),
        ("Contradiction Detection", "contradiction_detection", "{:.2f}"),
        ("Severity F1", "severity_classification_f1", "{:.2f}"),
        ("Actionability", "actionability", "{:.2f}"),
        ("Avg Latency (s)", "latency_seconds", "{:.2f}"),
        ("Avg Cost ($)", "cost_usd_estimate", "{:.3f}"),
        ("Critiques per Run", "critique_count", "{:.1f}"),
    ]

    header = "| Metric | " + " | ".join(treatments) + " | Δ (first→last) |"
    sep = "|" + "|".join(["---"] * (len(treatments) + 2)) + "|"
    out = [header, sep]
    last = treatments[-1] if len(treatments) > 1 else treatments[0]
    for label, key, fmt in rows:
        cells = [
            fmt.format(report.aggregated.get(t, {}).get(f"{key}_mean", 0.0))
            for t in treatments
        ]
        if len(treatments) > 1:
            d = report.delta.get(last, {}).get(key, 0.0)
            delta = f"{d:+.0%}" if d != 0 else "—"
        else:
            delta = "—"
        out.append(f"| {label} | " + " | ".join(cells) + f" | {delta} |")
    return "\n".join(out)


def _render_tradeoff_paragraph(report: AblationReport) -> str:
    if len(report.treatments) < 2:
        return "_Single treatment — no trade-off to compare._"
    last = report.treatments[-1]
    first = report.treatments[0]
    d = report.delta.get(last, {})
    recall_delta = d.get("overall_recall", 0.0)
    precision_delta = d.get("precision", 0.0)
    latency_delta = d.get("latency_seconds", 0.0)
    cost_delta = d.get("cost_usd_estimate", 0.0)

    direction = (
        "improves" if recall_delta > 0
        else "regresses" if recall_delta < 0
        else "is unchanged"
    )
    return (
        f"Compared to the **{first}** baseline, the **{last}** treatment "
        f"{direction} defect recall by **{recall_delta:+.0%}** "
        f"(precision Δ {precision_delta:+.0%}). "
        f"Latency changes by {latency_delta:+.0%} and cost by {cost_delta:+.0%}. "
        "Under MockProvider these numbers reflect the additional canned "
        "critiques returned when a `<retrieved_skills>` block is present "
        "in the prompt — they validate the pipeline plumbing, not real-LLM "
        "behaviour."
    )


def _render_per_prd_tables(report: AblationReport) -> str:
    by_prd: dict[str, list[AblationRunResult]] = {}
    for r in report.raw_runs:
        by_prd.setdefault(r.prd_filename, []).append(r)
    out: list[str] = []
    for prd, runs in by_prd.items():
        out.append(f"### {prd}")
        out.append("")
        out.append("| Treatment | Recall | Precision | Critiques | Matched defects |")
        out.append("|---|---|---|---|---|")
        for r in runs:
            out.append(
                f"| {r.treatment} | "
                f"{r.metrics.get('overall_recall', 0):.2f} | "
                f"{r.metrics.get('precision', 0):.2f} | "
                f"{r.critique_count} | "
                f"{', '.join(r.matched_defect_ids) or '—'} |"
            )
        out.append("")
    return "\n".join(out)


# ---- Convenience -----------------------------------------------------------


def list_golden_prds(directory: Path | None = None) -> list[Path]:
    d = directory or DEFAULT_GOLDEN_DIR
    return sorted(d.glob("prd_*.md"))


def run_ablation_sync(*args, **kwargs) -> AblationReport:
    """Synchronous wrapper for callers that aren't in an event loop."""
    return asyncio.run(run_ablation(*args, **kwargs))
