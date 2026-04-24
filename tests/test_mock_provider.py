"""Tests for MockProvider — verifies keyword routing and streaming shape."""

from __future__ import annotations

import json

import pytest

from src.llm.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_complete_routes_by_keyword():
    provider = MockProvider()

    # JSON-shaped responders (intake + 4 critics) — text parses as JSON and
    # carries a matching `role` marker.
    json_cases = {
        "You are the User Advocate critic.": "user_advocate",
        "You are the Engineering critic.": "engineering",
        "You are the Business critic.": "business",
        "You are the Design critic.": "design",
        "You are the Intake agent.": "intake",
    }
    for system, expected_role in json_cases.items():
        resp = await provider.complete(system=system, user="PRD body")
        payload = json.loads(resp.text)
        assert payload["role"] == expected_role
        assert resp.model_id == "mock-1"

    # Supervisor is special: it returns an XML envelope, not bare JSON.
    sup = await provider.complete(system="You are the Supervisor agent.", user="x")
    assert "<thinking>" in sup.text and "</thinking>" in sup.text
    assert "<verdict>" in sup.text and "</verdict>" in sup.text
    assert sup.model_id == "mock-1"

    assert len(provider.call_log) == len(json_cases) + 1


@pytest.mark.asyncio
async def test_complete_unknown_system():
    provider = MockProvider()
    resp = await provider.complete(system="totally unrelated prompt", user="x")
    assert json.loads(resp.text)["role"] == "unknown"


@pytest.mark.asyncio
async def test_stream_yields_chunks():
    provider = MockProvider()
    chunks = []
    async for chunk in provider.stream(
        system="You are the Engineering critic.", user="PRD"
    ):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert all(c["type"] == "text" for c in chunks)
    assert all(isinstance(c["delta"], str) for c in chunks)
    joined = "".join(c["delta"] for c in chunks).strip()
    assert "engineering" in joined
