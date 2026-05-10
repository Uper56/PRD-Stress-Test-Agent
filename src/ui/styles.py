"""Global visual system for the Streamlit app.

Design language: **Modern tech / Blue-violet** preset from
[garden-skills](https://github.com/ConardLi/garden-skills). Translated from
that skill's HTML/CSS targeting into Streamlit-safe CSS injection.

Palette is defined in **OKLCH** (perceptually uniform — derivatives stay
harmonic across lightness/chroma shifts; you can't get the same property
out of HSL or RGB-shifted palettes). Streamlit's `config.toml` accepts
only hex, so the four base theme tokens are provided as hex
approximations there; everything else (severity badges, dialog
backgrounds, hover states, semantic colours) lives in injected CSS that
the modern browser interprets natively.

Anti-cliché checklist enforced here:
  - No purple→pink→blue gradient backgrounds anywhere.
  - No coloured left-border accent on cards (we use a top-border or a
    flat background tint instead).
  - No drawn SVG decorations — placeholders only.
  - No "peak AI aesthetic" of Inter + Roboto everywhere; Space Grotesk
    handles every display surface (h1-h3, badges), Inter only carries
    body / caption text.
  - Severity stays as flat text badges (P0 / P1 / P2), no emoji icons.
  - Section markers (🎯 🧠 💡 📊 📚 🧪) are explicitly allowed by the
    project's design brief and act as wayfinding, not decoration.
"""

from __future__ import annotations

import streamlit as st


# ---------------------------------------------------------------------------
# Palette — derived from primary `oklch(0.55 0.25 250)` (blue-violet).
#
# Use these as semantic names, not as raw values, in the rest of the UI.
# When you need a new shade, derive it via oklch() in the same hue family
# (250) — never mint a new hex out of thin air.
# ---------------------------------------------------------------------------

PALETTE = {
    # Brand
    "primary": "oklch(0.55 0.25 250)",            # blue-violet
    "primary_hover": "oklch(0.62 0.23 250)",
    "primary_subtle_bg": "oklch(0.95 0.04 250)",  # used on dark? no — for cards in light mode only
    "primary_on_dark": "oklch(0.72 0.18 250)",    # higher L for dark surfaces

    # Surface (dark mode default — matches existing config.toml choice)
    "bg": "oklch(0.18 0.02 250)",
    "surface": "oklch(0.22 0.02 250)",
    "surface_raised": "oklch(0.26 0.02 250)",
    "border": "oklch(0.32 0.02 250)",

    # Text
    "text": "oklch(0.96 0.01 250)",
    "text_muted": "oklch(0.72 0.02 250)",
    "text_subtle": "oklch(0.55 0.02 250)",

    # Semantic — perceptually balanced, not pure-red / pure-yellow.
    # Each holds the same L≈0.62 so badges look balanced side-by-side.
    "severity_p0": "oklch(0.62 0.20 25)",   # warm red-orange
    "severity_p1": "oklch(0.72 0.15 70)",   # amber
    "severity_p2": "oklch(0.65 0.03 250)",  # cool neutral
    "success": "oklch(0.65 0.15 150)",      # teal-green, not stoplight green
    "info": "oklch(0.65 0.12 220)",         # close to primary hue, slightly cooler
}


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------

_FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Space+Grotesk:wght@500;600;700&"
    "family=Inter:wght@400;500;600&"
    'display=swap" rel="stylesheet">'
)


