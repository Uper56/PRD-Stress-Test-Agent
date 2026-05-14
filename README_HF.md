---
title: PRD Stress Test
emoji: 📋
colorFrom: blue
colorTo: purple
sdk: streamlit
sdk_version: 1.40.0
app_file: app.py
pinned: false
license: mit
---

# PRD Stress Test

Multi-agent PRD review with self-improving Skill library. Chinese-first product UX.

Four parallel critic agents (User Advocate / Engineering / Business / Design)
review a PRD, push back on each other's findings, and a Supervisor synthesises
a P0/P1/P2 verdict. A Skill Library (Anthropic `SKILL.md` spec) disciplines
every critic; a Distiller mines run-history for missed patterns and proposes
new skills under human approval.

This Space runs against `gpt-4o-mini` for both critics and the supervisor.

**Demo quota**: 50 runs/day shared across all visitors · 5 runs/hour per IP.

See full README, ablation methodology, and source at:
https://github.com/Uper56/PRD-Stress-Test-Agent
