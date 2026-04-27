"""CLI entry: `python -m src.eval.ablation` (or `python -m src.eval`).

Examples:

    # Quick smoke run — 1 repeat per cell, all 5 PRDs, all 3 treatments.
    python -m src.eval --quick

    # Full sweep, 3 repeats per cell.
    python -m src.eval --runs-per-treatment 3

    # Two treatments only.
    python -m src.eval --treatments skill_off,skill_seed_plus_learned
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .ablation import (
    DEFAULT_OUTPUT_DIR,
    AblationConfig,
    list_golden_prds,
    run_ablation,
)


_AVAILABLE_TREATMENTS = (
    "skill_off",
    "skill_seed_only",
    "skill_seed_plus_learned",
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.eval")
    parser.add_argument(
        "--prd-files",
        nargs="*",
        default=None,
        help="Specific PRD paths. Defaults to all golden PRDs.",
    )
    parser.add_argument(
        "--treatments",
        default=",".join(_AVAILABLE_TREATMENTS),
        help=f"Comma-separated treatment presets. Available: {','.join(_AVAILABLE_TREATMENTS)}",
    )
    parser.add_argument("--runs-per-treatment", type=int, default=3)
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to write report"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="One repeat per (treatment, PRD) cell. Wall-clock ≤1 minute.",
    )
    args = parser.parse_args()

    treatments = [
        AblationConfig.preset(name)
        for name in (t.strip() for t in args.treatments.split(",") if t.strip())
    ]

    prd_paths = (
        [Path(p) for p in args.prd_files]
        if args.prd_files
        else list_golden_prds()
    )

    runs = 1 if args.quick else args.runs_per_treatment
    print(
        f"Ablation sweep: {len(prd_paths)} PRD(s) × {len(treatments)} treatment(s) "
        f"× {runs} run(s) = {len(prd_paths) * len(treatments) * runs} total runs"
    )

    report = asyncio.run(
        run_ablation(
            prd_files=prd_paths,
            treatments=treatments,
            output_dir=Path(args.output_dir),
            runs_per_treatment=runs,
        )
    )

    print()
    print(f"Report written to {args.output_dir}/ablation_*_report.md")
    print(f"JSON record:      {args.output_dir}/latest.json")
    print()
    print("Headline (mean overall_recall per treatment):")
    for tname in report.treatments:
        recall = report.aggregated.get(tname, {}).get("overall_recall_mean", 0.0)
        precision = report.aggregated.get(tname, {}).get("precision_mean", 0.0)
        print(f"  {tname:<28} recall={recall:.2f}  precision={precision:.2f}")


if __name__ == "__main__":
    main()
