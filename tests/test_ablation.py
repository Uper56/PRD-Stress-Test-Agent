"""Tests for the Day-10 ablation runner + rubric."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.eval.ablation import (
    AblationConfig,
    AblationReport,
    list_golden_prds,
    render_markdown_report,
    run_ablation,
)
from src.eval.rubric import (
    RubricScore,
    score_actionability,
    score_run,
    score_structure_compliance,
)
from src.llm.mock_provider import MockProvider


# ---- Rubric --------------------------------------------------------------


def test_score_run_picks_up_golden_defects() -> None:
    """score_run on the canned MockProvider critiques against a real golden
    PRD's manifest entry must produce non-zero recall."""

    async def _go():
        from src.main import run_pipeline

        prd_path = Path("src/eval/golden_prds/prd_001_ai_support_widget.md")
        state = await run_pipeline(
            prd_path.read_text(encoding="utf-8"),
            llm=MockProvider(),
            prd_filename=prd_path.name,
            persist=False,
        )
        return state

    state = asyncio.run(_go())
    score = score_run(dict(state), prd_filename="prd_001_ai_support_widget.md")
    assert isinstance(score, RubricScore)
    assert score.overall_recall > 0, (
        f"expected at least one matched defect, got recall={score.overall_recall}"
    )
    assert score.matched_defect_ids, "expected matched defect ids on a known PRD"


def test_score_structure_compliance_handles_empty_and_malformed() -> None:
    assert score_structure_compliance([]) == 0.0
    assert score_structure_compliance([{"not": "a critique"}]) == 0.0


def test_actionability_requires_imperative_and_length() -> None:
    good = [{"suggested_fix": "Add a staged rollout 1% to 100% with named thresholds"}]
    bad_short = [{"suggested_fix": "fix it"}]
    bad_no_verb = [{"suggested_fix": "this is a long sentence without imperatives"}]
    assert score_actionability(good) == 1.0
    assert score_actionability(bad_short) == 0.0
    assert score_actionability(bad_no_verb) == 0.0


# ---- Ablation runner ------------------------------------------------------


def test_run_ablation_executes_full_grid_and_persists(tmp_path: Path) -> None:
    """2 treatments × 2 PRDs × 1 run = 4 runs. The report JSON must round-trip
    via AblationReport.model_validate, and a `latest.json` mirror must exist."""
    prds = list_golden_prds()[:2]
    treatments = [
        AblationConfig.preset("skill_off"),
        AblationConfig.preset("skill_seed_only"),
    ]
    report = asyncio.run(
        run_ablation(
            prd_files=prds,
            treatments=treatments,
            output_dir=tmp_path,
            runs_per_treatment=1,
        )
    )
    assert isinstance(report, AblationReport)
    assert len(report.raw_runs) == 4
    assert set(report.aggregated.keys()) == {"skill_off", "skill_seed_only"}
    for cell in report.aggregated.values():
        assert cell, "aggregated metrics must be non-empty per treatment"
        assert "overall_recall_mean" in cell

    latest = tmp_path / "latest.json"
    assert latest.exists()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    AblationReport.model_validate(payload)  # re-hydrate

    # Markdown report exists and contains the metric labels.
    md_files = list(tmp_path.glob("ablation_*_report.md"))
    assert md_files, "markdown report not written"
    md = md_files[0].read_text(encoding="utf-8")
    assert "Headline Metrics" in md
    assert "Defect Recall" in md


def test_skill_off_vs_skill_on_recall_delta_is_visible(tmp_path: Path) -> None:
    """Under MockProvider the canned critic extras only fire when a
    `<retrieved_skills>` block is in the user message — so skill_seed_only
    MUST produce more critiques than skill_off, lifting recall measurably.
    """
    prds = list_golden_prds()[:2]
    treatments = [
        AblationConfig.preset("skill_off"),
        AblationConfig.preset("skill_seed_only"),
    ]
    report = asyncio.run(
        run_ablation(
            prd_files=prds,
            treatments=treatments,
            output_dir=tmp_path,
            runs_per_treatment=1,
        )
    )
    off = report.aggregated["skill_off"]["overall_recall_mean"]
    on = report.aggregated["skill_seed_only"]["overall_recall_mean"]
    assert on >= off + 0.05, (
        f"expected skill_on recall to lead by ≥0.05, got off={off:.2f} on={on:.2f}"
    )


def test_render_markdown_report_handles_single_treatment(tmp_path: Path) -> None:
    """A single-treatment report must still render (no Δ column blow-up)."""
    report = asyncio.run(
        run_ablation(
            prd_files=list_golden_prds()[:1],
            treatments=[AblationConfig.preset("skill_off")],
            output_dir=tmp_path,
            runs_per_treatment=1,
        )
    )
    md = render_markdown_report(report)
    assert "Headline Metrics" in md
    assert "skill_off" in md


def test_ablation_config_preset_unknown_raises() -> None:
    with pytest.raises(ValueError):
        AblationConfig.preset("bogus")
