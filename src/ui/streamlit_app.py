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
from src.ui.prd_loader import (
    EmptyExtractionError,
    FileTooLargeError,
    PRDLoaderError,
    UnsupportedFileType,
    extract_text as extract_prd_text,
)
from src.ui.rate_limit import (
    GLOBAL_PER_DAY as RATE_GLOBAL_PER_DAY,
    PER_IP_PER_HOUR as RATE_PER_IP_PER_HOUR,
    check as rate_check,
    consume as rate_consume,
    detect_ip,
)
from src.ui.styles import (
    compliance_badge_block_html,
    dialog_panel_open_html,
    inject_global_css,
    severity_badge_html,
    skill_chip_html,
    thinking_html,
)


GOLDEN_DIR = Path(__file__).resolve().parents[1] / "eval" / "golden_prds"

# Severity colours moved into src/ui/styles.py — see PALETTE there.
# We reach severity badges through `severity_badge_html()` so the per-call
# inline style blob disappears and theme tweaks happen in one place.


# ---------------------------------------------------------------------------
# 中文 UI 文案集中区
# ---------------------------------------------------------------------------
# Translation policy (审核基准):
#   ✅ 翻译: 描述性词汇/动词/section 名/按钮/提示
#   ❌ 不翻译:
#       - 缩写 (PRD/API/JSON/HITL/MCP/LLM/SDK)
#       - 严重度 (P0/P1/P2)
#       - 角色名 (Critic / Supervisor / Distiller / Curator)
#       - ML 指标 (Recall / Precision / F1)
#       - 文件名 / 变量名 / 技术配置 (skill_id, claim_id, injected_into …)
#       - SKILL.md 内容 / critique 内容 / LLM prompt
#       - 错误信息中的 raw exception (`{e}`)
#
# All UI strings live here so a reviewer can scan one block to verify the
# translation policy. **Anything not in this dict that's user-facing
# English is a bug.** Run `grep -nE '"[A-Z][a-z]+ [a-z]+' src/ui/streamlit_app.py`
# after edits to catch escapees.
T = {
    # ---- Hero ---------------------------------------------------------------
    "title": "PRD Stress Test",
    "subtitle": "多智能体对抗式 PRD 评审 · Skills 自学习",

    # ---- Tabs ---------------------------------------------------------------
    "tab_stress_test": "🏠 评审",
    "tab_ablation": "📊 消融实验",

    # ---- Main input section --------------------------------------------------
    "input_heading": "输入",
    "prd_source_label": "PRD 来源",
    "prd_source_paste": "粘贴文本",
    "prd_source_golden": "选择内置 PRD",
    "prd_source_upload": "上传文件",
    "prd_golden_label": "内置 PRD",
    "prd_preview": "预览",
    "prd_paste_label": "粘贴 PRD 全文",
    "prd_upload_label": "上传 PRD 文件",
    "prd_upload_help": "支持 PDF / Word(.docx) / Markdown / TXT，单文件上限 2 MB",
    "prd_upload_success": "✅ 已读取 {chars} 字 · 来自 {filename}",
    "prd_upload_failed": "📛 文件读取失败：{error}",
    "btn_run_stress_test": "开始评审",
    "btn_reset": "重置",
    "warn_no_prd": "请先提供 PRD",

    # ---- Run summary --------------------------------------------------------
    "summary_intake": "Intake 抽取 {claims} 条 claim · Critic 产出 {critiques} 条 finding",
    "critic_findings_heading": "Critic 评审结果",
    "no_findings_from_critic": "此 Critic 暂无发现",

    # ---- Critic tab labels (角色名 + 首次出现的中文注释) --------------------
    "critic_tab_user_advocate": "User Advocate（用户视角）",
    "critic_tab_engineering": "Engineering（工程视角）",
    "critic_tab_business": "Business（商业视角）",
    "critic_tab_design": "Design（设计视角）",

    # ---- Critique card ------------------------------------------------------
    "critique_evidence_prefix": "**原文依据：** {text}",
    "critique_fix_prefix": "**建议改进：** {text}",
    "btn_feedback_useful": "✓ 采纳",
    "btn_feedback_noise": "✗ 误报",
    "feedback_recorded_useful": "已记录为 ✓ 采纳 —— 计入 Skill acceptance_rate",
    "feedback_recorded_noise": "已记录为 ✗ 误报 —— 计入 Skill acceptance_rate",
    "feedback_failed": "反馈失败：{error}",
    "btn_discuss_open": "💬 继续追问",
    "btn_discuss_close": "💬 收起追问",

    # ---- Discussion dialog --------------------------------------------------
    "dialog_prefix": "继续追问",
    "dialog_cap_reached": "🛑 已达到追问上限（{max_rounds} 轮）。如需继续请关闭后重开。",
    "dialog_chat_input_placeholder": "继续追问 {critic_id}…",

    # ---- Cross-challenge ----------------------------------------------------
    "cross_challenge_heading": "🔀 智能体互辩",
    "cross_converged": "✅ 第 {rounds} 轮收敛",
    "cross_not_converged": "⚠️ 达到最大轮数（{rounds}）仍未收敛",
    "cross_no_challenges": "无互辩 —— 各 Critic 均认可其他人的发现",
    "cross_round_title": "第 {round} 轮 —— {n} 条互辩",

    # ---- Supervisor section -------------------------------------------------
    "supervisor_heading": "Supervisor 裁决",
    "supervisor_thinking_in_progress": "推理中…",
    "supervisor_thinking_done": "推理（完成）",
    "verdict_heading": "### 裁决",
    "verdict_executive_summary": "#### 核心结论",
    "verdict_p0_blockers": "P0 阻断项",
    "verdict_p1_concerns": "P1 关注项",
    "verdict_p2_suggestions": "P2 建议",
    "verdict_none": "—— 暂无 ——",
    "verdict_conflicts_heading": "#### 分歧裁决",

    # ---- Run history sidebar ------------------------------------------------
    # 目标用户是中高级 PM：P0/P1/P2 直接用，Skill 这种项目术语不淡化。
    # 但结构上仍然减负: 默认 caption 只露 P 计数, dev metadata
    # (critique 数/hits/misses) 折进"更多详情"里.
    "history_heading": "📊 历史评审",
    "history_load_failed": "无法加载历史记录",
    "history_empty": "还没跑过评审 —— 点上方「开始评审」试一下",
    "history_count": "最近 {n} 次评审",
    "history_run_title": "{ts} · {filename}",
    "history_run_filename_default": "自定义 PRD",
    "history_run_caption": "P0 {p0} · P1 {p1} · P2 {p2}",
    "history_run_summary": "**总结**：{summary}",
    "history_more_details": "更多详情",
    "history_details_meta": "共 {critiques} 条 critique · 命中 Skill {hits} 处 · 未覆盖 {misses} 处",

    # ---- Skill library sidebar ----------------------------------------------
    "skill_lib_heading": "📚 Skill 库",
    "skill_lib_load_failed": "Skill 库加载失败",
    "skill_lib_caption": "{n} 个 Skill 启用中",
    "skill_lib_expander_label": "{name}",
    "skill_lib_usage_inline": "已应用 {usage} 次",
    "skill_lib_tech_details": "技术细节",
    "skill_lib_tech_meta": "v{version} · 由 {created_by} 创建 · 注入到 {routes}",
    "btn_show_skill_md": "查看 SKILL.md",
    "btn_skill_pin": "📌 置顶",
    "btn_skill_deprecate": "🗑 停用",

    # ---- Skill distillation sidebar -----------------------------------------
    "distill_heading": "🧪 Skill 提炼",
    "distill_intro": "系统从历史评审中提炼新 Skill，待你确认后加入 Skill 库。",
    "distill_history_load_failed": "无法加载历史",
    "distill_proposals_load_failed": "无法加载提案",
    "distill_stats_caption": "历史 {runs} 次评审 · {misses} 处 Skill 未覆盖的盲点",
    "btn_run_distiller": "🔍 提炼 Skill",
    "spinner_distill_mining": "正在跨 PRD 挖掘重复出现的模式…",
    "distill_failed": "提炼失败",
    "btn_distill_clear": "清除",
    "btn_distill_clear_help": "隐藏上次结果",
    "distill_no_new_candidates": "暂未发现稳定的新 Skill 候选",
    "distill_found_candidates": "发现 {n} 个候选 Skill",
    "distill_no_pending": "暂无待审议的 Skill 提案",
    "distill_pending_count": "{n} 个待审议 Skill 提案",

    # ---- Proposal card ------------------------------------------------------
    "proposal_caption": "在 {freq} 份不同 PRD 中重复出现 · 注入到 {routes}",
    "proposal_evidence_expander": "📎 证据 ({n} 条)",
    "proposal_full_md_expander": "📄 完整 SKILL.md",
    "btn_proposal_approve": "✅ 采纳",
    "btn_proposal_reject": "❌ 驳回",
    "btn_proposal_save_edit": "✏️ 保存修改",
    "proposal_promote_failed": "采纳失败 —— 请查看日志",
    "proposal_added": "✅ 已加入 Skill 库：{name}",
    "proposal_approve_failed": "采纳失败：{error}",
    "proposal_edit_saved": "修改已保存",
    "proposal_no_changes": "无修改需保存",

    # ---- Pipeline run -------------------------------------------------------
    "spinner_critics_running": "4 个 Critic 并行审查中…",
    "history_save_failed": "历史记录保存失败：{error}",

    # ---- Demo deployment banner + rate limit --------------------------------
    "demo_banner": (
        "🎯 Demo deployment · 今日共享额度 {per_day} 次 · "
        "今日剩余 {remaining_global} 次 · 本 IP 本小时剩余 {remaining_ip} 次 · "
        "详情见 [GitHub](https://github.com/Uper56/PRD-Stress-Test-Agent)"
    ),
    "rate_limit_global_exhausted": (
        "🛑 今日额度已用尽（共 {per_day} 次/天），请明天再试。"
        "想本地无限制运行？克隆仓库后跑 `streamlit run app.py` 即可。"
    ),
    "rate_limit_ip_exhausted": (
        "⏳ 本 IP 本小时已达 {per_hour} 次上限，请稍后再试。"
        "（这是 Demo 配额，本地运行无此限制）"
    ),

    # ---- Ablation tab -------------------------------------------------------
    "ablation_heading": "📊 消融实验结果",
    "ablation_intro": (
        "通过在多种检索条件下重跑每份 PRD 并对照预埋缺陷集打分，"
        "量化 Skill 库对系统的贡献。"
    ),
    "ablation_no_report": (
        "尚无消融报告。点击下方 **重新运行消融实验**，"
        "或在命令行运行 `python -m src.eval --quick`。"
    ),
    "ablation_load_failed": "latest.json 加载失败：{error}",
    "ablation_rerun_heading": "重新运行消融实验",
    "ablation_quick_mode_label": "快速模式（每格运行 1 次）",
    "btn_rerun_ablation": "▶️ 重新运行",
    "spinner_ablation_running": "消融实验运行中 —— 约需 1 分钟…",
    "ablation_complete": "消融完成 —— 滚动到顶部查看结果",
    "ablation_failed": "消融失败：{error}",
    "ablation_disclaimer": (
        "数据源：OpenAI gpt-4o-mini（Critics + Supervisor 同模型，"
        "supervisor 升级到 gpt-4o 为后续工作）· 完整方法论见 README。"
    ),
    "ablation_headline_heading": "核心对比：skill_on vs skill_off",
    "ablation_metric_recall": "缺陷召回率",
    "ablation_metric_precision": "Precision",
    "ablation_metric_latency": "平均耗时 (秒)",
    "ablation_metric_cost": "平均成本 ($)",
    "ablation_metric_delta_vs_off": "{delta:+.2f} vs OFF",
    "ablation_comparison_heading": "对比表",
    "ablation_table_metric_col": "指标",
    "ablation_row_recall": "缺陷召回率",
    "ablation_row_precision": "Precision",
    "ablation_row_structure": "结构合规率",
    "ablation_row_dependency_recall": "依赖识别召回率",
    "ablation_row_contradiction": "矛盾检测召回率",
    "ablation_row_severity_f1": "Severity F1",
    "ablation_row_actionability": "可执行性",
    "ablation_row_latency": "平均耗时 (秒)",
    "ablation_row_cost": "平均成本 ($)",
    "ablation_row_critiques_per_run": "单次产出数",
    "ablation_charts_heading": "各实验组对比图",
    "ablation_meta_caption": "生成于 {ts} · PRD: {n} 份 · 每组运行: {runs}",
}


