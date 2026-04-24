# PRD-004: Internal Growth Dashboard

## Problem
PMs currently run ad-hoc SQL to answer the same weekly growth questions: DAU, new
signups, feature adoption. This wastes ~3 hours per PM per week and answers often
disagree across PMs due to inconsistent queries.

## Solution
Build an internal "Growth Dashboard" web app with pre-built charts for DAU, WAU, MAU,
new signups, and per-feature adoption funnels. Data is surfaced in near real-time so
PMs can monitor launches as they roll out.
<!-- DEFECT #1 [P2, scope_ambiguity]: "Near real-time" is undefined — seconds, minutes, or hours of lag? Eng and PM will interpret this differently and build / expect different systems. -->

## UX
- Left nav listing metric groups.
- Each chart supports date-range selection and segment filter.
- Export to CSV.

## Requirements
- Internal-only, SSO-gated.
- Queries run against our event warehouse and our application Postgres replica.
<!-- DEFECT #2 [P1, dependency_identification]: The PRD names the event warehouse and Postgres replica but growth funnels also require the CRM data (Salesforce) to attribute paid signups. That third data source is not listed as a dependency. -->

## Metrics
- Adopted by PMs.
<!-- DEFECT #3 [P2, metric_quality]: "Adopted by PMs" has no measurement method — weekly active PM users? logged-in PMs? PMs who created a saved view? No baseline, no target, no window. -->

## Launch
- Internal launch on Day 1, no external exposure.
<!-- DEFECT #4 [P1, risk_management]: The dashboard reads production user event data; no mention of PII review, data-retention for the dashboard cache, or access-audit logging. Without these, the internal-only claim is a policy statement, not an enforced control. -->

## Dependencies
- Event warehouse.
- Application Postgres read replica.
- SSO provider.
