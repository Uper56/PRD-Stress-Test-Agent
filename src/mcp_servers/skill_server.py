"""Read-only MCP server exposing the Skill Library.

Three tools are registered via FastMCP:
  - list_skills(status="active")
  - read_skill(skill_id)
  - search_skills(query, critic_id=None, top_k=3)

Run with stdio transport:

    python -m src.mcp_servers.skill_server

Or point an MCP client at this command in its `.mcp.json` / config. The
server reads `src/skills/library.yaml` and the fragments directory at
startup; restart the server to pick up library edits.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..skills import SkillRetriever


# Instantiate once at import time so cold starts pay the YAML-load cost
# up front, not on the first tool call.
_retriever = SkillRetriever()
_retriever.load_library()

mcp = FastMCP("prd-skill-library")


def _skill_to_dict(skill, include_body: bool = False) -> dict[str, Any]:
    """Serialize a Skill to a plain dict for MCP transport.

    `include_body` gates the (potentially large) `prompt_fragment_content`
    field — list endpoints skip it; `read_skill` includes it.
    """
    data = skill.model_dump()
    if not include_body:
        data.pop("prompt_fragment_content", None)
    return data


@mcp.tool()
def list_skills(status: str = "active") -> list[dict[str, Any]]:
    """Return metadata for every skill whose `status` matches.

    Pass `status="all"` to get active + deprecated in one call.
    """
    lib = _retriever.load_library()
    if status == "all":
        skills = lib.skills
    else:
        skills = [s for s in lib.skills if s.status == status]
    return [_skill_to_dict(s, include_body=False) for s in skills]


@mcp.tool()
def read_skill(skill_id: str) -> dict[str, Any]:
    """Return a single skill including its full `prompt_fragment_content`.

    Raises `ValueError` if the id is not in the library.
    """
    lib = _retriever.load_library()
    skill = lib.by_id(skill_id)
    if skill is None:
        raise ValueError(f"Unknown skill_id: {skill_id!r}")
    return _skill_to_dict(skill, include_body=True)


@mcp.tool()
def search_skills(
    query: str,
    critic_id: str | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Keyword-rank skills against `query`; filter to `critic_id` if given.

    When `critic_id` is None, searches across all critics. Result is ordered
    by descending keyword hit count (tie-break: confidence).
    """
    # If no critic_id, temporarily run retrieval once per critic and merge.
    # Fine for library sizes we'll see in practice (< ~50 skills).
    if critic_id is not None:
        skills = _retriever.retrieve(query, critic_id=critic_id, top_k=top_k)
    else:
        merged: dict[str, Any] = {}
        for cid in ("engineering", "business", "user_advocate", "design"):
            for s in _retriever.retrieve(query, critic_id=cid, top_k=top_k):
                merged[s.id] = s
        skills = list(merged.values())[:top_k]
    return [_skill_to_dict(s, include_body=False) for s in skills]


def main() -> None:  # pragma: no cover — runtime entry point
    """Run the server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
