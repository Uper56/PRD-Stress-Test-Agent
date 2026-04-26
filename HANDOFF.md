# HANDOFF — PRD Stress Test Agent

## 1. Project in one sentence

A multi-agent system that takes a PRD as input, runs 4 parallel critic agents
(User Advocate / Engineering / Business / Design), performs up to 2 rounds of
cross-challenge between them, and has a Supervisor agent synthesize a
structured, severity-ranked blindspot report. The long-term differentiator is
a Skill Library (cross-PRD reusable review heuristics) exposed via a custom
MCP server — not yet implemented.

---

## 2. Progress — Days 1 through 9

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

### Day 8 — Telemetry persistence + skill usage tracking
**Plan change**: original Day 8 was Distiller + Curator, but Distiller depends
on cross-PRD pattern detection which requires run history. Pulled forward
the original D-05 (telemetry persistence) so Distiller has data to consume.
Original Day 8 → new Day 9. Original Day 9 → new Day 10.

- **Run history** (`src/storage/`):
  * `history_store.py:RunRecord` — Pydantic model: `run_id`, ISO timestamp,
    optional `prd_filename`, sha256 `prd_text_hash`, 500-char excerpt,
    serialized critiques + challenges + supervisor_verdict,
    `retrieved_skill_ids` / `skill_hits` / `skill_misses`, plus token /
    cost slots wired but mock-fed.
  * `HistoryStore.save(state, prd_filename=None)` — atomic JSON write
    (`tempfile → os.replace`). Per-run file under
    `data/results/history/run_<YYYYMMDD_HHMMSS>_<id8>.json`. One-line
    summary appended to `index.jsonl` (no excerpt, no full critiques —
    keeps the index small forever).
  * `list_recent(n)` reads the index only, sorts newest-first, hydrates
    each run lazily from its JSON.
  * `query(only_misses=True, since=...)` — Day 9 distiller's input; filters
    runs containing at least one critique with `skill_id is None`.
  * Skill telemetry (`retrieved_skill_ids` etc.) is recomputed at save
    time by re-running the retriever per critic — avoids threading a new
    list reducer through the graph.
  * All disk failures are caught and logged, not raised. Pipeline never
    breaks because telemetry broke.
- **Skill usage write-back** (`src/skills/curator.py`):
  * `SkillCurator.increment_usage(ids)` — dedups within a single call,
    bumps `usage_count` for matching skills, atomic-writes `library.yaml`,
    busts the retriever's in-memory cache so the sidebar reflects the
    new counts on the next read.
  * Persistence uses PyYAML (no new dependency). Inline comments on
    individual entries are not preserved; the file's leading header
    block IS preserved by re-prepending a hardcoded canonical header on
    every write. Each skill's keys are reordered to a canonical sequence
    so diffs stay tight.
  * `update_acceptance` and `deprecate` are stubs — they raise
    `NotImplementedError` with a Day 9 message. Importable today;
    callable Day 9.
- **Pipeline integration** (`src/main.py`):
  * `run_pipeline(..., persist=None, prd_filename=None)`. When
    `include_supervisor=True` and `persist` is unset, defaults to writing
    history + bumping usage. When `include_supervisor=False`, auto-persist
    is skipped because the verdict isn't part of the merged state yet —
    the caller (Streamlit two-phase) is expected to call
    `persist_run(state)` itself after streaming the verdict.
  * `PRD_PIPELINE_PERSIST=0` env var (set by `tests/conftest.py`) keeps
    the suite hermetic.
- **Streamlit sidebar**:
  * `📊 Run History` panel above the Skill Library — shows the 20 most
    recent runs, each expander surfaces P0/P1/P2 counts, executive
    summary, full grouped verdict, and a nested critique-detail expander
    with per-critique skill chip.
  * Each Skill Library expander now displays `used N×` next to the id
    and again inside the body, so you can see usage growth between runs.
- **Tests** (18 new):
  * `tests/test_history_store.py` (10): round-trip save/load,
    newest-first ordering, n-cap, empty-history baseline, index.jsonl
    summary shape (no full bodies), `query(only_misses)` filtering,
    `query(since)` filtering, atomic-write rollback on simulated crash,
    save-failure-returns-None contract, skill hits/misses computation.
  * `tests/test_skill_curator.py` (8): single-id increment, multi-id
    independence, dedup-within-call, unknown-id no-op, empty-input no-op,
    canonical header preserved on rewrite, key order preserved,
    Day-9 stubs raise `NotImplementedError`.

**Test suite: 53 tests, 0 warnings, runs in <5.5s** (the extra time is from
two `time.sleep(1.1)` calls in the history-store ordering tests — they need
distinct seconds-precision timestamps).

