# HANDOFF — PRD Stress Test Agent

## 1. Project in one sentence

A multi-agent system that takes a PRD as input, runs 4 parallel critic agents
(User Advocate / Engineering / Business / Design), performs up to 2 rounds of
cross-challenge between them, and has a Supervisor agent synthesize a
structured, severity-ranked blindspot report. The long-term differentiator is
a Skill Library (cross-PRD reusable review heuristics) exposed via a custom
MCP server — not yet implemented.

---

## 2. Progress — Days 1 through 6

### Day 1 — Scaffold
- Repo skeleton, empty package tree, `.env.example`, `.gitignore`.
- `LLMProvider` abstract base + `LLMResponse` pydantic model.
- `MockProvider` with deterministic keyword-routed canned responses and a
  `call_log` for test introspection.
- Streamlit shell with a placeholder `run_pipeline()`.
- First async test wired up.

### Day 2 — Schemas, prompts, eval set
- `GraphState` (TypedDict) with `Annotated[list, operator.add]` reducers on
  `critiques` and `challenges` so parallel writes merge.
- Pydantic v2 models: `PRDClaim`, `Critique`, `CrossChallenge`, `SupervisorVerdict`.
- 6 system prompts (intake + 4 critics + supervisor). Supervisor uses
  `<thinking>…</thinking><verdict>{JSON}</verdict>` envelope.
- 5 golden PRDs with 23 HTML-commented defects across 5 dimensions
  (metric_quality / dependency_identification / internal_contradiction /
  risk_management / scope_ambiguity). Manifest at
  `src/eval/golden_prds/manifest.yaml`.
- Rubric stubs in `src/eval/rubric.py`.

### Day 2.5 — Prompt hardening (based on architectural review)
- **Line-number hallucination fix**: `src/graph/preprocess.py:number_lines()`
  prefixes every PRD line with a zero-padded `[NNN] ` marker. Intake prompt
  tells the model to COPY the bracketed integer, not count lines. Critic
  prompts reference those same markers in evidence quotes.
- **Skill Library closure**: `src/agents/critics/_shared.py` holds
  `SKILL_CONTEXT_RULES` — a shared fragment defining the `<retrieved_skills>`
  injection contract. Critics no longer hardcode `skill_id: null`; the field
  is now a typed telemetry slot with rules forbidding id invention. Day 8/9
  retriever integration only needs to prepend the `<retrieved_skills>` block
  to the user message.

### Day 3 — Pipeline skeleton
- `run_intake()`, `run_<critic>()` functions (all four) with graceful JSON
  parse (`src/agents/_parsing.py:extract_json`).
- `build_graph(llm, include_supervisor=True)` wires `intake → [4 critics in
  parallel] → merge → …`. Parallel writes merge via `operator.add` reducer.
- `src/main.py:run_pipeline()` — entry point, optionally accepts a pre-built
  `llm` so tests can inject a `MockProvider` and inspect `call_log`.
- `pyproject.toml` with `[tool.setuptools.packages.find] include = ["src*"]`
  so `pip install -e .` actually registers `src` as importable.

### Day 4 — Supervisor + streaming
- `src/agents/supervisor.py:run_supervisor_stream` — async generator with a
  4-state XML parser (scan / thinking / verdict / post_verdict) that holds a
  20-char tail guard so no character possibly belonging to a close tag is
  emitted early. Works on 1-char-at-a-time chunks (regression test exists).
- Events: `{stage: "thinking"|"verdict"|"done", ...}`.
- `run_supervisor` is a non-streaming drain. Graceful degrade on JSON parse:
  returns `{"executive_summary": "parse failed: ...", ...}` placeholder.
- Streamlit: two-phase run. Phase 1 runs the graph without supervisor, paints
  4 critic tabs; Phase 2 streams supervisor into an `st.empty()` placeholder
  with a `▌` cursor glyph, then renders the structured P0/P1/P2 card.
