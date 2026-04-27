---
name: non-happy-state-spec
description: Use this skill ANY TIME the PRD specifies a UI flow without explicitly listing empty / loading / error / offline states. The non-happy states are where trust is built or broken — flag missing specs as P1 minimum.
version: "1.0"
created_by: distiller
injected_into:
  - design
trigger_keywords: [flow, screen, modal, list, table, error]
trigger_semantic: UI flow specified without enumerated non-happy states.
confidence: 0.74
---

# Skill: Non-Happy State Spec

## When to apply
The PRD specifies a UI flow without listing empty / loading / error / offline states.

## Instruction
For each surface, verify the four non-happy states are specified.

## Rationale
Non-happy states are where users build or lose trust.

## Examples of issues this catches
- New list with no empty state.
- Submit flow with no error toast spec.
- Mobile view with no offline behavior.
