"""Language detection + bilingual prompt directives.

When the PRD comes in Chinese, the agent prompts (all written in English)
otherwise pull the model toward English-only output — the user sees a
Chinese PRD but `finding` / `evidence` / `suggested_fix` come back in
English. This module gives every agent a small directive to append to
its system prompt so the model returns human-readable fields in the
same language as the input PRD, while keeping JSON field names + role
identifiers (`critic_id`, `claim_id`, `skill_id`, severity `P0/P1/P2`)
in English so the parsers don't break.

The detector is intentionally simple: count CJK Unified Ideographs and
common CJK Extension-A chars in the input. We don't need to distinguish
Simplified vs Traditional, and we don't need to handle Japanese
specifically (the directive says "match the PRD's language", which
covers Japanese too via the same fallback).
"""

from __future__ import annotations

from typing import Literal

Language = Literal["en", "zh"]


# Threshold: if the PRD contains ≥ this many CJK characters we treat it
# as Chinese. Picked low (20) because even short Chinese PRDs (~50 chars)
# clear this comfortably, but a single Chinese name in an English doc
# (e.g. "by 王明") doesn't trip it.
_CJK_THRESHOLD = 20


def _is_cjk(ch: str) -> bool:
    """True for the main CJK Unified Ideographs ranges."""
    cp = ord(ch)
    # U+4E00–U+9FFF: CJK Unified Ideographs (main block)
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    # U+3400–U+4DBF: CJK Extension A
    if 0x3400 <= cp <= 0x4DBF:
        return True
    return False


def detect_language(text: str) -> Language:
    """Return "zh" if the text contains ≥ `_CJK_THRESHOLD` CJK chars, else "en".

    Cheap O(n) scan, no regex compile.
    """
    if not text:
        return "en"
    cjk_count = 0
    for ch in text:
        if _is_cjk(ch):
            cjk_count += 1
            if cjk_count >= _CJK_THRESHOLD:
                return "zh"
    return "en"


# Hard rule for the directive: JSON field names + technical identifiers
# stay English (so Pydantic validation doesn't break and so severity
# stays comparable across runs), but the human-readable text in each
# field is written in the PRD's language.
_ZH_DIRECTIVE = """

---

# 输出语言要求 / Output language requirement

本次 PRD 为中文。请按以下规则填写 JSON 输出：

- **人类可读的字符串值用简体中文**：包括 finding / evidence / suggested_fix /
  executive_summary / counter_finding 等所有自然语言字段的 VALUE。
- **JSON key 和技术标识符保持英文**：包括 `finding`, `evidence`,
  `suggested_fix`, `critic_id`, `claim_id`, `skill_id`,
  `severity` 的取值 (P0 / P1 / P2 / 而不是"严重/中等/轻微"),
  `claim_type` 的取值 (assumption / requirement / metric / scope / dependency)，
  以及任何 `skl_*` 形式的 ID。
- 引用 PRD 原文时用原文里的语言（中文 PRD → 中文引用）。

严格遵守这两条规则，否则下游解析器会拒绝你的输出。
"""


def language_directive(lang: Language) -> str:
    """Return the directive to append to a system prompt for the given language.

    English returns the empty string — the upstream prompts already
    assume English so no directive is needed.
    """
    if lang == "zh":
        return _ZH_DIRECTIVE
    return ""


def system_with_language(base_system: str, prd_text: str) -> str:
    """Convenience wrapper used at every agent's call site.

    Detects the language from `prd_text`, appends the directive (if any)
    to `base_system`, and returns the combined system prompt.
    """
    return base_system + language_directive(detect_language(prd_text))
