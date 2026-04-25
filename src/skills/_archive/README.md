# Archived: pre-Day-8.5 skill format

This directory holds the **pre-Day-8.5** Skill Library layout, kept on
disk as a one-commit rollback safety net. **Nothing in this directory is
loaded by the runtime** — `SkillRetriever` only scans
`src/skills/seed/<name>/SKILL.md` and `src/skills/learned/<name>/SKILL.md`.

What was here:

- `library.yaml` — single YAML index listing every skill's metadata,
  including `usage_count`. Replaced by per-skill `SKILL.md` frontmatter
  + a separate `runtime_stats.yaml` (telemetry decoupled from content).
- `fragments/skl_*.md` — one Markdown file per skill, the body of which
  was injected into critic prompts. Now merged into each skill's
  `SKILL.md` as the body following the frontmatter fence.

If you need to compare against the old format, this is the snapshot.
Once the new layout has been live for a few days without regression,
delete this directory.

See `docs/skill_format.md` for the rationale and Anthropic Agent Skills
spec mapping.
