# Skill: API Dependency Enumeration

## When to apply
The PRD mentions one or more third-party services, SDKs, webhooks, or external
APIs — examples: payments (Stripe, Adyen), auth (Auth0, OAuth), email/SMS
(SendGrid, Twilio), analytics (Segment, Amplitude), ML model providers (OpenAI,
Anthropic), or any service your team does not own end-to-end.

## Instruction to inject
When the PRD references any external service, you MUST check that each of the
following is addressed explicitly in the PRD:

1. **Full enumeration** — is every external dependency listed by name? A
   phrase like "integrate with payment providers" is incomplete; the PRD
   must name the provider(s).
2. **SLA assumption** — does the PRD state or implicitly assume an uptime /
   latency budget for each dependency? If the downstream SLA is tighter than
   the provider's, flag it as a P0/P1 risk.
3. **Failure mode** — what happens when the API returns 5xx, times out, or
   rate-limits? Is there a queue, retry policy, circuit breaker, or graceful
   degradation path? "We'll retry" is not a failure-mode plan.
4. **Idempotency** — for any write-side call (charge, send, mutate), is an
   idempotency key used so retries do not cause duplicate side effects?
5. **Cost exposure** — per-call pricing multiplied by worst-case traffic;
   is there a circuit breaker on cost itself?

If any of these are missing, emit a critique with severity:
- **P0** if the missing item is idempotency on a financial write or absence of
  failure handling on a launch-blocking path.
- **P1** for missing SLA assumptions or unnamed dependencies.
- **P2** for missing cost exposure analysis.

## Rationale
External dependencies are where PRDs silently absorb risk. The author usually
assumes "the API will be there" because it is today; production outages in the
first month of launch almost always trace back to a dependency the PRD did not
enumerate. Forcing per-dependency enumeration moves the failure mode from
"surprise in prod" to "explicit trade-off at planning time".

## Examples of issues this catches
- "Send confirmation emails" with no SendGrid fallback if SMTP outage.
- "Charge the card" with no idempotency key — retry doubles the charge.
- "We'll add webhooks later" — no signature verification, no retry budget.
- "Use OpenAI for summaries" with no rate-limit handling, no fallback model.
- LLM calls assumed at 100ms when p99 is 8s; entire request path starves.
