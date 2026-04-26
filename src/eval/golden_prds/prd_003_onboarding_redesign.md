# PRD-003: New-User Onboarding Redesign

## Problem
Our current onboarding has a high drop-off between sign-up and first meaningful action.
PMs have anecdotally observed that new users feel "lost" after landing in the empty
dashboard. We want to reduce drop-off and speed up activation.

## Solution
Replace the existing 2-step onboarding with a 5-step guided tour covering: profile
setup, workspace creation, teammate invite, first-project setup, and a product tour.
Each step has a skip link so users never feel forced.

## UX
- Full-bleed overlay on first login.
- Progress indicator at the top; each step can be skipped via a "Skip for now" link.
- Users can re-enter the tour later from Settings.
- Supported on mobile and web.
<!-- DEFECT #1 [P2, scope_ambiguity]: "Supported on mobile and web" — no parity spec. Does mobile get all 5 steps? Is the overlay adapted for small surfaces? Are skip-links identical? -->

## Requirements
- All 5 steps are enforced for new accounts created after launch.
<!-- DEFECT #2 [P1, internal_contradiction]: UX says each step has "Skip for now" and users "never feel forced". Requirements says all 5 steps are enforced. These conflict and engineering cannot implement both. -->
- Completion data must be logged per-step for analytics.

## Metrics
- Reduce drop-off from sign-up to first meaningful action.
<!-- DEFECT #3 [P1, metric_quality]: No current drop-off rate baseline cited, no target reduction number, no window. The metric is a direction, not a testable goal. -->
- Increase activation rate (not defined).

## Launch
- Enable for 100% of new signups on launch day.
<!-- DEFECT #4 [P1, risk_management]: No A/B test, no staged %-rollout, no rollback criteria. If the new flow performs worse than the old 2-step flow we have no way to detect it early or revert. -->

## Dependencies
- Analytics pipeline (already in prod).
- Auth / account creation service.
- Workspace service.
