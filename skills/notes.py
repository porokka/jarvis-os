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
from typing import Optional, List


SKILL_NAME = "notes"
SKILL_DESCRIPTION = "Obsidian notes — create, append, search, daily notes, tags"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "productivity"
SKILL_TAGS = ["obsidian", "notes", "vault", "markdown", "journal", "todo"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "create_note",
    "append_note",
    "daily_note",
    "search_notes",
    "find_by_tag",
    "list_directory",
    "add_wikilink",
    "add_todo",
]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "capabilities": SKILL_CAPABILITIES,
    "writes_files": True,
    "reads_files": True,
    "entrypoint": "exec_notes",
}

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")


def _safe_path(path: str) -> Optional[Path]:
    """Resolve path within vault and block traversal outside it."""
    clean = (path or "").strip().replace("\\", "/").lstrip("/")
    target = (VAULT_DIR / clean).resolve()
    vault_root = VAULT_DIR.resolve()

    try:
        target.relative_to(vault_root)
    except ValueError:
        return None

    return target


def _normalize_note_path(path: str) -> str:
    """Append .md if caller omitted it."""
    path = (path or "").strip().replace("\\", "/")
    if path and not path.endswith(".md") and not path.endswith("/"):
        path += ".md"
    return path


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_time() -> str:
    return datetime.now().strftime("%H:%M")


def _parse_tag_list(tags: str) -> List[str]:
    raw = [t.strip().lstrip("#") for t in (tags or "").split(",")]
    return [t for t in raw if t]


def _build_frontmatter(tag_list: List[str]) -> str:
    today = _today()
    frontmatter = (
        "---\n"
        f"created: {today}\n"
        f"updated: {today}\n"
    )
    if tag_list:
        frontmatter += f"tags: [{', '.join(tag_list)}]\n"
    frontmatter += "---\n\n"
    return frontmatter


def _extract_title_from_path(target: Path) -> str:
    return target.stem.replace("-", " ").replace("_", " ").title()


def _ensure_updated_field(text: str) -> str:
    today = _today()

    # If there's frontmatter, update or insert updated:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            frontmatter = text[: end + 5]
            body = text[end + 5 :]

            if re.search(r"(?m)^updated:\s*\d{4}-\d{2}-\d{2}\s*$", frontmatter):
                frontmatter = re.sub(
                    r"(?m)^updated:\s*\d{4}-\d{2}-\d{2}\s*$",
                    f"updated: {today}",
                    frontmatter,
                )
            else:
                frontmatter = frontmatter[:-5] + f"updated: {today}\n---\n"

            return frontmatter + body

    return text


def _daily_note_path() -> Path:
    safe = _safe_path(f"Daily/{_today()}.md")
    if safe is None:
        raise ValueError("Failed to resolve daily note path safely.")
    return safe


def _ensure_daily_note_exists() -> Path:
    daily_path = _daily_note_path()
    if not daily_path.exists():
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        daily_path.write_text(
            (
                "---\n"
                f"created: {_today()}\n"
                f"updated: {_today()}\n"
                "tags: [daily]\n"
                "---\n\n"
                f"# {_today()}\n\n"
            ),
            encoding="utf-8",
        )
    return daily_path


