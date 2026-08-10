"""
JARVIS coding skill wrapper.

Public ReAct-visible tool:
    code_edit

Internal dispatch:
    - Qwen/Qwen3 coder models -> skills._coding_qwen3_coder
    - everything else         -> skills._coding_generic
"""

from __future__ import annotations

import os
from typing import Any, Dict

try:
    from skills.coding_generic import exec_code_edit as exec_generic_code_edit
except Exception as e:
    exec_generic_code_edit = None
    GENERIC_IMPORT_ERROR = e
else:
    GENERIC_IMPORT_ERROR = None

try:
    from skills.coding_qwen3_coder import exec_code_edit as exec_qwen3_code_edit
except Exception as e:
    exec_qwen3_code_edit = None
    QWEN_IMPORT_ERROR = e
else:
    QWEN_IMPORT_ERROR = None


SKILL_NAME = "coding"
SKILL_DESCRIPTION = "Code inspection, patching, generation, and model-aware coding workflows."


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "code_edit",
            "description": (
                "Inspect, generate, edit, or patch code. "
                "Automatically routes to the best coding backend for the active model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The coding task to perform.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional file or project path.",
                    },
                    "code": {
                        "type": "string",
                        "description": "Optional source code or snippet.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Optional programming language.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Optional active model override.",
                    },
                    "mode": {
                        "type": "string",
                        "description": "Optional mode such as inspect, patch, full_file, explain.",
                    },
                },
                "required": ["task"],
            },
        },
    }
]


KEYWORDS = {
    "code_edit": [
        "code",
        "coding",
        "patch",
        "diff",
        "fix",
        "bug",
        "refactor",
        "typescript",
        "python",
        "react",
        "nextjs",
        "qwen coder",
        "qwen3 coder",
    ]
}


SKILL_META = {
    "route": "code",
    "keywords": ["code", "coding", "patch", "fix", "refactor"],
    "tools": {
        "code_edit": {
            "route": "code",
            "intent_aliases": [
                "edit code",
                "fix code",
                "create patch",
                "review code",
                "generate code",
            ],
            "direct_match": [
                "fix this code",
                "give full code",
                "make patch",
                "code edit",
            ],
        }
    },
}


def _active_model(args: Dict[str, Any]) -> str:
    """
    Resolve active model from tool args or environment/runtime hints.
    Keep this forgiving because different JARVIS routes may pass model differently.
    """
    candidates = [
        args.get("model"),
        args.get("active_model"),
        args.get("ollama_model"),
        os.getenv("JARVIS_ACTIVE_MODEL"),
        os.getenv("OLLAMA_MODEL"),
        os.getenv("JARVIS_CODE_MODEL"),
    ]

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    return ""


def _is_qwen_coder(model: str) -> bool:
    """
    Match likely Qwen coder model names.

    Examples:
        qwen3-coder
        qwen2.5-coder:32b
        qwen3.6:27b  (hybrid — replaced qwen3-coder:30b as the code model)
        qwen-coder
    """
    m = model.lower()
    return ("qwen" in m and "coder" in m) or m.startswith("qwen3.6")


def _error_result(message: str, detail: Any = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": False,
        "skill": "coding",
        "error": message,
    }

    if detail is not None:
        result["detail"] = str(detail)

    return result


def exec_code_edit(
    task: str,
    path: str | None = None,
    code: str | None = None,
    language: str | None = None,
    model: str | None = None,
    mode: str | None = None,
    **extra: Any,
) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "task": task,
        "path": path,
        "code": code,
        "language": language,
        "model": model,
        "mode": mode,
        **extra,
    }
    """
    Public executor used by ReAct.

    It keeps one stable tool name but delegates implementation according
    to the selected/active model.
    """
    if not isinstance(args, dict):
        return _error_result("code_edit expected a JSON object as arguments.")

    task = args.get("task")
    if not isinstance(task, str) or not task.strip():
        return _error_result("Missing required argument: task")

    model = _active_model(args)

    # Route to qwen coder when the model is a qwen coder OR when no model
    # hint exists at all — qwen3-coder is the local default coding backend.
    # The generic backend only handles file creation and errors on
    # everything else, so it must never be the silent default.
    if _is_qwen_coder(model) or (not model and exec_qwen3_code_edit is not None):
        if exec_qwen3_code_edit is None:
            return _error_result(
                "Qwen coder backend is not available.",
                QWEN_IMPORT_ERROR,
            )

        enriched_args = dict(args)
        enriched_args["selected_backend"] = "qwen3_coder"
        enriched_args["active_model"] = model or "qwen3.6:27b"
        return exec_qwen3_code_edit(**enriched_args)

    if exec_generic_code_edit is None:
        return _error_result(
            "Generic coding backend is not available.",
            GENERIC_IMPORT_ERROR,
        )

    enriched_args = dict(args)
    enriched_args["selected_backend"] = "generic"
    enriched_args["active_model"] = model
    return exec_generic_code_edit(**enriched_args)


TOOL_MAP = {
    "code_edit": exec_code_edit,
}