### Day 8.5 — Migrate to Anthropic Agent Skills `SKILL.md` spec
**Why now**: The Day 7 layout (`library.yaml` + `fragments/*.md`) was the
2024 way. Anthropic shipped the **Agent Skills `SKILL.md` spec** in
December 2025 — folder-per-skill, frontmatter + Markdown body, telemetry
decoupled — and OpenAI Codex CLI adopted the same shape. Migrating now
means the Day 9 Distiller writes spec-compliant skills from day one,
nothing is grandfathered in.

- **Format**: each skill is `src/skills/seed/<kebab-name>/SKILL.md`
  (or `src/skills/learned/<kebab-name>/SKILL.md` for distiller output).
  YAML frontmatter holds `name` / `description` / `version` /
  `created_by` / `injected_into` (+ optional `trigger_keywords` /
  `trigger_semantic` / `confidence`); Markdown body holds the prompt
  fragment. See `docs/skill_format.md` for the full spec mapping.
- **Telemetry decoupling**: `src/skills/runtime_stats.yaml` is the
  ONLY file touched by `SkillCurator` between PRD runs. Each skill's
  `SKILL.md` stays diff-clean across hundreds of runs — PR review of
  skill content is no longer drowned by `usage_count` churn.
- **Schema split** (`src/skills/schema.py`):
  * `SkillDefinition` — frontmatter + body (design-time)
  * `SkillRuntimeStats` — usage_count / acceptance_rate / status
    (runtime, keyed by name in `runtime_stats.yaml`)
  * `Skill` — flat merged view returned by the retriever; preserves
    the legacy `id` field (= `name`) so historical `RunRecord`
    payloads with `retrieved_skill_ids` keep their semantics.
- **Retriever**: scans `seed/` and `learned/` for SKILL.md folders,
  parses frontmatter via a homegrown 30-line parser (no
  `python-frontmatter` dependency), merges `runtime_stats.yaml` at
  load time. Public surface (`retrieve` / `format_skills_block` /
  `default_retriever`) is unchanged — critic code untouched.
- **Curator**: `increment_usage` now mutates `runtime_stats.yaml`,
  also stamps `last_used` (ISO 8601 UTC). Atomic write helper reused.
- **MCP server / client**: `list_skills`, `read_skill`, `search_skills`
  return the new shape. **New tool `read_skill_md(skill_name)`**
  returns the raw `SKILL.md` text verbatim — same bytes any
  spec-compliant consumer (Anthropic, Codex CLI) would see.
- **Streamlit**:
  * Top-of-page badge: 🏷️ Anthropic Agent Skills v1.0 compliant.
  * Sidebar shows skill `name`, version, created_by, usage count,
    description (frontmatter `description`), and a "Show SKILL.md"
    button that renders the body.
- **Tests** (8 new, 18 updated):
  * `tests/test_skill_md_format.py` (7) — parametrized over every
    SKILL.md on disk; validates kebab-case name = folder name,
    required frontmatter fields, allowed `created_by` values,
    `injected_into` non-empty + only known critic ids, body non-empty.
  * `tests/test_skill_retriever.py` rewritten to assert kebab-case
    names; new test for `read_skill_md` round-tripping the raw file.
  * `tests/test_skill_curator.py` rewritten against the new
    `runtime_stats.yaml` schema (header preservation, key order,
    `last_used` stamping, dedup, unknown-name no-op).
  * `tests/test_history_store.py` updated: skill name in the telemetry
    test is now `api-dependency-enumeration`.
- **Archive**: pre-Day-8.5 layout sits under `src/skills/_archive/`
  (`library.yaml` + `fragments/`) for one-commit rollback safety.
  Not loaded by the runtime. Delete after a few days of no regression.
- **New doc**: `docs/skill_format.md` — interview-ready explainer of
  why we switched, what the spec requires, how our extensions map,
  and how to author a new skill.

**Test suite: 61 tests, 0 warnings.**

### Day 9 — Skill Distiller + Curator advanced + HITL approval loop

The closed loop: **Run PRD → Telemetry → Distiller → Proposal → HITL
Approve → Skill in `learned/` → Next run uses it → Acceptance feedback →
Curator updates stats → Auto-deprecate if low quality.**

