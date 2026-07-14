"""Visual system for the Streamlit PRD Review Desk.

The product is used by PMs reading dense documents and comparing findings for
minutes at a time.  The UI therefore uses a calm light reading surface, an
ink-blue sidebar, and blue-violet only for focus, state, and primary actions.
All non-theme color values remain in OKLCH so derived tints stay perceptually
consistent.
"""

from __future__ import annotations

import html

import streamlit as st


PALETTE = {
    "primary": "oklch(0.55 0.25 250)",
    "primary_hover": "oklch(0.49 0.23 250)",
    "primary_soft": "oklch(0.94 0.045 250)",
    "canvas": "oklch(0.975 0.008 250)",
    "surface": "oklch(1 0 0)",
    "surface_tint": "oklch(0.965 0.012 250)",
    "sidebar": "oklch(0.22 0.025 250)",
    "sidebar_raised": "oklch(0.27 0.026 250)",
    "border": "oklch(0.87 0.015 250)",
    "text": "oklch(0.24 0.025 250)",
    "muted": "oklch(0.48 0.025 250)",
    "sidebar_text": "oklch(0.94 0.01 250)",
    "p0": "oklch(0.57 0.20 27)",
    "p1": "oklch(0.66 0.16 75)",
    "p2": "oklch(0.54 0.035 250)",
    "success": "oklch(0.53 0.13 155)",
}


def _build_css() -> str:
    p = PALETTE
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {{
  --psa-primary: {p['primary']};
  --psa-primary-hover: {p['primary_hover']};
  --psa-primary-soft: {p['primary_soft']};
  --psa-canvas: {p['canvas']};
  --psa-surface: {p['surface']};
  --psa-surface-tint: {p['surface_tint']};
  --psa-sidebar: {p['sidebar']};
  --psa-sidebar-raised: {p['sidebar_raised']};
  --psa-border: {p['border']};
  --psa-text: {p['text']};
  --psa-muted: {p['muted']};
  --psa-sidebar-text: {p['sidebar_text']};
  --psa-p0: {p['p0']};
  --psa-p1: {p['p1']};
  --psa-p2: {p['p2']};
  --psa-success: {p['success']};
  --psa-display: 'Space Grotesk', 'Inter', sans-serif;
  --psa-body: 'Inter', ui-sans-serif, sans-serif;
}}

html, body, .stApp, [data-testid='stAppViewContainer'] {{
  font-family: var(--psa-body);
  background: var(--psa-canvas);
  color: var(--psa-text);
}}
[data-testid='stAppViewContainer'] > .main {{ background: var(--psa-canvas); }}
[data-testid='stMainBlockContainer'] {{ max-width: 1180px; padding-top: 2.1rem; padding-bottom: 4rem; }}

/* Typography: display font only for hierarchy, compact sans everywhere else. */
h1, h2, h3, h4, .stTabs [data-baseweb='tab'] p, [data-testid='stMetricLabel'], [data-testid='stMetricValue'] {{
  font-family: var(--psa-display) !important;
  color: var(--psa-text);
  letter-spacing: -0.02em;
}}
h1 {{ font-size: 2.25rem !important; line-height: 1.12 !important; text-align: center; margin-bottom: .35rem !important; }}
h2 {{ font-size: 1.35rem !important; line-height: 1.25 !important; margin-top: 1.85rem !important; }}
h3 {{ font-size: 1.08rem !important; }}
p, li, [data-testid='stCaptionContainer'] {{ font-family: var(--psa-body); line-height: 1.6; }}
[data-testid='stCaptionContainer'] {{ color: var(--psa-muted); }}

