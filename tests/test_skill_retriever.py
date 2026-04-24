"""Tests for the Skill Library + retriever + MCP client surface.

Covers:
  - `SkillRetriever.load_library()` reads every seed skill AND its fragment body.
  - `retrieve()` filters by critic_id (a skill not routed to `design`
    cannot come back when `critic_id="design"`).
  - `retrieve()` ranks skl_001 first for a PRD heavy on API keywords.
  - `skill_id` is stamped onto Critique objects when retrieval fires.
  - The `mcp_client` tool surface (`list_skills` / `read_skill` /
    `search_skills`) returns the 6 seed skills and can round-trip by id.
"""

from __future__ import annotations

import pytest

from src.agents.critics.engineering import run_engineering
from src.llm.mock_provider import MockProvider
from src.skills.mcp_client import list_skills, read_skill, search_skills
from src.skills.retriever import SkillRetriever, format_skills_block


# ---- Library load ----------------------------------------------------------


def test_load_library_includes_all_seed_skills_with_bodies() -> None:
    r = SkillRetriever()
    lib = r.load_library()
    ids = {s.id for s in lib.skills}
    expected = {
        "skl_001_api_dependency_enumeration",
        "skl_002_quantified_metrics",
        "skl_003_phased_rollout",
        "skl_004_accessibility_check",
        "skl_005_user_evidence",
        "skl_006_internal_contradiction",
    }
    assert ids == expected, f"unexpected library contents: {ids}"
    # Every fragment must have loaded into prompt_fragment_content.
    for s in lib.skills:
        assert s.prompt_fragment_content, f"{s.id} missing fragment body"
        assert "## When to apply" in s.prompt_fragment_content, (
            f"{s.id} fragment body looks malformed"
        )


# ---- Retrieval filtering + ranking ----------------------------------------


def test_retrieve_filters_by_critic_id() -> None:
    """A skill injected only into `engineering` must never return for `design`."""
    r = SkillRetriever()
    # skl_001 lives only on engineering — use a prompt loaded with engineering
    # keywords but query as `design`.
    hits = r.retrieve(
        "We will integrate with Stripe API and add webhook handlers.",
        critic_id="design",
    )
    assert all(s.id != "skl_001_api_dependency_enumeration" for s in hits)


def test_retrieve_ranks_api_skill_first_for_api_heavy_prd() -> None:
    r = SkillRetriever()
    prd = (
        "We will integrate with the Stripe API for payments. Webhooks will "
        "notify our endpoint on charge events. We will also use OpenAI SDK "
        "for summaries and Twilio for SMS."
    )
    hits = r.retrieve(prd, critic_id="engineering", top_k=3)
    assert hits, "expected at least one engineering hit on an API-heavy PRD"
    assert hits[0].id == "skl_001_api_dependency_enumeration"


def test_retrieve_returns_empty_when_no_keywords_match() -> None:
    r = SkillRetriever()
    # Keyword-free text → no skill should be force-injected.
    hits = r.retrieve("hello world, nothing interesting here", "engineering")
    assert hits == []


def test_format_skills_block_wraps_in_xml_tags() -> None:
    r = SkillRetriever()
    hits = r.retrieve("deflect 40% of tickets, measure retention", "business")
    block = format_skills_block(hits)
    assert "<retrieved_skills>" in block
    assert "skl_002_quantified_metrics" in block
    assert "</retrieved_skills>" in block


# ---- End-to-end: critic stamps skill_id onto critiques --------------------


async def test_engineering_critic_stamps_skill_id_when_retrieval_fires() -> None:
    """Even though MockProvider returns skill_id=None, `_shared.run_critic`
    backfills the first retrieved skill_id so telemetry is preserved.
    """
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
    assert critiques[0].skill_id == "skl_001_api_dependency_enumeration"


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
    # Body excluded from list for payload-size hygiene.
    assert all("prompt_fragment_content" not in s for s in items)


def test_mcp_read_skill_includes_fragment_body() -> None:
    data = read_skill("skl_002_quantified_metrics")
    assert data["id"] == "skl_002_quantified_metrics"
    assert data["prompt_fragment_content"]
    assert "Baseline" in data["prompt_fragment_content"]


def test_mcp_read_skill_raises_on_unknown_id() -> None:
    with pytest.raises(ValueError):
        read_skill("skl_999_nope")


def test_mcp_search_skills_with_and_without_critic_filter() -> None:
    # Engineering-filtered: only engineering-injected skills are candidates.
    eng = search_skills("Stripe API webhook", critic_id="engineering")
    assert any(s["id"] == "skl_001_api_dependency_enumeration" for s in eng)

    # No filter: should still surface the engineering skill, plus possibly
    # skl_006 (multi-role) depending on keyword overlap.
    any_critic = search_skills("Stripe API webhook", critic_id=None, top_k=5)
    assert any(s["id"] == "skl_001_api_dependency_enumeration" for s in any_critic)
