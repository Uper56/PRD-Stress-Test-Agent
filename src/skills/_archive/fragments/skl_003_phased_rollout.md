# Skill: Phased Rollout / Gated Launch

## When to apply
The PRD describes a launch, release, rollout, or change that affects production
users — whether that's a new feature, a migration, a config flip, an ML
model swap, or a pricing change.

## Instruction to inject
For every launch described in the PRD, verify that the rollout plan covers:

1. **Staged ramp** — a concrete percentage ladder, e.g. `1% → 10% → 50% →
   100%`, with the duration of each stage and the criteria to advance.
   A single "launch day" with no ramp is a systems risk for anything
   touching write paths, payments, or ML.
2. **Rollback criteria** — explicit numeric thresholds that trigger a roll
   back (error rate > X%, latency p95 > Yms, revenue per user ≤ Z). "We'll
   watch the dashboard" is not a rollback criterion.
3. **Kill-switch ownership** — who has the authority and the tooling to
   flip the feature off? Is it a feature flag, config change, or code
   revert? What is the MTTR?
4. **Dogfooding / canary cohort** — who sees this first (employees?
   internal beta?) and for how long before external users?
5. **Bake time between stages** — minimum observation period at each
   percentage before advancing. Going 0→100 within the same hour defeats
   the purpose of staging.

Severity guidance:
- **P0** if launch touches payments, auth, or data-integrity paths and has
  no staging plan.
- **P1** if staging is mentioned but lacks rollback criteria or kill-switch
  owner.
- **P2** if only bake time or dogfooding cohort is missing.

## Rationale
"Day 1 100%" launches are where resumes are updated. A rollout ladder bounds
the blast radius of any single bug: a 1% exposure means a 1% maximum harm,
and you learn whether to advance or roll back with very few users affected.
Not every PRD needs six stages — but every PRD should state which stages
it is intentionally skipping and why.

## Examples of issues this catches
- "Ship to 100% of users on Day 1" — no ramp, no rollback criteria.
- "Gradual rollout" with no percentages, no durations, no thresholds.
- Staging mentioned but no named owner of the kill switch.
- ML model swap described as an atomic cutover with no shadow-mode period.
- Migration with no "new path on, old path off" overlap window.
