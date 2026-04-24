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

from src.agents.critique_dialog import MAX_DIALOG_ROUNDS, run_critique_dialog
from src.agents.supervisor import run_supervisor_stream
from src.graph.state import Critique
from src.llm.mock_provider import MockProvider
from src.main import run_pipeline


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
    st.markdown(f"**Evidence:** {c.get('evidence', '')}")
    st.markdown(f"**Suggested fix:** {c.get('suggested_fix', '')}")

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


def _run_and_cache(prd_text: str) -> None:
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


def main() -> None:
    st.set_page_config(page_title="PRD Stress Test", layout="wide")
    st.title("PRD Stress Test")

    golden = _load_golden_prds()

    st.subheader("Input")
    source = st.radio(
        "PRD source",
        ["Paste text", "Pick a golden PRD"],
        horizontal=True,
    )

    prd_text = ""
    if source == "Pick a golden PRD" and golden:
        choice = st.selectbox("Golden PRD", list(golden.keys()))
        prd_text = golden[choice]
        st.expander("Preview").code(prd_text, language="markdown")
    else:
        prd_text = st.text_area("Paste your PRD here", height=300)

    col_run, col_reset = st.columns([1, 1])
    if col_run.button("Run Stress Test", type="primary"):
        if not prd_text.strip():
            st.warning("Please provide a PRD first.")
            return
        # Clear any stale dialogs from a previous run before caching the new one.
        st.session_state["active_dialogs"] = {}
        _run_and_cache(prd_text)

    if col_reset.button("Reset"):
        for k in ("run", "active_dialogs", "prd_text", "dialog_llm"):
            st.session_state.pop(k, None)
        st.rerun()

    run = st.session_state.get("run")
    if run:
        _render_run(run)


if __name__ == "__main__":
    main()
