# PRD Stress Test — Project Handoff

> Last updated: 2026-08-23 (post: Skill Lifecycle Center shipped)
>
> Current focus: the Skill Lifecycle Center is now **implemented** (backend,
> governance, three-view UI). Next focus: demo hardening around it and a
> re-run of the real-LLM ablation under the new admission gates.

## 1. Project Positioning

PRD Stress Test is a self-improving multi-agent system that reviews a PRD before formal review, exposes blind spots with evidence, and turns recurring misses across different PRDs into reusable `SKILL.md` review skills.

The interview narrative is deliberately ordered as:

1. **Product problem**: PRD reviews are inconsistent, reviewer-dependent, and weak at retaining institutional learning.
2. **Product mechanism**: four specialist Critics challenge the PRD in parallel, then cross-challenge each other before a Supervisor decides.
3. **Differentiation**: recurring review misses can become governed, reusable Skills rather than disappearing after one review.
4. **Proof**: golden PRDs, persisted telemetry, real-LLM ablation, and human feedback quantify whether Skills improve output quality.

The core differentiator is the **verifiable Skill self-evolution loop**. Multi-Agent is the review mechanism; LangGraph, MCP, React, FastAPI, and OpenAI are implementation choices; evaluation metrics are the evidence.

---

## 2. Current Product State

### Review pipeline — implemented

```text
PRD input
  -> Intake claim extraction
  -> User Advocate / Engineering / Business / Design Critics in parallel
  -> Cross-Challenge, maximum 2 rounds
  -> Supervisor synthesis
  -> Structured P0 / P1 / P2 report
  -> Run history and Skill telemetry
```

Implemented capabilities:

- Pasted text, built-in golden PRD selection, PDF upload, and Word upload.
- Parallel LangGraph critic execution with additive state reducers.
- Evidence-grounded critiques containing finding, evidence, suggested fix, severity, and optional Skill attribution.
- Cross-Challenge with a hard round cap, empty-round convergence, and similarity convergence.
- Streaming Supervisor reasoning and structured verdict.
- Per-critique HITL discussion with a five-round cap.
- Per-critique acceptance/noise feedback for Skill statistics; feedback is now an immutable lifecycle record that drives auto-degrade.
- Persisted run history, proposal history, ablation reports, and runtime Skill statistics.
- **Skill Lifecycle Center**: lifecycle statuses, immutable lineage/use-event/evaluation records in SQLite, four admission gates, probation/degrade/rollback, and an Overview/Proposals/Library UI (details in §5).
- Chinese/English UI toggle; verdict language is forced while source evidence remains verbatim.
- Markdown export, print-to-PDF, history deep links, and two-step history deletion.

### Current frontend — implemented

The primary UI is no longer the original Streamlit shell. It is now a React/Vite single-page application:

- React 19 + TypeScript 6 + Vite 8.
- Pixel-inspired visual shell, bilingual UI, progressive run sequence, completion beat, and responsive result views.
- Main pages: Review, Skills, and Ablation.
- FastAPI serves `/api/*` and the production SPA from one process.
- Streamlit remains in the repository as a legacy/deployment-compatible surface, not the main product experience.

Relevant paths:

| Area | Path |
|---|---|
| React application | `web/src/` |
| Review page | `web/src/pages/ReviewPage.tsx` |
| Skills page (Lifecycle Center) | `web/src/pages/SkillsPage.tsx`, `web/src/components/LifecycleViews.tsx` |
| Ablation page | `web/src/pages/AblationPage.tsx` |
| Bilingual copy | `web/src/lib/i18n.tsx` |
| FastAPI application | `api/app.py` |
| API routes | `api/routes_review.py`, `api/routes_history.py`, `api/routes_skills.py`, `api/routes_ablation.py`, `api/routes_lifecycle.py` |

### LLM providers — implemented

- `MockProvider` supports deterministic local tests.
- `OpenAIProvider` supports async completion, streaming, JSON mode, retries, timeouts, usage accounting, base URL configuration, and Azure-compatible configuration.
- Current real-LLM evaluation used `gpt-4o-mini` for both Critics and Supervisor.
- Splitting the Supervisor to a stronger model is intentionally deferred as technical debt D-14.

Relevant paths:

