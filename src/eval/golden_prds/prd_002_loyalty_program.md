# PRD-002: Storefront Loyalty Program

## Problem
Repeat purchase rate is low. Customer interviews report that buyers feel "no reason
to come back" after their first order. Competitors offer points programs; we don't.
<!-- DEFECT #1 [P0, internal_contradiction]: Problem cites that users "feel points are worthless at other retailers" in a companion research doc, yet the Solution below sets 1 point = $0.001 in redemption value, which preserves the exact pain point the PRD claims to address. -->

## Solution
Launch "StoreClub": every $1 spent earns 1 point. Points can be redeemed at checkout
at a rate of 1 point = $0.001 off the order total. Points expire after 12 months of
account inactivity. Existing customers are auto-enrolled.
<!-- DEFECT #2 [P1, risk_management]: No migration plan for the 2M existing customers: do they start at zero, or get backdated points from their order history? Not specified — will generate support tickets on day 1. -->

## UX
- Account page shows current point balance and redemption history.
- Checkout shows a "Redeem points" toggle.
- Email notifies users when they earn ≥500 points.

## Metrics
- Increase repeat purchase rate.
<!-- DEFECT #3 [P1, metric_quality]: No baseline repeat-purchase rate, no target number, no measurement window. Unscorable. -->
- Improve customer lifetime value.

## Launch
- Phased rollout.
<!-- DEFECT #4 [P2, scope_ambiguity]: "Phased rollout" is named with no definition — what percentage of users per phase, what criteria gate a phase, who decides? -->

## Dependencies
- Checkout service (for redemption).
- Account service (for point balance).
<!-- DEFECT #5 [P1, dependency_identification]: The transactional email service used to notify users at 500 points is not listed as a dependency. Neither is the analytics pipeline needed to measure the Metrics goals, nor the scheduled job / cron needed to implement the 12-month inactivity expiry. -->
