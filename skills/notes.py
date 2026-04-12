"""
JARVIS Skill — Obsidian note management.

Create, append, search, and organize notes in the vault.
Supports frontmatter, tags, wikilinks, and daily notes.

Uses the same vault as the vault skill but with write capabilities.
"""

import os
import re
from datetime import datetime
from pathlib import Path

SKILL_NAME = "notes"
SKILL_DESCRIPTION = "Obsidian notes — create, append, search, daily notes, tags"

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")


def _safe_path(path: str) -> Path:
    """Resolve path within vault, block traversal."""
    target = (VAULT_DIR / path).resolve()
    if not str(target).startswith(str(VAULT_DIR.resolve())):
        return None
    return target


def exec_notes(action: str, path: str = "", content: str = "", tags: str = "", query: str = "") -> str:
    """Obsidian note management."""
    action = action.lower().strip()

    if action == "create":
        if not path:
            return "Specify a path. Example: create Projects/NewProject/overview.md"
        target = _safe_path(path)
        if not target:
            return "Error: invalid path"
        if target.exists():
            return f"Note already exists: {path}. Use 'append' to add content."

        # Build frontmatter
        now = datetime.now()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        frontmatter = (
            f"---\n"
            f"created: {now.strftime('%Y-%m-%d')}\n"
            f"updated: {now.strftime('%Y-%m-%d')}\n"
        )
        if tag_list:
            frontmatter += f"tags: [{', '.join(tag_list)}]\n"
        frontmatter += f"---\n\n"

        # Title from filename
        title = target.stem.replace("-", " ").replace("_", " ").title()
        body = f"{frontmatter}# {title}\n\n{content}\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return f"Created: {path}"

    elif action == "append":
        if not path or not content:
            return "Specify path and content."
        target = _safe_path(path)
        if not target:
            return "Error: invalid path"
        if not target.exists():
            return f"Note not found: {path}. Use 'create' first."

        # Update 'updated' in frontmatter
        text = target.read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")
        text = re.sub(r'updated: \d{4}-\d{2}-\d{2}', f'updated: {today}', text)

        # Append content
        ts = datetime.now().strftime("%H:%M")
        text += f"\n## {ts}\n{content}\n"
        target.write_text(text, encoding="utf-8")
        return f"Appended to {path}"

    elif action == "daily":
        # Create or append to today's daily note
        today = datetime.now().strftime("%Y-%m-%d")
        daily_path = VAULT_DIR / "Daily" / f"{today}.md"

        if not daily_path.exists():
            daily_path.parent.mkdir(parents=True, exist_ok=True)
            daily_path.write_text(
                f"---\ncreated: {today}\ntags: [daily]\n---\n\n# {today}\n\n",
                encoding="utf-8",
            )

        if content:
            ts = datetime.now().strftime("%H:%M")
            with open(daily_path, "a", encoding="utf-8") as f:
                f.write(f"\n## {ts}\n{content}\n")
            return f"Added to daily note: {today}"

        return daily_path.read_text(encoding="utf-8")[:3000]

    elif action == "search":
        if not query:
            return "Specify a search query."

        results = []
        query_lower = query.lower()

        for md_file in VAULT_DIR.rglob("*.md"):
            if ".git" in str(md_file) or ".claude" in str(md_file):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                if query_lower in text.lower():
                    # Find matching line
                    for i, line in enumerate(text.split("\n")):
                        if query_lower in line.lower():
                            rel = md_file.relative_to(VAULT_DIR)
                            results.append(f"  {rel}:{i+1} — {line.strip()[:80]}")
                            break
            except Exception:
                continue

        if results:
            return f"Found {len(results)} notes matching '{query}':\n" + "\n".join(results[:15])
        return f"No notes matching '{query}'."

    elif action == "tag":
        if not query:
            return "Specify a tag to find."

        tag = query.lower().strip().lstrip("#")
        results = []

        for md_file in VAULT_DIR.rglob("*.md"):
            if ".git" in str(md_file):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                if f"#{tag}" in text.lower() or f"tags: [{tag}" in text.lower() or f", {tag}" in text.lower():
                    rel = md_file.relative_to(VAULT_DIR)
                    # Get title
                    title = ""
                    for line in text.split("\n"):
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break
                    results.append(f"  [[{rel}]] — {title}")
            except Exception:
                continue

        if results:
            return f"Notes tagged #{tag}:\n" + "\n".join(results[:20])
        return f"No notes with tag #{tag}."

    elif action == "list":
        # List notes in a directory
        target = _safe_path(path or "")
        if not target:
            return "Error: invalid path"
        if not target.exists():
            return f"Directory not found: {path}"

        entries = []
        for item in sorted(target.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                count = len(list(item.rglob("*.md")))
                entries.append(f"  {item.name}/ ({count} notes)")
            elif item.suffix == ".md":
                size = item.stat().st_size
                entries.append(f"  {item.name} ({size // 1024}KB)")

        return "\n".join(entries) if entries else "(empty)"

    elif action == "link":
        # Create a wikilink reference
        if not path or not content:
            return "Specify source path and link target."
        target = _safe_path(path)
        if not target or not target.exists():
            return f"Note not found: {path}"

        text = target.read_text(encoding="utf-8")
        text += f"\n\nSee also: [[{content}]]\n"
        target.write_text(text, encoding="utf-8")
        return f"Added link to [[{content}]] in {path}"

    elif action == "todo":
        # Add a todo item to a note
        if not content:
            return "Specify the todo item."
        target_path = path or "Daily/" + datetime.now().strftime("%Y-%m-%d") + ".md"
        target = _safe_path(target_path)
        if not target:
            return "Error: invalid path"
        if not target.exists():
            # Create if daily note
            target.parent.mkdir(parents=True, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            target.write_text(f"---\ncreated: {today}\ntags: [daily]\n---\n\n# {today}\n\n", encoding="utf-8")

        with open(target, "a", encoding="utf-8") as f:
            f.write(f"- [ ] {content}\n")
        return f"Todo added: {content}"

    else:
        return (
            "Available actions: create, append, daily, search, tag, list, link, todo\n"
            "Examples:\n"
            "  create Projects/NewProject/overview.md 'Project description' tags:project,active\n"
            "  append Daily/2026-04-12.md 'Meeting notes from standup'\n"
            "  daily 'Had lunch with the team'\n"
            "  search 'deployment pipeline'\n"
            "  tag jarvis\n"
            "  todo 'Review PR for stockwatch'"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "notes",
            "description": "Manage Obsidian vault notes. Actions: create (new note with frontmatter), append (add to existing), daily (today's note), search (find in vault), tag (find by tag), list (directory listing), link (add wikilink), todo (add checkbox item).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: create, append, daily, search, tag, list, link, todo",
                    },
                    "path": {
                        "type": "string",
                        "description": "Note path relative to vault (e.g. Projects/MyProject/overview.md)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Note content or todo text",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags for create (e.g. project,active)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query or tag name",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {"notes": exec_notes}

KEYWORDS = {
    "notes": [
        "note", "notes", "write", "create note", "daily note", "todo",
        "obsidian", "journal", "log", "write down", "take note", "jot down",
    ],
}