| Area | Path |
|---|---|
| Provider abstraction and errors | `src/llm/provider.py` |
| Mock provider | `src/llm/mock_provider.py` |
| OpenAI provider | `src/llm/openai_provider.py` |
| Provider/model factory | `src/config.py` |

Never commit `.env` or expose an API key. `.env.example` is the public configuration template.

---

## 3. Skill System — What Exists Today

### Agent Skills-compatible library

Skill definitions follow the Agent Skills folder convention:

```text
src/skills/
  seed/<skill-name>/SKILL.md
  learned/<skill-name>/SKILL.md
  runtime_stats.yaml
```

There are six seed Skills and one learned Skill:

- `api-dependency-enumeration`
- `quantified-metrics`
- `phased-rollout`
- `accessibility-check`
- `user-evidence`
- `internal-contradiction`
- `non-happy-state-spec` — learned from cross-PRD misses

`SKILL.md` holds design-time definition and instructions. `runtime_stats.yaml` holds mutable counters and status so normal runs do not rewrite Skill definitions.

### Retrieval and attribution

- Critics retrieve role-compatible Skills through `src/skills/retriever.py`.
- The current retriever uses explainable keyword scoring and source filtering.
- The latency-sensitive critic hot path reads through the in-process retriever.
- `retrieve_scored()` exposes the keyword/role components, rank, and rejected zero-hit candidates; `HistoryStore.save` persists one `SkillUseEvent` per (run, critic, skill) with those components — retrieval telemetry is now durable, not just a flat id set.
- Attribution must be described precisely:
  - **Retrieved** is a system-observed fact.
  - **Applied** is currently model self-report through `skill_id`, so it is weaker evidence.
  - **Validated impact** requires a counterfactual OFF/ON evaluation — now implemented as the shadow gate (`src/lifecycle/shadow.py`).

Do not claim that every critique with a `skill_id` was causally produced by that Skill.

### Distillation and approval

Implemented loop:

```text
Run history
  -> query critiques without Skill attribution
  -> cluster recurring findings by critic
  -> require the pattern in at least 3 distinct PRDs
  -> LLM proposes a complete SKILL.md
  -> PM approves/rejects/edits
  -> approved Skill moves to learned/
  -> later runs retrieve it
  -> feedback updates runtime statistics
```

Canonical learned example: `non-happy-state-spec`.

- Proposal: `data/results/proposals/c1d43bf4cfd349a3a2aaa0d75bc515a3.json`
- Evidence: the same design miss appeared in three distinct PRDs: loyalty program, onboarding redesign, and payment retry.
- Generalization score: `0.77`.
- Status: approved.
- Current runtime record: 11 uses and acceptance rate `1.0`, but this is based on only **one feedback sample** and must not be presented as robust effectiveness evidence.

### MCP architecture

The MCP server is real, not a fake client:

- FastMCP server: `src/mcp_servers/skill_server.py`
- Transport: stdio
- Tools: `list_skills`, `read_skill`, `read_skill_md`, `search_skills`
- Live display client: `src/skills/mcp_live_client.py`
- Independent verifier: `scripts/verify_mcp.py`

Intentional architecture boundary:

- External/UI browsing can use the live MCP interface.
- The critic hot path uses the same retriever backend in-process to avoid subprocess/protocol latency.
- If the hosting environment blocks subprocesses, the display layer can fall back locally and must disclose that fallback.

Truthful claim: **“The Skill library is exposed over a custom FastMCP stdio server; UI/external access can use MCP, while the latency-sensitive critic loop reads the shared retriever in-process.”**

Do not claim that the main critic pipeline retrieves Skills through MCP.

---

## 4. Evaluation Evidence

### Dataset and rubric

- Five hand-crafted golden PRDs.
- Twenty-two known defects across metric quality, dependency identification, internal contradiction, risk management, and scope ambiguity.
- Rubric measures structure compliance, dependency recall, contradiction detection, severity F1, actionability, overall recall, precision/false positives, latency, and cost.
- Matching currently uses `difflib`; this is a proxy and should be upgraded to embedding or judge-assisted evaluation in v2.

### Real-LLM ablation — main sweep

Five PRDs, three treatments, one run per cell:

