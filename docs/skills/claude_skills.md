# Claude Skills Browser

Browse and load Claude Code skills from the Obsidian vault. 34 specialized skills for frontend design, SEO, Playwright testing, React, and more.

**File:** `skills/claude_skills.py`

---

## Prerequisites

- Claude Code skills installed in `D:/Jarvis_vault/.claude/skills/`
- Each skill is a directory with a `SKILL.md` file

---

## Tools

### list_skills

List all available Claude Code skills with descriptions.

No parameters.

**Example:**
```
"What skills do you have?"
"List your capabilities"
```

---

### use_skill

Load a skill by name — returns the full skill instructions for the LLM to follow.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | yes | Skill name (e.g. `frontend-design`, `seo`, `playwright-skill`) |

Supports fuzzy matching — if the exact name isn't found, suggests close matches.

**Examples:**
```
"Use the frontend design skill"
"Load the SEO skill"
"Apply the playwright skill for testing"
```

---

## Available Skills (sample)

These are Claude Code skills stored in the vault, loaded on demand:

- `frontend-design` — Production-grade UI with high design quality
- `seo` / `seo-audit` / `seo-technical` — Comprehensive SEO analysis
- `playwright-skill` — Browser automation and testing
- `react-best-practices` — React/Next.js performance patterns
- `svg-precision-skill` — SVG generation and validation
- `obsidian-cli` — Obsidian vault management
- `app-scaffolder` — Full-stack project scaffolding

Use `list_skills` to see the full list.
