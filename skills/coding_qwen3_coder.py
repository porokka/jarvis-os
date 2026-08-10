from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

SKILL_NAME = "coding_qwen3_coder"
SKILL_DESCRIPTION = "Read project files and ask the coder model to review, compare, or patch code."
SKILL_VERSION = "1.0.0"

PROJECT_ROOT = Path("/mnt/e/coding/jarvis-os")
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
CODER_MODEL = "qwen3.6:27b"

ALLOWED_ROOTS = [
    PROJECT_ROOT,
]

KEYWORDS = [
    "code",
    "coding",
    "check code",
    "read file",
    "compare file",
    "fix code",
    "skills",
    "patch",
    "review",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "coding_review",
            "description": "Read selected project files and ask qwen coder to review or compare them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["instruction", "paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coding_qwen3_coder",
            "description": "Read selected project files and return a minimal patch only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["instruction", "paths"],
            },
        },
    }
]


def _safe_path(path: str) -> Path:
    p = Path(path)

    if not p.is_absolute():
        p = PROJECT_ROOT / p

    p = p.resolve()

    if not any(str(p).startswith(str(root.resolve())) for root in ALLOWED_ROOTS):
        raise ValueError(f"Path outside allowed roots: {p}")

    return p

def exec_code_edit(
    task: str | None = None,
    path: str | None = None,
    code: str | None = None,
    language: str | None = None,
    model: str | None = None,
    mode: str | None = None,
    instruction: str | None = None,
    paths: List[str] | None = None,
    **extra: Any,
) -> Dict[str, Any]:
    instruction_text = instruction or task or ""

    if paths is None:
        if path:
            paths = [path]
        else:
            paths = ["."]

    return coding_qwen3_coder(
        instruction=instruction_text,
        paths=paths,
    )

# Directories that must never be bulk-read into a prompt
_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    "orpheus_env", "site-packages", "dist", "build", ".next",
}
_MAX_DIR_FILES = 20        # max files pulled from a directory read
_MAX_TOTAL_CHARS = 120000  # hard cap on total prompt payload from files


def _read_path(path: str, max_chars: int = 20000) -> str:
    p = _safe_path(path)

    if p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
        return f"\n\n### FILE: {p}\n```\n{text[:max_chars]}\n```"

    if p.is_dir():
        parts: List[str] = []
        total = 0
        count = 0
        for f in sorted(p.rglob("*.py")):
            if any(part in _SKIP_DIRS for part in f.parts):
                continue
            if count >= _MAX_DIR_FILES or total >= _MAX_TOTAL_CHARS:
                parts.append(
                    f"\n\n### NOTE: directory truncated at {count} files "
                    f"({total} chars). Pass explicit paths for more."
                )
                break
            text = f.read_text(encoding="utf-8", errors="replace")
            block = f"\n\n### FILE: {f}\n```\n{text[:max_chars]}\n```"
            parts.append(block)
            total += len(block)
            count += 1
        return "\n".join(parts)

    # New file case
    return f"\n\n### NEW FILE: {p}\nFile does not exist yet. Create it if the task requires it.\n"


def _call_coder(prompt: str, timeout: int = 600) -> str:
    payload = {
        "model": CODER_MODEL,
        "stream": False,
        # qwen3.6 is a thinking model — a strict patch generator gains
        # nothing from a reasoning preamble, only latency.
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict code patch generator. "
                    "You do not analyze, explain, review, or summarize. "
                    "You only output writable patch content in the required format. "
                    "Use only the provided files. "
                    "write to file only code and minimal necessary context. "
                    "if multiple steps modify file you need to read again the file with previous changes. "
                    "Reference exact filenames and functions. "
                    "Give concrete fixes and patches. "
                    "Do not give generic architecture advice."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result.get("message", {}).get("content", "")
def coding_qwen3_coder(instruction: str, paths: List[str]) -> Dict[str, Any]:
    try:
        file_blocks = []
        for path in paths:
            file_blocks.append(_read_path(path))

        prompt = f"""
            {instruction}

            STRICT OUTPUT RULES:
            - Return ONLY patch format
            - No explanation
            - No markdown fences
            - Must start with:
            --- FILE:
            @@
            - Only minimal changes

            CODE:
            {''.join(file_blocks)}
            """

        answer = _call_coder(prompt)

        return {
            "ok": True,
            "speech": answer[:500],
            "ui": {
                "type": "code_patch",
                "content": answer,
            },
            "data": {
                "paths": paths,
                "model": CODER_MODEL,
            },
            "error": None,
        }

    except Exception as e:
        return {
            "ok": False,
            "speech": f"Coding failed: {e}",
            "ui": None,
            "data": {"paths": paths},
            "error": str(e),
        }

def coding_review(instruction: str, paths: List[str]) -> Dict[str, Any]:
    try:
        file_blocks = []
        for path in paths:
            file_blocks.append(_read_path(path))

        prompt = f"""
Task:
{instruction}

Rules:
- Analyze only the supplied files.
- Reference exact filenames.
- Focus on concrete bugs and exact fixes.
- If patching, provide minimal replacement code blocks.
- Do not ask follow-up questions.

CODE:
{''.join(file_blocks)}
"""

        answer = _call_coder(prompt)

        return {
            "ok": True,
            "speech": answer[:1200],
            "ui": {
                "type": "code_review",
                "content": answer,
            },
            "data": {
                "paths": paths,
                "model": CODER_MODEL,
            },
            "error": None,
        }

    except Exception as e:
        return {
            "ok": False,
            "speech": f"Coding review failed: {e}",
            "ui": None,
            "data": {"paths": paths},
            "error": str(e),
        }


TOOL_MAP = {
    "coding_review": coding_review,
    "coding_qwen3_coder": coding_qwen3_coder,
    "exec_code_edit": exec_code_edit,
}