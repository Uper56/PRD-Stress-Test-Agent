"""Live MCP client — talks to the real `skill_server` over stdio.

This is the *real* MCP path, in contrast to `mcp_client.py` (an in-process
mirror that calls `SkillRetriever` directly). The Streamlit UI's Skill
Library panel uses THIS module so that "the UI browses skills over a live
MCP connection" is literally true.

Architecture note (intentional layering):
  - Display surface (Streamlit sidebar)  → live MCP over stdio (this module)
  - Latency-sensitive critic hot path     → in-process `default_retriever()`
    read (unchanged). We don't pay subprocess + protocol overhead on every
    critic call; we DO expose the library through a standard MCP interface.

Why a background thread + dedicated event loop?
  Streamlit reruns the script synchronously and each `asyncio.run()` spins
  up a fresh event loop. An MCP `ClientSession` (and its stdio transport)
  is bound to the loop it was created on, so it cannot be cached across
  reruns and reused from a different loop. The `MCPGateway` owns ONE
  persistent loop on a daemon thread; the Streamlit main thread marshals
  tool calls onto it via `run_coroutine_threadsafe`. This keeps a single
  server subprocess alive across reruns (what `st.cache_resource` is for)
  without cross-loop reuse bugs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Repo root = parents[2] of src/skills/mcp_live_client.py. Passed as the
# subprocess cwd so `python -m src.mcp_servers.skill_server` resolves
# `src` regardless of where Streamlit was launched.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CONNECT_TIMEOUT = 20.0
_CALL_TIMEOUT = 20.0


# ---- result unwrapping -----------------------------------------------------


def unwrap_tool_result(result: Any) -> Any:
    """Extract the Python value from a FastMCP `CallToolResult`.

    FastMCP returns typed tool outputs two ways at once:
      - `structuredContent = {"result": <value>}`  (the clean path)
      - `content = [TextContent, ...]`              (one block per list item
                                                      for list returns; a
                                                      single block for str)

    We prefer `structuredContent["result"]`. The old verify script read
    `content[0].text` and counted its dict *keys* — that's the "15 vs 7"
    bug. This helper is pure and unit-tested without a server.
    """
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]

    blocks = getattr(result, "content", None) or []
    if not blocks:
        return None
    if len(blocks) == 1:
        text = getattr(blocks[0], "text", None)
        if text is None:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    # Multiple content blocks → a list. Parse each as JSON, fall back to raw.
    out: list[Any] = []
    for b in blocks:
        text = getattr(b, "text", "")
        try:
            out.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            out.append(text)
    return out


# ---- persistent gateway ----------------------------------------------------


class MCPConnectionError(RuntimeError):
    """Raised when the live MCP server can't be reached."""


class MCPGateway:
    """Owns a persistent stdio connection to the skill MCP server.

    Construction spawns the server subprocess, completes the MCP
    handshake, and leaves the session open on a dedicated background
    event loop. Raises `MCPConnectionError` if any of that fails (the
    Streamlit caller catches this and falls back to in-process reads).
    """

    def __init__(self, connect_timeout: float = _CONNECT_TIMEOUT) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="mcp-gateway-loop", daemon=True
        )
        self._thread.start()
        self._session: Any = None
        self._stack: AsyncExitStack | None = None
        try:
            self._run(self._aconnect(), connect_timeout)
        except Exception as e:  # noqa: BLE001
            self.close()
            raise MCPConnectionError(f"failed to start MCP server: {e}") from e

    # ---- async plumbing ---------------------------------------------------

    def _run(self, coro, timeout: float):
        """Marshal a coroutine onto the gateway's loop and block for its result."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _aconnect(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_servers.skill_server"],
            cwd=str(_REPO_ROOT),
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    # ---- public tool surface ---------------------------------------------

    def tool_names(self, timeout: float = _CALL_TIMEOUT) -> list[str]:
        result = self._run(self._session.list_tools(), timeout)
        return [t.name for t in result.tools]

    def call_tool(
        self, name: str, args: dict[str, Any], timeout: float = _CALL_TIMEOUT
    ) -> Any:
        result = self._run(self._session.call_tool(name, args), timeout)
        return unwrap_tool_result(result)

    def list_skills(self, status: str = "active") -> list[dict]:
        out = self.call_tool("list_skills", {"status": status})
        return out if isinstance(out, list) else []

    def read_skill_md(self, skill_name: str) -> str:
        out = self.call_tool("read_skill_md", {"skill_name": skill_name})
        return out if isinstance(out, str) else str(out)

    def search_skills(
        self, query: str, critic_id: str | None = None, top_k: int = 3
    ) -> list[dict]:
        out = self.call_tool(
            "search_skills",
            {"query": query, "critic_id": critic_id, "top_k": top_k},
        )
        return out if isinstance(out, list) else []

    # ---- teardown ---------------------------------------------------------

    def close(self) -> None:
        """Best-effort: close the session + stop the loop thread."""
        try:
            if self._stack is not None and self._loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    self._stack.aclose(), self._loop
                )
                try:
                    fut.result(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
        finally:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:  # noqa: BLE001
                pass


def build_gateway() -> MCPGateway:
    """Factory used by the Streamlit cache. Raises MCPConnectionError on failure."""
    return MCPGateway()
