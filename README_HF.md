---
title: PRD Stress Test
emoji: 📋
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
license: mit
---

# PRD Stress Test

Multi-agent PRD review with a **governed, self-evolving Skill library**.
Chinese-first product UX, full English toggle.

Four parallel critic agents (User Advocate / Engineering / Business / Design)
review a PRD, push back on each other's findings, and a Supervisor synthesises
a P0/P1/P2 verdict. A Skill Library (Anthropic `SKILL.md` spec) disciplines
every critic.

## What's new — Skill Lifecycle Center

The Skills page is now a lifecycle center with three views (Overview /
Proposals / Library) backed by SQLite governance records:

- **Immutable provenance** — lineage (proposal → PRD evidence → admission
  decision), per-run retrieval telemetry, counterfactual OFF/ON evaluations.
- **Four-gate admission** — spec, evidence (≥3 distinct PRDs, hash-deduped),
  novelty, and a shadow OFF/ON evaluation. An LLM can propose a skill but
  cannot approve one: approval is structurally impossible until every gate
  passes, and every gate run is persisted with its evaluator version.
- **Probation & rollback** — admissions start a probation window; a wrong P0,
  an evidence-compliance failure, or <40% recent acceptance automatically
  degrades the skill and stamps a rollback target. `SKILL.md` files are never
  deleted.

Honest evidence: the previously-approved learned skill (`non-happy-state-spec`)
fails the new admission policy **retroactively** (precision 0.394 → 0.347 on
the recorded ablation) — the governance that would have rejected it is exactly
what this release ships.

## About this Space

React SPA + FastAPI in one Docker container (the pixel-styled UI is the
product surface). Runs against `gpt-4o-mini` for both critics and supervisor.

**Demo quota**: 50 runs/day shared across all visitors · 5 runs/hour per IP.

See full README, ablation methodology, and source at:
https://github.com/Uper56/PRD-Stress-Test-Agent