| Treatment | Recall | Precision | Critiques/run | False positives/run |
|---|---:|---:|---:|---:|
| Skill off | 0.95 | 0.30 | 15.2 | 10.8 |
| Seed only | 0.95 | 0.39 | 12.2 | 7.8 |
| Seed + learned | 0.91 | 0.35 | 12.2 | 8.0 |

### Stability check

`prd_001`, three runs per treatment:

| Treatment | Recall mean ± std | Precision mean ± std | Latency mean ± std | Critiques/run mean ± std |
|---|---:|---:|---:|---:|
| Skill off | 0.93 ± 0.09 | 0.28 ± 0.05 | 33.9s ± 2.0s | 17.0 ± 1.4 |
| Seed only | 1.00 ± 0.00 | 0.56 ± 0.00 | 29.0s ± 2.3s | 9.0 ± 0.0 |
| Seed + learned | 0.93 ± 0.09 | 0.44 ± 0.04 | 30.1s ± 2.7s | 10.7 ± 0.9 |

### Defensible interpretation

1. **Recall saturation on a strong model**: the base model already finds most known defects, so Recall alone understates Skill value.
2. **Skill value is primarily Precision lift**: seed Skills preserved Recall while reducing noisy critiques and false positives.
3. **HITL governance is necessary**: adding the learned Skill did not outperform seed-only and slightly reduced Recall in the main sweep. Learned Skills must earn admission and remain subject to rollback.

Do not say “Skills improved all metrics” or “the learned Skill is proven effective.” The data supports a narrower, stronger claim: **curated seed Skills improved review efficiency/Precision, while learned Skills require counterfactual validation and lifecycle governance.**

---

## 5. Skill Lifecycle Center — Shipped 2026-08-23

The Skills page is now a **Skill Lifecycle Center**. Backend records, gates,
governance, and the three-view UI are implemented and tested (140 backend
tests). What follows is the shipped design plus the as-built decisions.

### Product information architecture

The Skills area contains three views (tabs, bilingual):

1. **Overview** — lifecycle counts, degraded Skills, intervention queue (probation signals), recent admissions/transitions.
2. **Proposals** — evidence, gate chips (spec/evidence/novelty/shadow with pass/fail/pending + reason tooltips), OFF/ON metric deltas for shadow, PM decision, edit history. Approve stays disabled until all four gates pass.
3. **Library** — status/version/provenance/usage/feedback per Skill, expandable version lineage + status audit trail, SKILL.md viewer, rollback (degraded) and deprecate (active) actions.

The pixel visual system remains the brand shell; governance surfaces use restrained Inter/monospace typography (`LifecycleViews.module.css`).

### Simplified lifecycle — as implemented

```text
Candidate -> Approved -> Active -> Degraded -> Deprecated
     |
     +-> Rejected
```

Every transition is appended to `skill_status_events` (audit trail); current
state lives in `skill_status`. `runtime_stats.yaml` is now a materialized
read cache mirrored from SQLite (the retriever's read path is unchanged;
anything not `status: active` is excluded from retrieval automatically).

### Immutable records — as implemented (`src/lifecycle/`)

- **`SkillLineage`** — per (skill, version): proposal linkage, source run ids, distinct PRD hashes, cited excerpts, parent version chain, admission decision/actor/time, gate-report and evaluation references, and the full SKILL.md snapshot (the rollback source).
- **`SkillUseEvent`** — per (run, critic, skill): retrieval score/components/rank/source, model-reported `applied`, attributed critique uids, provider, timestamp. Recorded by `HistoryStore.save` (failure-tolerant; off the critic hot path).
- **`SkillEvaluation`** — OFF/ON configs, per-arm metric dicts (recall, precision, false-P0, evidence compliance, actionability, latency, cost), target-pattern hit count, gate verdict + reason, policy and evaluator versions.
- **`SkillFeedback`** — per HITL sample: accepted, critique uid, severity, deterministic evidence-compliance check, timestamp. The probation evidence base.
- **`GateReport`** — every gate run persisted with evaluator version; UI shows latest per gate.

### Admission gate — as implemented

`SkillGovernance.run_gates()` runs and persists the four checks;
`approve()` refuses unless all four latest reports passed (no code path lets
the model approve itself):

