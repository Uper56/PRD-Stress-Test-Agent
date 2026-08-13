"""Tests for the bilingual prompt-directive helper."""

from __future__ import annotations

from src.agents._language import (
    detect_language,
    force_language,
    language_directive,
    system_with_language,
)


def test_detect_pure_english_is_en() -> None:
    assert detect_language("# PRD: Loyalty program\n\nUsers earn points for purchases.") == "en"


def test_detect_pure_chinese_is_zh() -> None:
    text = (
        "本 PRD 描述一个新的会员积分系统。"
        "用户每消费一元获得一积分。积分可以兑换奖品。"
        "我们希望提升用户留存率。"
    )
    assert detect_language(text) == "zh"


def test_detect_english_with_one_chinese_name_stays_en() -> None:
    """A stray CJK character (e.g. an author name) should not flip the
    detector — we'd lose English-PRD output discipline if it did."""
    text = "This PRD was authored by 王明. " * 3
    # 3 chars × 3 = 9 CJK chars total, below the threshold of 20.
    assert detect_language(text) == "en"


def test_detect_empty_string_is_en() -> None:
    assert detect_language("") == "en"


def test_directive_for_zh_mentions_required_constraints() -> None:
    d = language_directive("zh")
    assert d, "expected non-empty directive for Chinese"
    # Must spell out the contract the JSON parsers depend on.
    for keyword in ("简体中文", "JSON key", "P0", "skill_id", "claim_type"):
        assert keyword in d, f"directive missing {keyword!r}"


def test_directive_for_en_is_empty() -> None:
    assert language_directive("en") == ""


def test_system_with_language_passes_through_for_english() -> None:
    base = "You are a critic. Respond in JSON."
    assert system_with_language(base, "All English PRD content.") == base


def test_system_with_language_appends_directive_for_chinese() -> None:
    base = "You are a critic. Respond in JSON."
    chinese_prd = "用户登录后看到首页。" * 5
    out = system_with_language(base, chinese_prd)
    assert out.startswith(base)
    assert "简体中文" in out


def test_forced_zh_beats_detection_for_english_prd() -> None:
    """The UI's「中文版本」must force Chinese output even for English PRDs —
    evidence quotes stay in the original language."""
    token = force_language("zh")
    try:
        out = system_with_language("Base prompt.", "An entirely English PRD body.")
        assert "简体中文" in out
        assert "不要翻译引用" in out
    finally:
        token.var.reset(token)


def test_forced_en_stays_directive_free() -> None:
    token = force_language("en")
    try:
        chinese_prd = "用户登录后看到首页。" * 5
        assert system_with_language("Base prompt.", chinese_prd) == "Base prompt."
    finally:
        token.var.reset(token)


def test_forced_language_resets_back_to_auto() -> None:
    """After reset, auto-detection is back."""
    assert system_with_language("Base.", "English text here") == "Base."
    token = force_language("zh")
    try:
        assert "简体中文" in system_with_language("Base.", "English text here")
    finally:
        token.var.reset(token)
    assert system_with_language("Base.", "English text here") == "Base."