- **Distiller agent** (`src/agents/skill_distiller.py`):
  * `run_distiller(llm, history_store, min_pattern_frequency=3,
    min_runs_required=3)` returns `list[SkillProposal]`. Pulls misses
    via `HistoryStore.query(only_misses=True)`, clusters by
    `(critic_id, finding similarity)` using
    `difflib.SequenceMatcher` ≥0.6 (TODO: upgrade to embeddings —
    debt D-10), drops clusters spanning <3 distinct PRDs.
  * For each surviving cluster the LLM is asked for ONE proposal:
    `proposed_name` (kebab), full `proposed_skill_md` with frontmatter,
    `injected_into`, `generalization_score`. Evidence (`run_id` +
    `critique_excerpt`, ≥3 rows) is filled in code, NOT trusted from
    the LLM.
  * Belt-and-braces validation: drops proposals if
    `generalization_score < 0.7`, fewer than 3 evidence rows, evidence
    missing `run_id`, name not kebab-case, frontmatter
    missing required fields, `created_by ≠ "distiller"`, frontmatter
    `name` ≠ `proposed_name`, body empty.
  * Hard guard at the top: if total history < `min_runs_required`,
    returns `[]` with a warning. No founder-fiction skills.
- **SkillProposal schema**: `proposal_id` / `proposed_name` /
  `proposed_skill_md` / `injected_into` / `generalization_score` /
  `evidence: list[{run_id, critique_excerpt}]` / `pattern_frequency`
  (distinct PRDs) / `created_at` / `status` ∈
  `{pending, approved, rejected, edited}` / `rejection_reason`.
- **ProposalsStore** (`src/storage/proposals_store.py`):
  Per-proposal JSON under `data/results/proposals/`. Public methods:
  `save`, `list_pending`, `list_all`, `load`, `update_status`,
  `promote_to_skill`. Promotion writes the proposal's
  `proposed_skill_md` to `src/skills/learned/<name>/SKILL.md` AND
  seeds a fresh row in `runtime_stats.yaml` (active, usage_count=0,
  `created_by: distiller`); the in-process retriever cache is busted
  so the new skill is visible without a restart. All disk failures
  are absorbed.
- **SkillCurator upgrades** (`src/skills/curator.py`):
  * `update_acceptance(name, accepted)` — sliding window of length 20
    (configurable), serializes the window as JSON in
    `acceptance_history` so a restart doesn't reset the signal.
    `acceptance_rate` is recomputed on every sample.
  * `auto_deprecate()` — flips `status` to `"deprecated"` for any
    skill with `usage_count ≥ 5` AND `acceptance_rate < 0.30`.
    Conservative defaults so a bad week doesn't kill a skill.
    Returns the list of just-deprecated names.
  * `merge_duplicates(threshold=0.85)` — finds active skills with
    SequenceMatcher similarity ≥ threshold on
    `(description, sorted(injected_into))`. Loser of each pair keeps
    its `SKILL.md` on disk untouched, but its `runtime_stats` row
    flips to `"deprecated_merged_into_<winner>"`. Reversible by
    editing one file.
  * Old `update_acceptance` / `deprecate` `NotImplementedError` stubs
    are now actually implemented.
- **MockProvider extension** (`src/llm/mock_provider.py`): when the
  system prompt contains "skill distillation", returns a critic-keyed
  fake `SkillProposal` JSON with full SKILL.md text, generalization
  scores in 0.77–0.84, and three placeholder evidence rows. Different
  `critic_id` clusters produce visibly different proposals.
- **Pipeline integration** (`src/main.py`):
  * New env var `DISABLE_AUTO_DISTILL` (default `"1"` — OFF).
  * When enabled, after each `run_pipeline` we may invoke the
    Distiller synchronously: only if ≥5 runs in history AND ≥3 new
    runs since the last marker (`data/results/.last_auto_distill`).
    Failure is swallowed — telemetry never breaks the pipeline.
- **Streamlit upgrades** (`src/ui/streamlit_app.py`):
  * 🧪 **Skill Distillation** sidebar panel: shows
    `<runs in history> · <unhit critiques>`, a ▶️ Run Distiller
    button (loading spinner while the agent runs), and a card per
    pending proposal with name + generalization-score progress bar
    (🟢/🟡/🔴 colour code) + folded evidence list + folded full
    SKILL.md (editable in a `st.text_area`). Buttons:
    ✅ Approve (writes to `learned/<name>/SKILL.md`),
    ❌ Reject, ✏️ Save edit. Approve picks up any unsaved edits
    automatically.
  * Each critique card now carries ✓ Useful / ✗ Not useful buttons
    when a `skill_id` is attached. Clicking either calls
    `SkillCurator.update_acceptance(skill_id, accepted=...)` and
    locks the row so a single PRD review can't double-vote.