def exec_notes(
    action: str,
    path: str = "",
    content: str = "",
    tags: str = "",
    query: str = "",
) -> str:
    """Obsidian note management."""
    action = (action or "").lower().strip()

    if action == "create":
        if not path:
            return "Specify a path. Example: create Projects/NewProject/overview.md"

        path = _normalize_note_path(path)
        target = _safe_path(path)
        if not target:
            return "Error: invalid path"
        if target.exists():
            return f"Note already exists: {path}. Use 'append' to add content."

        tag_list = _parse_tag_list(tags)
        frontmatter = _build_frontmatter(tag_list)
        title = _extract_title_from_path(target)
        body = f"{frontmatter}# {title}\n\n{content.strip()}\n"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return f"Created: {path}"

    elif action == "append":
        if not path or not content:
            return "Specify path and content."

        path = _normalize_note_path(path)
        target = _safe_path(path)
        if not target:
            return "Error: invalid path"
        if not target.exists():
            return f"Note not found: {path}. Use 'create' first."

        text = target.read_text(encoding="utf-8")
        text = _ensure_updated_field(text)
        ts = _now_time()
        text += f"\n## {ts}\n{content.strip()}\n"

        target.write_text(text, encoding="utf-8")
        return f"Appended to {path}"

    elif action == "daily":
        daily_path = _ensure_daily_note_exists()

        if content:
            text = daily_path.read_text(encoding="utf-8")
            text = _ensure_updated_field(text)
            text += f"\n## {_now_time()}\n{content.strip()}\n"
            daily_path.write_text(text, encoding="utf-8")
            return f"Added to daily note: {_today()}"

        return daily_path.read_text(encoding="utf-8")[:3000]

    elif action == "search":
        if not query:
            return "Specify a search query."

        results = []
        query_lower = query.lower()

        for md_file in VAULT_DIR.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            if query_lower in text.lower():
                for i, line in enumerate(text.splitlines(), start=1):
                    if query_lower in line.lower():
                        rel = md_file.relative_to(VAULT_DIR).as_posix()
                        results.append(f"  {rel}:{i} — {line.strip()[:120]}")
                        break

        if results:
            return f"Found {len(results)} notes matching '{query}':\n" + "\n".join(results[:15])
        return f"No notes matching '{query}'."

    elif action == "tag":
        if not query:
            return "Specify a tag to find."

        tag = query.lower().strip().lstrip("#")
        results = []

        for md_file in VAULT_DIR.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            lower = text.lower()

            frontmatter_match = re.search(r"(?s)^---\n(.*?)\n---\n", text)
            has_frontmatter_tag = False
            if frontmatter_match:
                fm = frontmatter_match.group(1).lower()
                has_frontmatter_tag = bool(
                    re.search(rf"(?m)^tags:\s*\[.*?\b{re.escape(tag)}\b.*?\]\s*$", fm)
                )

            has_inline_tag = f"#{tag}" in lower

            if has_frontmatter_tag or has_inline_tag:
                rel = md_file.relative_to(VAULT_DIR).as_posix()
                title = ""
                for line in text.splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                results.append(f"  [[{rel}]] — {title or md_file.stem}")

        if results:
            return f"Notes tagged #{tag}:\n" + "\n".join(results[:20])
        return f"No notes with tag #{tag}."

    elif action == "list":
        target = _safe_path(path or "")
        if not target:
            return "Error: invalid path"
        if not target.exists():
            return f"Directory not found: {path or '/'}"
        if not target.is_dir():
            return f"Not a directory: {path}"

        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith("."):
                continue

            if item.is_dir():
                count = len(list(item.rglob("*.md")))
                entries.append(f"  {item.name}/ ({count} notes)")
            elif item.suffix.lower() == ".md":
                size_kb = max(1, item.stat().st_size // 1024) if item.stat().st_size else 0
                entries.append(f"  {item.name} ({size_kb}KB)")

        return "\n".join(entries) if entries else "(empty)"

    elif action == "link":
        if not path or not content:
            return "Specify source path and link target."

        path = _normalize_note_path(path)
        target = _safe_path(path)
        if not target or not target.exists():
            return f"Note not found: {path}"

        text = target.read_text(encoding="utf-8")
        text = _ensure_updated_field(text)
        text += f"\n\nSee also: [[{content.strip()}]]\n"
        target.write_text(text, encoding="utf-8")
        return f"Added link to [[{content.strip()}]] in {path}"

    elif action == "todo":
        if not content:
            return "Specify the todo item."

        target_path = path.strip() if path else f"Daily/{_today()}.md"
        target_path = _normalize_note_path(target_path)

        target = _safe_path(target_path)
        if not target:
            return "Error: invalid path"

        if not target.exists():
            if target_path.startswith("Daily/"):
                _ensure_daily_note_exists()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                title = _extract_title_from_path(target)
                target.write_text(
                    f"{_build_frontmatter([])}# {title}\n\n",
                    encoding="utf-8",
                )

        text = target.read_text(encoding="utf-8")
        text = _ensure_updated_field(text)
        text += f"- [ ] {content.strip()}\n"
        target.write_text(text, encoding="utf-8")
        return f"Todo added: {content.strip()}"

    else:
        return (
            "Available actions: create, append, daily, search, tag, list, link, todo\n"
            "Examples:\n"
            "  create Projects/NewProject/overview.md 'Project description' tags:project,active\n"
            "  append Daily/2026-04-12.md 'Meeting notes from standup'\n"
            "  daily 'Had lunch with the team'\n"
            "  search 'deployment pipeline'\n"
            "  tag jarvis\n"
            "  list Projects\n"
            "  link Projects/NewProject/overview.md 'Roadmap'\n"
            "  todo 'Review PR for stockwatch'"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "notes",
            "description": (
                "Manage Obsidian vault notes. "
                "Actions: create, append, daily, search, tag, list, link, todo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "append", "daily", "search", "tag", "list", "link", "todo"],
                        "description": "Operation to perform on the Obsidian vault.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Path relative to vault, e.g. Projects/MyProject/overview.md. "
                            "Optional for daily and search; defaults may apply."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Body text, appended text, wikilink target, or todo text depending on action.",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags used when creating a note, e.g. project,active",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search text or tag name depending on action.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "notes": exec_notes,
}

KEYWORDS = {
    "notes": [
        "note",
        "notes",
        "write",
        "create note",
        "daily note",
        "todo",
        "obsidian",
        "journal",
        "log",
        "write down",
        "take note",
        "jot down",
        "append note",
        "search notes",
        "find note",
        "wikilink",
        "tagged note",
    ],
}