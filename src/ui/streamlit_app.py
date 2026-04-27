"""Streamlit UI — select a golden PRD or paste your own, run the pipeline, view critiques.

Two-phase run for the UI:
  Phase 1. Graph through the merge node → render 4 critic tabs.
  Phase 2. Stream the supervisor separately → live `<thinking>` text, then a
           structured verdict (P0/P1/P2 grouped).
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import streamlit as st

import json

from src.agents.critique_dialog import MAX_DIALOG_ROUNDS, run_critique_dialog
from src.agents.skill_distiller import run_distiller
from src.agents.supervisor import run_supervisor_stream
from src.eval.ablation import (
    AblationConfig,
    DEFAULT_OUTPUT_DIR as ABLATION_OUTPUT_DIR,
    list_golden_prds,
    run_ablation,
)
from src.graph.state import Critique
from src.llm.mock_provider import MockProvider
from src.main import persist_run, run_pipeline
from src.skills.curator import SkillCurator
from src.skills.mcp_client import list_skills, read_skill_md
from src.storage import HistoryStore, ProposalsStore


GOLDEN_DIR = Path(__file__).resolve().parents[1] / "eval" / "golden_prds"

SEVERITY_COLOR = {"P0": "#c62828", "P1": "#ef9a00", "P2": "#6d6d6d"}

CRITIC_TABS = [
    ("user_advocate", "User Advocate"),
    ("engineering", "Engineering"),
    ("business", "Business"),
    ("design", "Design"),
]


def _load_golden_prds() -> dict[str, str]:
    """Return {filename: contents} for every .md PRD in the golden directory."""
    if not GOLDEN_DIR.exists():
        return {}
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(GOLDEN_DIR.glob("prd_*.md"))
    }


def _critique_uid(c: dict) -> str:
    """Stable short id for a critique, used as session_state key.

    Hashing (critic_id, claim_id, finding) means the same critique across
    reruns of the script yields the same id, so the dialog state survives
    Streamlit's top-to-bottom rerun model.
    """
    raw = f"{c.get('critic_id','?')}|{c.get('claim_id','?')}|{c.get('finding','')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _render_critique(c: dict) -> None:
    sev = c.get("severity", "P?")
    color = SEVERITY_COLOR.get(sev, "#888")
    uid = _critique_uid(c)

    st.markdown(
        f"<span style='background:{color};color:white;padding:2px 6px;"
        f"border-radius:4px;font-size:0.8em;'>{sev}</span> "
        f"<b>{c.get('finding', '')}</b>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"claim_id: {c.get('claim_id', '?')}  ·  "
        f"skill_id: {c.get('skill_id') or '—'}"
    )
    # "💡 Triggered by" tag — links this critique back to the skill that fired.
    skill_id = c.get("skill_id")
    if skill_id:
        st.markdown(
            f"<span style='background:#fff8d6;color:#7a5d00;padding:2px 8px;"
            f"border-radius:10px;font-size:0.8em;border:1px solid #e6d488;'>"
            f"💡 Triggered by <code>{skill_id}</code></span>",
            unsafe_allow_html=True,
        )

    st.markdown(f"**Evidence:** {c.get('evidence', '')}")
    st.markdown(f"**Suggested fix:** {c.get('suggested_fix', '')}")

    # HITL feedback row — only meaningful when a skill_id is attached.
    if skill_id:
        feedback = st.session_state.setdefault("critique_feedback", {})
        already = feedback.get(uid)
        col_yes, col_no, col_status = st.columns([1, 1, 4])
        if col_yes.button("✓ Useful", key=f"fb_yes_{uid}", disabled=already is not None):
            try:
                SkillCurator().update_acceptance(skill_id, accepted=True)
                feedback[uid] = "accepted"
                st.rerun()
            except Exception as e:  # pragma: no cover
                st.warning(f"feedback failed: {e}")
        if col_no.button("✗ Not useful", key=f"fb_no_{uid}", disabled=already is not None):
            try:
                SkillCurator().update_acceptance(skill_id, accepted=False)
                feedback[uid] = "rejected"
                st.rerun()
            except Exception as e:  # pragma: no cover
                st.warning(f"feedback failed: {e}")
        if already == "accepted":
            col_status.success("Recorded as ✓ useful — feeds skill acceptance_rate")
        elif already == "rejected":
            col_status.info("Recorded as ✗ not useful — feeds skill acceptance_rate")

    # Discuss button — opens a dialog for this critique.
    active = st.session_state.get("active_dialogs", {})
    is_open = uid in active
    label = "💬 Close discussion" if is_open else "💬 Discuss"
    if st.button(label, key=f"discuss_btn_{uid}"):
        dialogs = st.session_state.setdefault("active_dialogs", {})
        if is_open:
            dialogs.pop(uid, None)
        else:
            dialogs[uid] = {
                "critic_id": c.get("critic_id", "unknown"),
                "critique": c,
                "history": [],
                "rounds": 0,
            }
        st.rerun()

    if is_open:
        _render_dialog_panel(uid, active[uid])

    st.divider()


def _render_dialog_panel(uid: str, dialog: dict) -> None:
    """Inline dialog panel beneath a critique.

    Streams the critic's reply via `run_critique_dialog`. State lives in
    `st.session_state["active_dialogs"][uid]`, so closing and reopening the
    panel preserves history within the same session.
    """
    st.markdown(
        "<div style='border-left:3px solid #4a90e2;padding:6px 12px;"
        "margin:6px 0;background:rgba(74,144,226,0.06);'>"
        f"<b>🗨 Follow-up with <code>{dialog['critic_id']}</code></b>"
        "</div>",
        unsafe_allow_html=True,
    )

    history = dialog["history"]
    rounds = dialog["rounds"]

    # Replay the chat so far.
    for msg in history:
        role = msg["role"]
        with st.chat_message(role):
            st.markdown(msg["content"])

    cap_reached = rounds >= MAX_DIALOG_ROUNDS
    if cap_reached:
        st.info(
            f"🛑 Discussion cap reached ({MAX_DIALOG_ROUNDS} rounds). "
            "Close this dialog and open a new one if needed."
        )

    # Input — disabled once cap is hit.
    prompt = None
    if not cap_reached:
        prompt = st.chat_input(
            f"Ask {dialog['critic_id']} a follow-up…",
            key=f"chat_input_{uid}",
        )

    if prompt:
        # Record the user turn and immediately paint it.
        history.append({"role": "user", "content": prompt})
        dialog["rounds"] = rounds + 1
        with st.chat_message("user"):
            st.markdown(prompt)

        # Stream the assistant reply. Reconstructing a PRD-bearing Critique
        # from the stored dict keeps the dialog module's type contract honest.
        crit_dict = dialog["critique"]
        critique_obj = Critique.model_validate(
            {k: v for k, v in crit_dict.items() if k in Critique.model_fields}
        )
        prd_text = st.session_state.get("prd_text", "")

        placeholder_llm = st.session_state.get("dialog_llm") or MockProvider()
        st.session_state["dialog_llm"] = placeholder_llm

        with st.chat_message("assistant"):
            box = st.empty()
            accumulated = ""

            async def _consume() -> None:
                nonlocal accumulated
                async for ev in run_critique_dialog(
                    critic_id=dialog["critic_id"],
                    original_critique=critique_obj,
                    prd_text=prd_text,
                    conversation_history=history,
                    llm=placeholder_llm,
                ):
                    if ev.get("type") == "text":
                        accumulated += ev.get("delta", "")
                        box.markdown(accumulated + "▌")

            asyncio.run(_consume())
            box.markdown(accumulated)

        history.append({"role": "assistant", "content": accumulated})
        # Force a rerun so the chat_input clears and the cap check refreshes.
        st.rerun()


def _severity_chip(label: str, color: str) -> str:
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:4px;font-size:0.85em;'>{label}</span>"
    )


def _render_verdict(verdict: dict) -> None:
    st.markdown("#### Executive summary")
    st.info(verdict.get("executive_summary", "—"))

    groups = [
        ("P0 Blockers", "p0_blockers", "#c62828"),
        ("P1 Concerns", "p1_concerns", "#ef9a00"),
        ("P2 Suggestions", "p2_suggestions", "#6d6d6d"),
    ]
    for label, key, color in groups:
        items = verdict.get(key, []) or []
        st.markdown(
            f"{_severity_chip(label, color)} &nbsp; <b>({len(items)})</b>",
            unsafe_allow_html=True,
        )
        if not items:
            st.caption("— none —")
        else:
            for item in items:
                st.markdown(f"- {item}")

    conflicts = verdict.get("conflict_resolutions", []) or []
    if conflicts:
        st.markdown("#### Conflict resolutions")
        for c in conflicts:
            st.markdown(f"- {c}")


def _stream_supervisor_sync(state: dict, llm, thinking_box) -> tuple[str, dict]:
    """Run the async supervisor stream synchronously.

    Each `thinking` delta is appended into `thinking_box` via
    `container.markdown(accumulated)`; Streamlit repaints placeholders between
    awaits, so with MockProvider's per-word sleep the user sees word-by-word
    streaming. `verdict` deltas are collected silently — the structured render
    happens once from `final_verdict` after the stream closes.
    Returns (thinking_text, final_verdict_dict).
    """
    thinking_text = ""
    final_verdict: dict = {}

    async def _consume() -> None:
        nonlocal thinking_text, final_verdict
        async for event in run_supervisor_stream(state, llm):
            stage = event.get("stage")
            if stage == "thinking":
                thinking_text += event.get("delta", "")
                thinking_box.markdown(
                    f"<div style='color:#888;font-style:italic;white-space:pre-wrap;'>"
                    f"🟡 Thinking… {thinking_text}▌</div>",
                    unsafe_allow_html=True,
                )
            elif stage == "done":
                final_verdict = event.get("final_verdict", {}) or {}

    asyncio.run(_consume())

    # Freeze the thinking placeholder (drop the cursor glyph) once streaming ends.
    if thinking_text:
        thinking_box.markdown(
            f"<div style='color:#888;font-style:italic;white-space:pre-wrap;'>"
            f"🟡 Thinking (done) {thinking_text}</div>",
            unsafe_allow_html=True,
        )
    return thinking_text, final_verdict


def _run_and_cache(prd_text: str, *, prd_filename: str | None = None) -> None:
    """Run the pipeline once and stash everything we need for later reruns.

    Streamlit re-executes the script top-to-bottom on every widget interaction
    (buttons, chat_input, rerun). Without this cache, clicking "💬 Discuss"
    would re-run the LLM pipeline and wipe the supervisor's streamed verdict.
    """
    llm = MockProvider()

    with st.spinner("Running 4 critics in parallel…"):
        state = asyncio.run(
            run_pipeline(prd_text, llm=llm, include_supervisor=False)
        )

    critiques = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (state.get("critiques", []) or [])
    ]
    challenges = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in (state.get("challenges", []) or [])
    ]

    # Supervisor stream — consume it once, save the final verdict for rerenders.
    thinking_placeholder = st.empty()
    thinking_text, verdict = _stream_supervisor_sync(
        dict(state), llm, thinking_placeholder
    )

    # Persist now that we have the full picture (critics + challenges + verdict).
    # `run_pipeline` skipped auto-persist because we used include_supervisor=False.
    final_state = dict(state)
    final_state["final_report"] = verdict
    try:
        persist_run(final_state, prd_filename=prd_filename)
    except Exception as e:  # pragma: no cover — defensive
        st.warning(f"Run history not saved: {e}")

    st.session_state["run"] = {
        "prd_text": state.get("prd_text", prd_text),
        "claim_count": len(state.get("prd_claims", []) or []),
        "critiques": critiques,
        "challenges": challenges,
        "challenge_round": state.get("challenge_round", 0) or 0,
        "converged": bool(state.get("convergence_signal", False)),
        "thinking_text": thinking_text,
        "verdict": verdict,
    }
    # PRD text also top-level so the dialog module can read it without digging.
    st.session_state["prd_text"] = state.get("prd_text", prd_text)
    # Dedicated LLM for dialogs — does not share call_log with the pipeline.
    st.session_state.setdefault("dialog_llm", MockProvider())
    st.session_state.setdefault("active_dialogs", {})


def _render_run(run: dict) -> None:
    """Render a completed run from session_state (no LLM work done here)."""
    st.success(
        f"Intake extracted {run['claim_count']} claims · "
        f"critics produced {len(run['critiques'])} findings"
    )

    by_critic: dict[str, list[dict]] = {k: [] for k, _ in CRITIC_TABS}
    for d in run["critiques"]:
        by_critic.setdefault(d.get("critic_id", "unknown"), []).append(d)

    st.subheader("Critic findings")
    tabs = st.tabs([label for _, label in CRITIC_TABS])
    for (key, _label), tab in zip(CRITIC_TABS, tabs):
        with tab:
            items = by_critic.get(key, [])
            if not items:
                st.info("No findings from this critic.")
            for item in items:
                _render_critique(item)

    # ---- Cross-Challenge section --------------------------------------------
    st.subheader("🔀 Cross-Challenge")
    rounds = run["challenge_round"]
    if run["converged"]:
        st.success(f"✅ Converged after round {rounds}")
    else:
        st.warning(f"⚠️ Reached max rounds ({rounds}) without convergence")

    challenges_raw = run["challenges"]
    by_round: dict[int, list[dict]] = {}
    for d in challenges_raw:
        by_round.setdefault(d.get("round", 0), []).append(d)

    if not challenges_raw:
        st.caption("No challenges raised — all critics accepted each other's findings.")
    else:
        for rn in sorted(by_round.keys()):
            items = by_round[rn]
            with st.expander(
                f"Round {rn} — {len(items)} challenge(s)", expanded=False
            ):
                for ch in items:
                    st.markdown(
                        f"**{ch.get('challenger', '?')}** → "
                        f"`{ch.get('target_critique_id', '?')}`"
                    )
                    st.markdown(f"↪ {ch.get('counter_finding', '')}")
                    st.divider()

    # ---- Supervisor verdict (cached from the one-time stream) ---------------
    st.subheader("Supervisor decision")
    thinking_text = run.get("thinking_text") or ""
    if thinking_text:
        st.markdown(
            f"<div style='color:#888;font-style:italic;white-space:pre-wrap;'>"
            f"🟡 Thinking (done) {thinking_text}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("### 🟢 Verdict")
    _render_verdict(run.get("verdict") or {})


def _render_run_history_sidebar() -> None:
    """List the most recent runs persisted to `data/results/history/`."""
    st.sidebar.header("📊 Run History")
    try:
        runs = HistoryStore().list_recent(n=20)
    except Exception as e:  # pragma: no cover
        st.sidebar.error(f"Failed to load history: {e}")
        return

    if not runs:
        st.sidebar.caption("No runs yet — kick one off to populate.")
        return

    st.sidebar.caption(f"{len(runs)} most-recent run(s)")
    for r in runs:
        verdict = r.supervisor_verdict or {}
        p0 = len(verdict.get("p0_blockers", []) or [])
        p1 = len(verdict.get("p1_concerns", []) or [])
        p2 = len(verdict.get("p2_suggestions", []) or [])
        title = (
            f"{r.timestamp[:19].replace('T',' ')} · "
            f"{r.prd_filename or 'custom input'}"
        )
        with st.sidebar.expander(title, expanded=False):
            st.caption(
                f"P0 {p0} · P1 {p1} · P2 {p2}  ·  critiques {len(r.critiques)}"
                f"  ·  hits {len(r.skill_hits)} · misses {len(r.skill_misses)}"
            )
            if verdict.get("executive_summary"):
                st.markdown(f"**Summary** — {verdict['executive_summary']}")
            for label, key in (("P0", "p0_blockers"), ("P1", "p1_concerns"), ("P2", "p2_suggestions")):
                items = verdict.get(key, []) or []
                if items:
                    st.markdown(f"_{label}_")
                    for item in items:
                        st.markdown(f"- {item}")
            if r.critiques:
                with st.expander("Critique details", expanded=False):
                    for c in r.critiques:
                        st.markdown(
                            f"**{c.get('critic_id','?')}** [{c.get('severity','?')}] "
                            f"{c.get('finding','')}"
                            + (
                                f"  · 💡 `{c['skill_id']}`"
                                if c.get("skill_id")
                                else ""
                            )
                        )


def _render_distillation_panel() -> None:
    """🧪 Skill Distillation — Day 9 HITL approval loop.

    Shows recent history stats, a Run Distiller button, and a card per
    pending proposal with Approve / Reject / Edit affordances.
    """
    st.sidebar.header("🧪 Skill Distillation")

    try:
        history = HistoryStore()
        runs = history.list_recent(n=10_000)
        miss_runs = history.query(only_misses=True)
    except Exception as e:  # pragma: no cover
        st.sidebar.error(f"Failed to load history: {e}")
        return

    miss_critiques = sum(
        sum(1 for c in r.critiques if not c.get("skill_id")) for r in miss_runs
    )
    st.sidebar.caption(
        f"{len(runs)} run(s) in history · {miss_critiques} unhit critiques across "
        f"{len(miss_runs)} run(s)"
    )

    col_run, col_clear = st.sidebar.columns([2, 1])
    if col_run.button(
        "▶️ Run Distiller",
        key="run_distiller_btn",
        use_container_width=True,
    ):
        with st.sidebar:
            with st.spinner("Mining cross-PRD patterns…"):
                try:
                    proposals = asyncio.run(run_distiller(MockProvider(), history))
                    store = ProposalsStore()
                    for p in proposals:
                        store.save(p)
                    st.session_state["last_distill_count"] = len(proposals)
                except Exception as e:  # pragma: no cover
                    st.error(f"Distiller failed: {e}")
                    return
        st.rerun()

    if col_clear.button("Clear", key="clear_distill_btn", help="dismiss the result banner"):
        st.session_state.pop("last_distill_count", None)
        st.rerun()

    last = st.session_state.get("last_distill_count")
    if last is not None:
        if last == 0:
            st.sidebar.info("No new candidates this run.")
        else:
            st.sidebar.success(f"Found {last} candidate skill(s).")

    # ---- Pending proposals -------------------------------------------------
    try:
        pending = ProposalsStore().list_pending()
    except Exception as e:  # pragma: no cover
        st.sidebar.error(f"Failed to load proposals: {e}")
        return

    if not pending:
        st.sidebar.caption("No pending proposals.")
        return

    st.sidebar.caption(f"{len(pending)} pending proposal(s)")
    for p in pending:
        _render_proposal_card(p)


def _render_proposal_card(proposal) -> None:
    """One proposal expander in the sidebar with Approve/Reject/Edit."""
    score = proposal.generalization_score
    score_color = "🟢" if score >= 0.8 else ("🟡" if score >= 0.7 else "🔴")
    title = f"{score_color} {proposal.proposed_name}  ·  gen={score:.2f}"
    with st.sidebar.expander(title, expanded=False):
        # Pull description out of the SKILL.md frontmatter for the summary.
        desc = _frontmatter_field(proposal.proposed_skill_md, "description") or "—"
        st.caption(
            f"freq={proposal.pattern_frequency} PRDs · "
            f"injected_into: {', '.join(proposal.injected_into)}"
        )
        st.write(desc)
        st.progress(min(max(score, 0.0), 1.0))

        # Evidence — collapsible list of (run_id, critique_excerpt).
        if proposal.evidence:
            with st.expander(
                f"📎 Evidence ({len(proposal.evidence)} rows)", expanded=False
            ):
                for ev in proposal.evidence:
                    st.markdown(
                        f"`{ev.get('run_id','?')[:12]}` — {ev.get('critique_excerpt','')}"
                    )

        # Full SKILL.md preview / edit.
        with st.expander("📄 Full SKILL.md", expanded=False):
            edit_key = f"edit_md_{proposal.proposal_id}"
            edited = st.text_area(
                "SKILL.md",
                value=proposal.proposed_skill_md,
                height=300,
                key=edit_key,
            )

        col_a, col_r, col_e = st.columns(3)
        if col_a.button("✅ Approve", key=f"approve_{proposal.proposal_id}"):
            try:
                # Persist any pending edits first, then promote.
                if (
                    edited := st.session_state.get(f"edit_md_{proposal.proposal_id}")
                ) and edited != proposal.proposed_skill_md:
                    ProposalsStore().update_status(
                        proposal.proposal_id, "edited", edited_md=edited
                    )
                path = ProposalsStore().promote_to_skill(proposal.proposal_id)
                if path is None:
                    st.error("Promotion failed — see logs.")
                else:
                    st.success(f"✅ Skill added: {proposal.proposed_name}")
                    st.rerun()
            except Exception as e:  # pragma: no cover
                st.error(f"approve failed: {e}")
        if col_r.button("❌ Reject", key=f"reject_{proposal.proposal_id}"):
            ProposalsStore().update_status(proposal.proposal_id, "rejected")
            st.rerun()
        if col_e.button("✏️ Save edit", key=f"save_edit_{proposal.proposal_id}"):
            edited_now = st.session_state.get(f"edit_md_{proposal.proposal_id}")
            if edited_now and edited_now != proposal.proposed_skill_md:
                ProposalsStore().update_status(
                    proposal.proposal_id, "edited", edited_md=edited_now
                )
                st.success("Edit saved (status: edited).")
                st.rerun()
            else:
                st.info("No changes to save.")


def _frontmatter_field(skill_md: str, field: str) -> str | None:
    """Best-effort scrape of one frontmatter field for the card summary."""
    if not skill_md.startswith("---"):
        return None
    try:
        end = skill_md.index("\n---", 3)
        block = skill_md[3:end]
    except ValueError:
        return None
    import yaml  # local — avoid import-time cost on the happy path

    try:
        data = yaml.safe_load(block) or {}
    except Exception:  # noqa: BLE001
        return None
    val = data.get(field)
    return str(val) if val else None


def _render_skill_library_sidebar() -> None:
    """Render the Skill Library panel in the Streamlit sidebar.

    Pulls data through `src/skills/mcp_client.py` so the UI is already on
    the same tool surface the MCP server will expose — swapping to a
    transport-backed client later touches one import line.
    """
    st.sidebar.header("📚 Skill Library")
    try:
        skills = list_skills(status="active")
    except Exception as e:  # pragma: no cover — defensive
        st.sidebar.error(f"Failed to load library: {e}")
        return

    st.sidebar.caption(
        f"{len(skills)} active skill(s) · SKILL.md spec · read-only"
    )

    for s in skills:
        name = s.get("name") or s.get("id")
        usage = int(s.get("usage_count", 0) or 0)
        header_label = f"{name}  ·  used {usage}×"
        with st.sidebar.expander(header_label, expanded=False):
            st.caption(
                f"injected_into: {', '.join(s.get('injected_into', [])) or '—'}"
                f"  ·  v{s.get('version', '1.0')}"
                f"  ·  by {s.get('created_by', '?')}"
                f"  ·  used {usage}×"
            )
            st.write(s.get("description", ""))

            # On-demand: load and render the raw SKILL.md (frontmatter + body).
            if st.button("Show SKILL.md", key=f"skill_body_{name}"):
                st.session_state[f"skill_body_open_{name}"] = True
            if st.session_state.get(f"skill_body_open_{name}"):
                try:
                    raw = read_skill_md(name)
                    # Strip frontmatter for prettier in-app rendering; keep
                    # the body's markdown structure intact.
                    body = raw
                    if raw.startswith("---"):
                        parts = raw.split("---", 2)
                        if len(parts) == 3:
                            body = parts[2].lstrip("\n")
                    st.markdown(body)
                except Exception as e:  # pragma: no cover
                    st.error(str(e))

            # Curator actions — Day 9 wiring placeholders.
            col_a, col_b = st.columns(2)
            col_a.button("📌 Pin", key=f"pin_{name}", disabled=True)
            col_b.button("🗑 Deprecate", key=f"dep_{name}", disabled=True)


def _render_ablation_tab() -> None:
    """📊 Ablation Results — load `data/results/ablation/latest.json` and render
    a four-card headline + comparison table + bar chart.
    """
    st.header("📊 Ablation Results")
    st.caption(
        "Quantifies the contribution of the Skill Library by re-running each "
        "PRD under multiple retrieval treatments and scoring against the "
        "golden defect manifest."
    )

    latest = ABLATION_OUTPUT_DIR / "latest.json"
    if not latest.exists():
        st.info(
            "No ablation report on disk yet. Click **Re-run Ablation** below "
            "or run `python -m src.eval --quick` from the command line."
        )
    else:
        try:
            report = json.loads(latest.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            st.error(f"Failed to load latest.json: {e}")
            report = None
        if report:
            _render_ablation_body(report)

    st.divider()
    st.subheader("Re-run Ablation")
    col_a, col_b = st.columns([1, 1])
    quick = col_a.checkbox(
        "Quick mode (1 run / cell)", value=True, key="ablation_quick"
    )
    if col_b.button("▶️ Re-run Ablation", type="primary", key="ablation_run_btn"):
        with st.spinner("Running ablation sweep — this can take ~1 minute…"):
            try:
                treatments = [
                    AblationConfig.preset(n)
                    for n in (
                        "skill_off",
                        "skill_seed_only",
                        "skill_seed_plus_learned",
                    )
                ]
                asyncio.run(
                    run_ablation(
                        prd_files=list_golden_prds(),
                        treatments=treatments,
                        runs_per_treatment=1 if quick else 3,
                        output_dir=ABLATION_OUTPUT_DIR,
                    )
                )
                st.success("Ablation complete — refresh / scroll up to see results.")
            except Exception as e:  # pragma: no cover
                st.error(f"Ablation failed: {e}")
        st.rerun()

    st.caption(
        "Disclaimer: numbers above come from MockProvider — they validate the "
        "ablation pipeline, not real LLM behaviour. Rerun against OpenAI when "
        "the API key arrives."
    )


def _render_ablation_body(report: dict) -> None:
    treatments: list[str] = report.get("treatments") or []
    aggregated: dict = report.get("aggregated") or {}

    # ---- Headline cards: ON vs OFF on 4 metrics ----------------------------
    if {"skill_off", "skill_seed_plus_learned"}.issubset(set(treatments)):
        on, off = "skill_seed_plus_learned", "skill_off"
    elif len(treatments) >= 2:
        off, on = treatments[0], treatments[-1]
    else:
        off = on = treatments[0] if treatments else None

    if on and off and on != off:
        st.subheader("Headline: skill_on vs skill_off")
        cols = st.columns(4)
        for col, label, key, fmt in zip(
            cols,
            ("Defect Recall", "Precision", "Avg Latency (s)", "Avg Cost ($)"),
            ("overall_recall", "precision", "latency_seconds", "cost_usd_estimate"),
            ("{:.2f}", "{:.2f}", "{:.2f}", "{:.3f}"),
        ):
            on_v = aggregated.get(on, {}).get(f"{key}_mean", 0.0)
            off_v = aggregated.get(off, {}).get(f"{key}_mean", 0.0)
            delta = on_v - off_v
            col.metric(
                label,
                fmt.format(on_v),
                f"{delta:+.2f} vs OFF",
            )

    # ---- Headline comparison table ----------------------------------------
    st.subheader("Comparison Table")
    rows = [
        ("Defect Recall", "overall_recall", "{:.2f}"),
        ("Precision", "precision", "{:.2f}"),
        ("Structure Compliance", "structure_compliance", "{:.2f}"),
        ("Dependency Recall", "dependency_recall", "{:.2f}"),
        ("Contradiction Detection", "contradiction_detection", "{:.2f}"),
        ("Severity F1", "severity_classification_f1", "{:.2f}"),
        ("Actionability", "actionability", "{:.2f}"),
        ("Avg Latency (s)", "latency_seconds", "{:.2f}"),
        ("Avg Cost ($)", "cost_usd_estimate", "{:.3f}"),
        ("Critiques per Run", "critique_count", "{:.1f}"),
    ]
    table_rows = []
    for label, key, fmt in rows:
        row = {"Metric": label}
        for t in treatments:
            row[t] = fmt.format(
                aggregated.get(t, {}).get(f"{key}_mean", 0.0)
            )
        table_rows.append(row)
    st.table(table_rows)

    # ---- Bar charts --------------------------------------------------------
    st.subheader("Per-treatment Bar Charts")
    chart_metrics = (
        ("Defect Recall", "overall_recall"),
        ("Precision", "precision"),
        ("Avg Latency (s)", "latency_seconds"),
        ("Avg Cost ($)", "cost_usd_estimate"),
    )
    for label, key in chart_metrics:
        data = {
            t: aggregated.get(t, {}).get(f"{key}_mean", 0.0) for t in treatments
        }
        st.markdown(f"**{label}**")
        st.bar_chart(data)

    # ---- Metadata ----------------------------------------------------------
    st.caption(
        f"Generated {report.get('timestamp','?')}  ·  "
        f"PRDs: {len(report.get('prds_used', []))}  ·  "
        f"runs/treatment: {report.get('runs_per_treatment', 1)}"
    )


def main() -> None:
    st.set_page_config(page_title="PRD Stress Test", layout="wide")
    st.title("PRD Stress Test")
    st.markdown(
        "<span style='background:#0a3d62;color:#cfe9ff;padding:3px 10px;"
        "border-radius:12px;font-size:0.78em;border:1px solid #0a3d62;'>"
        "🏷️ Anthropic Agent Skills v1.0 compliant"
        "</span>",
        unsafe_allow_html=True,
    )

    _render_run_history_sidebar()
    _render_skill_library_sidebar()
    _render_distillation_panel()

    page = st.tabs(["🏠 Stress Test", "📊 Ablation Results"])

    with page[1]:
        _render_ablation_tab()

    with page[0]:
        _render_main_tab()


def _render_main_tab() -> None:
    golden = _load_golden_prds()

    st.subheader("Input")
    # Stable explicit keys are mandatory: without them Streamlit identifies
    # widgets by (type, label, script-position). The sidebar grows as
    # proposals come in, which can shift this widget's position and reset
    # the radio back to its default ("Paste text") on every Run Distiller
    # rerun. Explicit keys persist state across reruns regardless of layout.
    source = st.radio(
        "PRD source",
        ["Paste text", "Pick a golden PRD"],
        horizontal=True,
        key="prd_source_choice",
    )

    prd_text = ""
    prd_filename: str | None = None
    if source == "Pick a golden PRD" and golden:
        choice = st.selectbox(
            "Golden PRD", list(golden.keys()), key="prd_golden_choice"
        )
        prd_text = golden[choice]
        prd_filename = choice
        st.expander("Preview").code(prd_text, language="markdown")
    else:
        prd_text = st.text_area(
            "Paste your PRD here", height=300, key="prd_paste_text"
        )

    col_run, col_reset = st.columns([1, 1])
    if col_run.button("Run Stress Test", type="primary"):
        if not prd_text.strip():
            st.warning("Please provide a PRD first.")
            return
        # Clear any stale dialogs from a previous run before caching the new one.
        st.session_state["active_dialogs"] = {}
        _run_and_cache(prd_text, prd_filename=prd_filename)

    if col_reset.button("Reset"):
        for k in ("run", "active_dialogs", "prd_text", "dialog_llm"):
            st.session_state.pop(k, None)
        st.rerun()

    run = st.session_state.get("run")
    if run:
        _render_run(run)


if __name__ == "__main__":
    main()