- **Stream-delay gotcha**: `MockProvider.stream()` sleeps `MOCK_STREAM_DELAY`s
  (default 0.02s) per word so Streamlit has wall-clock time to paint between
  deltas. `tests/conftest.py` sets `MOCK_STREAM_DELAY=0` to keep suite fast.

### Day 5 — Cross-challenge
- `src/graph/edges.py:run_cross_challenge` — sequential rounds, parallel
  within a round (`asyncio.gather`). Three safety layers:
  1. `MAX_CROSS_CHALLENGE_ROUNDS` from config (default 2).
  2. Empty-round-1 early exit → `convergence_signal=True`.
  3. `difflib.SequenceMatcher` ratio on sorted challenge blobs;
     `CONVERGENCE_SIMILARITY_THRESHOLD = 0.75` (TODO: swap for real embeddings
     — 0.85 is the embeddings number, 0.75 is the SequenceMatcher analogue).
- Per-critic wrappers `run_<critic>_challenge(...)` delegating to
  `run_challenger()` in `_shared.py`. Post-parse forces `challenger` and
  `round` fields server-side to prevent spoofing.
- Graph now: `intake → [4 critics] → merge → cross_challenge → supervisor → END`.
- Supervisor's user message carries the challenges list; prompt updated with
  "if CrossChallenges are present, you MUST surface them in
  `conflict_resolutions`".
- Streamlit has a "🔀 Cross-Challenge" section between critic tabs and the
  supervisor box, with ✅/⚠️ convergence badge and per-round `st.expander`
  listings.

### Day 6 — HITL critique dialog
- `src/agents/critique_dialog.py` — new module. `run_critique_dialog(critic_id,
  original_critique, prd_text, conversation_history, llm)` yields
  `{"type":"text","delta":...}` chunks. Reuses each critic's base SYSTEM_PROMPT
  and appends a DIALOG MODE preamble that forbids new findings / JSON output.
  Hard 5-round cap enforced in Python (`MAX_DIALOG_ROUNDS`); after the model
  reply, a terminator chunk is appended so the UI can freeze the input.
- `src/llm/mock_provider.py` — new branch in `_match`: when the system prompt
  contains `"dialog mode"` / `"讨论这个问题"` / `"discussion"`, returns a 2–3
  sentence flavour line keyed by critic_id (engineering = systems lens,
  business = commercial lens, etc.). The routing check sits above the plain-
  critic fallback, because dialog prompts are `<critic prompt> + <preamble>`.
- `src/ui/streamlit_app.py` — rewritten to persist run state in
  `st.session_state["run"]`. The whole pipeline now runs exactly once per
  "Run Stress Test" click; subsequent reruns (e.g. from clicking "💬 Discuss")
  re-render from cache. Each rendered critique now has a "💬 Discuss" button
  that opens an inline `st.chat_message` panel. Dialog state lives in
  `st.session_state["active_dialogs"][critique_uid]`, where `critique_uid` is
  `sha1(critic_id|claim_id|finding)[:10]` so it survives reruns. Multiple
  dialogs can be open simultaneously, each independent. After 5 user turns
  the `st.chat_input` is replaced with a "cap reached" info box.
- `tests/test_critique_dialog.py` — 9 tests covering:
  * dialog system prompt correctly routes by critic_id (4 parametrized cases),
  * unknown critic_id falls back gracefully rather than KeyError,
  * stream yields at least one text delta,
  * mock flavour differs between critic ids (engineering vs business),
  * 5-round cap appends the terminator chunk,
  * below-cap conversations do NOT emit the terminator.

**Test suite: 24 tests, 0 warnings, runs in <0.7s.**

---

## 3. Tech stack and key file paths

- Python 3.11+ (installed against 3.14 locally), LangGraph 1.x, Pydantic v2,
  Streamlit ≥1.40, pytest + pytest-asyncio.