- **Tests** (16 new):
  * `tests/test_skill_distiller.py` (9): short-history guard,
    cluster grouping by critic_id, 4 validation rejections (low
    score / few evidence / missing run_id / non-kebab name), one
    happy-path validation, end-to-end promotion writes a
    spec-compliant SKILL.md the retriever immediately picks up,
    LLM-failure tolerance.
  * `tests/test_curator_advanced.py` (7): acceptance_rate sliding
    window math (single sample + window overflow), unknown-name
    no-op, auto_deprecate happy-path, two skip cases (below usage
    floor, no acceptance data), merge_duplicates demotes loser
    without deleting either SKILL.md file.

**Test suite: 77 tests, 0 warnings, runs in <6s.**

#### Standards compliance

- Each skill is one folder containing one `SKILL.md` with YAML
  frontmatter (`---` … `---`) followed by a Markdown body. ✅
- Required frontmatter fields (`name`, `description`, `version`) are
  present on all 6 seed skills and validated by
  `tests/test_skill_md_format.py`. ✅
- Project-specific extensions (`injected_into`, `trigger_keywords`,
  `confidence`) coexist with the spec fields without breaking
  spec-only consumers. ✅
- Runtime telemetry is decoupled in `runtime_stats.yaml` so the
  on-disk skill content is identical across runs. ✅
- An MCP tool (`read_skill_md`) returns the raw spec-compliant file
  bytes for any client that wants to render the canonical format. ✅

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
| Skill Library schema + retriever | `src/skills/{schema,retriever,curator}.py`            |
| Skill library data (SKILL.md spec) | `src/skills/seed/<name>/SKILL.md` + `src/skills/learned/<name>/SKILL.md` |
| Skill runtime telemetry          | `src/skills/runtime_stats.yaml`                       |
| Skill format docs                | `docs/skill_format.md`                                |
| Skill Distiller                  | `src/agents/skill_distiller.py`                       |
| Proposals store (HITL queue)     | `src/storage/proposals_store.py`                      |
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
| D-03 | Skill Library is read-only for skill *content*. Distiller / curator UI / pin / deprecate write tools not yet built (UI buttons exist but disabled). `usage_count` write-back shipped Day 8. | Day 9. | `src/skills/`, Streamlit sidebar |
| D-04 | `SupervisorVerdict` schema is loose — parse failures fall back to a placeholder dict merged with whatever keys were parseable. | Day 9 eval harness. | `src/agents/supervisor.py` |
| D-05 | ~~No CrossChallenge / critique / skill-hit telemetry persisted to `data/results/`.~~ **RESOLVED Day 8** — `HistoryStore` writes per-run JSON + `index.jsonl` summary; skill hits/misses recomputed at save time. | Day 8. ✅ | `src/storage/history_store.py` |
| D-06 | Dialog module works only against MockProvider flavour text; it does NOT grow the reply based on the PM's question. Fine for demo, won't pass real eval. | Day 8 OpenAI wiring. | `src/llm/mock_provider.py` |
| D-07 | Supervisor prompt has no token-budget guard. | Before first OpenAI call. | `src/agents/supervisor.py` |
| D-08 | Streamlit UI is functional but unstyled — card borders, sticky header, dark-mode verification. | Rolled as Day 8 stretch. | `src/ui/streamlit_app.py` |
| D-09 | ~~Day 9 Distiller MUST write spec-compliant SKILL.md folders…~~ **RESOLVED Day 9** — `src/agents/skill_distiller.py:_validate_proposal` rejects malformed proposals before they ever reach disk; `ProposalsStore.promote_to_skill` re-parses on the way out. | Day 9. ✅ | `src/agents/skill_distiller.py` |
| D-10 | Distiller clustering uses `difflib.SequenceMatcher` ≥ 0.6. Misses obvious near-paraphrases (different vocabulary, same concept). Same upgrade path as D-01/D-02 (sentence-transformers). | Day 10 (embeddings). | `src/agents/skill_distiller.py` |
| D-11 | Auto-distill is synchronous in `src/main.py:_maybe_auto_distill`. Fine under MockProvider (sub-second); blocks the request under real-API mode. Move to a worker queue or background task before flipping `DISABLE_AUTO_DISTILL=0` against OpenAI. | Before first OpenAI deployment. | `src/main.py` |

**Note on MCP server:** Day 7 shipped a *real* FastMCP stdio server, not the
fallback `mcp_client.py`-only path. Both surfaces exist and share the same
`SkillRetriever`. If a future change breaks the FastMCP import, falling
back to `mcp_client.py` alone is legitimate — but flag it explicitly in
this table with a "revert by Day 10" gate.

---

## 7. Next — Day 10: Ablation Study + Embedding upgrade

