# Architecture — PRD Stress Test Agent

The system is a **LangGraph state machine** with parallel critic agents,
two skill-library side branches (read path + write path), and an ablation
harness that gives the whole thing a measurable contract.

This document covers each component's interface, the design trade-off
that produced it, and the failure mode it's designed to absorb.

---

## 1. State machine (`src/graph/`)

```
Intake → [4 critics in parallel] → merge → cross-challenge → supervisor → END
```

- **State type**: `GraphState` (`src/graph/state.py`) — `TypedDict` with
  `Annotated[list, operator.add]` reducers on `critiques` and
  `challenges` so parallel writes from multiple critics merge instead of
  overwriting.
- **Why TypedDict + Annotated**: LangGraph's reducer model is the
  cleanest way I've seen to express "four nodes write the same key in
  parallel, just concatenate." CrewAI hides this behind a role-based
  abstraction; I wanted it visible because cross-challenge depends on
  knowing which critic wrote what.
- **Failure mode absorbed**: parallel-write race conditions. Without the
  reducer, whichever critic finishes last wins, silently dropping the
  other three.

### 1a. Intake (`src/agents/intake.py`)

- Input: line-numbered PRD text (`number_lines()` prefixes every line
  with `[NNN]`). Output: a list of `PRDClaim` objects.
- The line-numbering preprocessor exists because models hallucinate
  line numbers when asked to count themselves. `[001] foo` is much more
  reliable than "look at line 1".
- `claim_type` is a `Literal["assumption","requirement","metric","scope","dependency"]`.
  `dependency` was added Day 11 after the real LLM started emitting it
  organically — schema drift between mock canon and real model output.

### 1b. Critics (`src/agents/critics/_shared.py:run_critic`)

Four critics — `user_advocate`, `engineering`, `business`, `design` —
share the same `run_critic` driver and differ only in system prompt.

- Each critic asks the retriever for top-K skills routed to its
  `critic_id`, prepends the `<retrieved_skills>` block to the user
  message, then invokes the LLM.
- **Skill-id back-fill + hallucination guard** (post-LLM):
  - If the model emits a `skill_id` not in the retrieved set →
    reset to `None`, log a warning. The real LLM regularly invents
    `SK-042` / `SK-017` from the prompt examples, validator catches it.
  - If the model emits no `skill_id` and a skill was retrieved →
    backfill the top retrieved skill's id. Without this, "skill never
    cited but obviously fired" runs would look like misses to the
    Distiller.
- **Failure mode absorbed**: silent skill-attribution drift. The
  retrieved skills are knowable at runtime; the model's free-text claim
  about which one fired is not. We trust the retrieval-side evidence,
  not the model's introspection.

### 1c. Cross-challenge (`src/graph/edges.py:run_cross_challenge`)

- Sequential rounds, parallel-within-round (`asyncio.gather`).
- **Three-layer convergence detection**:
  1. `MAX_CROSS_CHALLENGE_ROUNDS = 2` — hard cap, configurable.
  2. Empty round-1 early exit — if no critic challenges anyone, set
     `convergence_signal=True` and stop.
  3. `difflib.SequenceMatcher` ratio over sorted challenge text;
     threshold 0.75 (the embedding-equivalent number is 0.85,
     SequenceMatcher needs to be looser to catch the same paraphrases).
- The sequential-rounds-but-parallel-within-round shape is a deliberate
  trade-off: full parallelism would let critics challenge stale views
  of each other; full sequence would 4× the latency. Within-round
  parallel keeps fan-out cheap.
- **Failure mode absorbed**: critics either stalling on infinite
  arguments or failing to push back at all. Without all three layers
  one mode or the other always wins.

### 1d. Supervisor (`src/agents/supervisor.py`)

- Streaming, with a 4-state XML parser
  (`scan` → `thinking` → `verdict` → `post_verdict`) that holds a
  20-char tail guard. Works on 1-char chunks.
- Output envelope: `<thinking>…</thinking><verdict>{JSON}</verdict>`
- **Why XML, not JSON-mode**: thinking-tag streaming gives the user
  visible reasoning live while the structured verdict lands at the end.
  JSON-mode forces full-buffer-then-parse, no partial UI.
- The XML envelope is what disqualifies o1/o1-mini from this role —
  they only return complete responses, breaking the stream.

---

## 2. Skill Library — read path (`src/skills/`)

Conforms to the **Anthropic Agent Skills `SKILL.md` spec** (Dec 2025):

```
src/skills/
├── seed/<name>/SKILL.md          # human-authored
├── learned/<name>/SKILL.md       # distiller-authored
├── runtime_stats.yaml            # decoupled telemetry
└── _archive/                     # pre-Day-8.5 layout, kept for rollback
```

