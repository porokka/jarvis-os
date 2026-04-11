"""
JARVIS Skill — Shell command execution with safety blocklist + file reading.
"""

import re
import subprocess
from pathlib import Path

SKILL_NAME = "shell"
SKILL_DESCRIPTION = "Shell commands + source code file reading"

SHELL_BLOCKLIST = re.compile(
    r"(rm\s+-rf|mkfs|dd\s+if|format\s+[a-z]:|del\s+/[sS]|shutdown|reboot|passwd|sudo\s+rm)",
    re.I,
)

ALLOWED_READ_ROOTS = [
    str(Path("/mnt/d/Jarvis_vault")),
    str(Path("/mnt/e/coding")),
    str(Path("D:/Jarvis_vault")),
    str(Path("E:/coding")),
]


def exec_shell_command(command: str) -> str:
    if SHELL_BLOCKLIST.search(command):
        return "Error: command blocked by safety filter"
    try:
        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:4000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"
    except Exception as e:
        return f"Error: {e}"


def exec_read_file(path: str) -> str:
    target = Path(path).resolve()
    if not any(str(target).startswith(root) for root in ALLOWED_READ_ROOTS):
        return "Error: path not in allowed roots"
    if not target.exists():
        return f"File not found: {path}"
    try:
        return target.read_text(encoding="utf-8")[:8000]
    except Exception as e:
        return f"Error reading file: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": "Execute a shell command. System status, git info, safe commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read any file from the coding directories. Check source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute file path, e.g. /mnt/e/coding/jarvis-os/scripts/watcher.sh",
                    }
                },
                "required": ["path"],
            },
        },
    },
]

TOOL_MAP = {
    "shell_command": exec_shell_command,
    "read_file": exec_read_file,
}

KEYWORDS = {
    "shell_command": ["system", "disk", "process", "git", "npm", "pip", "check status", "run", "ip", "location"],
    "read_file": ["read file", "show code", "check code", "source"],
}
