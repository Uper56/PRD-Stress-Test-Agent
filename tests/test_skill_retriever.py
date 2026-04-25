"""Tests for the Skill Library + retriever + MCP client surface.

Day 8.5: skills now live as SKILL.md folders under src/skills/seed/.
Identifiers are kebab-case names (e.g. "api-dependency-enumeration"),
not the legacy `skl_001_*` ids.
"""

from __future__ import annotations

import pytest

from src.agents.critics.engineering import run_engineering
from src.llm.mock_provider import MockProvider
from src.skills.mcp_client import (
    list_skills,
    read_skill,
    read_skill_md,
    search_skills,
)
from src.skills.retriever import SkillRetriever, format_skills_block


SEED_NAMES = {
    "api-dependency-enumeration",
    "quantified-metrics",
    "phased-rollout",
    "accessibility-check",
    "user-evidence",
    "internal-contradiction",
}


# ---- Library load ----------------------------------------------------------


def test_load_library_includes_all_seed_skills_with_bodies() -> None:
    r = SkillRetriever()
    lib = r.load_library()
    names = {s.name for s in lib.skills}
    assert names == SEED_NAMES, f"unexpected library contents: {names}"
    for s in lib.skills:
        assert s.prompt_fragment_content, f"{s.name} missing markdown body"
        assert "## When to apply" in s.prompt_fragment_content, (
            f"{s.name} body looks malformed"
        )
        # id mirrors name on the new format.
        assert s.id == s.name


# ---- Retrieval filtering + ranking ----------------------------------------


def test_retrieve_filters_by_critic_id() -> None:
    """A skill injected only into `engineering` must never return for `design`."""
    r = SkillRetriever()
    hits = r.retrieve(
        "We will integrate with Stripe API and add webhook handlers.",
        critic_id="design",
    )
    assert all(s.name != "api-dependency-enumeration" for s in hits)


def test_retrieve_ranks_api_skill_first_for_api_heavy_prd() -> None:
    r = SkillRetriever()
    prd = (
        "We will integrate with the Stripe API for payments. Webhooks will "
        "notify our endpoint on charge events. We will also use OpenAI SDK "
        "for summaries and Twilio for SMS."
    )
    hits = r.retrieve(prd, critic_id="engineering", top_k=3)
    assert hits, "expected at least one engineering hit on an API-heavy PRD"
    assert hits[0].name == "api-dependency-enumeration"


def test_retrieve_returns_empty_when_no_keywords_match() -> None:
    r = SkillRetriever()
    hits = r.retrieve("hello world, nothing interesting here", "engineering")
    assert hits == []


def test_format_skills_block_wraps_in_xml_tags() -> None:
    r = SkillRetriever()
    hits = r.retrieve("deflect 40% of tickets, measure retention", "business")
    block = format_skills_block(hits)
    assert "<retrieved_skills>" in block
    assert "quantified-metrics" in block
    assert "</retrieved_skills>" in block


# ---- End-to-end: critic stamps skill_id onto critiques --------------------


async def test_engineering_critic_stamps_skill_id_when_retrieval_fires() -> None:
    """`_shared.run_critic` backfills the first retrieved skill name when
    the model itself didn't attribute one — telemetry survives."""
    llm = MockProvider()
    state = {
        "prd_text": (
            "[001] We integrate with the Stripe API for payments.\n"
            "[002] Webhooks notify our endpoint on charge events.\n"
        ),
        "prd_claims": [],
    }
    critiques = await run_engineering(state, llm)
    assert critiques, "engineering should return a critique on this mock"
    assert critiques[0].skill_id == "api-dependency-enumeration"


async def test_skill_id_stays_null_when_no_keywords_match() -> None:
    """Clean mock PRD → no retrieval hit → skill_id stays None."""
    llm = MockProvider()
    state = {
        "prd_text": "[001] hello world\n[002] nothing special\n",
        "prd_claims": [],
    }
    critiques = await run_engineering(state, llm)
    assert critiques
    assert critiques[0].skill_id is None


# ---- MCP client surface (mirror of MCP server tools) ----------------------


def test_mcp_list_skills_returns_six_active() -> None:
    items = list_skills()
    assert len(items) == 6
    assert all(s["status"] == "active" for s in items)
    assert all("prompt_fragment_content" not in s for s in items)
    # The new spec exposes name (= id) and version on every entry.
    assert all(s["name"] == s["id"] for s in items)
    assert all(s.get("version") == "1.0" for s in items)


def test_mcp_read_skill_includes_markdown_body() -> None:
    data = read_skill("quantified-metrics")
    assert data["name"] == "quantified-metrics"
    assert data["prompt_fragment_content"]
    assert "Baseline" in data["prompt_fragment_content"]


def test_mcp_read_skill_md_returns_raw_file_with_frontmatter() -> None:
    raw = read_skill_md("quantified-metrics")
    assert raw.startswith("---\n"), "must include leading frontmatter fence"
    assert "name: quantified-metrics" in raw
    assert "## When to apply" in raw, "markdown body must be present"


def test_mcp_read_skill_raises_on_unknown_name() -> None:
    with pytest.raises(ValueError):
        read_skill("does-not-exist")


def test_mcp_search_skills_with_and_without_critic_filter() -> None:
    eng = search_skills("Stripe API webhook", critic_id="engineering")
    assert any(s["name"] == "api-dependency-enumeration" for s in eng)

    any_critic = search_skills("Stripe API webhook", critic_id=None, top_k=5)
    assert any(s["name"] == "api-dependency-enumeration" for s in any_critic)