Each `SKILL.md` is YAML frontmatter (name, description, version,
created_by, injected_into) + Markdown body. See
[`docs/skill_format.md`](skill_format.md) for the full spec mapping.

### 2a. Schema split (`src/skills/schema.py`)

- `SkillDefinition` — frontmatter + body (design-time)
- `SkillRuntimeStats` — usage_count / acceptance_rate /
  acceptance_history / status (runtime-time)
- `Skill` — flat merged view returned by the retriever

The split exists so each PRD run only mutates `runtime_stats.yaml`. The
on-disk skill content (`SKILL.md`) is untouched across hundreds of
runs, keeping PR review of skill content uncluttered.

### 2b. Retriever (`src/skills/retriever.py`)

- Scans `seed/` and `learned/` for SKILL.md folders, parses frontmatter
  via a homegrown 30-line parser (no `python-frontmatter` dep), merges
  `runtime_stats.yaml` at load time.
- Ranking: case-insensitive keyword count over `trigger_keywords` from
  the SKILL.md frontmatter. Tie-break on `confidence`. Zero-hit skills
  are filtered out — keyword-free injection just noises the prompt.
- **Why keyword-not-embedding**: shipping cost. Embeddings are debt
  D-02 (alongside D-01 cross-challenge similarity, D-10 distiller
  clustering, D-12 rubric matcher). The four call sites get upgraded
  together once `sentence-transformers` is in `requirements.txt`.

### 2c. MCP server (`src/mcp_servers/skill_server.py`)

Real FastMCP stdio server, four tools:
- `list_skills(status="active")` — metadata only
- `read_skill(name)` — parsed skill including body
- `read_skill_md(name)` — raw SKILL.md text verbatim (for spec-aware
  consumers like the OpenAI Codex CLI)
- `search_skills(query, critic_id=None, top_k=3)` — keyword ranker

The same surface is mirrored in-process by
`src/skills/mcp_client.py` so tests / Streamlit can hit tools without
spawning a stdio subprocess.

---

## 3. Skill Library — write path

### 3a. Distiller (`src/agents/skill_distiller.py`)

Mines `data/results/history/` (run history, Day 8) for cross-PRD
patterns the existing skill library missed:

1. `HistoryStore.query(only_misses=True)` — runs with at least one
   `skill_id=None` critique.
2. Group misses by `critic_id`.
3. Within each critic, cluster findings by SequenceMatcher ≥0.6.
4. Drop clusters spanning <3 distinct PRDs (admission gate).
5. Ask LLM for one proposal per cluster — full SKILL.md text +
   generalization_score (0–1).
6. Validate 8 ways before returning: ≥3 evidence rows, kebab name,
   valid critic ids, frontmatter complete, `created_by="distiller"`,
   name == frontmatter name, body non-empty, score ≥ 0.7.
7. Evidence (`run_id` + `critique_excerpt`) is filled IN CODE from
   the cluster, never from the LLM — so no proposal can ever be
   "evidence-free" by accident.

**Why all the gates**: without them the Distiller recreates the
"founder-fiction skill" failure the system is supposed to detect.

### 3b. ProposalsStore (`src/storage/proposals_store.py`)

Per-proposal JSON under `data/results/proposals/`. Approved proposals
are PROMOTED — written to `src/skills/learned/<name>/SKILL.md`, with a
fresh row seeded into `runtime_stats.yaml`. The retriever cache is
busted so the new skill is visible without a restart.

### 3c. Curator (`src/skills/curator.py`)

- `increment_usage(names)` — bump usage + stamp last_used. De-duped
  per call so a single PRD run touching the same skill across 4
  critics still counts as 1 use.
- `update_acceptance(name, accepted)` — sliding window of length 20
  (configurable). Stored as JSON in `acceptance_history` so a
  restart doesn't erase the signal.
- `auto_deprecate()` — flips `status` to `deprecated` for skills with
  `usage_count ≥ 5` AND `acceptance_rate < 0.30`. Conservative
  defaults so a bad week doesn't kill a skill.
- `merge_duplicates(threshold=0.85)` — finds active skills with
  similar (description, sorted(injected_into)). Loser keeps SKILL.md
  on disk; only `runtime_stats.yaml` flips status to
  `deprecated_merged_into_<winner>`. Reversible by editing one file.

### 3d. HITL approval (Streamlit UI)

`🧪 Skill Distillation` sidebar shows pending proposals with
generalization-score progress bar (🟢/🟡/🔴), evidence list, full
editable SKILL.md (`st.text_area`), Approve / Reject / Save edit.
Approve picks up unsaved edits automatically.

---

## 4. Telemetry & evaluation

