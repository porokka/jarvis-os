# Memory Skill

Long-term memory via MemPalace (vector database) + Obsidian vault daily logs. Search past conversations, save new memories, check memory status.

**File:** `skills/memory.py`

---

## Prerequisites

- **MemPalace** installed: `pip install mempalace`
- Obsidian vault at `D:/Jarvis_vault` (Windows) or `/mnt/d/Jarvis_vault` (WSL)
- MemPalace initialized: `python3 -m mempalace init`

---

## Tools

### memory_search

Search long-term memory for past conversations, decisions, facts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | yes | What to search for |

**Examples:**
```
"What do you remember about StockWatch?"
"Who is Inga?"
"What was the auth migration decision?"
"Do you know my preferences?"
```

---

### memory_add

Save a new memory to the Obsidian vault and queue it for MemPalace vector indexing.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | yes | The fact or memory to store |
| `room` | string | no | Category: `projects`, `team`, `daily`, `general`, `research` (default: `general`) |

Memories are written to `Daily/{date}.md` in the vault, then MemPalace mines the vault in the background.

**Examples:**
```
"Remember that StockWatch deploy moved to Railway"
"Save that Sami prefers dark mode"
"Note that the API key rotates monthly"
```

---

### memory_status

Show MemPalace stats — wings, rooms, total memory count.

No parameters.

---

## How Storage Works

```
User says "remember X"
        │
   ┌────▼──────────┐
   │ Append to      │ Daily/2026-04-11.md
   │ Obsidian vault │
   └────┬──────────┘
        │
   ┌────▼──────────┐
   │ MemPalace mine │ Background: vectorize vault notes
   └───────────────┘
```

Search queries hit the MemPalace vector DB for semantic matching across all stored memories.
