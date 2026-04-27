# PRD Stress Test Agent

## Problem
PRDs often ship with blindspots across user, engineering, business, and design dimensions.
Single-reviewer feedback is inconsistent and lacks structured coverage.

## Solution
A multi-agent system that runs 4 parallel critic agents (User Advocate / Engineering /
Business / Design) over a PRD, with a Supervisor agent synthesizing a structured blindspot
report. A cross-PRD Skill Library — conformant to the Anthropic Agent Skills `SKILL.md`
spec, served via a custom MCP server — lets agents accumulate and reuse review heuristics
over time, and a Distiller agent learns new skills from review history under a
human-in-the-loop approval flow.

## Architecture
- **Critics**: 4 LangGraph nodes running in parallel; each returns severity-ranked findings.
- **Cross-Challenge**: critics push back on each other's findings for up to 2 rounds with
  difflib-based convergence detection.
- **Supervisor**: synthesises the merged critique stream into a P0/P1/P2 verdict.
- **Skill Library**: kebab-named SKILL.md folders under `src/skills/seed/` and
  `src/skills/learned/`, with runtime telemetry decoupled into `runtime_stats.yaml`.
- **Skill Distiller**: mines `data/results/history/` for repeating cross-PRD blindspots,
  proposes new skills via LLM (≥3-PRD evidence required), routed through HITL approval
  in the Streamlit UI.

## Ablation Study

Headline numbers from `python -m src.eval --quick` against the 5 golden PRDs (latest
report at `data/results/ablation/latest.json`):

| Metric            | skill_off | skill_seed_only | skill_seed_plus_learned | Δ (off→learned) |
|-------------------|-----------|-----------------|-------------------------|-----------------|
| Defect Recall     | 0.61      | 0.74            | 0.74                    | **+21%**        |
| Precision         | 0.70      | 0.42            | 0.41                    | −41%            |
| Avg Latency (s)   | 4.24      | 4.27            | 4.20                    | −1%             |
| Avg Cost ($)      | 0.044     | 0.088           | 0.090                   | +105%           |

**Read**: enabling skill retrieval lifts defect recall by ~21% (skills surface
additional defects the critics would otherwise miss) at the cost of more critiques per
run (which drives the precision drop and the cost increase). The `seed_only` →
`seed_plus_learned` step is flat under MockProvider because the lone learned skill
(`non-happy-state-spec`) covers a defect already partly caught by the seed library.

> Note: numbers are produced under MockProvider — they validate the ablation pipeline,
> not real-LLM behaviour. They will be updated with real data once the university OpenAI
> API key is wired up.

## Quickstart

```bash
pip install -e .
pip install -r requirements.txt
pytest tests/ -W error                            # full test suite
streamlit run src/ui/streamlit_app.py             # UI: stress-test + ablation tabs
python -m src.eval --quick                        # quick ablation (~1 min)
python -m src.mcp_servers.skill_server            # stdio MCP server
```

## Status
Days 1–10 shipped (scaffold → graph → critics → supervisor → cross-challenge →
HITL dialog → Skill Library + MCP → telemetry persistence → Anthropic SKILL.md spec
migration → Distiller + Curator + HITL approval → Ablation runner). LLM calls are
mocked; OpenAI provider lands when the school API key is available.

See [`HANDOFF.md`](./HANDOFF.md) for the full day-by-day progress and
[`docs/skill_format.md`](./docs/skill_format.md) for the SKILL.md spec mapping.