Day 9 closed the learning loop (Telemetry → Distiller → HITL → Skill in
library → Acceptance feedback → Curator). Day 10 turns the loop into a
measurable system and replaces the placeholder similarity heuristics with
real embeddings.

### 10a. Ablation harness (skills ON vs OFF)

- `src/eval/ablation.py:run_ablation(prd_paths, llm)` — runs each PRD
  twice: once with the Skill Library enabled, once with retrieval forced
  to return `[]` (ENV `DISABLE_SKILL_RETRIEVAL=1`). Compares:
  * Critique counts by severity.
  * P0/P1/P2 verdict deltas.
  * Defect-detection rate against the golden manifest's HTML-commented
    expected defects (`src/eval/golden_prds/manifest.yaml`).
  * Mean `acceptance_rate` of the on-run skills (from `runtime_stats.yaml`).
- Write results to `data/results/ablation/run_<ts>.json` and surface a
  side-by-side table in a new "📊 Ablation" sidebar tab.
- Pin a baseline number per golden PRD so Day 10+ regressions are visible.

### 10b. Embedding upgrade — kill three debts in one stroke

Resolves **D-01** (`CONVERGENCE_SIMILARITY_THRESHOLD`), **D-02** (skill
retriever ranking) and **D-10** (Distiller clustering).

- Add `sentence-transformers` to requirements; cache embeddings on disk
  under `data/embeddings/skills.npz` keyed by SKILL.md sha256.
- Replace the three SequenceMatcher call sites:
  1. `src/graph/edges.py` cross-challenge convergence — bump to 0.85
     cosine (the number we wanted but couldn't honour with difflib).
  2. `src/skills/retriever.py` keyword scoring — fold cosine similarity
     into the score; keep keyword count as a tie-break for transparency.
  3. `src/agents/skill_distiller.py` clustering — replace 0.6 ratio with
     0.75 cosine on finding embeddings; pre-cluster across PRDs in a
     single linkage pass.
- Provide a fallback in `src/embeddings/__init__.py` that returns
  difflib-based scores when the model can't load (no GPU / no network).

### 10c. OpenAI wiring (still parallel track)

- `src/llm/openai_provider.py` implementing `complete` + `stream` with
  chunks shaped as `{"type":"text","delta":str}`.
- Flip `src/config.py` branches, set `LLM_PROVIDER=openai` in `.env`.
- Add token-budget guard on supervisor prompt (debt D-07).
- Move `_maybe_auto_distill` to a background worker before
  flipping `DISABLE_AUTO_DISTILL=0` against the real API (debt D-11).

### Out of scope for Day 10

- Frontend polish (rolled forward indefinitely).
- Real-time event streaming for the Run History sidebar.

---

## Quick sanity checklist before starting Day 10

```
pip install -e .                              # package installs
pip install -r requirements.txt               # includes mcp>=1.0
pytest tests/ -W error                        # 77 pass, 0 warnings
python -m src.mcp_servers.skill_server        # stdio server starts; Ctrl-C to exit
streamlit run src/ui/streamlit_app.py
  → Top-of-page badge: 🏷️ Anthropic Agent Skills v1.0 compliant
  → Sidebar "📊 Run History" panel shows runs (empty on first launch — run once)
  → Sidebar "📚 Skill Library" shows 6 active kebab-named skills, each tagged "used N×"
  → "Show SKILL.md" button renders the full Markdown body
  → Pick a golden PRD → Run
  → After the run, data/results/history/run_<ts>_<id8>.json appears
  → data/results/history/index.jsonl gains a new line
  → Run History panel refreshes (rerun the app) and lists the new run
  → src/skills/runtime_stats.yaml: matching skills' usage_count incremented + last_used stamped
  → src/skills/seed/*/SKILL.md is UNCHANGED (telemetry decoupling working)
  → Every critique card carries a "💡 Triggered by skl_xxx" chip
  → ✓ Useful / ✗ Not useful buttons appear under critiques with a skill_id
  → Clicking either updates acceptance_rate + acceptance_history in runtime_stats.yaml
  → Run 5 different golden PRDs → "🧪 Skill Distillation" panel shows "5 runs in history"
  → Click "▶️ Run Distiller" → 0–N candidate cards appear (depends on miss patterns)
  → Approve a candidate → src/skills/learned/<name>/SKILL.md created
  → Next PRD run: new skill may appear as "💡 Triggered by <name>" on a critique
  → "💬 Discuss" buttons still work (Day 6 regression)
  → Cross-Challenge + Supervisor sections unchanged (Day 5/4 regression)
```

If any step above fails, do NOT start Day 10 — fix the regression first.
