---
name: quantified-metrics
description: Use this skill EVERY TIME the PRD names a success metric, KPI, target percentage, OKR, or any numeric outcome claim. The PRD MUST state baseline + target + measurement window TOGETHER for each metric. Anything missing one of the three is unmeasurable and must be flagged P0. Apply aggressively — "improve retention" with no baseline is not a goal.
version: "1.0"
created_by: seed
injected_into:
  - business
trigger_keywords:
  - metric
  - kpi
  - success
  - deflect
  - reduce
  - increase
  - retention
  - conversion
  - adoption
  - north star
trigger_semantic: PRD states a success metric, KPI, or target percentage without specifying baseline, target, and measurement window together.
confidence: 0.9
---

# Skill: Quantified Metrics (Baseline / Target / Window)

## When to apply
The PRD names a success metric, KPI, target percentage, OKR, or any other
numeric outcome claim — examples: "deflect 40% of tickets", "grow DAU by
15%", "reduce p95 latency", "improve retention".

## Instruction
For every numeric success claim, verify that ALL THREE of the following are
stated in the PRD:

1. **Baseline** — what is the current value of this metric, measured how, as
   of when? A target without a baseline cannot be evaluated. "Reduce churn
   by 2pp" means nothing without today's churn figure.
2. **Target** — the desired value, stated as an absolute number or as a
   delta from the baseline. Both forms need units.
3. **Measurement window** — over what time period will the metric be
   computed? A 7-day window and a 90-day window on the same metric answer
   very different questions.

Additional quality checks:
- **Attribution model** — if the PRD claims the change CAUSED the metric
  shift, how will causation be isolated from seasonality, concurrent
  launches, or cohort effects?
- **Floor / ceiling** — is there a guardrail metric that must not regress?
  (e.g. "lift conversion without dropping NPS below X").
- **Anti-gaming** — could the metric be hit in a way that is technically
  correct but violates the spirit of the PRD? (e.g. "reduce ticket volume"
  gamed by hiding the help link).

If any of baseline / target / window is missing, emit a **P0** critique —
these are not measurable goals and cannot be held accountable to.

## Rationale
An unmeasurable metric is worse than no metric. Teams ship, claim success
based on any directionally-positive number, and the organization loses the
ability to evaluate which bets actually worked. This is the single most
common cause of "everything launched; nothing improved" retrospectives.

## Examples of issues this catches
- "Achieve 40% ticket deflection" — baseline volume unknown, window unstated.
- "Improve user satisfaction" — metric undefined, no window, no target.
- "Increase retention by 10%" — which retention curve? D1, D7, D30?
- "Reduce load time" — from what to what? measured on which devices?
- Launch succeeds on the target metric but tanks a paired guardrail metric
  that was never declared.
