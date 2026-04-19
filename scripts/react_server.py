"""
JARVIS ReAct Server v3 — tool-augmented Ollama proxy with shared model routing,
profile-aware prompting, dynamic skill discovery, better logging, and Claude Code–style behavior.

Endpoints:
  POST /api/chat
  GET  /api/health
  GET  /api/skills
  GET  /api/models
  GET  /api/events
  GET  /api/timers
  GET  /api/radio
  GET  /api/network

Usage:
  python scripts/react_server.py --port 7900
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import urllib.error
import urllib.request

# -- Add project root to sys.path so `skills` package is importable --
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.loader import (  # type: ignore
    get_all_keywords,
    get_all_skill_meta,
    get_all_tool_map,
    get_all_tools,
    get_loaded_skills,
    load_skills,
)
from scripts.model_config import (
    get_planner_model,
    load_model_config,
    resolve_model,
)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
PORT = (
    int(sys.argv[sys.argv.index("--port") + 1])
    if "--port" in sys.argv
    else int(os.environ.get("JARVIS_PORT", "7900"))
)

MAX_ITERATIONS = int(os.environ.get("JARVIS_MAX_ITERATIONS", "8"))
MAX_TOOL_SELECTION = int(os.environ.get("JARVIS_MAX_TOOL_SELECTION", "6"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("JARVIS_MAX_CONTEXT_MESSAGES", "12"))
PLANNER_TIMEOUT_SEC = int(os.environ.get("JARVIS_PLANNER_TIMEOUT_SEC", "45"))
CHAT_TIMEOUT_SEC = int(os.environ.get("JARVIS_CHAT_TIMEOUT_SEC", "180"))
TOOL_RESULT_CHAR_LIMIT = int(os.environ.get("JARVIS_TOOL_RESULT_CHAR_LIMIT", "12000"))

ENABLE_TTS_ACK = os.environ.get("JARVIS_ENABLE_TTS_ACK", "1") == "1"
ENABLE_STREAM_STATUS = os.environ.get("JARVIS_ENABLE_STREAM_STATUS", "1") == "1"
DEBUG = os.environ.get("JARVIS_DEBUG", "1") == "1"

VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)
BRIDGE_DIR = Path(os.environ.get("JARVIS_BRIDGE_DIR", "/tmp/jarvis"))
EVENTS_FILE = BRIDGE_DIR / "react_events.jsonl"
POWERSHELL = os.environ.get(
    "JARVIS_POWERSHELL",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
)

ACTIVE_PROFILE_PATH = VAULT_DIR / ".jarvis" / "active_profile.json"
SETTINGS_PATH = VAULT_DIR / ".jarvis" / "settings.json"

NO_TOOLS_MODELS: set[str] = set()

SYSTEM_ORCHESTRATOR_PROMPT = """You are JARVIS, a capable local coding and systems assistant.

Operating mode:
- Be concise, direct, and action-oriented.
- Use tools when they will materially improve accuracy.
- Do not call tools speculatively.
- Prefer one strong tool call over many weak ones.
- When using tools, think step-by-step internally but return only the answer.
- If tool results are incomplete, say what is known and what is missing.
- For engineering tasks, act like an implementation partner: diagnose, modify, verify, and summarize.
- Keep momentum. Avoid hedging unless uncertainty is real.

Tool rules:
- Only call tools that are relevant to the user's current request.
- Use exact tool names and JSON arguments.
- After tool results arrive, integrate them and continue toward a final answer.
- If no tools are needed, answer directly.
"""

MODE_PROMPTS: Dict[str, str] = {
    "fast": """Respond quickly and directly.
Keep the answer lean unless the user clearly wants depth.
""",
    "reason": """Act as a high-competence analyst and technical advisor.
Be structured, practical, and evidence-oriented.
""",
    "code": """Act as an expert software engineer and systems debugger.
Work like a senior implementation partner.

Priorities:
- understand the code before changing it
- diagnose root cause, not just symptoms
- prefer minimal correct fixes
- preserve existing working behavior
- when relevant, explain exactly what changed and why
- for debugging, identify the failure point and verify the fix
- for architecture and code review, be concrete and technically rigorous
- do not give vague advice when exact implementation guidance is possible
- when asked to modify code, produce production-quality changes
""",
    "deep": """Act as a senior strategist, architect, and analyst.
