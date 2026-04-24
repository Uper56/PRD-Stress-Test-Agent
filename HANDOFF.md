# HANDOFF — PRD Stress Test Agent

## 1. Project in one sentence

A multi-agent system that takes a PRD as input, runs 4 parallel critic agents
(User Advocate / Engineering / Business / Design), performs up to 2 rounds of
cross-challenge between them, and has a Supervisor agent synthesize a
structured, severity-ranked blindspot report. The long-term differentiator is
a Skill Library (cross-PRD reusable review heuristics) exposed via a custom
MCP server — not yet implemented.

---

## 2. Progress — Days 1 through 7

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

### Day 7 — Skill Library + MCP Server (read-only)
- **Data layer** (`src/skills/`):
  * `schema.py` — `Skill` (adds `prompt_fragment_content` as a load-time-only
    field) + `SkillLibrary` container with `by_id` / `active` helpers.
  * `library.yaml` — 6 seed skills covering engineering (2) /
    business / user_advocate / design / multi-role: `skl_001_api_dependency_enumeration`,
    `skl_002_quantified_metrics`, `skl_003_phased_rollout`,
    `skl_004_accessibility_check`, `skl_005_user_evidence`,
    `skl_006_internal_contradiction`.
  * `fragments/*.md` — one fragment per skill, following the
    `When to apply / Instruction to inject / Rationale / Examples` shape.
    Non-trivial content; each lists 3–6 concrete failure modes.
  * `retriever.py` — `SkillRetriever.load_library()` reads YAML + every
    fragment; `.retrieve(prd_text, critic_id, top_k=3)` filters by
    `injected_into`, ranks by case-insensitive keyword hits (word-boundary
    for single-word keywords, substring for multi-word). Zero-hit skills
    are NOT force-injected — prompt stays clean. `format_skills_block()`
    renders the winners as the `<retrieved_skills>` XML the critics expect.
  * `mcp_client.py` — in-process mirror of the MCP server tool surface
    (`list_skills`, `read_skill`, `search_skills`). Same signatures as
    the real server; exists so tests and Streamlit can hit the tools
    without spawning a subprocess. Swap to transport-backed client later
    with one import change.
- **MCP server** (`src/mcp_servers/skill_server.py`): **real FastMCP server**,
  not a stub. Uses `mcp.server.fastmcp.FastMCP`, exposes the three tools
  above, stdio transport. Run with `python -m src.mcp_servers.skill_server`.
  README in `src/mcp_servers/README.md` documents launch + `.mcp.json`
  registration. `mcp>=1.0` added to `requirements.txt`.
- **Critic integration** (`src/agents/critics/_shared.py:run_critic`):
  before the LLM call, retrieves top-K skills for the critic, prepends a
  `<retrieved_skills>` block to the user message, and post-processes the
  model's output so:
  * Hallucinated `skill_id`s not in the retrieved set are dropped to `None`.
  * Critiques with no model-attributed `skill_id` get backfilled with the
    top retrieved skill's id, so telemetry survives even when the model
    forgets to cite. Retrieval failures degrade to "no skills, continue".
- **Streamlit extensions** (`src/ui/streamlit_app.py`):
  * `📚 Skill Library` sidebar panel rendered from `mcp_client.list_skills`,
    one expander per skill showing name / injected_into / confidence /
    description, with a "Show fragment" button that calls
    `mcp_client.read_skill` on demand. "📌 Pin" / "🗑 Deprecate" buttons
    are visible but disabled — Day 8 wires them up.
  * Each critique card now renders a `💡 Triggered by <skl_id>` chip when
    `skill_id` is non-null. On a real golden PRD all four critics fire with
    a skill_id populated.
- **Tests** (`tests/test_skill_retriever.py`, 11 cases): library load +
  fragment read, critic filtering, API-heavy ranking, no-match empty result,
  XML block shape, end-to-end critic stamping, no-false-positive when
  keywords are absent, MCP client list/read/search (including unknown-id
  raises, filtered vs unfiltered search).

**Test suite: 35 tests, 0 warnings, runs in <0.6s.**

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
| Skill Library schema + retriever | `src/skills/{schema,retriever}.py`                    |
| Skill library data               | `src/skills/library.yaml` + `src/skills/fragments/*.md` |
| MCP server (read-only)           | `src/mcp_servers/skill_server.py` + `README.md`       |
| MCP in-process client mirror     | `src/skills/mcp_client.py`                            |
| Critique dialog (HITL)           | `src/agents/critique_dialog.py`                       |
| Tests                            | `tests/test_{mock_provider,pipeline,supervisor,cross_challenge,critique_dialog,skill_retriever}.py` |
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
- **Skill Library shipped Day 7.** Retriever is keyword-based; see technical
  debt section for the upgrade plan to embeddings (Day 10).
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

## 6. Technical debt ledger

Things that are intentionally cut corners. Each has a "must fix by" gate
so they don't silently rot.