/* The app shell. */
[data-testid='stSidebar'] {{
  background: var(--psa-sidebar);
  border-right: 1px solid color-mix(in oklch, var(--psa-sidebar) 70%, white);
}}
[data-testid='stSidebar'] h1,
[data-testid='stSidebar'] h2,
[data-testid='stSidebar'] h3,
[data-testid='stSidebar'] p,
[data-testid='stSidebar'] label,
[data-testid='stSidebar'] [data-testid='stMarkdownContainer'],
[data-testid='stSidebar'] [data-testid='stMarkdownContainer'] * {{ color: var(--psa-sidebar-text) !important; }}
[data-testid='stSidebar'] [data-testid='stCaptionContainer'],
[data-testid='stSidebar'] [data-testid='stCaptionContainer'] * {{ color: color-mix(in oklch, var(--psa-sidebar-text) 72%, transparent) !important; }}
[data-testid='stSidebar'] h2 {{ margin-top: 1.35rem !important; font-size: 1rem !important; }}
[data-testid='stSidebar'] [data-testid='stExpander'] {{
  background: var(--psa-sidebar-raised);
  border: 1px solid color-mix(in oklch, var(--psa-sidebar-text) 12%, transparent);
  border-radius: 8px;
  margin-bottom: .45rem;
}}

/* Tabs behave as a compact navigation bar, not oversized pills. */
.stTabs [data-baseweb='tab-list'] {{ gap: 1.25rem; border-bottom: 1px solid var(--psa-border); }}
.stTabs [data-baseweb='tab'] {{
  height: 42px;
  padding: 0 2px;
  background: transparent;
  border: 0;
  font-size: .93rem;
}}
.stTabs [aria-selected='true'] {{ color: var(--psa-primary) !important; }}
.stTabs [data-baseweb='tab-highlight'] {{ background-color: var(--psa-primary) !important; height: 2px !important; }}

/* Inputs and buttons: conventional, high-contrast product controls. */
.stTextArea textarea, .stTextInput input, [data-baseweb='select'] > div, [data-baseweb='base-input'] {{
  background: var(--psa-surface) !important;
  border-color: var(--psa-border) !important;
  color: var(--psa-text) !important;
  border-radius: 8px !important;
}}
.stTextArea textarea:focus, .stTextInput input:focus {{ border-color: var(--psa-primary) !important; box-shadow: 0 0 0 3px color-mix(in oklch, var(--psa-primary) 16%, transparent) !important; }}
.stButton > button {{
  min-height: 38px;
  border-radius: 7px;
  border: 1px solid var(--psa-border);
  background: var(--psa-surface);
  color: var(--psa-text);
  font-family: var(--psa-body);
  font-weight: 600;
  transition: background-color 150ms ease, border-color 150ms ease, transform 150ms ease;
}}
.stButton > button:hover:not(:disabled) {{ background: var(--psa-surface-tint); border-color: var(--psa-primary); transform: translateY(-1px); }}
.stButton > button[kind='primary'] {{ background: var(--psa-primary); border-color: var(--psa-primary); color: white; }}
.stButton > button[kind='primary']:hover:not(:disabled) {{ background: var(--psa-primary-hover); border-color: var(--psa-primary-hover); }}
.stButton > button:focus-visible {{ outline: 3px solid color-mix(in oklch, var(--psa-primary) 30%, transparent); outline-offset: 2px; }}

/* Containers become quiet document panels, not decorative cards. */
[data-testid='stVerticalBlockBorderWrapper'] {{
  background: var(--psa-surface);
  border: 1px solid var(--psa-border) !important;
  border-radius: 10px;
  box-shadow: none !important;
}}
[data-testid='stExpander'] {{ background: var(--psa-surface); border: 1px solid var(--psa-border) !important; border-radius: 8px; }}
[data-testid='stMetric'] {{ background: var(--psa-surface); border: 1px solid var(--psa-border); border-radius: 8px; padding: 12px 14px; }}

/* Sidebar controls share the dark shell.  This must come after the global
   panel/control rules above: Streamlit containers are otherwise white, while
   their sidebar copy is intentionally light. */