Use deeper reasoning, compare alternatives, and make justified recommendations.
""",
}

ACKS = [
    "On it.",
    "Working.",
    "Understood.",
    "Processing now.",
    "Let me handle that.",
]

# -----------------------------------------------------------------------------
# Skill loading
# -----------------------------------------------------------------------------

print(f"[REACT] Loading skills from {PROJECT_ROOT / 'skills'}...")
load_skills()

TOOLS = get_all_tools()
TOOL_MAP = get_all_tool_map()
TOOL_KEYWORDS = get_all_keywords()
TOOL_SKILL_META = get_all_skill_meta()
TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}

TOOL_LIST_TEXT = "\n".join(
    f"- {t['function']['name']}: {t['function'].get('description', '')}" for t in TOOLS
)

# -----------------------------------------------------------------------------
# Dynamic discovery maps from skill metadata
# -----------------------------------------------------------------------------

def build_intent_tool_candidates(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        aliases = meta.get("intent_aliases", [])
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            key = alias.strip().lower()
            if not key:
                continue
            out.setdefault(key, []).append(tool_name)
    return out


def build_tool_hints(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        keywords = meta.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        out[tool_name] = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
    return out


def build_tool_direct_match(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        direct_match = meta.get("direct_match", [])
        if not isinstance(direct_match, list):
            direct_match = []
        out[tool_name] = [k.strip().lower() for k in direct_match if isinstance(k, str) and k.strip()]
    return out


def build_tool_route_hints(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for tool_name, meta in tool_skill_meta.items():
        route = meta.get("route")
        if isinstance(route, str) and route.strip():
            out[tool_name] = route.strip().lower()
    return out


INTENT_TOOL_CANDIDATES = build_intent_tool_candidates(TOOL_SKILL_META)
TOOL_HINTS = build_tool_hints(TOOL_SKILL_META)
TOOL_DIRECT_MATCH = build_tool_direct_match(TOOL_SKILL_META)
TOOL_ROUTE_HINTS = build_tool_route_hints(TOOL_SKILL_META)

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def debug(msg: str) -> None:
    if DEBUG:
        print(f"[REACT] {msg}")


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def ensure_dirs() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_DIR.mkdir(parents=True, exist_ok=True)


def append_log(line: str) -> None:
    try:
        ensure_dirs()
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def emit_event(event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        ensure_dirs()
        payload = {
            "ts": time.time(),
            "time": now_iso(),
            "type": event_type,
            "message": message,
            "data": data or {},
        }
        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def recent_events(limit: int = 100) -> List[Dict[str, Any]]:
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def truncate_text(value: Any, limit: int = TOOL_RESULT_CHAR_LIMIT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = safe_json_dumps(value)
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n\n[truncated to {limit} chars]"


def sanitize_for_tts(text: str) -> str:
    return text.replace("'", "''")


def speak_ack(text: str) -> None:
    if not ENABLE_TTS_ACK:
        return

    def _speak() -> None:
        try:
            safe = sanitize_for_tts(text)
            subprocess.run(
                [
                    POWERSHELL,
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Speech; "
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "$s.Rate = 2; "
                        f"$s.Speak('{safe}')"
                    ),
                ],
                timeout=10,
                capture_output=True,
            )
        except Exception as e:
            debug(f"ACK TTS error: {e}")

    threading.Thread(target=_speak, daemon=True).start()


def write_bridge_status(state: str, text: Optional[str] = None) -> None:
    try:
        ensure_dirs()
        (BRIDGE_DIR / "state.txt").write_text(state, encoding="utf-8")
        if text is not None:
            (BRIDGE_DIR / "output.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


def request_ollama_chat(payload: Dict[str, Any], timeout: int):
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def request_ollama_tags() -> Dict[str, Any]:
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_thinking_tags(text: str) -> str:
    if not text:
        return text
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.replace("</think>", "")
    return text.strip()


def load_active_profile() -> Dict[str, Any]:
    try:
        if ACTIVE_PROFILE_PATH.exists():
            return json.loads(ACTIVE_PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        debug(f"Failed to load active profile: {e}")
    return {}


def get_profile_options() -> Dict[str, Any]:
    profile = load_active_profile()
    options: Dict[str, Any] = {}

    temperature = profile.get("temperature")
    if isinstance(temperature, (int, float)):
        options["temperature"] = temperature

    top_p = profile.get("topP")
    if isinstance(top_p, (int, float)):
        options["top_p"] = top_p

    return options
def parse_planner_response(answer: str) -> List[str]:
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []

    # First try strict JSON
    try:
        data = json.loads(text)
        tools = data.get("tools", [])
        if isinstance(tools, list):
            out = []
            for item in tools:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
            return out
    except Exception:
        pass

    # Fallback: extract JSON object from surrounding text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            tools = data.get("tools", [])
            if isinstance(tools, list):
                out = []
                for item in tools:
                    if isinstance(item, str) and item.strip():
                        out.append(item.strip())
                return out
        except Exception:
            pass

    # Final fallback: comma-separated names
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts

def build_system_prompt_for_route(route: str) -> str:
    profile = load_active_profile()

    profile_prompt = (profile.get("systemPrompt") or "").strip()
    if not profile_prompt:
        profile_prompt = "You are JARVIS, a capable local assistant."

    profile_mode_prompt = (
        ((profile.get("modePrompts") or {}).get(route) or "").strip()
        if isinstance(profile.get("modePrompts"), dict)
        else ""
    )

    base_mode_prompt = MODE_PROMPTS.get(route or "reason", "").strip()
    orchestrator = SYSTEM_ORCHESTRATOR_PROMPT.strip()

    parts = [profile_prompt]

    if profile_mode_prompt:
        parts.append(profile_mode_prompt)
    elif base_mode_prompt:
        parts.append(base_mode_prompt)

    parts.append(orchestrator)
    return "\n\n".join(part for part in parts if part.strip())


def normalize_messages(
    messages: List[Dict[str, Any]],
    system_prompt: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        out.append(
            {
                "role": "system",
                "content": system_prompt or SYSTEM_ORCHESTRATOR_PROMPT,
            }
        )

    for m in messages:
        role = m.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue

        item: Dict[str, Any] = {"role": role}
        if "content" in m:
            item["content"] = m.get("content", "")
        if "tool_calls" in m and isinstance(m["tool_calls"], list):
            item["tool_calls"] = m["tool_calls"]
        if "name" in m:
            item["name"] = m["name"]
        out.append(item)

    return out


def compact_context(messages: List[Dict[str, Any]], max_messages: int = MAX_CONTEXT_MESSAGES) -> List[Dict[str, Any]]:
    systems = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]

    if len(others) <= max_messages:
        trimmed = others
    else:
        first_user = next((m for m in others if m.get("role") == "user"), None)
        tail = others[-(max_messages - (1 if first_user else 0)):]
        trimmed = ([first_user] if first_user and first_user not in tail else []) + tail

    return systems[:1] + trimmed


def get_last_user_text(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
            return safe_json_dumps(content)
    return ""

# -----------------------------------------------------------------------------
# Tool selection
# -----------------------------------------------------------------------------
def build_planner_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []

    for tool in TOOLS:
        try:
            name = tool["function"]["name"]
            description = tool["function"].get("description", "")
        except Exception:
            continue

        meta = TOOL_SKILL_META.get(name, {})

        catalog.append(
            {
                "name": name,
                "description": description,
                "intent_aliases": meta.get("intent_aliases", []),
                "keywords": meta.get("keywords", []),
                "direct_match": meta.get("direct_match", []),
                "route": meta.get("route", "reason"),
            }
        )

    return catalog


def build_planner_prompt(user_text: str) -> str:
    catalog = build_planner_catalog()

    compact_catalog = []
    for item in catalog:
        compact_catalog.append(
            {
                "name": item["name"],
                "description": item.get("description", ""),
                "aliases": item.get("intent_aliases", []),
                "route": item.get("route", "reason"),
                "keywords": item.get("keywords", [])[:12],
            }
        )

    return (
        "/no_think\n"
        "You select the minimum useful tools for a user request.\n"
        "Return ONLY valid JSON with this exact shape:\n"
        '{"tools":["tool_name_1","tool_name_2"]}\n'
        "If no tools are needed, return:\n"
        '{"tools":[]}\n\n'
        "Rules:\n"
        "- Choose the minimum useful tools.\n"
        "- Prefer exact tool names from the catalog.\n"
        "- Do not invent tool names.\n"
        "- Do not return aliases, only tool names.\n"
        "- If the request is simple conversation, return no tools.\n"
        "- If a direct answer is sufficient, return no tools.\n\n"
        f"Tool catalog:\n{json.dumps(compact_catalog, ensure_ascii=False)}\n\n"
        f"User request:\n{user_text}\n"
    )

def parse_planner_response(answer: str) -> List[str]:
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []

    # First try strict JSON
    try:
        data = json.loads(text)
        tools = data.get("tools", [])
        if isinstance(tools, list):
            out = []
            for item in tools:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
            return out
    except Exception:
        pass

    # Fallback: extract JSON object from surrounding text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            tools = data.get("tools", [])
            if isinstance(tools, list):
                out = []
                for item in tools:
                    if isinstance(item, str) and item.strip():
                        out.append(item.strip())
                return out
        except Exception:
            pass

    # Final fallback: comma-separated names
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts
    
def dedupe_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for tool in tools:
        try:
            name = tool["function"]["name"]
        except Exception:
            continue
        if name not in seen:
            seen.add(name)
            out.append(tool)
    return out


def resolve_intent_or_tool_names(names: List[str]) -> List[Dict[str, Any]]:
    resolved: List[Dict[str, Any]] = []

    for raw_name in names:
        name = (raw_name or "").strip().lower()
        if not name:
            continue

        if name in TOOLS_BY_NAME:
            resolved.append(TOOLS_BY_NAME[name])
            continue

        candidates = INTENT_TOOL_CANDIDATES.get(name, [])
        for candidate in candidates:
            if candidate in TOOLS_BY_NAME:
                resolved.append(TOOLS_BY_NAME[candidate])

    return dedupe_tools(resolved)


def direct_tools_for_text(user_text: str) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    matched_tool_names: List[str] = []

    for tool_name, phrases in TOOL_DIRECT_MATCH.items():
        if any(phrase in text for phrase in phrases):
            matched_tool_names.append(tool_name)

    for intent_alias, tool_names in INTENT_TOOL_CANDIDATES.items():
        if intent_alias in text:
            matched_tool_names.extend(tool_names)

    return dedupe_tools(
        [TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME]
    )


def select_tools_by_hints(user_text: str) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    matched_tool_names: List[str] = []

    for tool_name, hints in TOOL_HINTS.items():
        if any(hint in text for hint in hints):
            matched_tool_names.append(tool_name)

    for tool_name, keywords in TOOL_KEYWORDS.items():
        if any((kw or "").lower() in text for kw in keywords):
            matched_tool_names.append(tool_name)

    return dedupe_tools(
        [TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME]
    )


def likely_needs_tools(user_text: str) -> bool:
    text = (user_text or "").lower()
    return bool(direct_tools_for_text(text) or select_tools_by_hints(text))


def select_tools_keyword(user_text: str, max_tools: int = MAX_TOOL_SELECTION) -> List[Dict[str, Any]]:
    scores: Dict[str, int] = {}
    text = (user_text or "").lower()

    for tool_name, keywords in TOOL_KEYWORDS.items():
        score = sum(1 for kw in keywords if (kw or "").lower() in text)
        if score > 0:
            scores[tool_name] = score

    top = sorted(scores, key=scores.get, reverse=True)[:max_tools]
    return [TOOLS_BY_NAME[name] for name in top if name in TOOLS_BY_NAME]

def select_tools_via_llm(user_text: str) -> List[Dict[str, Any]]:
    planner_model = get_planner_model()
    prompt = build_planner_prompt(user_text)

    payload = {
        "model": planner_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "num_predict": 256,
            "temperature": 0,
        },
    }

    try:
        emit_event("plan", "Selecting tools", {"planner_model": planner_model})
        debug(f"Planner model: {planner_model}")
        debug(f"Planner payload: {safe_json_dumps(payload)[:2000]}")

        with request_ollama_chat(payload, timeout=PLANNER_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        answer = strip_thinking_tags(data.get("message", {}).get("content", "")).strip()
        debug(f"Planner raw: {answer}")

        selected_names = parse_planner_response(answer)
        if not selected_names:
            emit_event("plan", "Planner selected no tools")
            return []

        selected = []
        seen = set()

        for name in selected_names:
            lowered = name.strip().lower()
            if lowered in seen:
                continue
            seen.add(lowered)

            if lowered in TOOLS_BY_NAME:
                selected.append(TOOLS_BY_NAME[lowered])
                continue

            # allow alias fallback if planner returns alias instead of tool name
            alias_resolved = resolve_intent_or_tool_names([lowered])
            for tool in alias_resolved:
                try:
                    tool_name = tool["function"]["name"]
                except Exception:
                    continue
                if tool_name not in {t["function"]["name"] for t in selected}:
                    selected.append(tool)

        if not selected:
            fallback = select_tools_keyword(user_text)
            emit_event(
                "warning",
                "Planner returned no resolvable tools, using keyword fallback",
                {"raw_answer": answer},
            )
            return fallback

        selected = dedupe_tools(selected)[:MAX_TOOL_SELECTION]
        emit_event(
            "plan",
            "Planner selected tools",
            {
                "tools": [t["function"]["name"] for t in selected],
                "raw_answer": answer,
            },
        )
        return selected

    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = "<no error body>"

        debug(f"Planner HTTP error {e.code}: {e.reason} :: {error_body}")
        emit_event(
            "warning",
            "Planner failed, using keyword fallback",
            {
                "error": f"HTTP {e.code} {e.reason}",
                "body": error_body,
                "planner_model": planner_model,
            },
        )
        return select_tools_keyword(user_text)

    except Exception as e:
        debug(f"Planner error: {e}")
        emit_event(
            "warning",
            "Planner failed, using keyword fallback",
            {"error": str(e), "planner_model": planner_model},
        )
        return select_tools_keyword(user_text)

def choose_tools(user_text: str) -> List[Dict[str, Any]]:
    text = user_text or ""

    direct = direct_tools_for_text(text)
    if direct:
        direct = dedupe_tools(direct)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Direct tool selection from metadata", {"tools": [t["function"]["name"] for t in direct]})
        return direct

    selected = select_tools_via_llm(text)
    if selected:
        selected = dedupe_tools(selected)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Planner tool selection used", {"tools": [t["function"]["name"] for t in selected]})
        return selected

    hinted = select_tools_by_hints(text)
    if hinted:
        hinted = dedupe_tools(hinted)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Hint-based tool selection used", {"tools": [t["function"]["name"] for t in hinted]})
        return hinted

    keyword_tools = select_tools_keyword(text)
    if keyword_tools:
        keyword_tools = dedupe_tools(keyword_tools)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Keyword tool selection used", {"tools": [t["function"]["name"] for t in keyword_tools]})
        return keyword_tools

    emit_event("plan", "No tools selected", {"user_text": text[:120]})
    return []


def should_select_tools(
    user_text: str,
    requested_route: Optional[str],
    requested_model: Optional[str],
) -> bool:
    text = (user_text or "").strip()
    lower = text.lower()

    if not text:
        return False

    if len(text.split()) <= 4 and not likely_needs_tools(lower):
        return False

    if requested_route == "fast" and not likely_needs_tools(lower):
        return False

    if requested_model and not likely_needs_tools(lower):
        return False

    return True


def is_simple_direct_chat(
    user_text: str,
    selected_tools: List[Dict[str, Any]],
    route: str,
) -> bool:
    if selected_tools:
        return False
    if route != "fast":
        return False
    return len((user_text or "").split()) <= 12

# -----------------------------------------------------------------------------
# Route inference and tool execution
# -----------------------------------------------------------------------------

def infer_route_from_tools(selected_tools: List[Dict[str, Any]]) -> str:
    if not selected_tools:
        return "reason"

    routes: List[str] = []

    for tool in selected_tools:
        try:
            name = tool["function"]["name"]
        except Exception:
            continue
        route = TOOL_ROUTE_HINTS.get(name)
        if route:
            routes.append(route)

    if "code" in routes:
        return "code"
    if "deep" in routes:
        return "deep"
    if "reason" in routes:
        return "reason"
    if "fast" in routes:
        return "fast"

    return "reason"


def make_tool_message(name: str, result: Any) -> Dict[str, Any]:
    return {"role": "tool", "name": name, "content": truncate_text(result)}


def normalize_tool_calls(assistant_msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_calls = assistant_msg.get("tool_calls") or []
    normalized = []

    for idx, call in enumerate(raw_calls):
        fn = call.get("function", {}) if isinstance(call, dict) else {}
        fn_name = fn.get("name", "")
        fn_args = fn.get("arguments", {})

        if isinstance(fn_args, str):
            try:
                fn_args = json.loads(fn_args)
            except Exception:
                fn_args = {}
        if not isinstance(fn_args, dict):
            fn_args = {}

        normalized.append(
            {
                "id": call.get("id", f"tool_{idx}"),
                "type": "function",
                "function": {"name": fn_name, "arguments": fn_args},
            }
        )

    return normalized


def execute_tool(fn_name: str, fn_args: Dict[str, Any]) -> str:
    executor = TOOL_MAP.get(fn_name)
    if not executor:
        emit_event("warning", f"Unknown tool {fn_name}")
        return f"Unknown tool: {fn_name}"

    started = time.time()
    emit_event("tool_start", f"Running tool {fn_name}", {"tool": fn_name, "args": fn_args})

    try:
        result = executor(**fn_args)
        elapsed = time.time() - started
        preview = truncate_text(result, 300)
        debug(f"Tool ok: {fn_name} in {elapsed:.2f}s")
        emit_event(
            "tool_result",
            f"Tool {fn_name} completed",
            {"tool": fn_name, "elapsed_sec": round(elapsed, 3), "result_preview": preview},
        )
        return truncate_text(result)
    except Exception as e:
        elapsed = time.time() - started
        debug(f"Tool failed: {fn_name} in {elapsed:.2f}s :: {e}")
        emit_event(
            "warning",
            f"Tool {fn_name} failed",
            {"tool": fn_name, "elapsed_sec": round(elapsed, 3), "error": str(e)},
        )
        return truncate_text(
            {
                "error": str(e),
                "tool": fn_name,
                "traceback": traceback.format_exc(limit=3),
            }
        )


def wait_for_ollama(max_wait_sec: int = 30) -> bool:
    emit_event("status", "Waiting for Ollama", {"host": OLLAMA_HOST})
    for _ in range(max_wait_sec):
        try:
            tags = request_ollama_tags()
            emit_event("status", "Ollama ready", {"model_count": len(tags.get("models", []))})
            return True
        except Exception:
            time.sleep(1)
    emit_event("warning", "Ollama not ready in time", {"host": OLLAMA_HOST})
    return False


@dataclass
class ChatRun:
    request_id: str
    model: str
    started_at: float = field(default_factory=time.time)
    selected_tools: List[str] = field(default_factory=list)
    iterations: int = 0
    used_tools: bool = False

    def duration_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)

# -----------------------------------------------------------------------------
# Core chat loop
# -----------------------------------------------------------------------------

def react_chat(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    route: str = "reason",
) -> Dict[str, Any]:
    tools = tools or []
    system_prompt = build_system_prompt_for_route(route)
    normalized_messages = normalize_messages(messages, system_prompt=system_prompt)
    normalized_messages = compact_context(normalized_messages)

    use_tools = model not in NO_TOOLS_MODELS and len(tools) > 0
    run = ChatRun(
        request_id=str(uuid.uuid4())[:8],
        model=model,
        selected_tools=[t["function"]["name"] for t in tools],
    )

    debug(f"run={run.request_id} model={model} route={route} selected_tools={run.selected_tools} use_tools={use_tools}")
    emit_event(
        "status",
        "Chat run started",
        {
            "request_id": run.request_id,
            "model": model,
            "route": route,
            "tools": run.selected_tools,
            "use_tools": use_tools,
        },
    )

    last_data: Dict[str, Any] = {
        "model": model,
        "created_at": now_iso(),
        "message": {"role": "assistant", "content": "No response generated."},
        "done": True,
    }

    for iteration in range(1, MAX_ITERATIONS + 1):
        run.iterations = iteration

        body: Dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "stream": False,
        }

        profile_options = get_profile_options()
        if profile_options:
            body["options"] = profile_options

        if use_tools:
            body["tools"] = tools

        try:
            emit_event(
                "status",
                "Calling Ollama",
                {
                    "request_id": run.request_id,
                    "iteration": iteration,
                    "model": model,
                    "route": route,
                    "use_tools": use_tools,
                },
            )
            with request_ollama_chat(body, timeout=CHAT_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = "<no error body>"

            if e.code == 400 and use_tools:
                debug(f"{model} rejected tools. Marking as no-tools model. body={error_body}")
                emit_event(
                    "warning",
                    f"{model} rejected tools, retrying without tools",
                    {
                        "request_id": run.request_id,
                        "iteration": iteration,
                        "body": error_body,
                    },
                )
                NO_TOOLS_MODELS.add(model)
                use_tools = False
                continue

            emit_event(
                "warning",
                "Ollama HTTP error",
                {
                    "request_id": run.request_id,
                    "code": e.code,
                    "reason": e.reason,
                    "body": error_body,
                },
            )
            return {
                "model": model,
                "created_at": now_iso(),
                "message": {"role": "assistant", "content": f"Error calling Ollama: HTTP {e.code} {e.reason}"},
                "done": True,
            }

        except Exception as e:
            emit_event("warning", "Ollama request failed", {"request_id": run.request_id, "error": str(e)})
            return {
                "model": model,
                "created_at": now_iso(),
                "message": {"role": "assistant", "content": f"Error calling Ollama: {e}"},
                "done": True,
            }

        last_data = data
        assistant_msg = data.get("message", {}) or {}
        tool_calls = normalize_tool_calls(assistant_msg)

        content_preview = (assistant_msg.get("content") or "")[:120].replace("\n", " ")
        debug(f"run={run.request_id} iter={iteration} tool_calls={len(tool_calls)} preview={content_preview!r}")

        emit_event(
            "status",
            "Model replied",
            {
                "request_id": run.request_id,
                "iteration": iteration,
                "tool_call_count": len(tool_calls),
                "content_preview": content_preview,
            },
        )

        if not tool_calls:
            append_log(
                f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} done "
                f"model={model} route={route} iterations={run.iterations} duration_ms={run.duration_ms()}"
            )
            emit_event("final", "Final response ready", {"request_id": run.request_id, "duration_ms": run.duration_ms()})
            return data

        normalized_messages.append(
            {
                "role": "assistant",
                "content": assistant_msg.get("content", ""),
                "tool_calls": tool_calls,
            }
        )

        run.used_tools = True

        for call in tool_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]

            debug(f"run={run.request_id} tool={fn_name} args={safe_json_dumps(fn_args)[:180]}")
            result = execute_tool(fn_name, fn_args)
            debug(f"run={run.request_id} tool={fn_name} result={result[:180]!r}")

            normalized_messages.append(make_tool_message(fn_name, result))

    append_log(
        f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} max_iterations "
        f"model={model} route={route} iterations={run.iterations} duration_ms={run.duration_ms()}"
    )
    emit_event("warning", "Max iterations reached", {"request_id": run.request_id, "duration_ms": run.duration_ms()})
    return last_data

# -----------------------------------------------------------------------------
# Streaming support
# -----------------------------------------------------------------------------

def stream_direct_chat(
    handler: "ReactHandler",
    model: str,
    messages: List[Dict[str, Any]],
    selected_tools: Optional[List[Dict[str, Any]]] = None,
    route: str = "reason",
) -> None:
    user_text = get_last_user_text(messages)
    selected_tools = selected_tools if selected_tools is not None else choose_tools(user_text)
    tool_names = [t["function"]["name"] for t in selected_tools]

    debug(f"Streaming selected tools: {tool_names}")
    emit_event("status", "Streaming chat started", {"model": model, "route": route, "tools": tool_names})

    system_prompt = build_system_prompt_for_route(route)
    working_messages = normalize_messages(messages, system_prompt=system_prompt)
    working_messages = compact_context(working_messages)

    if selected_tools:
        ack = random.choice(ACKS)
        write_bridge_status("thinking", ack)
        speak_ack(ack)

        if ENABLE_STREAM_STATUS:
            handler._write_sse_json(
                {
                    "model": model,
                    "created_at": now_iso(),
                    "message": {"role": "assistant", "content": ""},
                    "done": False,
                    "status": f"Using tools: {', '.join(tool_names)}",
                }
            )

        result = react_chat(model, working_messages, selected_tools, route=route)
        final_messages = normalize_messages(messages, system_prompt=system_prompt)
        final_messages.append(result.get("message", {"role": "assistant", "content": ""}))
        working_messages = compact_context(final_messages)

    body = {
        "model": model,
        "messages": working_messages,
        "stream": True,
    }

    profile_options = get_profile_options()
    if profile_options:
        body["options"] = profile_options

    try:
        with request_ollama_chat(body, timeout=CHAT_TIMEOUT_SEC) as resp:
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                handler.wfile.write((line + "\n").encode("utf-8"))
                handler.wfile.flush()
    except Exception as e:
        emit_event("warning", "Streaming error", {"error": str(e), "model": model, "route": route})
        handler._write_sse_json(
            {
                "model": model,
                "created_at": now_iso(),
                "message": {"role": "assistant", "content": f"Streaming error: {e}"},
                "done": True,
            }
        )

# -----------------------------------------------------------------------------
# HTTP handler
# -----------------------------------------------------------------------------

class ReactHandler(BaseHTTPRequestHandler):
    server_version = "JarvisReact/3.0"

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw_body)
        except Exception:
            self._json_response({"error": "Invalid JSON body"}, code=400)
            return

        requested_model = body.get("model")
        requested_route = body.get("route")
        messages = body.get("messages", [])
        stream = bool(body.get("stream", False))

        if not isinstance(messages, list):
            self._json_response({"error": "messages must be a list"}, code=400)
            return

        user_text = get_last_user_text(messages)

        if should_select_tools(user_text, requested_route, requested_model):
            selected_tools = choose_tools(user_text)
        else:
            selected_tools = []

        tool_names = [t["function"]["name"] for t in selected_tools]

        resolved_route = (
            requested_route
            if requested_route in {"fast", "reason", "code", "deep"}
            else infer_route_from_tools(selected_tools)
        )

        model = resolve_model(requested_model=requested_model, route=resolved_route)

        debug(
            f"POST /api/chat "
            f"requested_model={requested_model!r} "
            f"requested_route={requested_route!r} "
            f"resolved_route={resolved_route!r} "
            f"resolved_model={model!r} "
            f"stream={stream} "
            f"tool_count={len(selected_tools)} "
            f"user={user_text[:140]!r}"
        )
        debug(f"Selected {len(selected_tools)} tools: {tool_names}")

        emit_event(
            "status",
            "Incoming chat request",
            {
                "requested_model": requested_model,
                "requested_route": requested_route,
                "resolved_route": resolved_route,
                "resolved_model": model,
                "stream": stream,
                "tool_count": len(selected_tools),
                "tools": tool_names,
                "user_preview": user_text[:140],
            },
        )

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            stream_direct_chat(self, model, messages, selected_tools=selected_tools, route=resolved_route)
            return

        if is_simple_direct_chat(user_text, selected_tools, resolved_route):
            payload = {
                "model": model,
                "messages": normalize_messages(
                    messages,
                    system_prompt=build_system_prompt_for_route(resolved_route),
                ),
                "stream": False,
            }

            profile_options = get_profile_options()
            if profile_options:
                payload["options"] = profile_options

            try:
                with request_ollama_chat(payload, timeout=CHAT_TIMEOUT_SEC) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._json_response(data)
                return
            except Exception as e:
                self._json_response(
                    {
                        "model": model,
                        "created_at": now_iso(),
                        "message": {"role": "assistant", "content": f"Error calling Ollama: {e}"},
                        "done": True,
                    }
                )
                return

        if selected_tools:
            ack = random.choice(ACKS)
            write_bridge_status("thinking", ack)
            append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ACK: {ack}")
            speak_ack(ack)

        result = react_chat(model, messages, selected_tools, route=resolved_route)
        self._json_response(result)

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/health":
            try:
                tags = request_ollama_tags()
                ollama_ready = True
                ollama_models = len(tags.get("models", []))
            except Exception:
                ollama_ready = False
                ollama_models = 0

            profile = load_active_profile()

            self._json_response(
                {
                    "status": "ok",
                    "service": "jarvis-react-v3",
                    "time": now_iso(),
                    "ollama_host": OLLAMA_HOST,
                    "ollama_ready": ollama_ready,
                    "ollama_model_count": ollama_models,
                    "loaded_skills": len(get_loaded_skills()),
                    "tool_count": len(TOOL_MAP),
                    "active_profile": {
                        "id": profile.get("id"),
                        "label": profile.get("label"),
                    },
                }
            )
            return

        if path == "/api/skills":
            self._json_response(
                {
                    "skills": get_loaded_skills(),
                    "tools": list(TOOL_MAP.keys()),
                    "tool_keywords": TOOL_KEYWORDS,
                    "tool_skill_meta": TOOL_SKILL_META,
                    "intent_tool_candidates": INTENT_TOOL_CANDIDATES,
                    "tool_route_hints": TOOL_ROUTE_HINTS,
                    "no_tools_models": sorted(NO_TOOLS_MODELS),
                }
            )
            return

        if path == "/api/models":
            cfg = load_model_config()
            self._json_response(
                {
                    "models": cfg.get("models", {}),
                    "planner_model": get_planner_model(),
                }
            )
            return

        if path == "/api/events":
            self._json_response({"events": recent_events(100)})
            return

        if path == "/api/timers":
            try:
                from skills.timer import get_active_timers  # type: ignore
                self._json_response({"timers": get_active_timers()})
            except ImportError:
                self._json_response({"timers": []})
            return

        if path == "/api/radio":
            try:
                from skills.radio import get_now_playing, get_radio_state, get_stations  # type: ignore
                self._json_response(
                    {
                        **get_radio_state(),
                        "stations": get_stations(),
                        "now_playing": get_now_playing(),
                    }
                )
            except ImportError:
                self._json_response({"playing": False, "stations": {}})
            return

        if path == "/api/network":
            try:
                from skills.network import get_topology  # type: ignore
                self._json_response(get_topology())
            except ImportError:
                self._json_response({"devices": [], "gateway": "192.168.0.1"})
            return

        self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json_response(self, data: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse_json(self, data: Dict[str, Any]) -> None:
        line = json.dumps(data, ensure_ascii=False) + "\n"
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()

   def log_message(self, fmt: str, *args: Any) -> None:
    return

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), "w", buffering=1)

    ensure_dirs()
    emit_event("status", "React server starting", {"port": PORT, "ollama_host": OLLAMA_HOST})
    wait_for_ollama()

    server = HTTPServer(("127.0.0.1", PORT), ReactHandler)
    print(f"[REACT] ReAct server v3 on http://127.0.0.1:{PORT}")
    print(f"[REACT] Ollama backend: {OLLAMA_HOST}")
    print(f"[REACT] Vault: {VAULT_DIR}")
    print(f"[REACT] Bridge: {BRIDGE_DIR}")
    print(f"[REACT] Active profile path: {ACTIVE_PROFILE_PATH}")
    print(f"[REACT] Tools ({len(TOOL_MAP)}): {', '.join(TOOL_MAP.keys())}")
    print("[REACT] READY")
    emit_event("status", "React server ready", {"port": PORT, "tool_count": len(TOOL_MAP)})

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[REACT] Server stopped")
        emit_event("status", "React server stopped")
        server.server_close()