def _build_css() -> str:
    p = PALETTE
    return f"""
<style>
:root {{
  --color-primary: {p["primary"]};
  --color-primary-hover: {p["primary_hover"]};
  --color-primary-on-dark: {p["primary_on_dark"]};
  --color-bg: {p["bg"]};
  --color-surface: {p["surface"]};
  --color-surface-raised: {p["surface_raised"]};
  --color-border: {p["border"]};
  --color-text: {p["text"]};
  --color-text-muted: {p["text_muted"]};
  --color-text-subtle: {p["text_subtle"]};
  --color-p0: {p["severity_p0"]};
  --color-p1: {p["severity_p1"]};
  --color-p2: {p["severity_p2"]};
  --color-success: {p["success"]};
  --color-info: {p["info"]};

  --font-display: 'Space Grotesk', ui-sans-serif, sans-serif;
  --font-body: 'Inter', ui-sans-serif, sans-serif;
}}

/* ------- typography ----------------------------------------------------- */

html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
.stButton > button,
.stTextArea textarea,
.stTextInput input,
[data-testid="stSidebar"] {{
  font-family: var(--font-body);
  text-wrap: pretty;
}}

/* Display surfaces use Space Grotesk for the 4-6× scale contrast garden-skills
   prescribes between h1 and body.  clamp() keeps the title readable on
   narrow viewports without over-shrinking. */
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
.stTabs [data-baseweb="tab"] p,
[data-testid="stMetric"] [data-testid="stMetricLabel"],
[data-testid="stMetric"] [data-testid="stMetricValue"] {{
  font-family: var(--font-display);
  letter-spacing: -0.01em;
}}
[data-testid="stMarkdownContainer"] h1 {{
  font-size: clamp(1.9rem, 2.6vw, 2.6rem);
  font-weight: 700;
  line-height: 1.15;
}}
[data-testid="stMarkdownContainer"] h2 {{
  font-size: clamp(1.35rem, 1.8vw, 1.65rem);
  font-weight: 600;
  margin-top: 1.5rem;
}}
[data-testid="stMarkdownContainer"] h3 {{
  font-size: 1.15rem;
  font-weight: 600;
}}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {{
  font-size: 1rem;
  line-height: 1.55;
  color: var(--color-text);
}}

/* ------- buttons -------------------------------------------------------- */
/* Flat, no gradient, no large radius. Hover = colour shift, not a glow. */

.stButton > button {{
  font-family: var(--font-body);
  font-weight: 500;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  transition: background-color 120ms ease, border-color 120ms ease;
}}
.stButton > button:hover:not(:disabled) {{
  border-color: var(--color-primary-on-dark);
  background: var(--color-surface-raised);
}}
.stButton > button[kind="primary"] {{
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: white;
}}
.stButton > button[kind="primary"]:hover:not(:disabled) {{
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
}}
.stButton > button:disabled {{
  opacity: 0.45;
}}

/* ------- compliance badge (top-of-page label) --------------------------- */

.psa-compliance-badge {{
  display: inline-block;
  font-family: var(--font-display);
  font-size: 0.78rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  padding: 4px 12px;
  border-radius: 999px;
  background: color-mix(in oklch, var(--color-primary) 18%, transparent);
  border: 1px solid color-mix(in oklch, var(--color-primary) 40%, transparent);
  color: var(--color-text);
}}

/* ------- severity tag (used by critique cards) -------------------------- */

.psa-severity {{
  display: inline-block;
  font-family: var(--font-display);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 2px 8px;
  border-radius: 4px;
  color: white;
}}
.psa-severity--p0 {{ background: var(--color-p0); }}
.psa-severity--p1 {{ background: var(--color-p1); }}
.psa-severity--p2 {{ background: var(--color-p2); }}

/* ------- skill chip ----------------------------------------------------- */
/* Replaces the previous yellow chip; uses primary tone instead of
   stoplight yellow to stay on-palette. */

.psa-skill-chip {{
  display: inline-block;
  font-family: var(--font-body);
  font-size: 0.78rem;
  padding: 2px 10px;
  border-radius: 999px;
  background: color-mix(in oklch, var(--color-primary) 14%, transparent);
  border: 1px solid color-mix(in oklch, var(--color-primary) 36%, transparent);
  color: var(--color-text);
}}
.psa-skill-chip code {{
  background: transparent;
  color: var(--color-primary-on-dark);
  padding: 0;
}}

/* ------- dialog panel --------------------------------------------------- */
/* Forbidden by garden-skills: coloured LEFT-border accent.
   We use a flat background tint + top-border instead. */

.psa-dialog-panel {{
  background: color-mix(in oklch, var(--color-primary) 10%, transparent);
  border-top: 2px solid var(--color-primary-on-dark);
  border-radius: 0 0 6px 6px;
  padding: 8px 14px;
  margin: 6px 0;
  font-family: var(--font-body);
}}
.psa-dialog-panel code {{
  font-size: 0.85em;
  color: var(--color-primary-on-dark);
}}

/* ------- supervisor thinking trace -------------------------------------- */

.psa-thinking {{
  font-family: var(--font-body);
  font-style: italic;
  color: var(--color-text-muted);
  white-space: pre-wrap;
  line-height: 1.5;
}}

/* ------- sidebar separator + headers ------------------------------------ */

[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
  font-family: var(--font-display);
  letter-spacing: -0.005em;
}}

/* Streamlit's default expander has a subtle bottom border that fights with
   the surface palette; tighten it. */
[data-testid="stExpander"] {{
  border-color: var(--color-border) !important;
}}

/* ------- metric cards (Ablation tab) ------------------------------------ */

[data-testid="stMetric"] {{
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 10px 14px;
}}

/* ------- tabs ----------------------------------------------------------- */

.stTabs [data-baseweb="tab"] {{
  font-family: var(--font-display);
  font-weight: 500;
  letter-spacing: -0.005em;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
  color: var(--color-primary-on-dark);
}}
</style>
"""


