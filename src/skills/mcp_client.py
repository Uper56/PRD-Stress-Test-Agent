"""In-process client mirror of the MCP skill-server tool surface.

Same function signatures as the tools registered in
`src/mcp_servers/skill_server.py`, but the implementations run in-process so
tests and notebooks can exercise the Skill Library without spawning a stdio
subprocess. The real MCP server wraps the same underlying `SkillRetriever`,
so swapping to a transport-backed client later is a drop-in replacement.
"""

from __future__ import annotations

from typing import Any

from .retriever import default_retriever


def _skill_to_dict(skill, include_body: bool = False) -> dict[str, Any]:
    data = skill.model_dump()
    if not include_body:
        data.pop("prompt_fragment_content", None)
    return data


def list_skills(status: str = "active") -> list[dict[str, Any]]:
    """List skills by status. `status="all"` returns active + deprecated."""
    lib = default_retriever().load_library()
    if status == "all":
        skills = lib.skills
    else:
        skills = [s for s in lib.skills if s.status == status]
    return [_skill_to_dict(s, include_body=False) for s in skills]


def read_skill(skill_id: str) -> dict[str, Any]:
    """Return one skill with full `prompt_fragment_content` body."""
    lib = default_retriever().load_library()
    skill = lib.by_id(skill_id)
    if skill is None:
        raise ValueError(f"Unknown skill_id: {skill_id!r}")
    return _skill_to_dict(skill, include_body=True)


def search_skills(
    query: str,
    critic_id: str | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Keyword-rank skills against `query`; optional critic_id filter."""
    r = default_retriever()
    if critic_id is not None:
        skills = r.retrieve(query, critic_id=critic_id, top_k=top_k)
    else:
        merged: dict[str, Any] = {}
        for cid in ("engineering", "business", "user_advocate", "design"):
            for s in r.retrieve(query, critic_id=cid, top_k=top_k):
                merged[s.id] = s
        skills = list(merged.values())[:top_k]
    return [_skill_to_dict(s, include_body=False) for s in skills]