1. **Spec** — deterministic frontmatter/body validation (`gates.validate_spec`).
2. **Evidence** — ≥3 distinct PRDs deduplicated by `prd_text_hash`; missing runs fail the gate.
3. **Novelty** — difflib similarity < 0.85 vs active skills sharing the same routed roles (self excluded for edits).
4. **Shadow** — OFF/ON counterfactual (`src/lifecycle/shadow.py`): staged copy of the current library, ON adds only the candidate; same PRDs/config/model; rubric-scored; policy verdict.

Policy `precision-first-v1`: Precision must not decline; Recall decline ≤ 0.02; ≥3 PRD target hits; no extra false P0; evidence/actionability compliance must not regress vs OFF (delta-based — absolute quoting quality is a pipeline property, not a candidate property). Advisory preference: Precision +0.03 or Recall +0.03 at equal Precision.

### Probation and rollback — as implemented

Publication stamps `probation_started_at`. `record_feedback()` appends the
immutable sample, mirrors the YAML cache, then `check_and_degrade()`
degrades (stop retrieval + stamp rollback target) on: a rejected **P0**
attributed to the Skill, a failed evidence-compliance check, or recent
acceptance < 40% with ≥3 samples (window 20). `rollback()` restores the
previous version's SKILL.md from its lineage snapshot. `SKILL.md` files are
never deleted by any path.

### Storage — as implemented

- SQLite at `data/lifecycle/skills.db` (gitignored; rebuilt deterministically).
- Repository surface: `src/lifecycle/store.py` (`LifecycleStore`) — swap to PostgreSQL later by re-implementing the same methods.
- Deterministic migration (`src/lifecycle/migration.py`) runs once, lazily, on first API access: imports lineage/status from SKILL.md folders + runtime stats, proposal linkage, PRD hashes via history, legacy use events, and (when `learned/` holds exactly one skill) the recorded ablation as a legacy evaluation. Unknowns stay NULL, rows are `provenance="legacy_import"`, the `demo-skill` orphan (D-19) is skipped and reported. Idempotent.
- As-built honesty note: the migrated ablation evaluation for `non-happy-state-spec` receives a **retroactive FAIL** under `precision-first-v1` (precision 0.394→0.347, recall −0.04). That is the truthful D-20 story — under the gates now shipped, that skill would not have been admitted.

### Retrieval strategy — unchanged

No vector DB. Explainable scoring with persisted components, ranks, rejected
candidates, and model-reported application kept separate from validated
impact. Revisit embeddings at ~50+ Skills or with demonstrated retrieval misses.

---

## 6. Canonical Interview Demo

Use `non-happy-state-spec` as the hero example. The core story must fit in three minutes; an optional technical drill-down may extend to eight minutes.

### Three-minute path

1. Run a PRD review and show the four Critics, Cross-Challenge, and Supervisor report.
2. Open the recurring design miss: “primary flow has no empty/loading/error/offline states.”
3. Show that the pattern came from three distinct PRDs, not three reruns.
4. Open the proposed `SKILL.md`, its evidence, and human approval.
5. Show retrieval in a later run and the feedback signal.
6. Show the ablation result: seed Skills improve Precision, while learned Skills still need admission gates and rollback.

### Optional technical drill-down

- LangGraph fan-out/fan-in state design.
- persisted run telemetry and PRD hash deduplication;
- deterministic checks versus LLM proposal generation;
- OFF/ON counterfactual evaluation;
- MCP display/external boundary versus in-process critic hot path;
- planned SQLite lineage/event/evaluation model.

---

## 7. Implementation Sequence — Status

Phases 1–3 are **shipped** on branch `feat/skill-lifecycle-center`:

- **Phase 1 — Domain model and persistence** ✅ enums, three immutable records (+ SkillFeedback/GateReport), SQLite schema + `LifecycleStore`, deterministic migration with `legacy_import` labeling and orphan cleanup; YAML/JSON readers unchanged.
- **Phase 2 — Validation and governance services** ✅ four gates with persisted outputs and evaluator versions; generator/verifier/decider separation; degrade/rollback policy with retrieval exclusion via the YAML cache.
- **Phase 3 — Skill Lifecycle Center UI** ✅ Overview/Proposals/Library views; gate failures visible before approval; version lineage + rollback target; bilingual copy; restrained governance typography inside the pixel shell.
- **Phase 4 — Demo hardening and evaluation** ⏳ remaining: migration/transition/rollback/counterfactual tests are in (`tests/test_lifecycle.py`, gated approve flow in `tests/test_api.py`); still to do — re-run the real-LLM ablation under the new gates and capture the stable three-minute demo path.