def inject_global_css() -> None:
    """Inject the global visual system. Call once at the top of `main()`.

    Idempotent in practice: Streamlit deduplicates identical markdown
    blocks across the same script run, so calling this twice in one
    request does no harm.
    """
    st.markdown(_FONTS_LINK + _build_css(), unsafe_allow_html=True)


def severity_badge_html(severity: str) -> str:
    """Render a severity badge using the visual-system class names.

    Centralised so every call site looks the same and the `style=` blob
    we used to inline at every render goes away. Falls back gracefully
    on unknown severities.
    """
    sev = severity.upper() if isinstance(severity, str) else "?"
    klass = f"psa-severity--{sev.lower()}" if sev in {"P0", "P1", "P2"} else ""
    return (
        f'<span class="psa-severity {klass}">{sev}</span>'
        if klass
        else f'<span class="psa-severity">{sev}</span>'
    )


def skill_chip_html(skill_id: str) -> str:
    """Render a 'Triggered by skill' chip in the on-palette style."""
    return (
        f'<span class="psa-skill-chip">'
        f'<span style="opacity:0.75;margin-right:4px;">↳ skill</span>'
        f'<code>{skill_id}</code>'
        f"</span>"
    )


def compliance_badge_html(label: str) -> str:
    """Render the top-of-page Anthropic-spec compliance badge."""
    return f'<span class="psa-compliance-badge">{label}</span>'


def dialog_panel_open_html(critic_id: str) -> str:
    """Open tag for the inline critique-dialog panel.

    Caller renders the chat history inside, then closes with
    `dialog_panel_close_html()`. The panel uses a flat background tint
    + top-border instead of the AI-cliché coloured left-border accent.
    """
    return (
        f'<div class="psa-dialog-panel">'
        f"<b>Follow-up with <code>{critic_id}</code></b>"
        f"</div>"
    )


def thinking_html(text: str, *, in_progress: bool) -> str:
    """Render the supervisor's `<thinking>` trace with our typography.

    `in_progress=True` appends a cursor glyph; `False` freezes the trace
    once streaming has finished.
    """
    label = "Thinking…" if in_progress else "Thinking (done)"
    cursor = "▍" if in_progress else ""
    return (
        f'<div class="psa-thinking">'
        f"<b>{label}</b> {text}{cursor}"
        f"</div>"
    )
