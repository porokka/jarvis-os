from __future__ import annotations

import json
import os
import time
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_VAULT = Path("/mnt/d/Jarvis_vault")
DEFAULT_MODEL = os.environ.get("JARVIS_CONTEXT_MODEL", "qwen3:14b")


def vault_root() -> Path:
    return Path(os.environ.get("JARVIS_VAULT", DEFAULT_VAULT))


def ensure_dirs() -> dict[str, Path]:
    vault = vault_root()

    paths = {
        "chat": vault / ".jarvis" / "chat",
        "memory": vault / ".jarvis" / "memory",
        "aaak": vault / ".jarvis" / "memory" / "aaak",
    }

    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)

    return paths


def today_log_path() -> Path:
    paths = ensure_dirs()
    return paths["chat"] / time.strftime("%Y-%m-%d.jsonl")


def log_chat_event(
    role: str,
    content: str,
    route: str | None = None,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not content:
        return

    event = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "role": role,
        "route": route,
        "model": model,
        "content": content,
        "metadata": metadata or {},
    }

    with today_log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_recent_chat(minutes: int = 15, max_items: int = 80) -> list[dict[str, Any]]:
    path = today_log_path()
    if not path.exists():
        return []

    cutoff = time.time() - minutes * 60
    rows: list[dict[str, Any]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue

        if item.get("ts", 0) >= cutoff:
            rows.append(item)

    return rows[-max_items:]


def format_recent_chat_for_model(rows: list[dict[str, Any]]) -> str:
    lines = []

    for item in rows:
        role = item.get("role", "unknown")
        route = item.get("route") or "-"
        model = item.get("model") or "-"
        content = str(item.get("content", "")).strip()

        if len(content) > 1500:
            content = content[:1500] + "..."

        lines.append(f"[{role} route={route} model={model}]\n{content}")

    return "\n\n".join(lines)


def ollama_generate(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 90) -> str:
    proc = subprocess.run(
        ["ollama", "run", model],
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ollama failed")

    return proc.stdout.strip()


def build_fallback_aaak(rows: list[dict[str, Any]]) -> str:
    lines = [
        "AAAK:1",
        f"UPDATED:{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "SRC:recent_chat",
        "",
        "RECENT:",
    ]

    for item in rows[-20:]:
        role = item.get("role", "unknown").upper()
        route = item.get("route") or "-"
        content = str(item.get("content", "")).strip().replace("\n", " ")

        if len(content) > 240:
            content = content[:240] + "..."

        lines.append(f"- {role}[{route}]: {content}")

    lines.extend(
        [
            "",
            "NEXT:",
            "- continue_current_task",
        ]
    )

    return "\n".join(lines) + "\n"
def clean_aaak_output(text: str) -> str:
    import re

    text = text or ""

    # remove ANSI terminal escape codes
    text = re.sub(
        r"\x1b\[[0-9;?]*[A-Za-z]",
        "",
        text,
    )

    # remove <think> blocks
    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # remove common thinking markers
    bad_lines = [
        "...done thinking.",
        "done thinking.",
        "thinking...",
    ]

    for marker in bad_lines:
        text = text.replace(marker, "")

    # keep only AAAK section if present
    idx = text.find("AAAK:")
    if idx >= 0:
        text = text[idx:]

    # normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

def summarize_to_aaak(minutes: int = 15, model: str = DEFAULT_MODEL) -> str:
    rows = read_recent_chat(minutes=minutes)

    if not rows:
        return "AAAK:1\nSTATE:no_recent_chat\n"

    recent_chat = format_recent_chat_for_model(rows)

    prompt = f"""
You compress recent chat into AAAK, a compact symbolic memory language readable by any LLM.

Rules:
- Output AAAK only.
- Do not explain.
- Keep it short.
- Preserve exact project names, file paths, commands, endpoints, model names, bugs, decisions, and next actions.
- Remove greetings, repetition, and irrelevant small talk.
- Prefer stable symbolic lines.
- Use this format when useful:

AAAK:1
UPDATED:<timestamp>
USR:<user>
PROJ:<project>
GOAL:<goal>
ACTIVE:<active_topic>
ISSUE:<issue>
FILES:<file1>,<file2>
MODELS:<model1>,<model2>
DECISION:<decision>
NEXT:<next_step>

Recent chat:
{recent_chat}
""".strip()

    try:
        text = clean_aaak_output(ollama_generate(prompt, model=model))

        if "AAAK" not in text[:50]:
            text = "AAAK:1\n" + text

        return text.strip() + "\n"
    except Exception:
        return build_fallback_aaak(rows)

def read_last_messages(
    max_user_chars: int = 1200,
    max_assistant_chars: int = 1200,
) -> tuple[str, str]:
    path = today_log_path()

    if not path.exists():
        return "", ""

    last_user = ""
    last_assistant = ""

    lines = path.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines()

    for line in reversed(lines):
        try:
            item = json.loads(line)
        except Exception:
            continue

        role = item.get("role")
        content = str(item.get("content", "")).strip()

        if role == "assistant" and not last_assistant:
            last_assistant = content[-max_assistant_chars:]

        elif role == "user" and not last_user:
            last_user = content[-max_user_chars:]

        if last_user and last_assistant:
            break

    return last_user, last_assistant 
def update_aaak_context(
    minutes: int = 15,
    model: str = DEFAULT_MODEL,
) -> Path:
    paths = ensure_dirs()

    aaak = summarize_to_aaak(
        minutes=minutes,
        model=model,
    )

    path = paths["aaak"] / "active.aaak"

    path.write_text(
        aaak,
        encoding="utf-8",
    )

    return path

def update_chat_context(minutes: int = 15, model: str = DEFAULT_MODEL) -> Path:
    paths = ensure_dirs()
    rows = read_recent_chat(minutes=minutes)

    lines = ["# Recent Chat Context", ""]

    if not rows:
        lines.append("No recent chat context.")
    else:
        for item in rows[-20:]:
            role = str(item.get("role", "unknown")).upper()
            route = item.get("route") or "-"
            content = str(item.get("content", "")).strip().replace("\n", " ")

            if len(content) > 300:
                content = content[:300] + "..."

            lines.append(f"- {role}[{route}]: {content}")

    path = paths["memory"] / "chat_context.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return path


def read_prompt_context(max_chars: int = 6000) -> str:
    paths = ensure_dirs()
    path = paths["memory"] / "chat_context.md"

    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8").strip()
    return text[-max_chars:]