[data-testid='stSidebar'] [data-testid='stVerticalBlockBorderWrapper'] {{
  background: var(--psa-sidebar-raised) !important;
  border-color: color-mix(in oklch, var(--psa-sidebar-text) 14%, transparent) !important;
}}
[data-testid='stSidebar'] [data-baseweb='select'] > div,
[data-testid='stSidebar'] [data-baseweb='base-input'],
[data-testid='stSidebar'] .stTextArea textarea,
[data-testid='stSidebar'] .stTextInput input {{
  background: var(--psa-sidebar-raised) !important;
  border-color: color-mix(in oklch, var(--psa-sidebar-text) 20%, transparent) !important;
  color: var(--psa-sidebar-text) !important;
}}
[data-testid='stSidebar'] [data-baseweb='select'] input,
[data-testid='stSidebar'] [data-baseweb='select'] span,
[data-testid='stSidebar'] [data-baseweb='select'] svg {{
  color: var(--psa-sidebar-text) !important;
  fill: var(--psa-sidebar-text) !important;
}}
[data-testid='stSidebar'] .stButton > button {{
  background: var(--psa-sidebar-raised);
  border-color: color-mix(in oklch, var(--psa-sidebar-text) 20%, transparent);
  color: var(--psa-sidebar-text);
}}
[data-testid='stSidebar'] .stButton > button:hover:not(:disabled) {{
  background: color-mix(in oklch, var(--psa-sidebar-raised) 82%, var(--psa-primary));
  border-color: color-mix(in oklch, var(--psa-sidebar-text) 38%, transparent);
}}
[data-testid='stSidebar'] .stButton > button[kind='primary'] {{
  background: var(--psa-primary);
  border-color: var(--psa-primary);
  color: white;
}}

/* Structured review components. */
.psa-title-block {{ text-align: center; margin: 0 auto 1.4rem; max-width: 680px; }}
.psa-subtitle {{ color: var(--psa-muted); font-size: .98rem; margin: 0; }}
.psa-review-intro {{ padding: .25rem 0 .8rem; margin: .2rem 0 .2rem; }}
.psa-review-composer__kicker {{ color: var(--psa-primary); font-family: var(--psa-display); font-size: .82rem; font-weight: 700; letter-spacing: .02em; margin-bottom: .28rem; }}
.psa-review-composer__title {{ font-family: var(--psa-display); font-size: 1.2rem; font-weight: 600; margin: 0; }}
.psa-review-composer__hint {{ color: var(--psa-muted); margin: .3rem 0 0; font-size: .9rem; }}
.psa-dialog-panel {{ background: var(--psa-surface-tint); border-top: 2px solid var(--psa-primary); border-radius: 0 0 8px 8px; padding: .7rem .9rem; margin: .3rem 0 .7rem; }}
.psa-run-summary {{
  display: flex; gap: .7rem; flex-wrap: wrap; align-items: center;
  background: var(--psa-primary-soft); border: 1px solid color-mix(in oklch, var(--psa-primary) 22%, var(--psa-border));
  border-radius: 9px; padding: .75rem .9rem; margin: .4rem 0 1.2rem;
  color: var(--psa-text);
}}
.psa-run-summary strong {{ font-family: var(--psa-display); }}
.psa-severity {{ display: inline-flex; align-items: center; font-family: var(--psa-display); font-size: .74rem; font-weight: 700; letter-spacing: .04em; padding: 3px 7px; border-radius: 4px; color: white; }}
.psa-severity--p0 {{ background: var(--psa-p0); }}
.psa-severity--p1 {{ background: var(--psa-p1); }}
.psa-severity--p2 {{ background: var(--psa-p2); }}
.psa-skill-chip {{ display: inline-block; font-size: .76rem; padding: 3px 8px; border-radius: 999px; background: var(--psa-primary-soft); color: var(--psa-primary-hover); border: 1px solid color-mix(in oklch, var(--psa-primary) 18%, var(--psa-border)); }}
.psa-skill-chip code {{ color: inherit; background: transparent; padding: 0; }}
.psa-critique-header {{ display: flex; align-items: flex-start; gap: .6rem; margin-bottom: .65rem; }}
.psa-critique-title {{ font-family: var(--psa-display); font-weight: 600; line-height: 1.45; color: var(--psa-text); }}
.psa-critique-meta {{ color: var(--psa-muted); font-size: .76rem; margin-bottom: .55rem; }}
.psa-field-label {{ font-size: .75rem; font-family: var(--psa-display); font-weight: 700; color: var(--psa-muted); letter-spacing: .02em; margin-bottom: .2rem; }}
.psa-field-value {{ color: var(--psa-text); font-size: .9rem; line-height: 1.55; }}
.psa-verdict-shell {{ background: var(--psa-surface); border: 1px solid var(--psa-border); border-radius: 12px; padding: 1.25rem; margin: .45rem 0 1rem; }}
.psa-verdict-summary {{ font-family: var(--psa-display); font-size: 1.08rem; line-height: 1.5; margin: 0 0 1rem; }}
.psa-thinking {{ color: var(--psa-muted); font-size: .88rem; line-height: 1.55; white-space: pre-wrap; background: var(--psa-surface-tint); border-radius: 8px; padding: .75rem .9rem; }}
.psa-demo-banner {{ background: var(--psa-surface-tint); border: 1px solid var(--psa-border); border-radius: 8px; padding: .52rem .75rem; color: var(--psa-muted); font-size: .82rem; text-align: center; margin-bottom: 1rem; }}