### 4a. Run history (`src/storage/history_store.py`)

Per-run JSON file under `data/results/history/run_<ts>_<id8>.json` +
append-only `index.jsonl` summary. The split exists so listing recent
runs (sidebar, Distiller input) reads only the index — small and
append-only, never rewritten.

`HistoryStore.save` is best-effort: telemetry failures are logged, not
raised. The pipeline never breaks because storage broke.

### 4b. Rubric (`src/eval/rubric.py`)

5 dimensions per run + 2 aggregates:
- `structure_compliance` — fraction of critiques that validate against
  the `Critique` pydantic schema
- `dependency_recall` — recall over `dependency_identification` defects
- `contradiction_detection` — recall over `internal_contradiction` defects
- `severity_classification_f1` — macro-F1 of P0/P1/P2 over matched defects
- `actionability` — fraction of critiques with non-empty +
  imperative-verbed suggested_fix
- `overall_recall` — matched defects / total defects in manifest
- `precision` — matched critiques / total critiques

Critique↔defect matching: per-field score using
`max(SequenceMatcher_ratio, token_jaccard)` against the defect's
manifest note. Threshold 0.35 — calibrated against the 5 golden PRDs
after observing that concatenating critique fields diluted the signal.

### 4c. Ablation runner (`src/eval/ablation.py`)

`run_ablation(prds, treatments, output_dir, runs_per_treatment)` —
runs every (treatment × PRD × repeat) cell, scores via `score_run`,
aggregates mean/std/min/max, writes JSON + Markdown + a
`latest.json` mirror that the Streamlit Ablation tab reads.

**Treatment switching** rebinds `default_retriever` in EVERY module
that imported it by name (`src.skills.retriever`,
`src.skills` package, `src.agents.critics._shared`,
`src.skills.curator`). This was the bug that hid the signal in the
first real-LLM run — patching only the source module is invisible
to callers that pulled the symbol into their namespace at import
time.

---

## 5. Provider abstraction (`src/llm/`)

- `LLMProvider` ABC + `LLMResponse` model.
- Three error types: `LLMError`, `LLMRateLimitError`, `LLMTimeoutError`.
- `MockProvider` — deterministic, keyword-routed canned responses,
  used by tests + the free-tier Streamlit demo.
- `OpenAIProvider` — async, vanilla / proxy / Azure auto-detect,
  json_mode=ON for critics, json_mode=OFF for supervisor (sniffs
  "supervisor" in the system prompt). Single 5-second backoff retry
  on 429 / timeout. Streaming chunks shaped as
  `{"type": "text", "delta": str}` to match `MockProvider.stream()`.
- Factories in `src/config.py`: `get_critic_llm()` and
  `get_supervisor_llm()`. Today both return `OpenAIProvider(model="gpt-4o-mini")`
  when `LLM_PROVIDER=openai`.

**Why one provider for both**: Day-3 simplification —
`build_graph(llm)` takes a single provider and uses it for critics
+ supervisor. Splitting requires threading a second provider through
the graph; tracked as debt **D-14**, low priority because gpt-4o-mini
runs the supervisor competently in practice.

---

## 6. Trade-offs I made deliberately

| Decision | Trade-off | Why I made it |
|---|---|---|
| LangGraph over CrewAI | More wiring code; less role abstraction | Cross-challenge reducers need to be visible |
| difflib over embeddings (4 sites) | Brittle to vocab drift | $0 deployment cost; unblocks v1 ship |
| One LLM provider for both critics+supervisor | Supervisor doesn't get gpt-4o | Day-3 simplification, debt D-14 |
| HITL approval on every distilled skill | Slower learning loop | Real-LLM ablation showed auto-distilled skill regresses — HITL gate empirically validated |
| Keyword retrieval over embeddings | No synonym matching | Same as above; v2 upgrade kills D-01/D-02/D-10/D-12 |
| Mock + Real coexist with one flag | One more branch in tests | Free demo path; ablation reproducibility |

---

## 7. Where the system can break

- **Real-LLM JSON parse failures.** gpt-4o-mini occasionally returns
  ```` ```json ... ``` ```` despite json_mode. Handled by
  `extract_json` in `src/agents/_parsing.py`.
- **Hallucinated skill ids.** Caught by the post-LLM validator;
  see §1b above.
- **Cross-PRD distillation on a small history.** Hard-blocked: < 3
  distinct PRDs in history → distiller returns `[]` with a warning.
- **HITL queue starvation.** If no human approves, the library never
  grows. The auto-distill cadence in `src/main.py` is OFF by default
  (`DISABLE_AUTO_DISTILL=1`) for exactly this reason — proposals
  pile up only when a human is actively reviewing.
