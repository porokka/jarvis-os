"""
JARVIS Skill — Obsidian vault file access (read files, list directories).
"""

from pathlib import Path

SKILL_NAME = "vault"
SKILL_DESCRIPTION = "Obsidian vault — read notes, list directories"

VAULT_DIR = Path("D:/Jarvis_vault") if __import__("os").name == "nt" else Path("/mnt/d/Jarvis_vault")


def exec_read_vault_file(path: str) -> str:
    target = (VAULT_DIR / path).resolve()
    if not str(target).startswith(str(VAULT_DIR.resolve())):
        return "Error: path traversal blocked"
    if not target.exists():
        return f"File not found: {path}"
    try:
        return target.read_text(encoding="utf-8")[:8000]
    except Exception as e:
        return f"Error reading file: {e}"


def exec_list_vault_dir(path: str) -> str:
    target = (VAULT_DIR / path).resolve()
    if not str(target).startswith(str(VAULT_DIR.resolve())):
        return "Error: path traversal blocked"
    if not target.exists():
        return f"Directory not found: {path}"
    try:
        entries = []
        for item in sorted(target.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                entries.append(f"  {item.name}/")
            elif item.suffix == ".md":
                entries.append(f"  {item.name}")
        return "\n".join(entries) if entries else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_vault_file",
            "description": "Read a markdown file from the Obsidian vault. Look up project info, people, references, decisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within the vault, e.g. People/sami.md",
                    }
                },
                "required": ["path"],
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
                "required": ["path"],
            },
        },
    },
]

TOOL_MAP = {
    "read_vault_file": exec_read_vault_file,
    "list_vault_dir": exec_list_vault_dir,
}

KEYWORDS = {
    "read_vault_file": ["project", "vault", "notes", "stockwatch", "caskra", "tender", "travel", "dravn", "poro-it"],
    "list_vault_dir": ["list projects", "what projects", "show vault", "what files"],
}
