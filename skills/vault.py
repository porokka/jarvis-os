"""
JARVIS Skill — Obsidian vault file access (read files, list directories).
"""

import os
from pathlib import Path
from typing import Optional


SKILL_NAME = "vault"
SKILL_DESCRIPTION = "Obsidian vault — read notes, list directories"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "productivity"
SKILL_TAGS = ["obsidian", "vault", "notes", "markdown", "files", "read-only"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "read_vault_file",
    "list_vault_dir",
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
    "writes_files": False,
    "reads_files": True,
    "network_access": False,
    "entrypoint": "exec_read_vault_file",
}

VAULT_DIR = Path("D:/Jarvis_vault") if os.name == "nt" else Path("/mnt/d/Jarvis_vault")


def _safe_vault_path(path: str) -> Optional[Path]:
    """Resolve path inside vault and block traversal."""
    clean = (path or "").strip().replace("\\", "/").lstrip("/")
    target = (VAULT_DIR / clean).resolve()
    vault_root = VAULT_DIR.resolve()

    try:
        target.relative_to(vault_root)
    except ValueError:
        return None

    return target


def exec_read_vault_file(path: str) -> str:
    target = _safe_vault_path(path)
    if not target:
        return "Error: path traversal blocked"
    if not target.exists():
        return f"File not found: {path}"
    if not target.is_file():
        return f"Error: not a file: {path}"

    try:
        raw = target.read_bytes()
        if b"\x00" in raw[:4096]:
            return "Error: binary files are not supported"
        return raw.decode("utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"Error reading file: {e}"


def exec_list_vault_dir(path: str = "") -> str:
    target = _safe_vault_path(path or "")
    if not target:
        return "Error: path traversal blocked"
    if not target.exists():
        return f"Directory not found: {path}"
    if not target.is_dir():
        return f"Error: not a directory: {path}"

    try:
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                md_count = len(list(item.glob("*.md")))
                entries.append(f"  {item.name}/ ({md_count} md files)")
            elif item.suffix.lower() in {".md", ".txt"}:
                entries.append(f"  {item.name}")

        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_vault_file",
            "description": "Read a text or markdown file from the Obsidian vault. Look up project info, people, references, and decisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within the vault, e.g. People/sami.md",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_vault_dir",
            "description": "List files and folders in a vault directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path, e.g. Projects/",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "read_vault_file": exec_read_vault_file,
    "list_vault_dir": exec_list_vault_dir,
}

KEYWORDS = {
    "read_vault_file": [
        "project",
        "vault",
        "notes",
        "stockwatch",
        "caskra",
        "tender",
        "travel",
        "dravn",
        "poro-it",
        "read vault file",
        "open note",
    ],
    "list_vault_dir": [
        "list projects",
        "what projects",
        "show vault",
        "what files",
        "list vault",
        "show folders",
    ],
}

SKILL_EXAMPLES = [
    {"command": "read sami note", "tool": "read_vault_file", "args": {"path": "People/sami.md"}},
    {"command": "list projects folder", "tool": "list_vault_dir", "args": {"path": "Projects"}},
    {"command": "show vault root", "tool": "list_vault_dir", "args": {"path": ""}},
]