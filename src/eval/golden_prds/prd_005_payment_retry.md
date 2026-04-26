# PRD-005: Failed-Payment Retry

## Problem
~8% of recurring subscription charges fail on first attempt. Many are transient
(issuer soft-decline, network timeout) and would succeed on retry. Today we cancel
the subscription on first failure, losing revenue and churning recoverable users.

## Solution
When a recurring charge fails, enqueue it for retry. Retry up to 3 times spaced over
24 hours. If all retries fail, then cancel the subscription as today. Notify the user
**immediately** of each failure via email.
<!-- DEFECT #1 [P0, internal_contradiction]: Solution says "Retry up to 3 times spaced over 24 hours" — so the outcome is not known for up to 24h — yet says users are notified "immediately" of each failure. Immediate notification of a soft-decline that will silently succeed on retry will alarm users and drive support volume. The two behaviors conflict. -->

## UX
- User receives email on each failed attempt.
- Account billing page shows a "payment retrying" state.
- After final failure, user sees a "subscription cancelled" state and a "Re-subscribe" link.

## Requirements
- Retry only "retryable" failures. Non-retryable failures (e.g. fraud) go straight
  to cancellation.
<!-- DEFECT #2 [P2, scope_ambiguity]: "Retryable failures" is undefined — which decline codes are retryable? This is critical: retrying `do_not_honor` is fine, retrying `stolen_card` is a compliance issue. The PRD punts. -->

## Metrics
- Recover 15% of previously-cancelled failed payments.
<!-- DEFECT #3 [P1, metric_quality]: "15% of previously-cancelled" — the baseline denominator is stated, the measurement window is missing, and so is a statistical significance threshold and a guardrail metric (e.g. chargeback rate) that would catch us over-retrying genuinely bad cards. -->

## Launch
- Roll out to 100% of subscriptions on launch day.
<!-- DEFECT #4 [P0, risk_management]: No circuit breaker for the case where the payment processor itself is degraded. Under a Stripe partial outage the retry queue will saturate, every retry will fail, and we will blast users with failure emails. No kill switch, no batch pause, no backoff strategy mentioned. -->

## Dependencies
- Payment processor (Stripe).
- Transactional email service.
- Subscription billing service.
<!-- DEFECT #5 [P0, dependency_identification]: Stripe integration requires an idempotency key on retry to avoid double-charging; not specified. Card network retry rules (e.g. Visa's VAU / RS1 reason-code limits) also constrain retry timing; not mentioned. Webhook failure handling for the retry outcome is not specified either. -->