- No ML deps yet. `difflib` (stdlib) for similarity. No sentence-transformers.

| Concern                          | Path                                                  |
| -------------------------------- | ----------------------------------------------------- |
| LLM abstraction base             | `src/llm/provider.py`                                 |
| MockProvider                     | `src/llm/mock_provider.py`                            |
| Provider factory (swap point)    | `src/config.py` — `get_critic_llm`, `get_supervisor_llm` |
| State schema (TypedDict + models)| `src/graph/state.py`                                  |
| Graph assembly                   | `src/graph/builder.py`                                |
| Cross-challenge orchestrator     | `src/graph/edges.py`                                  |
| Line-numbering preprocessor      | `src/graph/preprocess.py`                             |
| Pipeline entry                   | `src/main.py`                                         |
| Intake agent                     | `src/agents/intake.py`                                |
| Critic agents                    | `src/agents/critics/{user_advocate,engineering,business,design}.py` |
| Shared critic machinery          | `src/agents/critics/_shared.py` (run_critic, run_challenger, prompt fragments) |
| Supervisor (incl. XML streamer)  | `src/agents/supervisor.py`                            |
| JSON-parse helper                | `src/agents/_parsing.py`                              |
| Streamlit app                    | `src/ui/streamlit_app.py`                             |
| Golden PRDs + manifest           | `src/eval/golden_prds/` (5 `.md` + `manifest.yaml`)   |
| Rubric stubs                     | `src/eval/rubric.py`                                  |
| Tests                            | `tests/test_{mock_provider,pipeline,supervisor,cross_challenge}.py` |
| Package config                   | `pyproject.toml`                                      |

Install + run:

```
pip install -e .
pip install -r requirements.txt
pytest tests/ -W error          # expect 15 passed
streamlit run src/ui/streamlit_app.py
```

---

## 4. LLM provider swap point

Every agent goes through `src/config.py:get_critic_llm()` and
`get_supervisor_llm()`. Today both return a fresh `MockProvider()` when
`LLM_PROVIDER=mock` (default in `.env.example`).

When the school OpenAI key arrives:

1. Add `openai` to `requirements.txt`.
2. Create `src/llm/openai_provider.py` implementing `LLMProvider.complete`
   and `LLMProvider.stream`. Stream chunks must be shaped as
   `{"type": "text", "delta": str}` to match what the supervisor XML parser
   and the Streamlit UI expect.
3. In `src/config.py`, fill in the `TODO` branches:
   ```python
   if PROVIDER == "openai":
       return OpenAIProvider(model="gpt-4o-mini", ...)
   ```
4. Flip `.env` → `LLM_PROVIDER=openai` and add the key.

**No agent code, no graph code, no UI code needs to change.** That separation
is the whole reason for the provider abstraction.

---

## 5. Known issues and deferred work

- **MockProvider is all happy-path.** Tests do not yet cover model returning
  malformed JSON, partial XML, or disconnects. Add a `FlakyMockProvider` in
  Day 6 or 7 when error paths start to matter.
- **`CONVERGENCE_SIMILARITY_THRESHOLD = 0.75` is a heuristic.** It matches
  `difflib.SequenceMatcher` behavior, not real semantic similarity. Replace
  once embeddings are available. See TODO in `src/graph/edges.py`.
- **Supervisor prompt has no token-budget guard.** Long PRD + 4 critics +
  challenges can exceed context. Not an issue under mock; add a truncation
  strategy before running against real OpenAI.
- **`SupervisorVerdict` schema is loose** — on validation failure,
  `_parse_verdict_json` falls back to a placeholder dict merged with whatever
  keys were parseable. Good for resilience, bad for strict eval scoring.
- **Rubric functions are stubs** (`src/eval/rubric.py`). Implementation is
  scheduled alongside the eval harness (Day 7).
- **Skill Library is architecturally wired but inert.** Critic prompts honor
  a `<retrieved_skills>` block if present; no retriever or MCP server exists
  yet. The `skill_id` field on every critique is always `null` in current runs.