@media (max-width: 760px) {{
  [data-testid='stMainBlockContainer'] {{ padding: 1.1rem 1rem 3rem; }}
  h1 {{ font-size: 1.8rem !important; }}
  .psa-review-intro {{ padding: .1rem 0 .7rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
"""


def inject_global_css() -> None:
    """Inject the review-desk theme once at app startup."""
    st.html(_build_css())


def subtitle_block_html(label: str) -> str:
    return f'<div class="psa-title-block"><p class="psa-subtitle">{html.escape(label)}</p></div>'


def review_composer_html(kicker: str, title: str, hint: str) -> str:
    return (
        '<div class="psa-review-intro">'
        f'<div class="psa-review-composer__kicker">{html.escape(kicker)}</div>'
        f'<p class="psa-review-composer__title">{html.escape(title)}</p>'
        f'<p class="psa-review-composer__hint">{html.escape(hint)}</p>'
        '</div>'
    )


def run_summary_html(claims: int, critiques: int) -> str:
    return (
        '<div class="psa-run-summary">'
        '<strong>评审完成</strong>'
        f'<span>Intake 抽取 {claims} 条 claim</span>'
        f'<span>·</span><span>Critic 识别 {critiques} 条 finding</span>'
        '</div>'
    )


def severity_badge_html(severity: str) -> str:
    sev = severity.upper() if isinstance(severity, str) else "?"
    klass = f"psa-severity--{sev.lower()}" if sev in {"P0", "P1", "P2"} else ""
    return f'<span class="psa-severity {klass}">{html.escape(sev)}</span>'


def skill_chip_html(skill_id: str) -> str:
    return f'<span class="psa-skill-chip">Skill · <code>{html.escape(skill_id)}</code></span>'


def critique_header_html(severity: str, finding: str, claim_id: str, skill_id: str | None) -> str:
    skill = skill_chip_html(skill_id) if skill_id else ""
    return (
        '<div class="psa-critique-header">'
        f'{severity_badge_html(severity)}'
        f'<div><div class="psa-critique-title">{html.escape(finding)}</div>'
        f'<div class="psa-critique-meta">claim_id: {html.escape(claim_id)} &nbsp; {skill}</div></div>'
        '</div>'
    )


def field_html(label: str, value: str) -> str:
    return (
        f'<div class="psa-field-label">{html.escape(label)}</div>'
        f'<div class="psa-field-value">{html.escape(value)}</div>'
    )


def verdict_open_html() -> str:
    return '<div class="psa-verdict-shell">'


def verdict_close_html() -> str:
    return '</div>'


def verdict_summary_html(text: str) -> str:
    return f'<p class="psa-verdict-summary">{html.escape(text)}</p>'


def dialog_panel_open_html(critic_id: str, *, prefix: str = "继续追问") -> str:
    return f'<div class="psa-dialog-panel"><strong>{html.escape(prefix)} {html.escape(critic_id)}</strong></div>'


def thinking_html(text: str, *, in_progress: bool, label: str | None = None) -> str:
    if label is None:
        label = "推理中" if in_progress else "推理过程"
    cursor = " ▌" if in_progress else ""
    return f'<div class="psa-thinking"><strong>{html.escape(label)}</strong><br>{html.escape(text)}{cursor}</div>'
