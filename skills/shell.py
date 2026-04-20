"""
JARVIS Skill — Shell command execution with safety restrictions + file reading.

Purpose:
  - Safe-ish shell diagnostics
  - Source code and text file reading from approved roots

Notes:
  - Uses command parsing instead of raw shell=True
  - Blocks dangerous commands, shell chaining, redirection, and scripting operators
  - Restricts file reads to approved root directories
"""

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional


SKILL_NAME = "shell"
SKILL_DESCRIPTION = "Shell diagnostics + source code file reading"
SKILL_VERSION = "1.2.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "developer"
SKILL_TAGS = ["shell", "terminal", "diagnostics", "files", "source-code", "read-only"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "run_safe_command",
    "read_text_file",
    "inspect_system",
    "inspect_git",
    "inspect_project_files",
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
    "entrypoint": "exec_shell_command",
}

# Approved roots for read_file
ALLOWED_READ_ROOTS = [
    Path("/mnt/d/Jarvis_vault").resolve(),
    Path("/mnt/e/coding").resolve(),
    Path("D:/Jarvis_vault").resolve(),
    Path("E:/coding").resolve(),
]

# Optional execution roots for commands that use cwd-like arguments
ALLOWED_EXEC_ROOTS = ALLOWED_READ_ROOTS[:]

# Reject shell metacharacters and chaining/redirection features
SHELL_META_BLOCKLIST = re.compile(
    r"(\|\||&&|[|;`]|>>|>|<|\$\(|\${|\\x|%0a|%0d)",
    re.I,
)

# Dangerous command patterns
DANGEROUS_PATTERN = re.compile(
    r"""
    (^|[\/\\])(
        rm|mkfs|dd|format|shutdown|reboot|halt|poweroff|passwd|chpasswd|
        useradd|usermod|userdel|groupadd|groupdel|
        chmod|chown|takeown|icacls|
        del|erase|cipher|diskpart|bcdedit|reg|sc|
        mount|umount|fdisk|parted|init|killall|pkill|taskkill
    )(\.exe)?$
    """,
    re.I | re.X,
)

# Allowed top-level commands
ALLOWED_COMMANDS = {
    "pwd",
    "ls",
    "dir",
    "echo",
    "cat",
    "type",
    "head",
    "tail",
    "wc",
    "find",
    "grep",
    "rg",
    "git",
    "python",
    "python3",
    "pip",
    "pip3",
    "node",
    "npm",
    "yarn",
    "pnpm",
    "pytest",
    "py",
    "whoami",
    "hostname",
    "uname",
    "df",
    "du",
    "free",
    "uptime",
    "ps",
    "tasklist",
    "ipconfig",
    "ifconfig",
    "ip",
    "netstat",
}

# Limit risky subcommands
ALLOWED_GIT_SUBCOMMANDS = {
    "status", "log", "branch", "remote", "rev-parse", "show", "diff", "ls-files"
}
ALLOWED_NPM_SUBCOMMANDS = {
    "list", "ls", "run", "outdated"
}
ALLOWED_PIP_SUBCOMMANDS = {
    "list", "show", "freeze"
}
ALLOWED_PYTHON_FLAGS = {
    "--version", "-V", "-m"
}
ALLOWED_PYTHON_MODULES = {
    "pip", "pytest"
}


