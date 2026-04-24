# PRD-001: AI Support Widget

## Problem
Our support inbox is overloaded. Response SLA has slipped and CSAT is trending down.
Users want faster answers for common "where is my order" and "how do I return" questions.

## Solution
Embed an AI chat widget on every page of the storefront. The widget answers customer
questions using our help-center articles as context. The widget replaces the current
"Contact Support" form. Escalation to a human agent is not part of this launch —
the AI handles everything end-to-end.
<!-- DEFECT #1 [P0, risk_management]: No kill-switch, rollback, or phased rollout is defined. If the AI starts giving wrong refund info at 2am there is no way to disable it without a deploy. -->

## UX
- Floating bubble in bottom-right corner.
- Click → opens chat panel with a greeting.
- User types question → AI responds in ≤3 seconds.
- A "Talk to an agent" button is visible in the chat panel header for dissatisfied users.
<!-- DEFECT #2 [P0, internal_contradiction]: Solution section says "Escalation to a human agent is not part of this launch". UX section describes a "Talk to an agent" button. These directly contradict. -->
- Widget supports all major languages.
<!-- DEFECT #3 [P2, scope_ambiguity]: "all major languages" is undefined — no list, no fallback behavior for unsupported locales. -->

## Metrics
- **Ticket deflection**: deflect 40% of inbound tickets.
<!-- DEFECT #4 [P0, metric_quality]: No baseline (current ticket volume), no measurement window, no definition of "deflected". Cannot be evaluated. -->
- CSAT on AI conversations should be "good".

## Launch
- Ship to 100% of logged-in users on Day 1.

## Dependencies
- Help-center CMS (already in prod).
- Frontend widget library (to be built).
<!-- DEFECT #5 [P1, dependency_identification]: The LLM provider (OpenAI or similar) is not listed as a dependency, nor is its rate limit, cost model, data-retention policy, or PII handling addressed. -->