- **No CrossChallenge telemetry.** `state.challenges` is produced and shown
  in UI but not yet logged to `data/results/` for later analysis.
- **Streamlit UI is functional but unstyled.** Day 6 added HITL but not polish
  (card borders, sticky header, dark-mode verification). Rolled into a Day 7
  stretch goal if time permits.
- **Dialog module only runs against MockProvider so far.** The flavour branch
  in the mock always returns a single canned 3-sentence reply; it does NOT
  grow the reply based on the PM's actual question. Good enough for UI demo,
  won't pass scrutiny once OpenAI is wired.
- **No MCP server.** Day 8/9.

---

## 6. Next — Day 7: Skill Library + MCP Server (first cut)

The Skill Library is the project's long-term differentiator — cross-PRD
reusable review heuristics exposed as structured `skill_id`s that critics
can cite. Today it's architecturally wired (prompt contract exists, critics
know how to consume `<retrieved_skills>`, telemetry field is on every
Critique) but there is no retriever and no server.

### 7a. Skill Library data layer

- `src/skills/` new package:
  * `store.py` — minimal SQLite or file-backed store. Schema:
    `skill_id, name, body, dimension, created_at, hit_count`.
  * `seed.py` — load 10–20 bootstrap skills derived from recurring findings
    in the 5 golden PRDs. `SK-042: metric-triple-check`,
    `SK-017: stripe-idempotency-key`, etc.
  * `retriever.py` — for a given PRD (or list of PRDClaims), return the
    top-K skills. Start with keyword matching (no embeddings yet);
    upgrade later.
- Wire the retriever into `src/main.py:run_pipeline`: after intake, before
  critics, fetch skills and set `state["retrieved_skills"]`. Each critic's
  user message gets a `<retrieved_skills>` block prepended.
- Extend `tests/` with `test_skill_retrieval.py`: given a PRD with a metric
  claim, `SK-042` comes back in the top-K.

### 7b. MCP server (first cut)

- `src/mcp_server/` — minimal MCP server exposing two tools:
  * `search_skills(query: str, k: int) → list[Skill]`
  * `record_skill_hit(skill_id: str) → None` (increments `hit_count`)
- Stdio transport first; HTTP can come later.
- Register it in `.mcp.json` at repo root so `claude mcp list` sees it.
- Dogfood check: run a fresh PRD through the pipeline and confirm at
  least one critique comes back with a non-null `skill_id`.

### 7c. (Stretch) Frontend polish carried over from original Day 6 plan

- Card-style layout with consistent borders and padding.
- Unified severity-chip helper used by critic findings, verdict, and challenges.
- Sticky header with claim / critique / challenge / verdict counts.
- Dark-mode verification of the `#c62828` / `#ef9a00` / `#6d6d6d` palette.
- Optional "Raw state JSON" debug expander.

### Out of scope for Day 7

- OpenAI wiring (Day 8), eval harness (Day 9), persistence to
  `data/results/` (Day 9), embedding-based similarity (Day 10).

---

## Quick sanity checklist before starting Day 7

```
pip install -e .                   # package installs
pytest tests/ -W error             # 24 pass, 0 warnings
streamlit run src/ui/streamlit_app.py
  → Pick a golden PRD → Run
  → 4 critic tabs populate; each critique has a "💬 Discuss" button
  → Cross-Challenge shows ✅ Converged after round 2, one expander with 3 challenges
  → 🟡 Thinking (done) block visible, 🟢 Verdict rendered
  → Click "💬 Discuss" on any critique → chat panel opens inline
  → Type a question → assistant reply streams word-by-word
  → After 5 user turns, chat_input is replaced by a "cap reached" info box
  → "💬 Close discussion" hides the panel; reopening preserves history
```

If any step above fails, do NOT start Day 7 — fix the regression first.