def _is_under_allowed_root(target: Path, roots: List[Path]) -> bool:
    try:
        resolved = target.resolve()
    except Exception:
        return False

    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _validate_command(command: str) -> Optional[str]:
    if not command or not command.strip():
        return "Error: empty command"

    if SHELL_META_BLOCKLIST.search(command):
        return "Error: command blocked by shell safety filter"

    try:
        parts = shlex.split(command, posix=os.name != "nt")
    except Exception as e:
        return f"Error: invalid command syntax: {e}"

    if not parts:
        return "Error: empty command"

    exe = parts[0].strip()
    exe_name = Path(exe).name.lower()

    if DANGEROUS_PATTERN.search(exe_name):
        return "Error: command blocked by safety filter"

    if exe_name not in ALLOWED_COMMANDS:
        return f"Error: command '{exe_name}' is not in allowlist"

    # Fine-grained rules
    if exe_name == "git":
        if len(parts) < 2:
            return None
        sub = parts[1].lower()
        if sub not in ALLOWED_GIT_SUBCOMMANDS:
            return f"Error: git subcommand '{sub}' is not allowed"

    elif exe_name in {"npm", "pnpm", "yarn"}:
        if len(parts) < 2:
            return None
        sub = parts[1].lower()
        if sub not in ALLOWED_NPM_SUBCOMMANDS:
            return f"Error: {exe_name} subcommand '{sub}' is not allowed"

    elif exe_name in {"pip", "pip3"}:
        if len(parts) < 2:
            return None
        sub = parts[1].lower()
        if sub not in ALLOWED_PIP_SUBCOMMANDS:
            return f"Error: {exe_name} subcommand '{sub}' is not allowed"

    elif exe_name in {"python", "python3", "py"}:
        # allow: python --version / python -V / python -m pip list / python -m pytest ...
        if len(parts) == 1:
            return None
        if parts[1] in ALLOWED_PYTHON_FLAGS:
            if parts[1] == "-m":
                if len(parts) < 3:
                    return "Error: python -m requires a module"
                mod = parts[2].lower()
                if mod not in ALLOWED_PYTHON_MODULES:
                    return f"Error: python module '{mod}' is not allowed"
            return None
        return "Error: raw Python script execution is not allowed"

    # Block suspicious path targets that escape roots when clearly path-like args are used
    for token in parts[1:]:
        if token.startswith("-"):
            continue
        if any(sep in token for sep in ("/", "\\")) or token.startswith("."):
            p = Path(token)
            if p.is_absolute():
                if not _is_under_allowed_root(p, ALLOWED_EXEC_ROOTS):
                    return f"Error: path outside allowed roots: {token}"

    return None


def exec_shell_command(command: str) -> str:
    """Run a restricted diagnostic shell command."""
    err = _validate_command(command)
    if err:
        return err

    try:
        parts = shlex.split(command, posix=os.name != "nt")
        result = subprocess.run(
            parts,
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            output = "(no output)"
        prefix = f"[exit {result.returncode}]\n"
        return _truncate(prefix + output, 4000)

    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"
    except FileNotFoundError:
        return "Error: command not found"
    except Exception as e:
        return f"Error: {e}"


def exec_read_file(path: str) -> str:
    """Read a text file from approved roots."""
    if not path or not path.strip():
        return "Error: path is required"

    try:
        target = Path(path).resolve()
    except Exception as e:
        return f"Error: invalid path: {e}"

    if not _is_under_allowed_root(target, ALLOWED_READ_ROOTS):
        return "Error: path not in allowed roots"

    if not target.exists():
        return f"File not found: {path}"

    if not target.is_file():
        return f"Error: not a file: {path}"

    try:
        # Basic binary detection
        raw = target.read_bytes()
        if b"\x00" in raw[:4096]:
            return "Error: binary file reading is not supported"

        text = raw.decode("utf-8", errors="replace")
        return _truncate(text, 8000)

    except Exception as e:
        return f"Error reading file: {e}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "shell_command",
            "description": (
                "Run a restricted diagnostic command. "
                "Intended for system info, git status/log, dependency inspection, and safe read-only checks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "A safe diagnostic command, e.g. "
                            "'git status', 'npm list', 'python --version', 'ipconfig', 'tasklist'"
                        ),
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text/source file from approved coding or vault directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute file path, e.g. "
                            "/mnt/e/coding/jarvis-os/scripts/watcher.sh or E:/coding/project/src/app.py"
                        ),
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "shell_command": exec_shell_command,
    "read_file": exec_read_file,
}

KEYWORDS = {
    "shell_command": [
        "system",
        "disk",
        "process",
        "git",
        "npm",
        "pip",
        "check status",
        "run",
        "ip",
        "network",
        "terminal",
        "shell",
        "diagnostics",
    ],
    "read_file": [
        "read file",
        "show code",
        "check code",
        "source",
        "open file",
        "view file",
    ],
}

SKILL_EXAMPLES = [
    {"command": "check git status", "tool": "shell_command", "args": {"command": "git status"}},
    {"command": "show python version", "tool": "shell_command", "args": {"command": "python --version"}},
    {"command": "list npm packages", "tool": "shell_command", "args": {"command": "npm list"}},
    {"command": "read watcher script", "tool": "read_file", "args": {"path": "/mnt/e/coding/jarvis-os/scripts/watcher.sh"}},
]