CRITIC_TABS = [
    ("user_advocate", T["critic_tab_user_advocate"]),
    ("engineering", T["critic_tab_engineering"]),
    ("business", T["critic_tab_business"]),
    ("design", T["critic_tab_design"]),
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
    uid = _critique_uid(c)

    st.markdown(
        f"{severity_badge_html(sev)} <b>{c.get('finding', '')}</b>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"claim_id: {c.get('claim_id', '?')}  ·  "
        f"skill_id: {c.get('skill_id') or '—'}"
    )
    # Skill chip — links this critique back to the skill that fired.
    skill_id = c.get("skill_id")
    if skill_id:
        st.markdown(skill_chip_html(skill_id), unsafe_allow_html=True)

    st.markdown(T["critique_evidence_prefix"].format(text=c.get("evidence", "")))
    st.markdown(T["critique_fix_prefix"].format(text=c.get("suggested_fix", "")))

    # HITL feedback row — only meaningful when a skill_id is attached.
    if skill_id:
        feedback = st.session_state.setdefault("critique_feedback", {})
        already = feedback.get(uid)
        col_yes, col_no, col_status = st.columns([1, 1, 4])
        if col_yes.button(T["btn_feedback_useful"], key=f"fb_yes_{uid}", disabled=already is not None):
            try:
                SkillCurator().update_acceptance(skill_id, accepted=True)
                feedback[uid] = "accepted"
                st.rerun()
            except Exception as e:  # pragma: no cover
                st.warning(T["feedback_failed"].format(error=e))
        if col_no.button(T["btn_feedback_noise"], key=f"fb_no_{uid}", disabled=already is not None):
            try:
                SkillCurator().update_acceptance(skill_id, accepted=False)
                feedback[uid] = "rejected"
                st.rerun()
            except Exception as e:  # pragma: no cover
                st.warning(T["feedback_failed"].format(error=e))
        if already == "accepted":
            col_status.success(T["feedback_recorded_useful"])
        elif already == "rejected":
            col_status.info(T["feedback_recorded_noise"])

    # Discuss button — opens a dialog for this critique.
    active = st.session_state.get("active_dialogs", {})
    is_open = uid in active
    label = T["btn_discuss_close"] if is_open else T["btn_discuss_open"]
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
    # garden-skills anti-cliché: no coloured left-border accent.
    # `dialog_panel_open_html` uses a flat surface tint + top-border instead.
    st.markdown(
        dialog_panel_open_html(dialog["critic_id"], prefix=T["dialog_prefix"]),
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
        st.info(T["dialog_cap_reached"].format(max_rounds=MAX_DIALOG_ROUNDS))

    # Input — disabled once cap is hit.
    prompt = None
    if not cap_reached:
        prompt = st.chat_input(
            T["dialog_chat_input_placeholder"].format(critic_id=dialog["critic_id"]),
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


def _render_verdict(verdict: dict) -> None:
    st.markdown(T["verdict_executive_summary"])
    st.info(verdict.get("executive_summary", "—"))

    # Use the shared severity badge so verdict headings track palette
    # changes from one place (src/ui/styles.py) instead of three.
    groups = [
        (T["verdict_p0_blockers"], "p0_blockers", "P0"),
        (T["verdict_p1_concerns"], "p1_concerns", "P1"),
        (T["verdict_p2_suggestions"], "p2_suggestions", "P2"),
    ]
    for label, key, sev in groups:
        items = verdict.get(key, []) or []
        st.markdown(
            f"{severity_badge_html(sev)} <b>{label}</b> &nbsp; "
            f"<span style='opacity:0.7'>({len(items)})</span>",
            unsafe_allow_html=True,
        )
        if not items:
            st.caption(T["verdict_none"])
        else:
            for item in items:
                st.markdown(f"- {item}")

    conflicts = verdict.get("conflict_resolutions", []) or []
    if conflicts:
        st.markdown(T["verdict_conflicts_heading"])
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
                    thinking_html(
                        thinking_text,
                        in_progress=True,
                        label=T["supervisor_thinking_in_progress"],
                    ),
                    unsafe_allow_html=True,
                )
            elif stage == "done":
                final_verdict = event.get("final_verdict", {}) or {}

    asyncio.run(_consume())

    # Freeze the thinking placeholder (drop the cursor glyph) once streaming ends.
    if thinking_text:
        thinking_box.markdown(
            thinking_html(
                thinking_text,
                in_progress=False,
                label=T["supervisor_thinking_done"],
            ),
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

    with st.spinner(T["spinner_critics_running"]):
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
        st.warning(T["history_save_failed"].format(error=e))

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
        T["summary_intake"].format(
            claims=run["claim_count"], critiques=len(run["critiques"])
        )
    )

    by_critic: dict[str, list[dict]] = {k: [] for k, _ in CRITIC_TABS}
    for d in run["critiques"]:
        by_critic.setdefault(d.get("critic_id", "unknown"), []).append(d)

    st.subheader(T["critic_findings_heading"])
    tabs = st.tabs([label for _, label in CRITIC_TABS])
    for (key, _label), tab in zip(CRITIC_TABS, tabs):
        with tab:
            items = by_critic.get(key, [])
            if not items:
                st.info(T["no_findings_from_critic"])
            for item in items:
                _render_critique(item)

    # ---- Cross-Challenge section --------------------------------------------
    st.subheader(T["cross_challenge_heading"])
    rounds = run["challenge_round"]
    if run["converged"]:
        st.success(T["cross_converged"].format(rounds=rounds))
    else:
        st.warning(T["cross_not_converged"].format(rounds=rounds))

    challenges_raw = run["challenges"]
    by_round: dict[int, list[dict]] = {}
    for d in challenges_raw:
        by_round.setdefault(d.get("round", 0), []).append(d)

    if not challenges_raw:
        st.caption(T["cross_no_challenges"])
    else:
        for rn in sorted(by_round.keys()):
            items = by_round[rn]
            with st.expander(
                T["cross_round_title"].format(round=rn, n=len(items)),
                expanded=False,
            ):
                for ch in items:
                    st.markdown(
                        f"**{ch.get('challenger', '?')}** → "
                        f"`{ch.get('target_critique_id', '?')}`"
                    )
                    st.markdown(f"↪ {ch.get('counter_finding', '')}")
                    st.divider()

    # ---- Supervisor verdict (cached from the one-time stream) ---------------
    st.subheader(T["supervisor_heading"])
    thinking_text = run.get("thinking_text") or ""
    if thinking_text:
        st.markdown(
            thinking_html(
                thinking_text,
                in_progress=False,
                label=T["supervisor_thinking_done"],
            ),
            unsafe_allow_html=True,
        )
    st.markdown(T["verdict_heading"])
    _render_verdict(run.get("verdict") or {})


def _render_run_history_sidebar() -> None:
    """User-friendly recent-evaluations panel.

    Default view shows just date + PRD name + a one-line severity count.
    Tech-y stuff (skill_id chips per critique, individual critic ownership)
    is hidden in an inner expander so the casual visitor sees a clean list.
    """
    st.sidebar.header(T["history_heading"])
    try:
        runs = HistoryStore().list_recent(n=20)
    except Exception:  # pragma: no cover — keep the sidebar usable even if disk broke
        st.sidebar.caption(T["history_load_failed"])
        return

    if not runs:
        st.sidebar.caption(T["history_empty"])
        return

    st.sidebar.caption(T["history_count"].format(n=len(runs)))
    for r in runs:
        verdict = r.supervisor_verdict or {}
        p0 = len(verdict.get("p0_blockers", []) or [])
        p1 = len(verdict.get("p1_concerns", []) or [])
        p2 = len(verdict.get("p2_suggestions", []) or [])
        # Drop seconds from the timestamp — minute precision is plenty
        # for "when did I run this", and shorter labels look cleaner.
        title = T["history_run_title"].format(
            ts=r.timestamp[:16].replace("T", " "),
            filename=r.prd_filename or T["history_run_filename_default"],
        )
        with st.sidebar.expander(title, expanded=False):
            st.caption(T["history_run_caption"].format(p0=p0, p1=p1, p2=p2))
            if verdict.get("executive_summary"):
                st.markdown(
                    T["history_run_summary"].format(
                        summary=verdict["executive_summary"]
                    )
                )
            # Show the P0 / P1 list inline — those are the "what went wrong"
            # the user most likely came back for. P2 hides into the
            # technical-details sub-expander.
            for sev_label, key in (("P0", "p0_blockers"), ("P1", "p1_concerns")):
                items = verdict.get(key, []) or []
                if items:
                    st.markdown(f"**{sev_label}**")
                    for item in items:
                        st.markdown(f"- {item}")

            # Dev-tier details: P2 list, per-critique critic ownership +
            # Skill attribution, and the critique/hits/misses count line.
            # Folded by default but still here for the curious PM.
            with st.expander(T["history_more_details"], expanded=False):
                st.caption(
                    T["history_details_meta"].format(
                        critiques=len(r.critiques),
                        hits=len(r.skill_hits),
                        misses=len(r.skill_misses),
                    )
                )
                p2_items = verdict.get("p2_suggestions", []) or []
                if p2_items:
                    st.markdown("**P2**")
                    for item in p2_items:
                        st.markdown(f"- {item}")
                if r.critiques:
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
    st.sidebar.header(T["distill_heading"])
    # One-liner explanation up top — most visitors will never click
    # "Run Distiller", but they should understand at a glance what
    # this panel claims the system can do.
    st.sidebar.caption(T["distill_intro"])

    try:
        history = HistoryStore()
        runs = history.list_recent(n=10_000)
        miss_runs = history.query(only_misses=True)
    except Exception:  # pragma: no cover
        st.sidebar.caption(T["distill_history_load_failed"])
        return

    miss_critiques = sum(
        sum(1 for c in r.critiques if not c.get("skill_id")) for r in miss_runs
    )
    st.sidebar.caption(
        T["distill_stats_caption"].format(runs=len(runs), misses=miss_critiques)
    )

    col_run, col_clear = st.sidebar.columns([2, 1])
    if col_run.button(
        T["btn_run_distiller"],
        key="run_distiller_btn",
        use_container_width=True,
    ):
        with st.sidebar:
            with st.spinner(T["spinner_distill_mining"]):
                try:
                    proposals = asyncio.run(run_distiller(MockProvider(), history))
                    store = ProposalsStore()
                    for p in proposals:
                        store.save(p)
                    st.session_state["last_distill_count"] = len(proposals)
                except Exception:  # pragma: no cover
                    st.error(T["distill_failed"])
                    return
        st.rerun()

    if col_clear.button(
        T["btn_distill_clear"],
        key="clear_distill_btn",
        help=T["btn_distill_clear_help"],
    ):
        st.session_state.pop("last_distill_count", None)
        st.rerun()

    last = st.session_state.get("last_distill_count")
    if last is not None:
        if last == 0:
            st.sidebar.info(T["distill_no_new_candidates"])
        else:
            st.sidebar.success(T["distill_found_candidates"].format(n=last))

    # ---- Pending proposals -------------------------------------------------
    try:
        pending = ProposalsStore().list_pending()
    except Exception:  # pragma: no cover
        st.sidebar.caption(T["distill_proposals_load_failed"])
        return

    if not pending:
        st.sidebar.caption(T["distill_no_pending"])
        return

    st.sidebar.caption(T["distill_pending_count"].format(n=len(pending)))
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
            T["proposal_caption"].format(
                freq=proposal.pattern_frequency,
                routes=", ".join(proposal.injected_into) or "—",
            )
        )
        st.write(desc)
        st.progress(min(max(score, 0.0), 1.0))

        # Evidence — collapsible list of (run_id, critique_excerpt).
        if proposal.evidence:
            with st.expander(
                T["proposal_evidence_expander"].format(n=len(proposal.evidence)),
                expanded=False,
            ):
                for ev in proposal.evidence:
                    st.markdown(
                        f"`{ev.get('run_id','?')[:12]}` — {ev.get('critique_excerpt','')}"
                    )

        # Full SKILL.md preview / edit. The text_area label stays "SKILL.md"
        # — that's the canonical Anthropic spec filename, not a UI string.
        with st.expander(T["proposal_full_md_expander"], expanded=False):
            edit_key = f"edit_md_{proposal.proposal_id}"
            edited = st.text_area(
                "SKILL.md",
                value=proposal.proposed_skill_md,
                height=300,
                key=edit_key,
            )

        col_a, col_r, col_e = st.columns(3)
        if col_a.button(T["btn_proposal_approve"], key=f"approve_{proposal.proposal_id}"):
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
                    st.error(T["proposal_promote_failed"])
                else:
                    st.success(T["proposal_added"].format(name=proposal.proposed_name))
                    st.rerun()
            except Exception as e:  # pragma: no cover
                st.error(T["proposal_approve_failed"].format(error=e))
        if col_r.button(T["btn_proposal_reject"], key=f"reject_{proposal.proposal_id}"):
            ProposalsStore().update_status(proposal.proposal_id, "rejected")
            st.rerun()
        if col_e.button(T["btn_proposal_save_edit"], key=f"save_edit_{proposal.proposal_id}"):
            edited_now = st.session_state.get(f"edit_md_{proposal.proposal_id}")
            if edited_now and edited_now != proposal.proposed_skill_md:
                ProposalsStore().update_status(
                    proposal.proposal_id, "edited", edited_md=edited_now
                )
                st.success(T["proposal_edit_saved"])
                st.rerun()
            else:
                st.info(T["proposal_no_changes"])


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
    st.sidebar.header(T["skill_lib_heading"])
    try:
        skills = list_skills(status="active")
    except Exception:  # pragma: no cover — defensive
        st.sidebar.caption(T["skill_lib_load_failed"])
        return

    st.sidebar.caption(T["skill_lib_caption"].format(n=len(skills)))

    for s in skills:
        name = s.get("name") or s.get("id")
        usage = int(s.get("usage_count", 0) or 0)
        with st.sidebar.expander(
            T["skill_lib_expander_label"].format(name=name),
            expanded=False,
        ):
            # Top of the expander stays plain-language: description + usage.
            # The dev-tier metadata (version / created_by / injected_into /
            # raw SKILL.md) tucks into the "技术细节" inner expander.
            st.write(s.get("description", ""))
            st.caption(T["skill_lib_usage_inline"].format(usage=usage))

            with st.expander(T["skill_lib_tech_details"], expanded=False):
                st.caption(
                    T["skill_lib_tech_meta"].format(
                        version=s.get("version", "1.0"),
                        created_by=s.get("created_by", "?"),
                        routes=", ".join(s.get("injected_into", [])) or "—",
                    )
                )
                if st.button(T["btn_show_skill_md"], key=f"skill_body_{name}"):
                    st.session_state[f"skill_body_open_{name}"] = True
                if st.session_state.get(f"skill_body_open_{name}"):
                    try:
                        raw = read_skill_md(name)
                        body = raw
                        if raw.startswith("---"):
                            parts = raw.split("---", 2)
                            if len(parts) == 3:
                                body = parts[2].lstrip("\n")
                        st.markdown(body)
                    except Exception as e:  # pragma: no cover
                        st.caption(str(e))

            # Curator-only actions: kept available but unobtrusive.
            # Disabled until Day-13 curator-write tools land.
            col_a, col_b = st.columns(2)
            col_a.button(T["btn_skill_pin"], key=f"pin_{name}", disabled=True)
            col_b.button(T["btn_skill_deprecate"], key=f"dep_{name}", disabled=True)


def _render_ablation_tab() -> None:
    """📊 Ablation Results — load `data/results/ablation/latest.json` and render
    a four-card headline + comparison table + bar chart.
    """
    st.header(T["ablation_heading"])
    st.caption(T["ablation_intro"])

    latest = ABLATION_OUTPUT_DIR / "latest.json"
    if not latest.exists():
        st.info(T["ablation_no_report"])
    else:
        try:
            report = json.loads(latest.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover
            st.error(T["ablation_load_failed"].format(error=e))
            report = None
        if report:
            _render_ablation_body(report)

    st.divider()
    st.subheader(T["ablation_rerun_heading"])
    col_a, col_b = st.columns([1, 1])
    quick = col_a.checkbox(
        T["ablation_quick_mode_label"], value=True, key="ablation_quick"
    )
    if col_b.button(
        T["btn_rerun_ablation"], type="primary", key="ablation_run_btn"
    ):
        with st.spinner(T["spinner_ablation_running"]):
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
                st.success(T["ablation_complete"])
            except Exception as e:  # pragma: no cover
                st.error(T["ablation_failed"].format(error=e))
        st.rerun()

    st.caption(T["ablation_disclaimer"])


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
        st.subheader(T["ablation_headline_heading"])
        cols = st.columns(4)
        headline_specs = (
            (T["ablation_metric_recall"], "overall_recall", "{:.2f}"),
            (T["ablation_metric_precision"], "precision", "{:.2f}"),
            (T["ablation_metric_latency"], "latency_seconds", "{:.2f}"),
            (T["ablation_metric_cost"], "cost_usd_estimate", "{:.3f}"),
        )
        for col, (label, key, fmt) in zip(cols, headline_specs):
            on_v = aggregated.get(on, {}).get(f"{key}_mean", 0.0)
            off_v = aggregated.get(off, {}).get(f"{key}_mean", 0.0)
            delta = on_v - off_v
            col.metric(
                label,
                fmt.format(on_v),
                T["ablation_metric_delta_vs_off"].format(delta=delta),
            )

    # ---- Headline comparison table ----------------------------------------
    st.subheader(T["ablation_comparison_heading"])
    rows = [
        (T["ablation_row_recall"], "overall_recall", "{:.2f}"),
        (T["ablation_row_precision"], "precision", "{:.2f}"),
        (T["ablation_row_structure"], "structure_compliance", "{:.2f}"),
        (T["ablation_row_dependency_recall"], "dependency_recall", "{:.2f}"),
        (T["ablation_row_contradiction"], "contradiction_detection", "{:.2f}"),
        (T["ablation_row_severity_f1"], "severity_classification_f1", "{:.2f}"),
        (T["ablation_row_actionability"], "actionability", "{:.2f}"),
        (T["ablation_row_latency"], "latency_seconds", "{:.2f}"),
        (T["ablation_row_cost"], "cost_usd_estimate", "{:.3f}"),
        (T["ablation_row_critiques_per_run"], "critique_count", "{:.1f}"),
    ]
    table_rows = []
    for label, key, fmt in rows:
        row = {T["ablation_table_metric_col"]: label}
        for t in treatments:
            row[t] = fmt.format(
                aggregated.get(t, {}).get(f"{key}_mean", 0.0)
            )
        table_rows.append(row)
    st.table(table_rows)

    # ---- Bar charts --------------------------------------------------------
    st.subheader(T["ablation_charts_heading"])
    chart_metrics = (
        (T["ablation_metric_recall"], "overall_recall"),
        (T["ablation_metric_precision"], "precision"),
        (T["ablation_metric_latency"], "latency_seconds"),
        (T["ablation_metric_cost"], "cost_usd_estimate"),
    )
    for label, key in chart_metrics:
        data = {
            t: aggregated.get(t, {}).get(f"{key}_mean", 0.0) for t in treatments
        }
        st.markdown(f"**{label}**")
        st.bar_chart(data)

    # ---- Metadata ----------------------------------------------------------
    st.caption(
        T["ablation_meta_caption"].format(
            ts=report.get("timestamp", "?"),
            n=len(report.get("prds_used", [])),
            runs=report.get("runs_per_treatment", 1),
        )
    )


def _render_demo_banner() -> None:
    """Show the demo-quota banner if rate limiting is active.

    `rate_check` is non-mutating — it just inspects the counters and
    reports remaining headroom. The actual debit happens in the Run
    button handler via `rate_consume`.
    """
    decision = rate_check(detect_ip())
    if decision.reason == "ok" and decision.remaining_global == RATE_GLOBAL_PER_DAY \
            and decision.remaining_ip == RATE_PER_IP_PER_HOUR:
        # Likely RATE_LIMIT_DISABLED=1 (local dev). Don't render the banner.
        # Also true on the very first request of a fresh process — but
        # then the banner still adds noise without value, so skip.
        return
    st.info(
        T["demo_banner"].format(
            per_day=RATE_GLOBAL_PER_DAY,
            remaining_global=decision.remaining_global,
            remaining_ip=decision.remaining_ip,
        )
    )


def main() -> None:
    st.set_page_config(page_title=T["title"], layout="wide")
    # Global visual system — Modern tech / blue-violet preset, OKLCH-based.
    # Must run before any st.markdown that styles itself, so it's the very
    # first call after set_page_config.
    inject_global_css()
    st.title(T["title"])
    # Subtitle replaces the compliance badge (per the Chinese-UI brief,
    # the badge was redundant chrome). `st.html` because Streamlit's
    # markdown sanitiser strips styled spans (since ~1.33).
    st.html(compliance_badge_block_html(T["subtitle"]))

    # Demo-deployment banner — only meaningful when rate limiting is on
    # (i.e. RATE_LIMIT_DISABLED unset). For local dev this surfaces the
    # default 50/day cap, which is honest signal.
    _render_demo_banner()

    _render_run_history_sidebar()
    _render_skill_library_sidebar()
    _render_distillation_panel()

    page = st.tabs([T["tab_stress_test"], T["tab_ablation"]])

    with page[1]:
        _render_ablation_tab()

    with page[0]:
        _render_main_tab()


def _render_main_tab() -> None:
    golden = _load_golden_prds()

    st.subheader(T["input_heading"])
    # Stable explicit keys are mandatory: without them Streamlit identifies
    # widgets by (type, label, script-position). The sidebar grows as
    # proposals come in, which can shift this widget's position and reset
    # the radio back to its default on every Run Distiller rerun.
    source = st.radio(
        T["prd_source_label"],
        [
            T["prd_source_paste"],
            T["prd_source_golden"],
            T["prd_source_upload"],
        ],
        horizontal=True,
        key="prd_source_choice",
    )

    prd_text = ""
    prd_filename: str | None = None
    if source == T["prd_source_golden"] and golden:
        choice = st.selectbox(
            T["prd_golden_label"], list(golden.keys()), key="prd_golden_choice"
        )
        prd_text = golden[choice]
        prd_filename = choice
        st.expander(T["prd_preview"]).code(prd_text, language="markdown")
    elif source == T["prd_source_upload"]:
        # File uploader: accept PDF / Word (.docx) / Markdown / TXT.
        # Streamlit keeps the UploadedFile in session_state across
        # reruns automatically when we pin the widget key — handy
        # because every interaction triggers a rerun.
        uploaded = st.file_uploader(
            T["prd_upload_label"],
            type=["pdf", "docx", "md", "markdown", "txt"],
            key="prd_upload_widget",
            help=T["prd_upload_help"],
        )
        if uploaded is not None:
            try:
                prd_text = extract_prd_text(uploaded.name, uploaded.getvalue())
                prd_filename = uploaded.name
                st.success(
                    T["prd_upload_success"].format(
                        chars=len(prd_text), filename=uploaded.name
                    )
                )
                with st.expander(T["prd_preview"], expanded=False):
                    st.code(prd_text, language="markdown")
            except (
                UnsupportedFileType,
                FileTooLargeError,
                EmptyExtractionError,
                PRDLoaderError,
            ) as e:
                # Show the localised exception message verbatim — these
                # are already Chinese strings raised from prd_loader.py.
                st.error(T["prd_upload_failed"].format(error=e))
                prd_text = ""
    else:
        prd_text = st.text_area(
            T["prd_paste_label"], height=300, key="prd_paste_text"
        )

    col_run, col_reset = st.columns([1, 1])
    if col_run.button(T["btn_run_stress_test"], type="primary"):
        if not prd_text.strip():
            st.warning(T["warn_no_prd"])
            return
        # Rate-limit gate — debits both per-IP and global counters
        # atomically. On exhaustion we show the i18n-localised limit
        # message and refuse to invoke the pipeline (which is the only
        # path that costs $ on the demo).
        decision = rate_consume(detect_ip())
        if not decision.allowed:
            if decision.reason == "global":
                st.error(
                    T["rate_limit_global_exhausted"].format(
                        per_day=RATE_GLOBAL_PER_DAY
                    )
                )
            else:
                st.error(
                    T["rate_limit_ip_exhausted"].format(
                        per_hour=RATE_PER_IP_PER_HOUR
                    )
                )
            return
        # Clear any stale dialogs from a previous run before caching the new one.
        st.session_state["active_dialogs"] = {}
        _run_and_cache(prd_text, prd_filename=prd_filename)

    if col_reset.button(T["btn_reset"]):
        for k in ("run", "active_dialogs", "prd_text", "dialog_llm"):
            st.session_state.pop(k, None)
        st.rerun()

    run = st.session_state.get("run")
    if run:
        _render_run(run)


if __name__ == "__main__":
    main()