| # | Debt | Must fix by | Owner note |
| - | ---- | ----------- | ---------- |
| D-01 | `CONVERGENCE_SIMILARITY_THRESHOLD = 0.75` is a `difflib.SequenceMatcher` heuristic, not semantic similarity. | Day 10 (embeddings). | `src/graph/edges.py` |
| D-02 | Skill retriever is keyword-based only. No synonyms, no embeddings, no learned weights. Confidence field is authored, never updated. | Day 10. | `src/skills/retriever.py` |
| D-03 | Skill Library is read-only. Distiller / curator / pin / deprecate write tools not yet built (UI buttons exist but disabled). | Day 8. | `src/skills/`, Streamlit sidebar |
| D-04 | `SupervisorVerdict` schema is loose — parse failures fall back to a placeholder dict merged with whatever keys were parseable. | Day 9 eval harness. | `src/agents/supervisor.py` |
| D-05 | No CrossChallenge / critique / skill-hit telemetry persisted to `data/results/`. | Day 9. | — |
| D-06 | Dialog module works only against MockProvider flavour text; it does NOT grow the reply based on the PM's question. Fine for demo, won't pass real eval. | Day 8 OpenAI wiring. | `src/llm/mock_provider.py` |
| D-07 | Supervisor prompt has no token-budget guard. | Before first OpenAI call. | `src/agents/supervisor.py` |
| D-08 | Streamlit UI is functional but unstyled — card borders, sticky header, dark-mode verification. | Rolled as Day 8 stretch. | `src/ui/streamlit_app.py` |

**Note on MCP server:** Day 7 shipped a *real* FastMCP stdio server, not the
fallback `mcp_client.py`-only path. Both surfaces exist and share the same
`SkillRetriever`. If a future change breaks the FastMCP import, falling
back to `mcp_client.py` alone is legitimate — but flag it explicitly in
this table with a "revert by Day 10" gate.

---

## 7. Next — Day 8: Skill Distiller + Curator (write path)

Day 7 shipped the read path. Day 8 adds the write path: a Distiller agent
that proposes new skills after a run, a Curator UI that lets a human
accept / deprecate / pin them, and the supporting MCP write tools.

### 8a. Distiller agent

- `src/agents/distiller.py:run_distiller(state, llm) -> list[Skill]`.
  Input: the full post-supervisor `GraphState` (critiques + challenges +
  verdict + PRD text). Output: 0–3 candidate skills phrased as
  `Skill(status="proposed", created_by="distiller", learned_from_prds=[...])`.
- Trigger heuristic: only propose a new skill when a critique carries
  `skill_id=None` AND the finding's pattern repeats across critiques /
  across PRDs (check `data/results/` history once it exists).
- Prompt shape mirrors the fragment .md skeleton so the agent's output can
  be written straight to disk if accepted.

### 8b. Curator UI + write tools

- `src/skills/writer.py`: `accept_skill(draft) → Skill`, `deprecate_skill(id)`,
  `pin_skill(id)`. Acceptance writes to `library.yaml` + `fragments/*.md`
  atomically (temp-file + rename); deprecate flips `status`.
- New MCP tools on `skill_server`: `propose_skill`, `accept_skill`,
  `deprecate_skill`. Every write goes through a human-in-the-loop gate —
  the server's `accept_skill` will refuse unless the caller passes an
  `approved_by` token set in the Streamlit UI.
- Enable the `📌 Pin` / `🗑 Deprecate` buttons in the sidebar (currently
  disabled placeholders). Wire a "Proposed skills" section that shows the
  distiller's output after each run with Accept / Reject buttons.

### 8c. OpenAI wiring (parallel track if the key arrives)

- `src/llm/openai_provider.py` implementing `complete` + `stream` with
  chunks shaped as `{"type":"text","delta":str}`.
- Flip `src/config.py` branches, set `LLM_PROVIDER=openai` in `.env`.
- Add token-budget guard on supervisor prompt (debt D-07).

### Out of scope for Day 8

- Eval harness (Day 9), persistence to `data/results/` (Day 9),
  embedding-based similarity (Day 10), frontend polish (stretch any day).

---

## Quick sanity checklist before starting Day 8

```
pip install -e .                              # package installs
pip install -r requirements.txt               # includes mcp>=1.0
pytest tests/ -W error                        # 35 pass, 0 warnings
python -m src.mcp_servers.skill_server        # stdio server starts; Ctrl-C to exit
streamlit run src/ui/streamlit_app.py
  → Sidebar "📚 Skill Library" shows 6 active skills
  → Each has an expander; "Show fragment" renders the full .md
  → Pick a golden PRD → Run
  → Every critique card carries a "💡 Triggered by skl_xxx" chip
  → "💬 Discuss" buttons still work (Day 6 regression)
  → Cross-Challenge + Supervisor sections unchanged (Day 5/4 regression)
```

If any step above fails, do NOT start Day 8 — fix the regression first.
