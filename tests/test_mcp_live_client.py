"""Tests for the live-MCP result unwrapper.

The heavy subprocess integration (spawning the real server, handshake,
tool calls) lives in `scripts/verify_mcp.py` so the test suite stays fast
and free of subprocess flakiness. Here we unit-test the pure
`unwrap_tool_result` helper that turns a FastMCP `CallToolResult` into a
plain Python value — this is exactly the logic that fixed the "15 vs 7"
bug (counting a dict's keys instead of reading the list).
"""

from __future__ import annotations

import json
import types

from src.skills.mcp_live_client import unwrap_tool_result


def _text_block(text: str):
    return types.SimpleNamespace(text=text)


def _result(*, structured=None, content=None):
    return types.SimpleNamespace(structuredContent=structured, content=content)


def test_prefers_structured_content_result() -> None:
    """The clean path: FastMCP's structuredContent={'result': <value>}."""
    skills = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    r = _result(
        structured={"result": skills},
        # content also present (one block per item) — must be ignored.
        content=[_text_block(json.dumps(s)) for s in skills],
    )
    assert unwrap_tool_result(r) == skills
    # Critically: length is the SKILL count (3), not a dict's key count.
    assert len(unwrap_tool_result(r)) == 3


def test_single_content_block_json_object() -> None:
    """No structuredContent; one block holding a JSON object."""
    r = _result(structured=None, content=[_text_block('{"name": "x", "v": 1}')])
    assert unwrap_tool_result(r) == {"name": "x", "v": 1}


def test_single_content_block_plain_string() -> None:
    """read_skill_md returns a raw string, not JSON."""
    raw = "---\nname: foo\n---\n# body"
    r = _result(structured=None, content=[_text_block(raw)])
    assert unwrap_tool_result(r) == raw


def test_multiple_content_blocks_become_a_list() -> None:
    """Fallback path: a list return spread across N content blocks."""
    items = [{"name": "a"}, {"name": "b"}]
    r = _result(structured=None, content=[_text_block(json.dumps(i)) for i in items])
    assert unwrap_tool_result(r) == items


def test_empty_result_is_none() -> None:
    assert unwrap_tool_result(_result(structured=None, content=[])) is None
    assert unwrap_tool_result(_result(structured=None, content=None)) is None
