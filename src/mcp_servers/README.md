# MCP Servers

Custom MCP servers owned by this project.

## `skill_server` — Skill Library (read-only)

Exposes the Skill Library in `src/skills/library.yaml` over MCP stdio
transport.

### Tools

| Tool | Signature | Description |
| ---- | --------- | ----------- |
| `list_skills` | `(status: str = "active") -> list[dict]` | Metadata for every skill with the given status. Use `status="all"` for both active and deprecated. |
| `read_skill` | `(skill_id: str) -> dict` | Single skill including its full `prompt_fragment_content`. |
| `search_skills` | `(query: str, critic_id: str \| None = None, top_k: int = 3) -> list[dict]` | Keyword-rank skills against `query`; optional `critic_id` filter. |

### Run

```bash
python -m src.mcp_servers.skill_server
```

The server uses stdio, so it expects an MCP client to connect over its
stdin/stdout. Register it in your client's config (e.g. `.mcp.json`,
`~/.claude.json`, Cursor/Zed MCP settings):

```json
{
  "mcpServers": {
    "prd-skill-library": {
      "command": "python",
      "args": ["-m", "src.mcp_servers.skill_server"],
      "cwd": "D:/AI WOrk/PRD Stress Test Agent"
    }
  }
}
```

### Quick smoke test without a client

For in-process testing (what the project's pytest suite does), import
`src/skills/mcp_client.py` — it mirrors the same tool surface but runs
synchronously in-process, no subprocess:

```python
from src.skills.mcp_client import list_skills, read_skill, search_skills

print(len(list_skills()))               # 6 seed skills
print(read_skill("skl_001_api_dependency_enumeration")["name"])
print([s["id"] for s in search_skills("integrate with Stripe API", "engineering")])
```

The two surfaces are kept intentionally identical so a future Day can flip
internal callers from `mcp_client` to a real MCP transport client with no
signature changes.

### Writing new skills

1. Drop a fragment file into `src/skills/fragments/skl_NNN_<slug>.md`.
   See the existing fragments for the expected section layout.
2. Append a YAML entry to `src/skills/library.yaml` pointing at the new
   fragment. `injected_into` decides which critic(s) see the skill;
   `trigger_keywords` drive the default keyword retriever's ranking.
3. Restart the MCP server (or your Streamlit / pytest process). There is
   no hot-reload on purpose — this is a read-only store.

### Status

- Day 7: read-only. No write tools. Library is edited by hand in YAML + MD.
- Day 8 (planned): add `propose_skill`, `accept_skill`, `deprecate_skill`
  write tools, gated by human approval before persisting to disk.
