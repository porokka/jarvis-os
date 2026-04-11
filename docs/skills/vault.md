# Vault Skill

Read and browse the Obsidian vault — project notes, people, references, decisions.

**File:** `skills/vault.py`

---

## Prerequisites

- Obsidian vault at `D:/Jarvis_vault` (Windows) or `/mnt/d/Jarvis_vault` (WSL)

---

## Tools

### read_vault_file

Read a markdown file from the vault.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Relative path within vault, e.g. `People/sami.md` |

Returns up to 8000 characters. Path traversal outside the vault is blocked.

**Examples:**
```
"Read the StockWatch overview"     → read_vault_file("Projects/StockWatch/StockWatch.md")
"Show me Sami's profile"           → read_vault_file("People/sami.md")
"Check the Caskra decisions"       → read_vault_file("Projects/Caskra/decisions.md")
```

---

### list_vault_dir

List files and folders in a vault directory.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Relative directory path, e.g. `Projects/` |

Only shows `.md` files and subdirectories. Hidden files (`.` prefix) are excluded.

**Examples:**
```
"What projects are in the vault?"  → list_vault_dir("Projects/")
"List the references"              → list_vault_dir("References/")
"What's in daily logs?"            → list_vault_dir("Daily/")
```

---

## Vault Structure

```
Jarvis_vault/
├── People/          # User profiles
├── Projects/        # One folder per project (overview, decisions, credentials)
├── References/      # Tools, services, CLI guides
├── Daily/           # Daily logs + JARVIS memories
├── Templates/       # Reusable templates
├── Archive/         # Retired notes
└── .claude/skills/  # 34 Claude Code skills
```
