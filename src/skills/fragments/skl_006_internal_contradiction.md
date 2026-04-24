# Skill: Internal Contradiction Scan

## When to apply
Always — this is a cross-cutting skill every critic applies. It fires whenever
the PRD has multiple sections (Goals, Scope, Requirements, Timeline, Metrics,
Rollout) that could constrain each other.

## Instruction to inject
Before producing your role-specific critique, do a consistency pass across
the whole PRD for:

1. **Scope contradictions** — one section says "opt-in only", another says
   "all users get", "Phase 2 includes X" contradicted by "X is out of
   scope". Scope conflict = shipping delay.
2. **Timeline contradictions** — launch date stated in one section is
   incompatible with dependency-delivery dates in another (e.g. launch
   Q1 but depends on an API that ships Q2).
3. **Metric contradictions** — success metric in one section cannot be
   measured given the rollout plan in another (e.g. "30-day retention
   uplift" paired with a 2-week rollout window).
4. **SLA / scale contradictions** — stated user volume vs. stated
   infrastructure budget vs. stated latency SLA — do they mutually
   support each other?
5. **Constraint contradictions** — a privacy / compliance constraint
   stated in one section violated by a requirement in another (e.g.
   "no PII logged" vs. "log full request for debugging").
6. **Role / ownership contradictions** — "Team A owns X" in one place
   and "Team B delivers X" in another.

For each contradiction found, emit a critique that:
- Cites BOTH line references (e.g. `line 042` and `line 087`).
- States the contradiction in one sentence.
- Proposes which side to resolve in favor of, or flags the decision as
  requiring a PM ruling.

Severity guidance:
- **P0** if the contradiction makes the PRD un-shippable as written
  (scope, timeline, or compliance).
- **P1** if the contradiction is resolvable but will delay the project
  if not addressed pre-kickoff.
- **P2** for cosmetic contradictions (inconsistent terminology,
  conflicting-but-minor numbers).

## Rationale
PRDs are written incrementally over days or weeks; sections written at
different times by different contributors routinely disagree. Reviewers
reading top-to-bottom tend to miss these because each section feels
coherent in isolation. An explicit contradiction scan surfaces the cost
of incremental authorship before it becomes a cost in engineering rework.

## Examples of issues this catches
- Goals section: "opt-in beta". Rollout section: "all users on Day 1".
- Timeline: "Launch March 15". Dependencies: "New pricing API lands April 1".
- Metric: "measure 90-day retention uplift". Launch: "2-week A/B test".
- Requirement: "must work offline". Architecture: "server-side rendering only".
- Scope: "Phase 1: English only". Design spec: includes RTL language mockups.
