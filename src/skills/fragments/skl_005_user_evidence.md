# Skill: User Evidence Required

## When to apply
The PRD asserts a user need, pain, frustration, or behavioral claim — any
statement of the form "users want…", "users struggle with…", "customers
complain that…", "there is friction in…".

## Instruction to inject
For every user-pain claim, verify the PRD cites at least ONE concrete
evidence source:

1. **Quantitative** — analytics event, funnel drop-off, support-ticket
   volume, survey score, usage metric, retention curve. The source should
   be named (e.g. "Amplitude cohort X", "Zendesk tag Y").
2. **Qualitative** — user interview notes with sample size, usability
   test findings, sales/CS call patterns, written user feedback.
3. **External** — industry research, academic study, competitive analysis
   with citation.

Additional probes:
- **Representativeness** — is the cited evidence from the target user
  segment, or from a different cohort? A B2B PRD citing B2C analytics is
  hollow.
- **Recency** — is the evidence current? A pain observed in a flow that
  was redesigned 18 months ago may not exist anymore.
- **Magnitude** — does the evidence tell us how many users feel this
  pain, or just that "some" do? Without magnitude, severity is unclear.
- **Alternative explanations** — could the observed signal come from a
  different cause (e.g. an unrelated bug, a tracking gap, a seasonal
  effect)?

If the pain is asserted with no evidence, emit a **P0** critique — the
feature is being built on a hypothesis, not a validated problem.

## Rationale
The highest-cost PRD failure mode is solving a problem users do not have.
An unvalidated pain becomes an unused feature, and the team's credibility
is spent. Requiring citable evidence turns "we think users want this"
into "here is the signal we saw, here is the cohort, here is the size" —
which can be debated, replicated, and falsified.

## Examples of issues this catches
- "Users are frustrated with the current onboarding" — no tickets, no
  analytics, no interviews cited.
- "Customers want more filter options" — which customers? how many? based
  on what?
- Behavior-change claim ("users will adopt the new flow") with no
  precedent or analog cited.
- Persona descriptions written without ever having talked to one.
- Evidence cited but from a different user segment than the one being
  targeted.
