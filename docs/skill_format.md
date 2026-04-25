# Skill Format — Anthropic Agent Skills `SKILL.md` Spec

This project's Skill Library conforms to the **Anthropic Agent Skills
specification** (December 2025). Each skill is a self-contained folder
containing one canonical `SKILL.md` file: a YAML frontmatter block (the
metadata Anthropic and OpenAI Codex CLI both consume) followed by a
Markdown body (the prompt fragment injected into critics).

## Layout

```
src/skills/
├── seed/                              # human-authored skills
│   └── <skill-name>/
│       └── SKILL.md
├── learned/                           # distiller-authored skills (Day 9+)
│   └── <skill-name>/
│       └── SKILL.md
├── runtime_stats.yaml                 # decoupled runtime telemetry
└── _archive/                          # pre-spec format, retained for rollback
```

## `SKILL.md` shape

```markdown
---
name: api-dependency-enumeration         # kebab-case, unique, == folder name
description: |
  Use this skill ANY TIME the PRD references an external API … (pushy,
  not soft. Tell the agent when it MUST apply.)
version: "1.0"
created_by: seed                          # "seed" | "distiller"
injected_into:
  - engineering
trigger_keywords: [api, webhook, stripe]  # optional retrieval metadata
trigger_semantic: PRD mentions any external API …
confidence: 0.85
---

# Skill: API Dependency Enumeration

## When to apply
…

## Instruction
…

## Rationale
…

## Examples of issues this catches
…
```

### Required frontmatter fields

| Field           | Required | Notes                                              |
| --------------- | :------: | -------------------------------------------------- |
| `name`          | ✅       | Kebab-case; must match the parent folder name      |
| `description`   | ✅       | Pushy trigger description; shown to the LLM        |
| `version`       | ✅       | SemVer-like string; we ship at `"1.0"`             |
| `created_by`    | ✅       | `"seed"` (human) or `"distiller"` (Day 9 agent)    |
| `injected_into` | ✅       | Non-empty list of critic ids that should see this  |

### Optional, retrieval-specific

| Field              | Notes                                                |
| ------------------ | ---------------------------------------------------- |
| `trigger_keywords` | List of words used by the keyword retriever to score |
| `trigger_semantic` | Free-text fallback used by future embedding retrieval|
| `confidence`       | 0–1 float, breaks ties on equal keyword hits         |

## Why decouple runtime stats?

`runtime_stats.yaml` is the **only** file the runtime mutates between
PRD runs. Each skill's `SKILL.md` stays diff-clean across hundreds of
runs, so reviewing skill content in PRs is uncluttered by churn from
`usage_count` increments. Format:

```yaml
skills:
  api-dependency-enumeration:
    usage_count: 0
    acceptance_rate: null
    last_used: null
    status: active           # "active" | "deprecated"
    learned_from_prds: []
```

Skill name is the key — same kebab-case identifier as the folder.

## Mapping to the Anthropic Agent Skills spec

| Anthropic spec field | This project              | Notes                          |
| -------------------- | ------------------------- | ------------------------------ |
| `name`               | `name`                    | Identical                      |
| `description`        | `description`             | Identical                      |
| `version`            | `version`                 | Identical                      |
| Body (Markdown)      | Body following `---`      | Spliced into critic prompt     |
| —                    | `injected_into`           | Project-specific routing       |
| —                    | `trigger_keywords` etc.   | Project-specific retrieval     |
| —                    | `runtime_stats.yaml`      | Decoupled telemetry            |

The required Anthropic fields (`name` / `description` / `version` /
Markdown body) map 1:1; project-specific extensions live alongside them
without breaking spec consumers (any tool that reads only the canonical
fields will still parse our `SKILL.md` correctly).

## OpenAI Codex CLI compatibility

OpenAI's Codex CLI (Q1 2026) consumes the same `SKILL.md` shape. The
folder-per-skill layout means a Codex extension could be pointed at
`src/skills/seed/` directly. The frontmatter validator in
`tests/test_skill_md_format.py` enforces the cross-vendor minimum.

## Authoring a new skill

1. Decide the kebab-case name (e.g. `pricing-elasticity-check`).
2. Create `src/skills/seed/pricing-elasticity-check/SKILL.md` with the
   frontmatter above and a Markdown body following the
   `When to apply / Instruction / Rationale / Examples` shape.
3. Add a stats row in `src/skills/runtime_stats.yaml` — copy any
   existing entry and zero the counts.
4. `pytest tests/test_skill_md_format.py` to validate the frontmatter.
5. Restart the Streamlit app or MCP server to pick up the new skill.

The Day 9 Distiller will follow the same recipe automatically when a
skill is accepted.
