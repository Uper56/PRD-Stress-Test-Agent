# PRD Stress Test Agent

## Problem
PRDs often ship with blindspots across user, engineering, business, and design dimensions.
Single-reviewer feedback is inconsistent and lacks structured coverage.

## Solution
A multi-agent system that runs 4 parallel critic agents (User Advocate / Engineering /
Business / Design) over a PRD, with a Supervisor agent synthesizing a structured blindspot
report. A cross-PRD Skill Library — served via a custom MCP server — lets agents accumulate
and reuse review heuristics over time.

## Status
Scaffold only. No business logic implemented yet. LLM calls are mocked; OpenAI provider
will be added once the school API key is available.