---

## 8. Open Decisions

Resolved during implementation (defaults chosen; revisit with evidence):

- ~~Validation synchronous or asynchronous~~ → **synchronous**, every run persisted as a `GateReport`; the shadow sweep is opt-in per request because it costs a full OFF/ON grid.
- ~~SQLite schema / deployment persistence~~ → schema v1 at `data/lifecycle/skills.db`; on ephemeral hosting (HF Spaces) the deterministic migration rebuilds lineage/status on boot, but **runtime events/feedback do not survive a wipe** — durable volume or Postgres remains future work.
- ~~Feedback aggregation model~~ → fixed sliding window of 20 (matches the curator's window), sample floor 3, acceptance floor 40%; Bayesian intervals deferred until samples justify them.
- ~~Novelty threshold/evaluator~~ → difflib similarity, threshold 0.85, same-role comparisons only (debt D-15 applies); swap for embeddings with measured need.
- Supervisor model split (D-14) — still deferred.

---

## 9. Known Technical Debt

| ID | Debt | Why it matters |
|---|---|---|
| D-14 | Critics and Supervisor currently share `gpt-4o-mini` in the recorded real run | A stronger Supervisor may improve arbitration but adds cost and another experimental variable. |
| D-15 | `difflib` is used for clustering/matching/convergence/novelty/evidence-compliance | It is explainable but not semantically robust. Upgrade only with a measured retrieval/evaluation need. |
| D-16 | ~~`runtime_stats.yaml` is mutable source of truth~~ → **resolved**: SQLite is the source of truth; YAML is a mirrored read cache | Remaining risk: on ephemeral hosting the cache+db regenerate but runtime records are lost (see §8). |
| D-17 | Skill application is model-reported | `skill_id` alone is still not causal evidence at runtime — but the shadow gate now produces counterfactual validation at admission time. |
| D-18 | Acceptance rates have tiny samples | `n` is now displayed with every rate (Library view); auto-degrade requires ≥3 samples. Confidence intervals still future work. |
| D-19 | ~~`demo-skill` orphan row~~ → **resolved**: skipped and reported by the deterministic migration | — |
| D-20 | Learned Skill underperformed seed-only in the main ablation | Governance now ships: the migrated evaluation carries a **retroactive FAIL** under `precision-first-v1`; future admissions face the same gate before publication. |
| D-21 | Mobile controls and some tiny labels need accessibility QA | Small touch targets and overflow can weaken the demo on narrow screens. |
| D-22 | Frontend lint has one `react(only-export-components)` warning in `web/src/lib/i18n.tsx` | Non-blocking, but should be cleaned before a polished release. |

---

## 10. Verification Snapshot

Verified at the lifecycle-center commit (2026-08-23, branch `feat/skill-lifecycle-center`):

- Backend: **140 tests green** (`pytest tests/ -W error`) — 123 pre-existing + 17 new lifecycle tests.
- Frontend unit tests: **7/7 passed**; `tsc --noEmit` clean; production build passed (~308 KB JS / ~97 KB gzip).
- Frontend lint: passed with the one pre-existing warning (D-22).
- Real-data smoke: booted `uvicorn api.app:app`, lazy migration imported 7 skills (orphan `demo-skill` skipped), `non-happy-state-spec` lineage carries proposal linkage + 3 distinct PRD hashes + the retroactive-fail evaluation.

Run before making a new feature branch:

```powershell
pytest tests/ -W error

Set-Location web
npm test -- --run
npm run lint
npm run build
Set-Location ..
```

Local production-like run:

```powershell
docker compose up --build
```

Local split development:

```powershell
# Terminal 1
uvicorn api.app:app --reload --port 8000

# Terminal 2
Set-Location web
npm run dev
```

MCP verification:

```powershell
python scripts/verify_mcp.py
```

---

## 11. Key Backend Paths

| Concern | Path |
|---|---|
| Pipeline entry | `src/main.py` |
| LangGraph assembly | `src/graph/builder.py` |
| State models | `src/graph/state.py` |
| Cross-Challenge | `src/graph/edges.py` |
| Intake | `src/agents/intake.py` |
| Critics | `src/agents/critics/` |
| Supervisor | `src/agents/supervisor.py` |
| Critique dialog | `src/agents/critique_dialog.py` |
| Distiller | `src/agents/skill_distiller.py` |
| Retriever | `src/skills/retriever.py` |
| Curator | `src/skills/curator.py` |
| Skill definitions | `src/skills/seed/`, `src/skills/learned/` |
| Runtime statistics (read cache) | `src/skills/runtime_stats.yaml` |
| FastMCP server | `src/mcp_servers/skill_server.py` |
| Run history | `src/storage/history_store.py` |
| Proposal storage | `src/storage/proposals_store.py` |
| Lifecycle domain models | `src/lifecycle/models.py` |
| Lifecycle SQLite store | `src/lifecycle/store.py` |
| Deterministic migration | `src/lifecycle/migration.py` |
| Admission gates + policy | `src/lifecycle/gates.py` |
| Shadow (OFF/ON) evaluation | `src/lifecycle/shadow.py` |
| Governance service | `src/lifecycle/governance.py` |
| Lifecycle API routes | `api/routes_lifecycle.py` |
| Ablation runner | `src/eval/ablation.py` |
| Evaluation rubric | `src/eval/rubric.py` |
| Golden PRDs | `src/eval/golden_prds/` |

---

## 12. Research Basis for the Next Iteration

Use these as design references, not as claims that the project already implements their full lifecycle:

- [Agent Skills specification](https://agentskills.io/specification) — portable Skill folders, required `SKILL.md`, and progressive disclosure.
- [Agent Skills for Large Language Models: Architecture, Acquisition, Security, and the Path Forward](https://arxiv.org/html/2607.10113) — lifecycle stages, provenance, admission, maintenance, governance, and portability.
- [XSkill](https://github.com/XSkill-Agent/XSkill) — separation of reusable Skill documents from accumulated experience records.
- [SkillWiki](https://github.com/Huangdingcheng/SkillWiki) — comprehensive provenance/version/governance reference; useful as a benchmark but too heavy to copy wholesale.
- [xskill](https://github.com/SkillNerds/xskill/blob/main/docs/agent.md) — candidate staging, evidence units, and canary-style quality checks.

The intended design is deliberately smaller than SkillWiki: enough governance to make self-evolution auditable, without turning this portfolio project into an enterprise knowledge platform.

---

## 13. Resume-Safe Claims

Safe:

> Built a bilingual multi-agent PRD review system with four parallel specialist agents, bounded cross-challenge, Supervisor synthesis, persisted telemetry, and an Agent Skills-compatible library. Designed a cross-PRD Distiller/HITL approval loop and validated Skill impact through real-LLM ablation: curated seed Skills preserved Recall while lifting Precision from 0.30 to 0.39 and reducing false positives from 10.8 to 7.8 per run.

Safe lifecycle wording (new, defensible since 2026-08-23):

> Designed and shipped a Skill Lifecycle Center: SQLite-backed immutable lineage/use-event/evaluation records, a four-gate admission pipeline (spec, evidence dedup by PRD hash, novelty, counterfactual OFF/ON shadow evaluation) with a Precision-first/Recall-non-regression policy, and automated probation/degradation/rollback — approvals are structurally impossible until every gate passes, and the legacy learned skill honestly receives a retroactive FAIL under the new policy.

Safe MCP wording:

> Exposed the Skill library through a custom FastMCP stdio server for UI/external access while keeping the latency-sensitive critic retrieval path in-process against the same backend.

Not safe yet:

- “The system autonomously learns reliable Skills.”
- “Learned Skills improve performance.”
- “All Skill retrieval happens through MCP.”
- “A 100% acceptance rate proves Skill quality.”
- “Shadow evaluation has been run against the real LLM for every admitted skill” — the gate machinery is real and mock-tested; the real-LLM shadow re-run is still pending (Phase 4 remainder).
