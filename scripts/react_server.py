"""
JARVIS ReAct Server v3 — tool-augmented Ollama proxy with shared model routing,
profile-aware prompting, dynamic skill discovery, better logging, runtime mode
resolution, and Claude Code–style behavior.

Important coder-route behavior:
- qwen3-coder models do NOT receive native Ollama tools.
- code route + coder model executes the local coding skill directly.
- coding skill is expected to read files and call qwen3-coder itself.

Endpoints:
  POST /api/chat
  GET  /api/health
  GET  /api/skills
  GET  /api/models
  GET  /api/events
  GET  /api/coding-log
  GET  /api/timers
  GET  /api/radio
  GET  /api/network
  GET  /api/self
  GET  /api/runtime-mode
  GET  /api/reload

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
import asyncio
import numpy as np
import base64
import wave
from dataclasses import dataclass, field
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import re
import urllib.error
import urllib.request
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import tts
from difflib import SequenceMatcher
from memory.redis_memory import (
    write_state, read_state, update_state, format_state_block,
    push_memory, read_memory, read_tools, write_tools, set_tool,
    increment_loop, read_loop, reset_loop,
    set_flag, get_flag, clear_flag,
    ping as redis_ping, snapshot as redis_snapshot,
)
import memory.memory_router as memory_router
from scripts.context_router import build_context_pack
from scripts.chat_context import today_log_path, log_chat_event
from scripts.agent_loop_core import run_agent_loop
from services.communications_gateway import CommunicationsGateway
from services.telegram_gateway import TelegramGateway
from scripts.jarvis_history import make_plan_id, save_json, append_event, plan_dir
from skills.loader import (  # type: ignore
    get_all_keywords,
    get_all_skill_meta,
    get_all_tool_map,
    get_all_tools,
    get_loaded_skills,
    load_skills,
)
from scripts.model_config import (  # type: ignore
    get_planner_model,
    load_model_config,
    resolve_model,
)


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
TELEGRAM_MAX_MESSAGE_CHARS = 3500
TELEGRAM_NOTIFY_CHAT_ID = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "6987301428")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
KOKORO_HOST = os.environ.get("KOKORO_HOST", "http://127.0.0.1:5100")
KOKORO_TIMEOUT_SEC = int(os.environ.get("KOKORO_TIMEOUT_SEC", "5"))
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "bm_george")
# Chatterbox handles non-English TTS (Kokoro is effectively English-only).
# TTS_LANGUAGE != "en" routes speak_via_kokoro to Chatterbox instead.
CHATTERBOX_HOST = os.environ.get("CHATTERBOX_HOST", "http://127.0.0.1:5200")
CHATTERBOX_TIMEOUT_SEC = int(os.environ.get("CHATTERBOX_TIMEOUT_SEC", "60"))
TTS_LANGUAGE = os.environ.get("TTS_LANGUAGE", "en").strip().lower()
PORT = (
    int(sys.argv[sys.argv.index("--port") + 1])
    if "--port" in sys.argv
    else int(os.environ.get("JARVIS_PORT", "7900"))
)
TELEGRAM_ENABLED = int(os.environ.get("JARVIS_TELEGRAM_ENABLED", "1"))
VALID_ROUTES = {"live", "fast", "tools", "reason", "code", "deep"}

# Redis / plan_runner keys — must match plan_runner.py constants
REDIS_TASKS_KEY   = "jarvis:tasks"
REDIS_PLANS_KEY   = "jarvis:plans"
REDIS_STATUS_KEY  = "jarvis:task_status"
REDIS_RESULTS_KEY = "jarvis:task_results"

MODE_PROFILE_PATH = PROJECT_ROOT / "config" / "mode_profiles.json"

MAX_ITERATIONS = int(os.environ.get("JARVIS_MAX_ITERATIONS", "8"))
MAX_TOOL_SELECTION = int(os.environ.get("JARVIS_MAX_TOOL_SELECTION", "6"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("JARVIS_MAX_CONTEXT_MESSAGES", "12"))
PLANNER_TIMEOUT_SEC = int(os.environ.get("JARVIS_PLANNER_TIMEOUT_SEC", "120"))
CHAT_TIMEOUT_SEC = int(os.environ.get("JARVIS_CHAT_TIMEOUT_SEC", "600"))
TOOL_RESULT_CHAR_LIMIT = int(os.environ.get("JARVIS_TOOL_RESULT_CHAR_LIMIT", "12000"))

ENABLE_TTS_ACK = os.environ.get("JARVIS_ENABLE_TTS_ACK", "1") == "1"
ENABLE_STREAM_STATUS = os.environ.get("JARVIS_ENABLE_STREAM_STATUS", "1") == "1"
DEBUG = os.environ.get("JARVIS_DEBUG", "1") == "1"
HF_TOKEN = os.environ.get("HUGGINGFACEHUB_API_TOKEN", "")
VAULT_DIR = Path(
    os.environ.get(
        "JARVIS_VAULT_DIR",
        "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault",
    )
)
TOOL_USAGE_PATH = VAULT_DIR / ".jarvis" / "tool_usage.json"
PROMPTS_DIR = VAULT_DIR / ".jarvis" / "prompts"
LIVE_ROUTER_PROMPT_PATH = PROMPTS_DIR / "live_router.txt"
LIVE_CHAT_PROMPT_PATH = PROMPTS_DIR / "live_chat.txt"
PLANNER_PROMPT_PATH = PROMPTS_DIR / "planner.txt"
CODER_PROMPT_PATH = PROMPTS_DIR / "coder.txt"
COMMUNICATIONS = CommunicationsGateway(VAULT_DIR)
TELEGRAM_GATEWAY = TelegramGateway(VAULT_DIR)
BRIDGE_DIR = Path(os.environ.get("JARVIS_BRIDGE_DIR", "/tmp/jarvis"))
RUNTIME_MODE_PATH = BRIDGE_DIR / "runtime_mode.json"
EVENTS_FILE = BRIDGE_DIR / "react_events.jsonl"
POWERSHELL = os.environ.get(
    "JARVIS_POWERSHELL",
    "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
)
TASK_GRAPH_PATH = VAULT_DIR / ".jarvis" / "tasks" / "task_graph.json"
ACTIVE_PROFILE_PATH = VAULT_DIR / ".jarvis" / "active_profile.json"
PROFILES_DIR = VAULT_DIR / ".jarvis" / "profiles"
SETTINGS_PATH = VAULT_DIR / ".jarvis" / "settings.json"
KOKORO_ENABLED = os.environ.get("JARVIS_KOKORO_ENABLED", "0") == "1"
WORKFLOW_STATE_PATH = VAULT_DIR / ".jarvis" / "workflow_state.json"
NO_TOOLS_MODELS: set[str] = set()
stage_start_events = {"plan", "code_phase", "tool_start", "agent_start", "agent_step"}
stage_end_events = {"tool_result", "code_step_ready", "agent_final", "final", "warning"}
DEFAULT_MODE_PROFILES: Dict[str, Any] = {
    "defaults": {
        "fast": {"mode": "conversation", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
        "tools": {"mode": "tools", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
        "code": {"mode": "deep_engineer", "persona": "the_one", "tts_engine": "fallback", "tts_enabled": False},
        "deep": {"mode": "deep_reasoning", "persona": "architect", "tts_engine": "fallback", "tts_enabled": False},
        "reason": {"mode": "analysis", "persona": "jarvis", "tts_engine": "kokoro", "tts_enabled": True},
    },
    "tool_overrides": [
        {
            "route": "tools",
            "tools_any": ["room_command", "radio", "plex", "volume"],
            "mode": "shield",
            "persona": "shield_hill",
            "tts_engine": "kokoro",
            "tts_enabled": True,
        }
    ],
}
LLAMA_CPP_HOST = os.environ.get("LLAMA_CPP_HOST", "http://127.0.0.1:8081")
LLAMA_CPP_ROUTES = {
    r.strip()
    for r in os.environ.get("JARVIS_LLAMA_CPP_ROUTES", "live,fast").split(",")
    if r.strip()
}

SYSTEM_ORCHESTRATOR_PROMPT = """You are JARVIS, a capable local coding and systems assistant.

Operating mode:
- You have access to TTS and what your replies are spoken aloud by Orpheus, a local TTS engine. Use it for acknowledgments and when it adds to the user experience, but you can skip it for internal thoughts or when a quick response is best.
- Be concise, direct, and action-oriented.
- Use tools when they will materially improve accuracy.
- Do not call tools speculatively.
- Prefer one strong tool call over many weak ones.
- When using tools, think step-by-step internally but return only the answer.
- If tool results are incomplete, say what is known and what is missing.
- For engineering tasks, act like an implementation partner: diagnose, modify, verify, and summarize.
- Keep momentum. Avoid hedging unless uncertainty is real.
- Respond humanly and be personable and remove unnecessary technical jargon when possible, but be precise and technically rigorous when needed.
- Remove special characters from tool results that are not relevant to the user-facing answer, such as markdown formatting, unless they are needed for clarity.
- Call all weekdays with full name, e.g. "Monday", not "Mon" or "Mon.".
- Make dates and times human-friendly, e.g. "2024-06-01T14:30:00Z" becomes "First of June, 2024 at 2:30 PM UTC".

When modifying code:

- NEVER rewrite the whole file unless explicitly asked
- ALWAYS prefer minimal patches
- Preserve existing structure, imports, and logic
- Only change the exact functions relevant to the request
- If adding functionality, wrap it in helper functions
- Do NOT remove existing behavior unless explicitly required
- Keep diffs small and surgical

Output format:

1. Explain what will change (1–3 lines)
2. Show ONLY the modified parts (diff-style or clearly scoped blocks)
3. Do NOT output full file unless asked

Tool rules:
- Only call tools that are relevant to the user's current request.
- Use exact tool names and JSON arguments.
- After tool results arrive, integrate them and continue toward a final answer.
- If no tools are needed, answer directly.
"""
CODER_WORKSPACE_HINT = """
You are coding inside the local workspace.

Default code root:
/mnt/e/coding

If the user asks to fix, edit, inspect, or create a skill:
- First look under /mnt/e/coding for project folders.
- Prefer folders that contain a skills/ directory.
- If exactly one matching project exists, proceed.
- If multiple matching projects exist, ask which project folder to use.
- If the user mentions JARVIS, jarvis-os, React server, coding skill, news skill, or local assistant, assume:
  /mnt/e/coding/jarvis-os

For skill files:
- Skills are usually under:
  /mnt/e/coding/jarvis-os/skills
- Example:
  news skill = /mnt/e/coding/jarvis-os/skills/news.py
  coding skill = /mnt/e/coding/jarvis-os/skills/coding_qwen3_coder.py

Do not run coding_review automatically unless explicitly requested.
For normal fix/edit requests, read the relevant file, make the smallest safe patch, and return only the patch or exact changed code.
"""


MODE_PROMPTS: Dict[str, str] = {
    "fast": """Respond quickly and directly.
Keep the answer lean unless the user clearly wants depth.
""",
    "tools": """Act as a precise tool-using operator.
Focus on selecting the right tools, calling them with correct arguments,
and integrating the results clearly and efficiently.
Prefer short direct answers unless deeper explanation is needed.
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

ACKS = ["On it.", "Working.", "Understood.", "Processing now.", "Let me handle that."]

# -----------------------------------------------------------------------------
# Redis helpers — graceful fallback if Redis is unavailable
# -----------------------------------------------------------------------------

def _redis_available() -> bool:
    try:
        return redis_ping()
    except Exception:
        return False


def _safe_update_state(**kwargs) -> None:
    """Update Redis agent state, silently skip if Redis is down."""
    try:
        if _redis_available():
            update_state(**kwargs)
    except Exception as e:
        debug(f"Redis state update failed: {e}")


def _safe_push_memory(item: str) -> None:
    try:
        if _redis_available():
            push_memory(item)
    except Exception as e:
        debug(f"Redis push_memory failed: {e}")


def _safe_increment_loop() -> int:
    try:
        if _redis_available():
            return increment_loop()
    except Exception:
        pass
    return 0


# -----------------------------------------------------------------------------
# plan_runner bridge — queue approved plans to Redis instead of running inline
# -----------------------------------------------------------------------------

def _get_redis():
    """Get a raw redis.Redis connection for plan_runner operations."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def queue_plan_to_redis(plan: Dict[str, Any]) -> bool:
    """
    Push each step of an approved plan onto the jarvis:tasks Redis queue
    so plan_runner picks them up for execution.

    Also stores the full plan in jarvis:plans under plan_id.

    Returns True on success, False if Redis is unavailable (caller falls
    back to inline agent_loop execution).
    """
    r = _get_redis()
    if not r:
        debug("plan_runner: Redis unavailable — will execute inline")
        return False

    plan_id = plan.get("plan_id")
    steps   = plan.get("steps", [])

    if not plan_id or not steps:
        return False

    # Store the full plan so plan_runner can publish completion events
    r.hset(REDIS_PLANS_KEY, plan_id, json.dumps({
        "plan_id": plan_id,
        "goal":    plan.get("user_request", ""),
        "tasks":   [
            {
                "plan_id":    plan_id,
                "task_id":    step.get("id", i),
                "task":       step.get("goal", ""),
                "skill":      step.get("tool", "coding"),
                "tool":       step.get("tool", "code_edit"),
                "args":       step.get("args", {}),
                "depends_on": [step["id"] - 1] if step.get("id", 1) > 1 else [],
            }
            for i, step in enumerate(steps)
        ],
    }))

    # Push tasks in order; depends_on ensures serial execution
    for i, step in enumerate(steps):
        step_tool = step.get("tool", "coding")
        tfiles    = step.get("target_files", [])
        # First target file as primary path, fallback to plan paths
        primary_path = tfiles[0] if tfiles else (plan.get("paths") or ["."])[0]
        task = {
            "plan_id":      plan_id,
            "task_id":      step.get("id", i + 1),
            "task":         step.get("goal", ""),
            "skill":        step_tool,
            "tool":         "code_edit" if step_tool in ("coding", "code_edit") else step_tool,
            "target_files": tfiles,
            "args":         {
                "task":   step.get("goal", ""),
                "path":   primary_path,
                "model":  plan.get("planner_model", ""),
                "mode":   "generate",
                **(step.get("args") or {}),
            },
            "depends_on": [step["id"] - 1] if step.get("id", 1) > 1 else [],
        }
        r.rpush(REDIS_TASKS_KEY, json.dumps(task))

    emit_event("plan_runner", f"Queued {len(steps)} tasks to Redis", {
        "plan_id":   plan_id,
        "task_count": len(steps),
    })

    return True


def poll_plan_runner_result(plan_id: str, timeout_sec: int = 300) -> Optional[str]:
    """
    Subscribe to the plan completion channel and wait for plan_runner
    to publish the final summary.  Returns the summary string or None.
    """
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
        pubsub = r.pubsub()
        channel = f"jarvis:plan:{plan_id}:done"
        pubsub.subscribe(channel)

        deadline = time.time() + timeout_sec
        for msg in pubsub.listen():
            if time.time() > deadline:
                break
            if msg["type"] == "message":
                data = json.loads(msg["data"])
                pubsub.unsubscribe(channel)
                return data.get("summary", "Plan complete.")
    except Exception as e:
        debug(f"poll_plan_runner_result failed: {e}")
    return None


# -----------------------------------------------------------------------------
# memory_router adapter — consistent interface for both HTTP and WS paths
# -----------------------------------------------------------------------------

def run_memory_router(user_text: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Call memory_router.route() with the correct signature and normalise the
    return value into the live_model dict shape the rest of the server expects.

    memory_router.route() returns (result: dict, meta: dict).
    The result dict already matches the live_model schema.

    Also injects memory_context into the message list when present.
    """
    # Build recent_turns from the last few user/assistant messages
    recent_turns: List[str] = []
    for m in messages[-8:]:
        role    = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            recent_turns.append(f"{role.upper()}: {content.strip()[:300]}")

    try:
        result, meta = memory_router.route(user_text, recent_turns or None)
    except Exception as e:
        emit_event("warning", "memory_router.route() failed", {"error": str(e)})
        result = {
            "speak":                  "",
            "transcript":             user_text,
            "intent":                 "fallback",
            "action":                 "chat_only",
            "route":                  "live",
            "tool":                   None,
            "chat_confidence":        0.0,
            "escalation_confidence":  0.0,
            "execute_confidence":     0.0,
            "need_memory":            False,
            "memory_confidence":      0.0,
            "args":                   {},
            "memory_context":         "",
        }
        meta = {"error": str(e)}

    emit_event("memory_router", "Routing result", {
        "intent":     result.get("intent"),
        "action":     result.get("action"),
        "route":      result.get("route"),
        "need_memory": result.get("need_memory"),
        "tool":       result.get("tool"),
        "meta":       meta,
    })

    # Update Redis working memory with current user turn
    _safe_push_memory(f"user: {user_text[:400]}")
    _safe_update_state(task=f"routing: {result.get('intent', 'unknown')}")

    return result


# -----------------------------------------------------------------------------
# Kokoro
# -----------------------------------------------------------------------------
def _inline_chat(body: dict) -> dict:
    captured: dict = {}

    class FakeHandler(ReactHandler):
        def __init__(self):
            pass  # skip BaseHTTPRequestHandler init

        def _json_response(self, payload: dict, code: int = 200) -> None:
            captured.update(payload)

        def _write_sse_json(self, data: dict) -> None:
            pass

        def log_message(self, fmt: str, *args) -> None:
            pass

    handler = FakeHandler()

    requested_model = body.get("model")
    requested_route = body.get("route")
    source = body.get("source", "voice")
    messages = body.get("messages", [])

    # Support top-level user_text shorthand (normalise into messages)
    top_level_text = body.get("user_text", "")
    if top_level_text and not messages:
        messages = [{"role": "user", "content": top_level_text}]

    user_text = get_last_user_text(messages)
    user_text = clean_telegram_prefix(user_text)

    handled, route_override = handler.handle_live_router(
        body=body,
        user_text=user_text,
        requested_model=requested_model,
        requested_route=requested_route,
        source=source,
        messages=messages,
    )

    if not handled:
        user_text = body.get("_user_text", user_text)
        if route_override:
            requested_route = route_override

        handler.handle_full_pipeline(
            body=body,
            user_text=user_text,
            requested_model=requested_model,
            requested_route=requested_route,
            source=source,
            messages=messages,
            stream=False,
        )

    return captured or {"message": {"role": "assistant", "content": ""}, "done": True
    }

async def speak_via_kokoro(
    wfile,
    text: str,
    voice: str,
    play: bool,
    interrupted: asyncio.Event,
):
    text = str(text or "").strip()
    voice=str(voice)
    if not text or interrupted.is_set():
        return
    print(
    "[KOKORO] voice type=",
    type(voice),
    "value=",
    repr(voice),
    flush=True,
        )
    
    safe_voice = voice if voice.startswith(("af_", "am_", "bf_", "bm_")) else KOKORO_VOICE
    play=False

    # Non-English → Chatterbox (Kokoro voices above are English-only)
    use_chatterbox = TTS_LANGUAGE != "en"
    if use_chatterbox:
        host, timeout = CHATTERBOX_HOST, CHATTERBOX_TIMEOUT_SEC
        payload = {"text": text, "language": TTS_LANGUAGE}
    else:
        host, timeout = KOKORO_HOST, KOKORO_TIMEOUT_SEC
        payload = {"text": text, "voice": safe_voice, "play": play}

    try:
        req = urllib.request.Request(
            f"{host}/tts/speak",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        loop = asyncio.get_running_loop()

        response_data = await loop.run_in_executor(
            None,
            lambda: json.loads(
                urllib.request.urlopen(
                    req,
                    timeout=timeout,
                ).read().decode("utf-8")
            ),
        )

        if interrupted.is_set():
            return

        _ws_send_json(wfile, {
            "type": "tts",
            "text": text,
            "voice": safe_voice,
            "audio": response_data.get("chunks", []),
            "sample_rate": response_data.get("sample_rate", 24000),
            "format": response_data.get("format", "int16_pcm_base64"),
        })

    except Exception as e:
        emit_event(
            "warning",
            "Kokoro speak failed",
            {
                "error": str(e),
                "voice": safe_voice,
                "preview": text[:100],
            },
        ) 

def is_kokoro_running() -> bool:
    return http_get_ok_simple(
    f"{KOKORO_HOST}/tts/health",
    timeout=2
)
def get_gpu_stats() -> list:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        gpus = []

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 10:
                continue

            gpus.append({
                "name": parts[0],
                "temp": int(float(parts[1])),
                "utilization": int(float(parts[2])),
                "memUsed": int(float(parts[3])),
                "memTotal": int(float(parts[4])),
                "power": float(parts[5]),
                "powerLimit": float(parts[6]),
                "fan": int(float(parts[7])) if parts[7] != "[N/A]" else 0,
                "clockCore": int(float(parts[8])),
                "clockMem": int(float(parts[9])),
            })

        return gpus

    except Exception as e:
        emit_event("warning", "GPU stats failed", {"error": str(e)})
        return []

# Add these WebSocket frame helpers and the runner before ReactHandler class:
def _ws_read_message(rfile) -> bytes | None:
    chunks: list[bytes] = []

    while True:
        header = rfile.read(2)
        if len(header) < 2:
            return None

        fin = (header[0] & 0x80) != 0
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if opcode == 0x8:
            return None

        if opcode == 0x9:
            continue

        if length == 126:
            length = int.from_bytes(rfile.read(2), "big")
        elif length == 127:
            length = int.from_bytes(rfile.read(8), "big")

        mask = rfile.read(4) if masked else b"\x00\x00\x00\x00"
        data = bytearray(rfile.read(length))

        if masked:
            for i in range(len(data)):
                data[i] ^= mask[i % 4]

        if opcode in (0x1, 0x2, 0x0):
            chunks.append(bytes(data))

        if fin:
            return b"".join(chunks)
        
def _ws_read_frame(rfile) -> bytes | None:
    """Read one WebSocket frame, return payload bytes or None on close."""
    try:
        header = rfile.read(2)
        if len(header) < 2:
            return None

        fin = (header[0] & 0x80) != 0
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if opcode == 0x8:  # close
            return None
        if opcode == 0x9:  # ping
            return b""    # ignore pings for now

        if length == 126:
            length = int.from_bytes(rfile.read(2), "big")
        elif length == 127:
            length = int.from_bytes(rfile.read(8), "big")

        mask = rfile.read(4) if masked else b"\x00\x00\x00\x00"
        data = bytearray(rfile.read(length))

        if masked:
            for i in range(len(data)):
                data[i] ^= mask[i % 4]

        return bytes(data)

    except Exception:
        return None


def _ws_send_frame(wfile, payload: bytes, opcode: int = 0x1) -> None:
    """Send one WebSocket text or binary frame."""
    try:
        length = len(payload)
        header = bytearray()
        header.append(0x80 | opcode)

        if length <= 125:
            header.append(length)
        elif length <= 65535:
            header.append(126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(length.to_bytes(8, "big"))

        wfile.write(bytes(header) + payload)
        wfile.flush()
    except Exception:
        pass



def _ws_send_json(wfile, data: dict) -> None:
    _ws_send_frame(wfile, json.dumps(data, ensure_ascii=False).encode("utf-8"))


async def _run_live_ws(rfile, wfile) -> None:
    import concurrent.futures

    loop = asyncio.get_event_loop()
    msg_queue: asyncio.Queue = asyncio.Queue()
    interrupted = asyncio.Event()
    running = [True]

    def reader_thread():
        while running[0]:
            raw = _ws_read_message(rfile)
            if raw is None:
                loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                return

            if raw:
                try:
                    msg = json.loads(raw.decode("utf-8"))
                    loop.call_soon_threadsafe(msg_queue.put_nowait, msg)
                except Exception as e:
                    debug(f"WS decode failed: {e}")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop.run_in_executor(executor, reader_thread)

    profile = load_active_profile()
    voice = profile.get("voice", "af_george")

    try:
        while True:
            msg = await msg_queue.get()
            if msg is None:
                break

            msg_type = msg.get("type", "user_audio")

            if msg_type == "interrupt":
                interrupted.set()
                continue

            interrupted.clear()

            if msg_type not in {"user_audio", "audio"}:
                continue

            audio_b64 = msg.get("audio", "")
            image_b64 = msg.get("image")

            transcript = await loop.run_in_executor(
                None,
                lambda a=audio_b64: transcribe_audio_b64(a),
            )

            if not transcript or len(transcript.strip()) < 2:
                continue

            _ws_send_json(wfile, {
                "type": "transcription",
                "text": transcript,
            })

            messages = []

            live_prompt = load_prompt_file(LIVE_CHAT_PROMPT_PATH, fallback="")
            system_content = (
                live_prompt
                or profile.get("systemPrompt")
                or SYSTEM_ORCHESTRATOR_PROMPT
            )

            short_ctx = build_short_term_context()
            last_exchange = build_last_exchange_context()
            coder_mem = load_coder_memory(max_chars=1000)

            context_parts = [
                p for p in [short_ctx, last_exchange, coder_mem]
                if p and p.strip()
            ]

            if context_parts:
                system_content += "\n\n" + "\n\n".join(context_parts)

            messages.append({
                "role": "system",
                "content": system_content,
            })

            if image_b64:
                messages.append({
                    "role": "system",
                    "content": (
                        "The user is showing their camera. "
                        "Describe what you see if relevant."
                    ),
                })

            messages.append({
                "role": "user",
                "content": transcript,
            })

            if interrupted.is_set():
                continue

            # ── Use memory_router for the WS path (correct signature) ──
            n = _safe_increment_loop()
            _safe_push_memory(f"[{n}] user: {transcript}")

            messages.insert(0, {
                "role": "system",
                "content": format_state_block(),
            })

            live_result = run_memory_router(transcript, messages)

            # Inject memory context into system if present
            memory_ctx = live_result.get("memory_context", "")
            if memory_ctx and memory_ctx.strip():
                messages.insert(1, {
                    "role": "system",
                    "content": (
                        "Memory context — optional background only. "
                        "Do not change user intent based on memory.\n\n"
                        + memory_ctx
                    ),
                })

            reply = live_result.get("speak", "") or ""
            route = live_result.get("route", "live")
            tool  = live_result.get("tool")
            live_action   = live_result.get("action", "chat_only")
            live_speak    = str(live_result.get("speak") or "").strip()
            live_memory       = live_result.get("need_memory")
            live_memory_conf  = live_result.get("memory_confidence")

            write_chat_log("user",      transcript, route=route, model="voice")
            write_chat_log("assistant", reply,      route=route, model="voice")

            # Push assistant reply to Redis working memory
            _safe_push_memory(f"[{n}] assistant: {reply[:300]}")

            if interrupted.is_set():
                continue

            _ws_send_json(wfile, {
                "type":           "text",
                "text":           reply,
                "route":          route,
                "tool":           tool,
                "transcription":  transcript,
                "live_memory":    live_memory,
                "live_memory_conf": live_memory_conf,
            })

            # Rule:
            # chat_only: speak live_speak/reply and stop.
            # tools/escalation: speak live_speak as ack, then final reply.
            if live_action == "chat_only":
                await speak_via_kokoro(
                    wfile,
                    live_speak or reply,
                    voice,
                    True,
                    interrupted,
                )
                continue

            if live_speak:
                await speak_via_kokoro(
                    wfile,
                    live_speak,
                    voice,
                    True,
                    interrupted,
                )

            if reply.strip():
                await speak_via_kokoro(
                    wfile,
                    reply,
                    voice,
                    True,
                    interrupted,
                )

    finally:
        running[0] = False
        executor.shutdown(wait=False)




# -----------------------------------------------------------------------------
# Skill loading
# -----------------------------------------------------------------------------
def load_tool_usage() -> dict:
    try:
        return json.loads(TOOL_USAGE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_tool_usage(data: dict) -> None:
    TOOL_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOOL_USAGE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(TOOL_USAGE_PATH)


def increment_tool_usage(tool_name: str) -> None:
    data = load_tool_usage()
    row = data.get(tool_name, {"count": 0})
    row["count"] = int(row.get("count", 0)) + 1
    row["last_used"] = now_iso()
    data[tool_name] = row
    save_tool_usage(data)
def write_chat_log(role: str, content: str, route: str = "", model: str = "") -> None:
    if not log_chat_event:
        print("[CHAT_LOG] log_chat_event not available")
        return

    if not content or not str(content).strip():
        return

    try:
        log_chat_event(
            role=role,
            content=str(content).strip(),
            route=route,
            model=model,
        )
        print(f"[CHAT_LOG] saved {role}: {str(content)[:80]}")
    except Exception as e:
        print(f"[CHAT_LOG] failed: {type(e).__name__}: {e}")

def get_top_used_tools(limit: int = 10) -> list[str]:
    data = load_tool_usage()
    return [
        name
        for name, _row in sorted(
            data.items(),
            key=lambda x: int(x[1].get("count", 0)),
            reverse=True,
        )[:limit]
    ]
RECENT_TOOL_COMMANDS = {}

def is_duplicate_tool_command(source: str, user_text: str, tool: str, window_sec: int = 10) -> bool:
    key = f"{source}:{tool}:{user_text.strip().lower()}"
    now = time.time()
    last = RECENT_TOOL_COMMANDS.get(key, 0)

    RECENT_TOOL_COMMANDS[key] = now
    return now - last < window_sec

def fuzzy_score(a: str, b: str) -> float:
    a = a.lower().strip()
    b = b.lower().strip()

    score = SequenceMatcher(None, a, b).ratio()

    # Boost prefix/contains matches
    if a.startswith(b) or b.startswith(a):
        score = max(score, 0.94)

    if b in a or a in b:
        score = max(score, 0.90)

    return score
def clean_tool_result_for_telegram(result: Any) -> str:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict) and data.get("plain"):
            return str(data["plain"])

        speech = result.get("speech")
        if isinstance(speech, dict) and speech.get("text"):
            return str(speech["text"])

        ui = result.get("ui")
        if isinstance(ui, dict) and ui.get("summary"):
            return str(ui["summary"])

    return truncate_text(result, limit=1200)

_CODE_VERBS = {
    "build", "create", "make", "write", "code", "develop", "generate",
    "scaffold", "implement", "program", "design", "fix", "patch", "update",
    "edit", "refactor", "add", "modify", "change",
}
_CODE_NOUNS = {
    "website", "site", "webpage", "app", "application", "game", "script",
    "tool", "api", "server", "bot", "widget", "component", "function",
    "class", "module", "plugin", "extension", "dashboard", "ui", "feature",
    "file", "html", "css", "js", "py", "ts", "tsx", "json", "yaml",
}

def force_correct_common_tool(user_text: str, live_result: dict) -> dict:
    text = (user_text or "").lower()
    words = set(text.split())

    if "news" in text or "headlines" in text or "day's news" in text or "days news" in text:
        live_result["action"] = "direct_tool"
        live_result["route"] = "tools"
        live_result["tool"] = "news"
        live_result["intent"] = "daily_news"
        live_result["args"] = {
            "action": "top",
            "location": "Estonia",
            "limit": 6,
        }
        return live_result

    # Force code route when user asks to build/create/write something
    if (words & _CODE_VERBS) and (words & _CODE_NOUNS):
        if live_result.get("action") not in ("code", "direct_tool"):
            live_result["action"] = "code"
            live_result["route"] = "code"
            live_result["tool"] = None
            live_result["args"] = {}

    return live_result

def build_skill_command_index() -> list[dict]:
    index = []

    for tool_name, tool in TOOLS_BY_NAME.items():
        fn = tool.get("function", {})
        description = fn.get("description", "")

        phrases = []

        # Tool name itself
        phrases.append(tool_name.replace("_", " "))

        # Description as weak phrase
        if description:
            phrases.append(description)

        # Optional custom metadata if your loader exposes it
        for phrase in tool.get("commands", []) or []:
            phrases.append(phrase)

        for phrase in tool.get("aliases", []) or []:
            phrases.append(phrase)

        for phrase in phrases:
            if phrase and isinstance(phrase, str):
                index.append({
                    "tool_name": tool_name,
                    "phrase": phrase,
                    "tool": tool,
                })

    return index
def load_markdown_skill_by_name(name: str) -> dict | None:
    skills = load_markdown_skills()

    for skill in skills:
        if skill.get("name", "").lower() == name.lower():
            return skill

    return None
def resolve_skill_command(user_text: str, threshold: float = 0.82) -> dict | None:
    best = None
    best_score = 0.0

    for item in build_skill_command_index():
        score = fuzzy_score(user_text, item["phrase"])

        if score > best_score:
            best_score = score
            best = item

    if not best or best_score < threshold:
        return None

    return {
        "tool_name": best["tool_name"],
        "tool": best["tool"],
        "phrase": best["phrase"],
        "score": round(best_score, 3),
    }

def build_intent_tool_candidates(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        aliases = meta.get("intent_aliases", [])
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                out.setdefault(alias.strip().lower(), []).append(tool_name)
    return out

from pathlib import Path

CODER_MEMORY_PATH = Path(VAULT_DIR) / ".jarvis" / "coder_memory.md"

def load_coder_memory(max_chars: int = 4000) -> str:
    if not CODER_MEMORY_PATH.exists():
        return ""

    text = CODER_MEMORY_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return ""

    if len(text) > max_chars:
        text = text[-max_chars:]

    return f"""Recent coder memory:
{text}"""
PLANNER_STATE_PATH = Path(VAULT_DIR) / ".jarvis" / "planner" / "active_plan.json"

def load_task_graph() -> dict:
    if not TASK_GRAPH_PATH.exists():
        return {"tasks": {}, "active_task_id": None}
    try:
        data = json.loads(TASK_GRAPH_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"tasks": {}, "active_task_id": None}
    except Exception:
        return {"tasks": {}, "active_task_id": None}


def save_task_graph(graph: dict) -> None:
    TASK_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASK_GRAPH_PATH.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_task(title: str, user_request: str, route: str, model: str) -> dict:
    graph = load_task_graph()
    task_id = "task_" + str(uuid.uuid4())[:8]
    now = now_iso()

    task = {
        "id": task_id,
        "title": title,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "route": route,
        "model": model,
        "user_request": user_request,
        "steps": [],
        "events": [],
    }

    graph.setdefault("tasks", {})[task_id] = task
    graph["active_task_id"] = task_id
    save_task_graph(graph)
    return task

def load_active_plan() -> Dict[str, Any]:
    # Try Redis first
    try:
        r = _get_redis()
        if r:
            active_id = r.get("jarvis:active_plan_id")
            if active_id:
                raw = r.hget(REDIS_PLANS_KEY, active_id)
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        return data
    except Exception:
        pass
    # Fall back to file
    if not PLANNER_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(PLANNER_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def load_plan_by_id(plan_id: str) -> Dict[str, Any]:
    # Try Redis first
    try:
        r = _get_redis()
        if r:
            raw = r.hget(REDIS_PLANS_KEY, plan_id)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    # Fall back to files
    plan_root = VAULT_DIR / ".jarvis" / "history" / "plans" / plan_id
    for filename in ["status.json", "plan.json"]:
        path = plan_root / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

def save_active_plan(plan: Dict[str, Any]) -> None:
    plan_id = plan.get("plan_id", "")
    # Persist to Redis
    try:
        r = _get_redis()
        if r and plan_id:
            r.hset(REDIS_PLANS_KEY, plan_id, json.dumps(plan, ensure_ascii=False))
            r.set("jarvis:active_plan_id", plan_id)
            r.expire("jarvis:active_plan_id", 86400)  # 24h TTL
    except Exception:
        pass
    # Also write to file as backup
    PLANNER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLANNER_STATE_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

def execute_skill_safely(tool_name: str, args: dict, skills: dict) -> str:
    try:
        skill = skills[tool_name]

        if hasattr(skill, "run"):
            result = skill.run(**args)
        elif callable(skill):
            result = skill(**args)
        else:
            return f"Skill {tool_name} is not executable."

        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        return f"Skill execution failed: {type(e).__name__}: {e}"
    
def is_plan_continue_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command in {"proceed", "continue", "next", "run next", "yes proceed"}

def is_plan_cancel_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command == "cancel"

def is_plan_modify_command(text: str) -> bool:
    command, _ = parse_plan_command(text)
    return command == "modify"

def extract_planner_steps(answer: str) -> List[Dict[str, Any]]:
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []

    steps: List[Dict[str, Any]] = []

    # Fast path: valid JSON
    try:
        data = json.loads(text)
        raw_steps = data.get("steps", []) if isinstance(data, dict) else data
        if isinstance(raw_steps, list):
            for item in raw_steps:
                if isinstance(item, dict) and item.get("goal"):
                    steps.append({"goal": str(item["goal"]).strip()})
            if steps:
                return steps
    except Exception:
        pass

        # Recovery path: extract every complete "goal": "..." from broken JSON
    for match in re.finditer(r'"goal"\s*:\s*"([^"]+)"', text):
        goal = match.group(1).strip()

        if "Make the smallest safe code change" in goal:
            goal = goal.split("Make the smallest safe code change", 1)[0].strip()

        if goal:
            steps.append({"goal": goal})

    return steps
def build_simple_code_plan(user_text: str, paths: List[str]) -> Dict[str, Any]:
    planner_model = get_planner_model()

    staging_hint = f"Staging root: /mnt/e/coding/staging/dev/<PLAN_ID>/"

    prompt = (
    "/no_think\n"
    "Create a concrete coding implementation plan.\n"
    "Return ONLY valid JSON — no markdown, no explanations, no code fences.\n\n"
    "Required JSON shape:\n"
    "{\n"
    '  "speak": "1-sentence summary of what will be built",\n'
    '  "intent": "code_plan_create",\n'
    '  "action": "code",\n'
    '  "route": "code",\n'
    '  "chat_confidence": 0.0,\n'
    '  "execution_confidence": 1.0,\n'
    '  "continue_plan": false,\n'
    '  "create_new_plan": true,\n'
    '  "plan_action": "create",\n'
    '  "tool": null,\n'
    '  "args": {},\n'
    '  "files": ["staging/dev/<PLAN_ID>/index.html", "staging/dev/<PLAN_ID>/style.css"],\n'
    '  "steps": [\n'
    '    {\n'
    '      "id": 1,\n'
    '      "goal": "detailed description of exactly what to implement in this step",\n'
    '      "tool": "coding",\n'
    '      "target_files": ["staging/dev/<PLAN_ID>/index.html"]\n'
    '    }\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Return JSON ONLY. No prose before or after.\n"
    "- All file paths use staging: /mnt/e/coding/staging/dev/<PLAN_ID>/filename.ext\n"
    "- Use <PLAN_ID> as a literal placeholder in paths — it gets replaced at runtime.\n"
    "- List every file that will be created or modified in top-level 'files' array.\n"
    "- Every step MUST have 'target_files' listing which files it touches.\n"
    "- Do not use directory names as files (use index.html not src/).\n"
    "- Write 5-10 steps. Each step implements one specific, concrete piece.\n"
    "- Step goals must be detailed: describe WHAT to implement, not just 'create file'.\n"
    "- For new projects: separate HTML structure, CSS, JS logic, animations into distinct steps.\n"
    "- For skill fixes: include read-file step, patch step, test step, deliver step.\n"
    "- Second-to-last step: run tests or verify the implementation works.\n"
    "- Last step: copy files from staging/dev to staging/tested/<PLAN_ID>/ for review.\n"
    "- tool field: 'coding' for code generation, 'shell' for tests/shell commands, 'podman' for containerized tests.\n\n"
    "Examples:\n"
    "{\n"
    '  "speak": "I will create a small HTML file with the requested page.",\n'
    '  "intent": "code_plan_create",\n'
    '  "action": "code",\n'
    '  "route": "code",\n'
    '  "chat_confidence": 0.0,\n'
    '  "execution_confidence": 1.0,\n'
    '  "continue_plan": false,\n'
    '  "create_new_plan": true,\n'
    '  "plan_action": "create",\n'
    '  "tool": null,\n'
    '  "args": {},\n'
    '  "files": ["staging/dev/<PLAN_ID>/love.html"],\n'
    '  "steps": [\n'
    '    {"id": 1, "goal": "Create HTML skeleton: DOCTYPE, head with viewport meta and link to style.css, body with a centered .container div holding an h1 title and empty #heart div.", "tool":"coding","target_files": ["staging/dev/<PLAN_ID>/love.html"]},\n'
    '    {"id": 2, "goal": "Add CSS: full-page flexbox centering, #heart as a 200px red div with heart clip-path, @keyframes pulse animation scaling 1.0-1.15 on a 1s loop.", "tool":"coding", "target_files": ["staging/dev/<PLAN_ID>/love.html"]},\n'
    '    {"id": 3, "goal": "Add the visible message text inside .container, style the h1 with a romantic font and color, ensure file is complete and valid HTML.", "tool":"coding", "target_files": ["staging/dev/<PLAN_ID>/love.html"]},\n'
    '    {"id": 4, "goal": "Open the file in a headless browser or validate HTML structure. Confirm animation classes are present.", "tool":"shell", "target_files": ["staging/dev/<PLAN_ID>/love.html"]},\n'
    '    {"id": 5, "goal": "Copy staging/dev/<PLAN_ID>/ to staging/tested/<PLAN_ID>/ for human review.", "tool":"shell", "target_files": ["staging/tested/<PLAN_ID>/love.html"]}\n'
    "  ]\n"
    "}\n\n"
    f"User request:\n{user_text}\n\n"
    f"Likely paths:\n{json.dumps(paths, ensure_ascii=False)}\n"
    f"{staging_hint}\n"
    )

    payload = {
        "model": planner_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 2400,
            "num_ctx": 8192,
        },
    }
    plan_files: List[str] = []
    parsed_plan: Dict[str, Any] = {}
    try:
        answer = ""
        raw_steps = []
        with request_ollama_chat(payload, timeout=PLANNER_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            emit_event(
                "code_phase",
                "Coding planner full response",
                {    "route": "code",
                    "model": planner_model,
                    "planner_model": planner_model,
                    "data": data,
                },
            )

            raw_content = data.get("message", {}).get("content", "")
            answer = strip_thinking_tags(raw_content).strip()

            parsed_plan = parse_json_object_from_text(answer) or {}

            plan_files = parsed_plan.get("files", [])
            if not isinstance(plan_files, list):
                plan_files = []

            raw_steps = parsed_plan.get("steps", [])
            if not isinstance(raw_steps, list):
                raw_steps = extract_planner_steps(answer)

            if not answer and raw_content:
                answer = raw_content.strip()
            if not raw_steps:
                raw_steps = extract_planner_steps(answer)

            emit_event(
                "code_phase",
                "Planner steps extracted",
                {
                    "count": len(raw_steps),
                    "raw_steps": raw_steps,
                    "preview": answer[:500],
                },
            )

        steps = []
        for i, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            goal = str(raw_step.get("goal", "")).strip()
            if not goal:
                continue
            step: Dict[str, Any] = {"id": i, "status": "pending", "goal": goal}
            tfiles = raw_step.get("target_files", [])
            if isinstance(tfiles, list) and tfiles:
                step["target_files"] = tfiles
            tool_field = raw_step.get("tool", "")
            if tool_field:
                step["tool"] = tool_field
            steps.append(step)

        if not steps:
            raise ValueError(f"planner returned no usable steps. Raw answer: {answer[:500]}")

    except Exception as e:
            emit_event("warning", "Coding planner failed, using fallback plan", {"error": str(e)})
            steps = [
                {
                    "id": 1,
                    "status": "pending",
                    "goal": f"PLANNER FAILED: {e}. Make the smallest safe code change requested by the user. Return patch format only.",
                }
            ]

    plan_id = make_plan_id()

    def _subst(val: Any) -> Any:
        """Replace <PLAN_ID> placeholder with actual plan_id in strings/lists."""
        if isinstance(val, str):
            return val.replace("<PLAN_ID>", plan_id)
        if isinstance(val, list):
            return [_subst(v) for v in val]
        return val

    plan_files = [_subst(f) for f in plan_files]
    for step in steps:
        if "target_files" in step:
            step["target_files"] = _subst(step["target_files"])
        step["goal"] = _subst(step["goal"])

    plan = {
        "plan_id": plan_id,
        "current_step": 0,

        "user_request": user_text,

        "paths": paths,
        "files": plan_files or paths,

        "planner_model": planner_model,

        "speak": parsed_plan.get(
            "speak",
            "Plan created."
        ),

        "intent": parsed_plan.get(
            "intent",
            "code_plan_create",
        ),

        "action": parsed_plan.get(
            "action",
            "code",
        ),

        "route": parsed_plan.get(
            "route",
            "code",
        ),

        "chat_confidence": float(
            parsed_plan.get(
                "chat_confidence",
                0.0,
            )
        ),

        "execution_confidence": float(
            parsed_plan.get(
                "execution_confidence",
                1.0,
            )
        ),

        "continue_plan": bool(
            parsed_plan.get(
                "continue_plan",
                False,
            )
        ),

        "create_new_plan": bool(
            parsed_plan.get(
                "create_new_plan",
                True,
            )
        ),

        "plan_action": parsed_plan.get(
            "plan_action",
            "create",
        ),

        "tool": parsed_plan.get(
            "tool",
            None,
        ),

        "args": parsed_plan.get(
            "args",
            {},
        ),

        "steps": steps,

        "created_at": now_iso(),

        "status": "waiting_for_approval",
    }

    save_json(plan_id, "plan.json", plan)

    append_event(
        "plan.created",
        "Coding plan created",
        plan_id=plan_id,
        route="code",
        model=planner_model,
        payload={
            "user_request": user_text,
            "paths": paths,
            "step_count": len(steps),
        },
    )

    return plan

def render_plan(plan: Dict[str, Any]) -> str:
    plan_id = plan.get("plan_id", "?")
    speak   = plan.get("speak", "").strip()
    files   = plan.get("files", [])

    lines = [f"PLAN_ID: {plan_id}"]
    if speak:
        lines.append(f"Summary: {speak}")
    if files:
        lines.append(f"Files:   {', '.join(files)}")
    lines.append("")

    for step in plan.get("steps", []):
        status = step.get("status", "pending")
        goal   = step.get("goal", "")
        sid    = step.get("id", "?")
        tfiles = step.get("target_files", [])
        tool   = step.get("tool", "")

        marker = "✓" if status == "done" else "•"
        line = f"  {marker} {sid}. {goal}"
        if tfiles:
            line += f"\n       files: {', '.join(tfiles)}"
        if tool and tool not in ("coding", "code_edit"):
            line += f"  [{tool}]"
        lines.append(line)

    lines.append("")
    lines.append("Reply:  proceed | modify <change> | cancel")
    return "\n".join(lines)

def build_tool_hints(tool_skill_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tool_name, meta in tool_skill_meta.items():
        keywords = meta.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        out[tool_name] = [k.strip().lower() for k in keywords if isinstance(k, str) and k.strip()]
    return out



# -----------------------------------------------------------------------------
# Audio transcription (Whisper via llama-server or fallback)
# -----------------------------------------------------------------------------
def transcribe_audio_b64(audio_b64: str) -> str:
    """Transcribe base64 WAV audio using llama-server /v1/audio/transcriptions."""
    if not audio_b64:
        return ""

    LLAMA_SERVER = os.environ.get("JARVIS_LLAMA_SERVER", "http://127.0.0.1:8081")

    try:
        import base64
        audio_bytes = base64.b64decode(audio_b64)

        boundary = "----JarvisAudioBoundary"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(audio_bytes)
        body.extend(f"\r\n--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
        body.extend(b"whisper-1")
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            f"{LLAMA_SERVER}/v1/audio/transcriptions",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("text", "")).strip()

    except Exception as e:
        emit_event("warning", "Audio transcription failed", {"error": str(e)})

        # Fallback: send audio as input_audio to chat completions and ask for transcription
        try:
            payload = {
                "model": "gemma4",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": audio_b64, "format": "wav"},
                            },
                            {"type": "text", "text": "Transcribe exactly what is said. Return only the transcription, nothing else."},
                        ],
                    }
                ],
                "stream": False,
            }

            req = urllib.request.Request(
                f"{LLAMA_SERVER}/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                raw = strip_thinking_tags(raw).strip()
                if "<channel|>" in raw:
                    raw = raw.split("<channel|>")[-1].strip()
                return raw

        except Exception as e2:
            emit_event("warning", "Audio transcription fallback failed", {"error": str(e2)})
            return ""


# -----------------------------------------------------------------------------
# handle_live_router — now uses memory_router for the HTTP path
# -----------------------------------------------------------------------------

def handle_live_router(
    self,
    body: dict,
    user_text: str,
    requested_model: str | None,
    requested_route: str | None,
    source: str,
    messages: list,
) -> tuple[bool, str | None]:
    """
    Fast path: memory_router classify + direct tool execution + chat_only responses.

    Now uses memory_router.route() for both HTTP and WS paths so routing,
    memory fetch, and Redis state are consistent everywhere.

    Returns (handled, requested_route_override).
    If handled=True, response has already been sent.
    If handled=False, caller should proceed to handle_full_pipeline.
    requested_route_override may override requested_route for the full pipeline.
    """
    # ── Plan command short-circuit (bypasses memory_router entirely) ──────
    # "proceed PLAN-ID", "cancel PLAN-ID", "modify ...", bare "proceed" etc.
    # must always go straight to the code route without memory_router interference.
    _plan_cmd_words = (user_text or "").strip().lower().split()
    _plan_cmd = _plan_cmd_words[0] if _plan_cmd_words else ""
    if _plan_cmd in {"proceed", "continue", "run", "yes", "accept", "cancel"}:
        return False, "code"
    if _plan_cmd == "modify" and len(_plan_cmd_words) > 1:
        return False, "code"

    # ── Pass 1-4 via memory_router ────────────────────────────────────────
    live_result = run_memory_router(user_text, messages)
    live_result = force_correct_common_tool(user_text, live_result)

    # Inject memory context into messages when present so full pipeline sees it
    memory_ctx = live_result.get("memory_context", "")
    if memory_ctx and memory_ctx.strip():
        insert_at = 1 if messages and messages[0].get("role") == "system" else 0
        messages.insert(insert_at, {
            "role": "system",
            "content": (
                "Memory context — optional background only. "
                "Do not change user intent based on memory.\n\n"
                + memory_ctx
            ),
        })

    live_action             = live_result.get("action")
    chat_confidence         = float(live_result.get("chat_confidence", 0))
    escalation_confidence   = float(live_result.get("escalation_confidence", 0))
    execute_confidence      = float(live_result.get("execute_confidence", 0))
    memory_confidence       = float(live_result.get("memory_confidence", 0))
    need_memory             = bool(live_result.get("need_memory", False))
    live_speak              = str(live_result.get("speak") or "").strip()
    live_transcript         = str(live_result.get("transcript") or "").strip()
    live_tool               = str(live_result.get("tool") or "").strip()
    live_intent             = str(live_result.get("intent") or "").strip()
    live_args               = live_result.get("args") or {}

    write_chat_log("assistant", live_speak, route=live_action or "live", model="memory_router")

    emit_event(
        "memory_router",
        "Reply and confidence",
        {
            "speak":                  live_speak,
            "tool":                   live_tool,
            "escalation_confidence":  escalation_confidence,
            "execute_confidence":     execute_confidence,
            "chat_confidence":        chat_confidence,
            "need_memory":            need_memory,
            "memory_confidence":      memory_confidence,
            "user_text":              user_text[:200],
        },
    )

    if not isinstance(live_args, dict):
        live_args = {}

    if live_tool == "radio" and live_args.get("action") == "play" and not live_args.get("station"):
        live_action = "chat_only"
        live_speak = "Which radio station should I play?"

    if live_transcript:
        user_text = live_transcript
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                messages[i] = {**messages[i], "content": user_text}
                break

    # --- chat_only fast return ---
    # Don't intercept if the caller explicitly set a non-live route
    _explicit_route_set = requested_route and requested_route not in ("live", None)

    # Research-shaped questions must reach the deep agent loop — a confident
    # inline chat_only answer or a single direct_tool call (one web search)
    # is not research. Mirrors detect_route's deep keyword fallback.
    if (
        not _explicit_route_set
        and live_action in ("chat_only", "direct_tool")
        and is_research_shaped(user_text)
    ):
        live_action = "deep_agent"
        live_result["action"] = "deep_agent"
        live_result["route"] = "deep"

    if live_action == "chat_only" and not _explicit_route_set and (chat_confidence >= 0.70 or escalation_confidence == 0.0) and live_speak:
        self._json_response({
            "model":      "memory_router",
            "created_at": now_iso(),
            "message":    {"role": "assistant", "content": live_speak},
            "done":       True,
            "route":      "live",
            "live":       live_result,
        })
        return True, None

    # --- direct tool fast return ---
    live_direct_skill_match = resolve_skill_command(user_text)
    live_tool_fixed = live_tool

    if live_direct_skill_match and live_direct_skill_match.get("score", 0) >= 0.88:
        live_tool_fixed = live_direct_skill_match.get("tool_name")

    if (
        live_action == "direct_tool"
        and execute_confidence >= 0.75
        and live_tool_fixed
        and live_tool_fixed in TOOL_MAP
    ):
        live_result = complete_tool_args_with_meta(
            tool_name=live_tool_fixed,
            user_text=user_text,
            parsed=live_result,
        )
        live_args = live_result.get("args") or {}
        result = execute_tool(live_tool_fixed, live_args)

        if source == "telegram" and live_tool_fixed == "flux":
            sent_media = send_flux_result_to_telegram(result)
            notify_telegram("Image sent to Telegram!" if sent_media else "Failed to send image to Telegram.")

        content = extract_tool_content(result)
        reply = content or live_speak or f"Done: {live_tool_fixed}"

        # Update Redis: tool executed
        _safe_update_state(task=f"tool:{live_tool_fixed}", confidence="high")
        _safe_push_memory(f"assistant: executed {live_tool_fixed} → {reply[:200]}")

        try:
            write_chat_log("user",      user_text, route="tools", model="memory_router")
            write_chat_log("assistant", reply,     route="tools", model="memory_router")
        except Exception as e:
            print(f"[CHAT_LOG] direct tool log failed: {e}")

        emit_event(
            "router",
            "Memory router decision",
            {
                "action":                 live_result.get("action"),
                "route":                  live_result.get("route"),
                "tool":                   live_tool_fixed,
                "chat_confidence":        live_result.get("chat_confidence"),
                "escalation_confidence":  live_result.get("escalation_confidence"),
                "execute_confidence":     live_result.get("execute_confidence"),
                "intent":                 live_result.get("intent"),
                "speak":                  live_result.get("speak", "")[:300],
            },
        )

        self._json_response({
            "model":       "memory_router",
            "created_at":  now_iso(),
            "message":     {"role": "assistant", "content": reply},
            "done":        True,
            "route":       "tools",
            "format":      "direct_tool",
            "tool":        live_tool_fixed,
            "tool_result": result,
            "live":        live_result,
        })
        return True, None

    # --- chat_history_query shortcut ---
    if live_result.get("action") == "chat_only" and requested_route == "live" and live_intent == "chat_history_query":
        model = resolve_model(requested_model=requested_model, route="live")
        try:
            from scripts.chat_context import read_last_chat_log_chars
        except Exception:
            from chat_context import read_last_chat_log_chars
        recent_chat = read_last_chat_log_chars(max_chars=4000)
        messages.insert(1, {
            "role": "system",
            "content": (
                "Recent chat log. Use this to answer the user's question about recent discussion. "
                "Do not dump the log unless the user asks. Answer concisely.\n\n"
                + recent_chat
            ),
        })
        data = call_ollama_once(model=model, messages=messages, route="live", persona=None, tools=None, stream=False)
        reply_text = data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
        write_chat_log("assistant", reply_text, route="live", model=model)
        if source == "telegram" and reply_text.strip():
            notify_telegram(reply_text.strip())
        self._json_response({**data, "route": "live", "live": live_result, "chat_history_used": True})
        return True, None

    # --- live chat_only with self context ---
    if live_result.get("action") == "chat_only" and requested_route == "live":
        model = resolve_model(requested_model=requested_model, route="live")
        self_context = build_self_context_prompt(persona=None, max_tools=20)
        messages.insert(1, {
            "role": "system",
            "content": "JARVIS self-context. Use this to understand who you are and what you can do.\n\n" + self_context,
        })
        data = call_ollama_once(model=model, messages=messages, route="live", persona=None, tools=None, stream=False)
        reply_text = data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
        write_chat_log("assistant", reply_text, route="live", model=model)
        if source == "telegram" and reply_text.strip():
            notify_telegram(reply_text.strip())
        self._json_response({**data, "route": "live", "live": live_result})
        return True, None

    # --- not handled: determine route override for full pipeline ---
    route_override = None
    if live_action == "chat_only":
        route_override = "live"
    elif live_action == "direct_tool":
        route_override = "tools"
    elif live_action == "planner":
        route_override = "reason"
    elif live_action == "code":
        route_override = "code"
    elif live_action == "deep_agent":
        route_override = "deep"

    # Store live_result on body so full pipeline can use it
    body["_live_result"] = live_result
    body["_live_intent"] = live_intent
    body["_user_text"]   = user_text  # updated with transcript if any

    return False, route_override


def handle_full_pipeline(
    self,
    body: dict,
    user_text: str,
    requested_model: str | None,
    requested_route: str | None,
    source: str,
    messages: list,
    stream: bool,
) -> None:
    """
    Full pipeline: workflow, memory, tool selection, code route, agent, react chat.

    When an approved coding plan is submitted:
      1. Try to queue tasks to plan_runner via Redis.
      2. If Redis unavailable, fall back to inline agent_loop.
    """
    live_result = body.get("_live_result", {})
    live_intent = body.get("_live_intent", "")

    # --- code request detection ---
    normalized_user = user_text.strip().lower()

    is_code_request = (
        any(ext in normalized_user for ext in [
            ".py", ".js", ".ts", ".tsx", ".jsx", ".sql", ".yaml", ".json", ".html",
        ])
        and any(verb in normalized_user for verb in [
            "fix", "edit", "patch", "refactor", "change", "update", "modify",
        ])
    )

    if live_result.get("action") == "code" or live_result.get("route") == "code":
        requested_route = "code"

    if is_code_request:
        requested_route = "code"

    # --- fuzzy skill match (skip for code, EXCEPT an explicit skill_builder match)
    # A "create/build a skill" request isn't a file-edit task — letting an
    # upstream is_code_request/route=="code" classification swallow it sends it
    # into the generic HTML/CSS-oriented code-planning template instead of
    # skill_builder's own autobuild pipeline. That's exactly what happened to
    # PLAN-20260712-002 (the user asked to use "skill creation skill", but
    # "modify" + a coding-flavored request forced route="code" first, so this
    # fuzzy match never even ran). Still require the same >=0.88 confidence
    # gate below — this only ever overrides "code" for skill_builder specifically.
    if requested_route == "code":
        direct_skill_match = resolve_skill_command(user_text)
        if not (direct_skill_match and direct_skill_match.get("tool_name") == "skill_builder"):
            direct_skill_match = None
    else:
        direct_skill_match = resolve_skill_command(user_text)
        if direct_skill_match and direct_skill_match.get("score", 0) >= 0.88:
            live_result.update({
                "action":               "direct_tool",
                "route":                "tools",
                "tool":                 direct_skill_match["tool_name"],
                "chat_confidence":      0.0,
                "escalation_confidence": 1.0,
                "execute_confidence":   1.0,
                "args":                 live_result.get("args") or {},
            })
            requested_route = "tools"

    if direct_skill_match:
        requested_route = "tools"

    # --- workflow ---
    workflow_state = load_workflow_state()
    if workflow_state:
        reply = continue_markdown_workflow(user_text, workflow_state)
        self._json_response({
            "model":      "workflow",
            "created_at": now_iso(),
            "message":    {"role": "assistant", "content": reply},
            "done":       True,
        })
        return

    md_skill = match_markdown_skill(user_text)
    if md_skill:
        body["markdown_skill"] = md_skill
        requested_route = md_skill.get("route", requested_route or "reason")

        if md_skill.get("type") == "interview_workflow":
            state = {
                "skill":      md_skill.get("name"),
                "skill_path": md_skill.get("path"),
                "phase":      "interview",
                "answers":    {},
            }
            save_workflow_state(state)
            question = get_next_workflow_question(state)
            self._json_response({
                "model":      "workflow",
                "created_at": now_iso(),
                "message":    {"role": "assistant", "content": question or "Workflow started."},
                "done":       True,
            })
            return

    # --- memory context (already injected by handle_live_router; skip if present) ---
    plan_command, plan_command_id = parse_plan_command(user_text)
    lower_user = user_text.strip().lower()

    active_task_followups = {
        "proceed", "continue", "save it", "write it", "create it",
        "do it", "yes", "yes proceed", "show directory", "save it and show directory",
    }
    direct_command_prefixes = (
        "list skills", "show skills", "what skills", "reload skills",
        "play ", "stop radio", "timer ", "set timer", "health",
    )

    is_active_followup = normalized_user in active_task_followups
    # Memory context already injected from memory_router result — skip re-fetch
    skip_memory = True

    planner_user_text = user_text
    # If memory_router found relevant context, prepend it to planner_user_text
    existing_memory_ctx = live_result.get("memory_context", "")
    if existing_memory_ctx and existing_memory_ctx.strip():
        planner_user_text = (
            f"USER COMMAND:\n{user_text}\n\n"
            f"OPTIONAL MEMORY HINTS:\n{existing_memory_ctx[:2500]}\n\n"
            "Instruction: obey USER COMMAND. Use memory only as supporting context."
        )

    # --- telegram plan commands ---
    if source == "telegram" and plan_command in {"proceed", "continue", "next", "run", "modify", "cancel", "accept"}:
        requested_route = "code"
        requested_model = None

    if requested_route not in VALID_ROUTES:
        requested_route = detect_route(user_text, source)

    # --- plan commands ---
    selected_tools: List[Dict[str, Any]] = []
    plan_decision = None

    if plan_command in {"proceed", "continue", "next", "run", "yes", "accept"}:
        plan_decision = {"action": "code", "route": "code", "chat_confidence": 0.0, "execution_confidence": 1.0, "continue_plan": True, "plan_action": "continue"}
        requested_route = "code"
        requested_model = None
    elif plan_command == "modify":
        plan_decision = {"action": "planner", "route": "reason", "chat_confidence": 1.0, "execution_confidence": 0.0, "continue_plan": True, "plan_action": "modify"}
        requested_route = "code"
        requested_model = None
    elif plan_command == "cancel":
        plan_decision = {"action": "code", "route": "code", "chat_confidence": 0.0, "execution_confidence": 1.0, "continue_plan": True, "plan_action": "cancel"}
        requested_route = "code"
        requested_model = None

    if direct_skill_match:
        selected_tools = [direct_skill_match["tool"]]
    elif plan_command in {"proceed", "continue", "next", "run", "modify", "cancel"}:
        selected_tools = []
    elif should_select_tools(user_text, requested_route, requested_model):
        selected_tools = choose_tools(user_text, requested_route=requested_route, requested_model=requested_model)

    emit_event("router", "Fuzzy skill command match", {
        "matched":   bool(direct_skill_match),
        "tool":      direct_skill_match.get("tool_name") if direct_skill_match else None,
        "score":     direct_skill_match.get("score") if direct_skill_match else None,
        "user_text": user_text[:200],
    })

    resolved_route = normalized_route(requested_route, selected_tools)

    # Don't let is_code_request re-force "code" over a confirmed skill_builder
    # match (see the fuzzy-skill-match block above) — otherwise this line
    # silently undoes that override and the bug it fixes recurs.
    _skill_builder_matched = bool(direct_skill_match) and direct_skill_match.get("tool_name") == "skill_builder"
    if (is_code_request or (plan_decision and plan_decision.get("execution_confidence", 0) >= 0.85)) \
            and not _skill_builder_matched:
        resolved_route = "code"

    if resolved_route == "code":
        requested_model = None
        model = resolve_model(requested_model=None, route="code")
        selected_tools = [TOOLS_BY_NAME["code_edit"]] if "code_edit" in TOOLS_BY_NAME else []
    else:
        model = resolve_model(requested_model=requested_model, route=resolved_route)

    route = resolved_route

    # Update Redis state for this request
    _safe_update_state(task=f"{route}:{live_intent or 'chat'}", confidence="high")

    if log_chat_event:
        try:
            log_chat_event(role="user", content=user_text, route=route, model=model)
        except Exception as e:
            print(f"[CHAT_LOG] user log failed: {e}")

    # --- agent continue ---
    if user_text.lower().startswith("agent: continue"):
        task = get_active_task(TASK_GRAPH_PATH)
        if task:
            user_text = (
                f"Continue this task.\n\nOriginal request:\n{task.get('user_request')}\n\n"
                f"Steps:\n{json.dumps(task.get('steps', []), indent=2)}\n\n"
                f"Recent events:\n{json.dumps(task.get('events', [])[-10:], indent=2)}"
            )
            body["task_id"] = task.get("id")

    agent_requested = route == "deep" or user_text.lower().startswith(("agent:", "do task:"))

    if agent_requested:
        _safe_update_state(task="deep_agent", confidence="high")
        result = run_agent_loop(
            user_message=planner_user_text,
            route=route,
            model=model,
            tools_by_name=TOOLS_BY_NAME,
            tool_map=TOOL_MAP,
            call_ollama_once=call_ollama_once,
            execute_tool=execute_tool,
            emit_event=emit_event,
            truncate_text=truncate_text,
            strip_thinking_tags=strip_thinking_tags,
            now_iso=now_iso,
            task_graph_path=TASK_GRAPH_PATH,
            task_id=body.get("task_id"),
            max_steps=8,
        )
        result_kind = classify_agent_output_kind("agent", user_text, result if isinstance(result, dict) else {})
        if result_kind == "report":
            _plan_id = (result.get("plan_id") if isinstance(result, dict) else None) or "agent_" + str(uuid.uuid4())[:8]
            report_path = write_analysis_report(
                skill_name="agent",
                plan_id=_plan_id,
                result={"markdown": result.get("answer", "") if isinstance(result, dict) else "", **({} if not isinstance(result, dict) else result)},
            )
            emit_event("artifact", "Analysis report written", {"plan_id": _plan_id, "path": str(report_path)})
            self._json_response({
                "model": model, "created_at": now_iso(),
                "message": {"role": "assistant", "content": result.get("answer", "") if isinstance(result, dict) else ""},
                "done": True, "route": route, "format": "report", "report_path": str(report_path),
            })
        else:
            answer = result.get("answer", "") if isinstance(result, dict) else ""
            write_chat_log("assistant", answer, route=route, model=model)
            _safe_push_memory(f"assistant: {answer[:300]}")
            self._json_response({
                "model": model, "created_at": now_iso(),
                "message": {"role": "assistant", "content": answer},
                "done": True, "route": route, "format": "agent",
                "task_id": result.get("task_id") if isinstance(result, dict) else None,
                "agent": {
                    "trace":        result.get("trace", []) if isinstance(result, dict) else [],
                    "observations": result.get("observations", []) if isinstance(result, dict) else [],
                },
            })
        return

    # --- code route ---
    # Route-based, not is_coder_model(model): the code route already forced
    # the configured code model above, and that model no longer has "coder"
    # in its name (qwen3.6:27b). is_coder_model stays name-based elsewhere —
    # it marks models that can't take native Ollama tools (qwen3-coder line).
    if resolved_route == "code":
        coder_tool = get_coder_tool()
        if coder_tool:
            selected_tools = [coder_tool]

        tool_names = [t["function"]["name"] for t in selected_tools if isinstance(t, dict) and isinstance(t.get("function"), dict)]
        runtime_mode = write_runtime_mode(resolved_route, model, selected_tools)
        persona = runtime_mode.get("persona")

        try:
            sync_kokoro_for_route(resolved_route, model)
        except Exception as e:
            emit_event("warning", "Kokoro sync failed", {"route": resolved_route, "model": model, "error": str(e)})

        emit_event("status", "Incoming coder skill request", {
            "resolved_route": resolved_route, "resolved_model": model,
            "tools": tool_names, "user_preview": user_text[:140],
        })

        if not selected_tools:
            self._json_response({
                "model": model, "created_at": now_iso(),
                "message": {"role": "assistant", "content": f"Code route selected but no coder skill loaded. Found: {tool_names}"},
                "done": True,
            })
            return

        ack = random.choice(ACKS)
        write_bridge_status("thinking", ack)
        speak_ack(ack)

        tool_name = selected_tools[0]["function"]["name"]
        paths = body.get("paths")
        if not isinstance(paths, list) or not paths:
            paths = guess_coding_paths(user_text)

        command, requested_plan_id = parse_plan_command(user_text)
        active_plan = load_plan_by_id(requested_plan_id) if requested_plan_id else load_active_plan()
        if requested_plan_id and active_plan:
            save_active_plan(active_plan)

        emit_event("code_phase", "Guessed coding paths", {"paths": paths})

        if command == "cancel":
            if not requested_plan_id:
                self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": "Cancel failed: missing plan id."}, "done": True})
                return
            plan = load_plan_by_id(requested_plan_id)
            if not plan:
                self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Plan not found: {requested_plan_id}"}, "done": True})
                return
            plan["status"] = "cancelled"
            plan["cancelled_at"] = now_iso()
            save_json(requested_plan_id, "status.json", plan)
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Cancelled plan {requested_plan_id}."}, "done": True})
            return

        if command == "modify" or user_text.strip().lower().startswith("modify this plan:"):
            active_plan = build_simple_code_plan(planner_user_text, paths)
            save_json(active_plan["plan_id"], "plan.json", active_plan)
            save_active_plan(active_plan)
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": render_plan(active_plan)}, "done": True})
            return

        if command not in {"proceed", "continue", "next", "run", "yes", "accept"}:
            active_plan = build_simple_code_plan(planner_user_text, paths)
            plan_files = active_plan.get("files") or []
            has_plan_file = any("." in str(p).split("/")[-1] for p in plan_files)

            if needs_output_path(user_text, paths) and not has_plan_file:
                plan_id = active_plan["plan_id"]
                active_plan["state"] = "waiting_input"
                active_plan["waiting_for"] = "output_path"
                save_active_plan(active_plan)
                self._json_response({
                    "model": model, "created_at": now_iso(),
                    "message": {"role": "assistant", "content": f"PLAN_ID: {plan_id}\n\nWhere should I save the generated file?\n\nExamples:\n- love.html\n- app/page.tsx\n- scripts/test.py"},
                    "done": True, "route": "code",
                })
                return

            emit_event("code_phase", "Plan created", {"phase": "plan_created", "plan_id": active_plan.get("plan_id"), "steps": active_plan.get("steps", [])})
            save_active_plan(active_plan)
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": render_plan(active_plan)}, "done": True})
            return

        if not active_plan:
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": "No active coding plan found. Send the coding request first."}, "done": True})
            return

        current_step = int(active_plan.get("current_step", 0))
        steps = active_plan.get("steps", [])

        if current_step >= len(steps):
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": "Coding plan is already complete."}, "done": True})
            return

        step = steps[current_step]

        emit_event("code_phase", f"Running step {step.get('id')}: {step.get('goal')}", {
            "phase": "running_step", "plan_id": active_plan.get("plan_id"), "step": step, "paths": paths,
        })

        # ── Try plan_runner (Redis) first; fall back to inline agent_loop ──
        plan_id_str = active_plan.get("plan_id", "")
        queued_to_runner = queue_plan_to_redis(active_plan)

        if queued_to_runner:
            emit_event("plan_runner", "Plan queued to Redis plan_runner", {
                "plan_id":    plan_id_str,
                "step_count": len(steps),
            })
            # Return immediately — plan_runner handles execution asynchronously.
            # Client can poll /api/plan-status/<plan_id> or listen to Telegram.
            self._json_response({
                "model":      model,
                "created_at": now_iso(),
                "message":    {
                    "role":    "assistant",
                    "content": (
                        f"Plan {plan_id_str} queued to plan_runner ({len(steps)} steps).\n"
                        "Execution is running in the background.\n"
                        f"You'll be notified on Telegram when it completes."
                    ),
                },
                "done":     True,
                "route":    "code",
                "format":   "plan_runner",
                "plan_id":  plan_id_str,
            })
            return

        # ── Fallback: inline agent_loop (Redis unavailable) ───────────────
        emit_event("plan_runner", "Redis unavailable — running inline agent_loop", {
            "plan_id": plan_id_str,
        })

        result = run_agent_loop(
            user_message=(
                "Execute this approved plan only.\n\n"
                f"Plan:\n{json.dumps(active_plan, indent=2)}\n\n"
                "Rules:\n- Follow the plan step by step.\n- Use code_edit only for file changes.\n- Stop when the plan is complete.\n"
            ),
            route="code", model=model,
            tools_by_name=TOOLS_BY_NAME,
            tool_map=TOOL_MAP,
            call_ollama_once=call_ollama_once, execute_tool=execute_tool,
            emit_event=emit_event, truncate_text=truncate_text,
            strip_thinking_tags=strip_thinking_tags, now_iso=now_iso,
            task_graph_path=TASK_GRAPH_PATH, task_id=active_plan.get("plan_id"),
            max_steps=len(active_plan.get("steps", [])) + 2,
        )

        result_dict = result if isinstance(result, dict) else {}
        result_kind = classify_agent_output_kind(tool_name, user_text, result_dict)
        content = extract_last_patch_from_anything(result)
        content = normalize_patch_text(content)

        if result_kind == "report":
            _plan_id = active_plan.get("plan_id") or "report_" + str(uuid.uuid4())[:8]
            markdown = result_dict.get("markdown") or result_dict.get("answer") or content
            report_path = write_analysis_report(skill_name=tool_name, plan_id=_plan_id, result={"markdown": markdown})
            emit_event("artifact", "Analysis report written", {"plan_id": _plan_id, "path": str(report_path)})
            self._json_response({
                "model": model, "created_at": now_iso(),
                "message": {"role": "assistant", "content": markdown},
                "done": True, "route": resolved_route, "format": "report", "report_path": str(report_path),
            })
            return

        if "--- FILE:" not in content or "@@" not in content:
            content = f"Coder returned analysis instead of a patch.\n\nThis output was rejected.\n\nPreview:\n{content[:1500]}"

        patch_file = f"patches/step_{step.get('id')}.patch"
        (plan_dir(active_plan["plan_id"]) / patch_file).write_text(content, encoding="utf-8")

        patch_part = content.split("### PATCH", 1)[1].strip() if "### PATCH" in content else content
        validation = validate_coder_output(patch_part)

        if not validation["ok"]:
            retry_args = {
                "task": (
                    active_plan.get("user_request", user_text)
                    + "\n\nYour previous answer was rejected.\nProblems:\n"
                    + "\n".join(f"- {p}" for p in validation.get("problems", []))
                    + "\n\nReturn ONLY:\n--- FILE: path/to/file.py\n@@\n<minimal patch>\n"
                ),
                "path":  paths[0] if paths else str(PROJECT_ROOT),
                "model": model, "mode": "patch",
            }
            retry_result = execute_tool(tool_name, retry_args)
            retry_content = normalize_patch_text(extract_tool_content(retry_result))
            retry_validation = validate_coder_output(retry_content)
            if retry_validation["ok"]:
                content = retry_content
                validation = retry_validation
            else:
                content = wrap_invalid_coder_output(retry_content, retry_validation)
                validation = retry_validation

        emit_event("final", "Coder skill response ready", {"route": resolved_route, "model": model, "validated": validation["ok"]})

        if validation["ok"]:
            apply_result = apply_file_patch(content)
            if apply_result.get("ok"):
                step["status"] = "done"
                step["summary"] = summarize_step_result(content)
                active_plan["current_step"] = current_step + 1
                save_active_plan(active_plan)
                save_json(active_plan["plan_id"], "status.json", active_plan)
                emit_event("code_step_ready", f"Step {step.get('id')} complete.", {
                    "plan_id":      active_plan.get("plan_id"), "step": step,
                    "current_step": active_plan["current_step"],
                    "remaining":    len(steps) - active_plan["current_step"],
                    "next_step":    steps[active_plan["current_step"]] if active_plan["current_step"] < len(steps) else None,
                })
            else:
                content = content + "\n\nAPPLY FAILED:\n" + json.dumps(apply_result, indent=2)

        self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": content}, "done": True, "validation": validation})
        return

    # --- normal non-code route ---
    tool_names = [t["function"]["name"] for t in selected_tools]
    runtime_mode = write_runtime_mode(resolved_route, model, selected_tools)
    persona = runtime_mode.get("persona")

    try:
        sync_kokoro_for_route(resolved_route, model)
    except Exception as e:
        emit_event("warning", "Kokoro sync failed", {"route": resolved_route, "model": model, "error": str(e)})

    emit_event("status", "Incoming chat request", {
        "resolved_route": resolved_route, "resolved_model": model,
        "stream": stream, "tool_count": len(selected_tools),
        "tools": tool_names, "user_preview": user_text[:140],
    })

    if stream:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        stream_direct_chat(self, model, messages, selected_tools=selected_tools, route=resolved_route, persona=persona)
        return

    if is_simple_direct_chat(user_text, selected_tools, resolved_route):
        try:
            data = call_ollama_once(model=model, messages=messages, route=resolved_route, persona=persona, tools=None, stream=False)
            reply_text = data.get("message", {}).get("content", "") if isinstance(data, dict) else ""
            write_chat_log("assistant", reply_text, route=resolved_route, model=model)
            _safe_push_memory(f"assistant: {reply_text[:300]}")
            self._json_response(data)
        except Exception as e:
            self._json_response({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Error: {e}"}, "done": True})
        return

    if selected_tools:
        ack = random.choice(ACKS)
        write_bridge_status("thinking", ack)
        speak_ack(ack)
        result = react_chat(model, messages, selected_tools, route=resolved_route, persona=persona)
        reply_text = result.get("message", {}).get("content", "") if isinstance(result, dict) else ""
        _safe_push_memory(f"assistant: {reply_text[:300]}")
        self._json_response(result)
        return


# -----------------------------------------------------------------------------
# Local chat call (react_server loopback)
# -----------------------------------------------------------------------------
def call_local_chat(payload: dict) -> dict:
    """Call react_server /api/chat locally — used by WebSocket handler."""
    REACT_SERVER = os.environ.get("JARVIS_REACT_SERVER", "http://127.0.0.1:7900")

    req = urllib.request.Request(
        f"{REACT_SERVER}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        emit_event("warning", "call_local_chat failed", {"error": str(e)})
        return {"message": {"role": "assistant", "content": f"Error: {e}"}, "done": True}

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
def normalize_patch_text(content: str) -> str:
    text = content or ""

    # Remove markdown fence leftovers
    text = text.replace("```html", "").replace("```python", "").replace("```", "").strip()

    # If model forgot @@, insert it after FILE line
    if "--- FILE:" in text and "@@" not in text:
        lines = text.splitlines()
        out = []
        inserted = False

        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.strip().startswith("--- FILE:"):
                out.append("@@")
                inserted = True

        text = "\n".join(out)

    return text
def complete_tool_args_with_meta(
    tool_name: str,
    user_text: str,
    parsed: dict,
) -> dict:
    if not tool_name or tool_name not in TOOLS_BY_NAME:
        return parsed

    tool_schema = TOOLS_BY_NAME.get(tool_name, {})
    tool_meta = TOOL_SKILL_META.get(tool_name, {})

    prompt = f"""
You fill missing tool arguments.

Return ONLY valid JSON:
{{
  "tool": "{tool_name}",
  "args": {{}}
}}

User message:
{user_text}

Router result:
{json.dumps(parsed, ensure_ascii=False)}

Tool schema:
{json.dumps(tool_schema, ensure_ascii=False)}

Tool metadata:
{json.dumps(tool_meta, ensure_ascii=False)}

Rules:
- Return only argument keys that exist in Tool schema properties.
- Remove any existing args that are not valid for this tool.
- Fill required missing args from user message, intent, schema, and metadata.
- Do not invent unrelated values.
- If a required value is impossible to infer, leave it missing.
- Return JSON only.
""".strip()

    payload = {
        "model": resolve_model(requested_model=None, route="live"),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.2,
            "num_ctx": 2048,
        },
    }

    try:
        with request_ollama_chat(payload, timeout=CHAT_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw = data.get("message", {}).get("content", "")
        filled = parse_json_object_from_text(raw)

        if not isinstance(filled, dict):
            return parsed

        filled_args = filled.get("args")
        if not isinstance(filled_args, dict):
            return parsed

        valid_props = (
            tool_schema
            .get("function", {})
            .get("parameters", {})
            .get("properties", {})
        )

        valid_arg_names = set(valid_props.keys())

        merged_args = {
            **(parsed.get("args") or {}),
            **filled_args,
        }

        parsed["args"] = {
            k: v
            for k, v in merged_args.items()
            if k in valid_arg_names
        }

        return parsed

    except Exception as e:
        emit_event(
            "warning",
            "Tool arg completion failed",
            {
                "tool":  tool_name,
                "error": str(e),
            },
        )
        return parsed
def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))

    if length <= 0:
        return {}

    try:
        raw = handler.rfile.read(length).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return {}
    
def reload_all_skills() -> Dict[str, Any]:
    global TOOLS, TOOL_MAP, TOOL_KEYWORDS, TOOL_SKILL_META
    global TOOLS_BY_NAME, TOOL_LIST_TEXT
    global INTENT_TOOL_CANDIDATES, TOOL_HINTS, TOOL_DIRECT_MATCH, TOOL_ROUTE_HINTS

    load_skills()
    TOOLS = get_all_tools()
    TOOL_MAP = get_all_tool_map()
    TOOL_KEYWORDS = get_all_keywords()
    TOOL_SKILL_META = get_all_skill_meta()
    TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}
    TOOL_LIST_TEXT = "\n".join(f"- {t['function']['name']}: {t['function'].get('description', '')}" for t in TOOLS)
    INTENT_TOOL_CANDIDATES = build_intent_tool_candidates(TOOL_SKILL_META)
    TOOL_HINTS = build_tool_hints(TOOL_SKILL_META)
    TOOL_DIRECT_MATCH = build_tool_direct_match(TOOL_SKILL_META)
    TOOL_ROUTE_HINTS = build_tool_route_hints(TOOL_SKILL_META)

    # Refresh tool health in Redis
    try:
        if _redis_available():
            write_tools({name: True for name in TOOL_MAP.keys()})
    except Exception:
        pass

    return {"status": "ok", "tool_count": len(TOOLS), "tools": list(TOOL_MAP.keys())}


print(f"[REACT] Loading skills from {PROJECT_ROOT / 'skills'}...")
reload_all_skills()
def match_markdown_skill(user_text: str) -> Optional[Dict[str, Any]]:
    text = (user_text or "").lower()

    for skill in load_markdown_skills():
        haystack = (
            str(skill.get("name", "")) + "\n" +
            str(skill.get("description", ""))
        ).lower()

        if "list" in text and "skill" in text:
            continue

        trigger_words = [
            "new app",
            "start a project",
            "build me an app",
            "set up a new service",
            "create a new project",
            "scaffold",
        ]

        if any(t in text for t in trigger_words):
            if "scaffold" in haystack or "project" in haystack:
                return skill

    return None
# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def read_last_chat_log_chars(max_chars: int = 4000) -> str:
    path = today_log_path()

    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return text[-max_chars:]

def load_prompt_file(path: Path, fallback: str = "") -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        return text or fallback
    except Exception:
        return fallback


def get_tool_names_text() -> str:
    try:
        return ", ".join(sorted(TOOLS_BY_NAME.keys()))
    except Exception:
        return ""
    
def build_compact_tool_catalog(limit: int = 10) -> str:
    preferred = get_top_used_tools(limit)

    core = [
        "radio",
        "weather",
        "news",
        "timer",
        "chat_log",
        "memory",
        "flux",
        "list_skills",
    ]

    names: list[str] = []

    for name in core + preferred:
        if name in TOOLS_BY_NAME and name not in names:
            names.append(name)

    lines = []

    for name in names[:limit]:
        fn = TOOLS_BY_NAME[name].get("function", {})
        desc = (fn.get("description") or "").split(".")[0]
        props = fn.get("parameters", {}).get("properties", {})
        args = ", ".join(props.keys()) or "none"

        lines.append(f"- {name}({args}): {desc}")

    return "\n".join(lines)

def build_short_term_context() -> str:
    try:
        from scripts.chat_context import read_recent_chat
    except Exception:
        try:
            from chat_context import read_recent_chat
        except Exception:
            return ""

    try:
        rows = read_recent_chat(
            minutes=30,
            max_items=12,
        )
    except Exception as e:
        print(f"[CHAT_CONTEXT] read failed: {e}")
        return ""

    if not rows:
        return ""

    lines = []

    for item in rows:
        role = str(item.get("role", "unknown")).upper()
        route = item.get("route") or "-"
        content = str(item.get("content", "")).strip()

        if not content:
            continue

        content = content.replace("\n", " ")

        if len(content) > 400:
            content = content[:400] + "..."

        lines.append(
            f"- {role}[{route}]: {content}"
        )

    if not lines:
        return ""

    return (
        "[ACTIVE CHAT CONTEXT]\n"
        "# Recent Chat Context\n\n"
        + "\n".join(lines)
        + "\n[/ACTIVE CHAT CONTEXT]"
    )

def load_named_prompt(path: Path, fallback: str = "") -> str:
    prompt = load_prompt_file(path, fallback=fallback)

    parts = [prompt]

    last_exchange = build_last_exchange_context()
    if last_exchange:
        parts.append(last_exchange)

    short_context = build_short_term_context()
    if short_context:
        parts.append(short_context)

    out = "\n\n".join(p for p in parts if p and p.strip())
    return out.replace("{{TOOL_CATALOG}}", build_compact_tool_catalog(limit=10)) 

def parse_workflow_questions(md_skill: Dict[str, Any]) -> List[Dict[str, str]]:
    content = md_skill.get("content", "")

    questions = []

    current_category = "general"

    for raw in content.splitlines():
        line = raw.strip()

        if line.startswith("# CATEGORY:"):
            current_category = line.split(":", 1)[1].strip()
            continue

        if line.startswith("Q:"):
            qid = line.split(":", 1)[1].strip()

            questions.append({
                "id": qid,
                "category": current_category,
                "prompt": "",
            })

            continue

        if line.startswith("Prompt:") and questions:
            questions[-1]["prompt"] = line.split(":", 1)[1].strip()

    return questions
def get_next_workflow_question(state: Dict[str, Any]) -> Optional[str]:
    md_skill = load_markdown_skill_by_name(state["skill"])

    questions = parse_workflow_questions(md_skill)

    answers = state.setdefault("answers", {})

    for q in questions:
        if q["id"] not in answers:
            state["last_question"] = q["id"]
            save_workflow_state(state)
            return q["prompt"]

    return None
def continue_markdown_workflow(user_text: str, state: Dict[str, Any]) -> str:
    answers = state.setdefault("answers", {})
    category = int(state.get("category", 1))

    last_question = state.get("last_question")

    if last_question:
        answers[last_question] = user_text.strip()

    if category == 1:
        questions = [
            "project_name",
            "project_description",
            "target_users",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "project_name": "What is the project name?",
                    "project_description": "Describe the project in 1-3 sentences.",
                    "target_users": "Who are the target users?",
                }

                return prompts[q]

        state["category"] = 2

    if state["category"] == 2:
        questions = [
            "frontend",
            "backend",
            "database",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "frontend": "Frontend stack? (Next.js, React, Vue, etc.)",
                    "backend": "Backend stack?",
                    "database": "Database?",
                }

                return prompts[q]

        state["category"] = 3

    if state["category"] == 3:
        questions = [
            "authentication",
            "payments",
            "deployment",
        ]

        for q in questions:
            if q not in answers:
                state["last_question"] = q
                save_workflow_state(state)

                prompts = {
                    "authentication": "Need authentication/login?",
                    "payments": "Need payment support?",
                    "deployment": "Where will this run? (local/cloud/docker/etc.)",
                }

                return prompts[q]

    state["phase"] = "complete"
    save_workflow_state(state)

    summary = json.dumps(answers, indent=2, ensure_ascii=False)

    return (
        "Interview complete.\n\n"
        "Project summary:\n\n"
        f"{summary}\n\n"
        "Reply with:\n"
        "- proceed\n"
        "- modify\n"
        "- cancel"
    )
def load_workflow_state() -> Dict[str, Any]:
    if not WORKFLOW_STATE_PATH.exists():
        return {}
    try:
        return json.loads(WORKFLOW_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_workflow_state(state: Dict[str, Any]) -> None:
    WORKFLOW_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKFLOW_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def clear_workflow_state() -> None:
    if WORKFLOW_STATE_PATH.exists():
        WORKFLOW_STATE_PATH.unlink()

def request_llama_cpp_chat(payload: Dict[str, Any], timeout: int):
    llama_payload = {
        "model": payload.get("model", "gemma4"),
        "messages": payload.get("messages", []),
        "stream": payload.get("stream", False),
        "temperature": payload.get("options", {}).get("temperature", 0.2),
        "top_p": payload.get("options", {}).get("top_p", 0.8),
    }

    req = urllib.request.Request(
        f"{LLAMA_CPP_HOST}/v1/chat/completions",
        data=json.dumps(llama_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)

def request_chat_backend(payload: Dict[str, Any], timeout: int, route: str = "fast"):
    if route in LLAMA_CPP_ROUTES:
        try:
            return request_llama_cpp_chat(payload, timeout)
        except (urllib.error.URLError, OSError) as e:
            # llama.cpp down → fall back to Ollama (model guard bumps small
            # gemma to the Ollama minimum; with the Claude proxy on :11434
            # this lands on the cloud automatically).
            print(f"[REACT] llama.cpp unavailable ({e}), falling back to Ollama")
    return request_ollama_chat(payload, timeout)

def normalize_chat_response(data: Dict[str, Any]) -> Dict[str, Any]:
    if "message" in data:
        return data

    choices = data.get("choices") or []
    if choices:
        msg = choices[0].get("message") or {}
        return {
            "message": {
                "role": msg.get("role", "assistant"),
                "content": msg.get("content", ""),
            },
            "raw": data,
        }

    return {
        "message": {
            "role": "assistant",
            "content": "",
        },
        "raw": data,
    }

def load_markdown_skills() -> list[dict]:
    root = VAULT_DIR / ".jarvis" / "markdown_skills"
    skills = []

    for path in root.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")

        meta = {}
        body = text

        if text.startswith("---"):
            _, frontmatter, body = text.split("---", 2)
            for line in frontmatter.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()

        skills.append({
            "path": str(path),
            "name": meta.get("name", path.stem),
            "description": meta.get("description", ""),
            "content": body.strip(),
        })

    return skills

def needs_output_path(task: str, paths: list[str]) -> bool:
    lower = (task or "").lower()

    create_keywords = [
        "create",
        "make",
        "generate",
        "write",
        "save",
        "build",
        "code",
    ]

    wants_file = any(k in lower for k in create_keywords)

    has_real_file = any(
        "." in p.split("/")[-1]
        for p in paths
    )

    return wants_file and not has_real_file

def clean_telegram_prefix(text: str) -> str:
    text = text or ""
    prefix = "Telegram message:"
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text

def split_telegram_text(text: str, limit: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    text = str(text or "").strip()

    if not text:
        return []

    chunks = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut < 1000:
            cut = text.rfind(" ", 0, limit)

        if cut < 1000:
            cut = limit

        chunks.append(text[:cut].strip())
        text = text[cut:].strip()

    if text:
        chunks.append(text)

    return chunks


def notify_telegram(text: str) -> None:
    if not TELEGRAM_NOTIFY_CHAT_ID:
        debug("Telegram notify skipped: missing JARVIS_TELEGRAM_CHAT_ID")
        return

    try:
        clean_text = clean_tool_result_for_telegram(text)

        for i, chunk in enumerate(split_telegram_text(clean_text), start=1):
            if i > 1:
                chunk = f"(continued {i})\n\n{chunk}"

            TELEGRAM_GATEWAY.send_message(
                TELEGRAM_NOTIFY_CHAT_ID,
                chunk,
            )

    except Exception as e:
        debug(f"Telegram notify failed: {e}")

def parse_file_patch(content: str) -> Optional[Dict[str, str]]:
    text = content or ""

    if "### PATCH" in text:
        text = text.split("### PATCH", 1)[1].strip()

    text = text.replace("\\n", "\n")

    try:
        data = json.loads(text.strip().strip("`"))
        if isinstance(data, dict) and isinstance(data.get("path"), str) and isinstance(data.get("content"), str):
            return {"path": data["path"], "content": data["content"]}
    except Exception:
        pass

    marker = "--- FILE:"
    if marker not in text:
        return None

    after = text.split(marker, 1)[1].strip()
    first_line, _, rest = after.partition("\n")
    if "@@" in rest:
        rest = rest.split("@@", 1)[1].strip()
    else:
        rest = rest.strip()
    path = first_line.strip()
    path = path.split("@@", 1)[0].strip()
    path = path.split(" ", 1)[0].strip()

    if "@@" in rest:
        rest = rest.split("@@", 1)[1].strip()

    cleaned_lines = []
    for line in rest.splitlines():
        if line.startswith("@@"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            cleaned_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            cleaned_lines.append(line)

    rest = "\n".join(cleaned_lines).strip()

    if not path or not rest:
        return None

    if "\n" in path or "\\n" in path or "@@" in path:
        return None

    return {"path": path, "content": rest}

def apply_file_patch(content: str) -> Dict[str, Any]:
    patch = parse_file_patch(content)
    if not patch:
        return {"ok": False, "error": "No writable file patch found"}

    path = Path(patch["path"])
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    path = path.resolve()

    if not str(path).startswith(str(PROJECT_ROOT.resolve())):
        return {"ok": False, "error": f"Refusing to write outside project root: {path}"}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(patch["content"], encoding="utf-8")

    return {"ok": True, "path": str(path)}

def validate_coder_output(content: str) -> Dict[str, Any]:
    text = content or ""
    lower = text.lower()

    problems = []

    dangerous_patterns = [
        "rm -rf",
        "sudo rm",
        "mkfs",
        "dd if=",
        ":(){",
        "chmod -r 777 /",
        "chown -r",
        "curl ",
        "wget ",
        "powershell -enc",
        "invoke-expression",
        "eval(",
        "exec(",
    ]

    for pattern in dangerous_patterns:
        if pattern in lower:
            problems.append(f"dangerous pattern detected: {pattern}")

    code_fence_count = text.count("```")
    line_count = len(text.splitlines())

    if line_count > 500:
        problems.append("output too large; likely full-file rewrite")

    if code_fence_count >= 6:
        problems.append("too many code blocks; likely not a minimal patch")

    has_patch_marker = (
        "--- FILE:" in text
        or "diff --git" in text
        or "@@" in text
        or "replace this" in lower
        or "modified parts" in lower
    )

    if not has_patch_marker:
        problems.append("no clear patch marker or scoped replacement block found")

    return {
        "ok": len(problems) == 0,
        "problems": problems,
        "line_count": line_count,
        "code_fence_count": code_fence_count,
    }


def wrap_invalid_coder_output(content: str, validation: Dict[str, Any]) -> str:
    problems = "\n".join(f"- {p}" for p in validation.get("problems", []))

    return f"""Coder output was rejected by validation.

Problems:
{problems}

The model must return a smaller, safer patch.

Required format:

--- FILE: path/to/file.py
@@
<only changed function/helper blocks>

Rules:
- Do not rewrite full files
- Do not include dangerous shell commands
- Do not include unrelated changes
- Keep the patch minimal

Original rejected output preview:

{content[:3000]}
"""

def debug(msg: str) -> None:
    if DEBUG:
        print(f"[REACT] {msg}")


def now_iso() -> str:
    return  datetime.now(timezone.utc).isoformat()


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
def character_stage_message(event_type: str, message: str, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    data = data or {}

    plan_id = data.get("plan_id")
    step = data.get("step") or {}
    step_id = step.get("id") if isinstance(step, dict) else data.get("task_id")
    route = data.get("route") or data.get("resolved_route")
    model = data.get("model") or data.get("resolved_model") or data.get("planner_model")
    
    if event_type == "code_edit_output":
        preview = str(data.get("result_preview", ""))[:1500]

        return (
            "💻 Coder produced output.\n\n"
            f"Path: {data.get('path')}\n"
            f"Mode: {data.get('mode')}\n\n"
            f"{preview}"
        )
    if event_type == "agent_start":
        return (
            "🧠 Agent mode started.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}\n\n"
            "I am breaking the task into reasoning steps."
        )

    if event_type == "agent_step":
        step_no = data.get("step") or data.get("step_no") or data.get("iteration")
        return (
            "⚙️ Agent is working.\n"
            f"Step: {step_no or 'unknown'}\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}\n\n"
            f"{message}"
        )

    if event_type == "agent_final":
        return (
            "🏁 Agent completed the task.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}"
        )
    if event_type == "code_phase":
        phase = data.get("phase")

        if phase == "plan_created":
            return (
                "🧠 Planning complete.\n"
                f"Plan: {plan_id}\n"
                f"Steps: {len(data.get('steps', []))}\n\n"
                "I have a structured route now. Waiting for approval."
            )

        if phase == "running_step":
            return (
                "💻 Executing coding step.\n"
                f"Plan: {plan_id}\n"
                f"Step: {step_id}\n\n"
                f"{step.get('goal', message) if isinstance(step, dict) else message}"
            )

        if phase == "validating_patch":
            return (
                "🔎 Patch returned.\n"
                f"Plan: {plan_id}\n\n"
                "I am validating the output before applying it."
            )

        if phase == "repairing_patch":
            return (
                "🛠️ Patch failed validation.\n"
                f"Plan: {plan_id}\n\n"
                "I am asking the coder to repair the patch."
            )

        if phase == "patch_applied":
            return (
                "✅ Patch applied successfully.\n"
                f"Plan: {plan_id}\n\n"
                "Step is complete."
            )

        if phase == "patch_apply_failed":
            return (
                "❌ Patch could not be applied.\n"
                f"Plan: {plan_id}\n\n"
                "I saved the failure details for inspection."
            )

    if event_type == "code_step_ready":
        remaining = data.get("remaining")
        next_step = data.get("next_step")

        text = (
            "✅ Coding step complete.\n"
            f"Plan: {plan_id}\n"
            f"Remaining steps: {remaining}\n"
        )

        if isinstance(next_step, dict):
            text += f"\nNext: {next_step.get('goal')}"

        return text

    if event_type == "plan":
        return (
            "🧭 Selecting tools and route.\n"
            f"Model: {model or 'unknown'}\n"
            f"{message}"
        )

    if event_type == "tool_start":
        return (
            "🔧 Running tool.\n"
            f"Tool: {data.get('tool')}\n"
            f"{message}"
        )

    if event_type == "tool_result":
        return (
            "📦 Tool completed.\n"
            f"Tool: {data.get('tool')}\n"
            f"Elapsed: {data.get('elapsed_sec')}s"
        )

    if event_type == "warning":
        return (
            "⚠️ JARVIS warning.\n"
            f"{message}\n\n"
            f"{str(data.get('error', ''))[:800]}"
        )

    if event_type == "final":
        return (
            "🏁 Final response ready.\n"
            f"Route: {route or 'unknown'}\n"
            f"Model: {model or 'unknown'}"
        )

    return None
def contains_patch(text: str) -> bool:
    text = text or ""
    return (
        "--- FILE:" in text
        or "diff --git" in text
        or "@@" in text
        or "### PATCH" in text
    )


def looks_like_markdown_report(text: str) -> bool:
    text = (text or "").strip()

    if not text:
        return False

    if contains_patch(text):
        return False

    return (
        text.startswith("#")
        or "\n## " in text
        or "- " in text
        or len(text) > 800
    )

def classify_agent_output_kind(skill_name, user_text, result=None):
    result = result or {}
    name = (skill_name or "").lower().strip()
    text = (user_text or "").lower().strip()

    result_kind = result.get("kind")
    if result_kind in {"report", "patch", "message"}:
        return result_kind

    result_text = (
        result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or result.get("answer")
        or ""
    )

    if contains_patch(result_text):
        return "patch"

    if looks_like_markdown_report(result_text):
        return "report"

    if name.startswith("analyze") or text.startswith("analyze ") or "analyze" in text:
        return "report"

    patch_words = [
        "fix ", "change ", "edit ", "modify ", "implement ",
        "refactor ", "apply patch", "write code", "create file",
    ]

    if name in {"code_edit", "apply_patch", "coder", "fix_file", "refactor_file"}:
        return "patch"

    if any(w in text for w in patch_words):
        return "patch"

    return "message"

def write_analysis_report(skill_name, plan_id, result):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_skill = skill_name.replace("/", "_").replace(" ", "_")

    path = VAULT_DIR / "Reports" / f"{ts}_{plan_id}.md"

    markdown = (
        result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or ""
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    return path

def classify_skill_task(skill_name: str, user_text: str, result: dict | None = None) -> str:
    name = skill_name.lower()
    text = user_text.lower()

    if name.startswith("analyze") or text.startswith("analyze"):
        return "report"

    if name in {"code_edit", "apply_patch", "coder", "fix_file", "refactor_file"}:
        return "patch"

    if any(w in text for w in ["fix ", "change ", "edit ", "modify ", "implement ", "add "]):
        return "patch"

    return "message"

def emit_event(
    event_type: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    event_type = (event_type or "").lower()
    try:
        ensure_dirs()

        payload = {
            "ts":      time.time(),
            "time":    now_iso(),
            "type":    event_type,
            "message": message,
            "data":    data or {},
        }
        stage_text = character_stage_message(event_type, message, data)

        if TELEGRAM_ENABLED and stage_text:
            notify_telegram(clean_tool_result_for_telegram(stage_text))


        with open(EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        typing_events = {
        "plan",
        "router",
        "memory_router",
        "code_phase",
        "tool_start",
        "status",
        "agent_start",
        "agent_step",
        }

        if TELEGRAM_ENABLED and event_type in typing_events:
            telegram_chat_action("typing")

        if event_type in {"planner.start", "coder.start", "tool_start", "agent_start", "agent_step"}:
            stage_id = str((data or {}).get("stage_id") or event_type)
            TELEGRAM_GATEWAY.start_typing_stage(TELEGRAM_NOTIFY_CHAT_ID, stage_id)

        if event_type in {"planner.done", "coder.done", "tool_result", "agent_final", "final", "warning"}:
            stage_id = str((data or {}).get("stage_id") or event_type.replace(".done", ".start"))
            TELEGRAM_GATEWAY.stop_typing_stage(stage_id)

        important_events = {
            "critical",
            "warning",
            "plan",
            "final",
            "code_phase",
            "code_step_ready",
            "Coding planner full response",
            "Live router decision",
            "memory_router",
            "agent_start",
            "agent_step",
            "agent_final",
            "code_edit_output",
            "plan_runner",
        }
        model = str(
            (data or {}).get("model")
            or (data or {}).get("resolved_model")
            or ""
        )
        if "coder" in model:
            emoji = "💻"
        elif "planner" in model:
            emoji = "🧠"
        else:
            emoji = "🤖"
        if event_type == "warning":
            emoji = "⚠️"
        if TELEGRAM_ENABLED and event_type in important_events:
            route = str((data or {}).get("route", ""))

            telegram_text = (
                f"{emoji} JARVIS EVENT\n\n"
                f"Type: {event_type}\n"
                f"Message: {message}\n"
            )

            if route:
                telegram_text += f"Route: {route}\n"

            if model:
                telegram_text += f"Model: {model}\n"

            notify_telegram(telegram_text)

    except Exception:
        pass
def save_report(
    skill_name: str,
    plan_id: str,
    result: Any,
    route: str = "code",
) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_skill = (skill_name or "unknown").replace("/", "_").replace(" ", "_")

    sections: List[str] = []

    observations = result.get("observations") or []
    for obs in observations:
        raw = obs.get("observation") or obs.get("content") or ""

        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                text = (
                    data.get("markdown")
                    or data.get("report")
                    or data.get("text")
                    or data.get("content")
                    or data.get("answer")
                    or ""
                )
                if text:
                    raw = text
            except Exception:
                pass

        if raw and raw.strip():
            sections.append(raw.strip())

    final_answer = (
        result.get("answer")
        or result.get("markdown")
        or result.get("report")
        or result.get("text")
        or result.get("content")
        or ""
    ).strip()

    if final_answer and all(
        section[:120] in final_answer for section in sections if section
    ):
        markdown = final_answer
    else:
        parts = sections + ([final_answer] if final_answer else [])
        markdown = "\n\n---\n\n".join(parts)

    if not markdown:
        markdown = json.dumps(result, indent=2, ensure_ascii=False)

    header = f"# Report: {safe_skill}\n\n_Plan: {plan_id} — {ts}_\n\n"
    markdown = header + markdown

    report_dir = VAULT_DIR / "Reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{ts}_{safe_skill}_{plan_id[:12]}.md"
    path = report_dir / filename
    path.write_text(markdown, encoding="utf-8")

    emit_event("artifact", "Report saved", {
        "plan_id":  plan_id,
        "skill":    skill_name,
        "path":     str(path),
        "chars":    len(markdown),
        "sections": len(sections),
        "route":    route,
    })

    append_event(
        "report.saved",
        f"Report saved for {skill_name}",
        plan_id=plan_id,
        route=route,
        model="",
        payload={
            "path":     str(path),
            "chars":    len(markdown),
            "sections": len(sections),
        },
    )

    return {
        "ok":      True,
        "kind":    "report",
        "path":    str(path),
        "markdown": markdown,
        "message": f"Report written to {path}",
    }

def recent_events(limit: int = 100) -> List[Dict[str, Any]]:
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def recent_coding_events(limit: int = 120) -> List[Dict[str, Any]]:
    events = recent_events(500)
    coding: List[Dict[str, Any]] = []

    for e in events:
        data = e.get("data", {}) or {}
        model = str(
            data.get("model")
            or data.get("resolved_model")
            or data.get("planner_model")
            or ""
        ).lower()
        route = str(data.get("route") or data.get("resolved_route") or "").lower()
        event_type = str(e.get("type") or "").lower()

        if (
            route == "code"
            or "coder" in model
            or event_type == "code_phase"
            or "planner" in str(e.get("message", "")).lower()
        ):
            coding.append(e)

    return coding[-limit:]


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


def http_get_ok_simple(url: str, timeout: int = 2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def sanitize_for_tts(text: str) -> str:
    return text.replace("'", "''").replace("JARVIS", "Jarvis").replace("FRIDAY", "Friday").replace("EDITH", "Edith").replace("HAL", "Hal")


def speak_ack(text: str) -> None:
    if not ENABLE_TTS_ACK:
        return

    emit_event("tts_ack", "TTS ack requested", {
        "text":     text,
        "engine":   "kokoro",
        "delivery": "websocket_required",
    })

def write_bridge_status(state: str, text: Optional[str] = None) -> None:
    try:
        ensure_dirs()
        (BRIDGE_DIR / "state.txt").write_text(state, encoding="utf-8")
        if text is not None:
            (BRIDGE_DIR / "output.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


# Small gemma models are llama.cpp-only (:8091). If one leaks into an Ollama
# call (e.g. llama.cpp fallback), bump it to the Ollama minimum model.
OLLAMA_MIN_MODEL = os.environ.get("JARVIS_OLLAMA_MIN_MODEL", "qwen3:14b")
_OLLAMA_BANNED_MODEL_PREFIXES = tuple(
    p.strip().lower()
    for p in os.environ.get(
        "JARVIS_OLLAMA_BANNED_MODELS", "gemma4:e4b,gemma4:4b,gemma3:4b,gemma3n"
    ).split(",")
    if p.strip()
)


def request_ollama_chat(payload: Dict[str, Any], timeout: int):
    model = str(payload.get("model", "")).lower()
    if model.startswith(_OLLAMA_BANNED_MODEL_PREFIXES):
        print(f"[REACT] Ollama model guard: {payload.get('model')} → {OLLAMA_MIN_MODEL}")
        payload = {**payload, "model": OLLAMA_MIN_MODEL}
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
    start_tag = "<think>"
    end_tag = "</think>"
    result: List[str] = []
    i = 0
    in_think = False
    while i < len(text):
        if text.startswith(start_tag, i):
            in_think = True
            i += len(start_tag)
            continue
        if text.startswith(end_tag, i):
            in_think = False
            i += len(end_tag)
            continue
        if not in_think:
            result.append(text[i])
        i += 1
    return "".join(result).replace(end_tag, "").strip()


def parse_json_object_from_text(text: str) -> Optional[Dict[str, Any]]:
    text = strip_thinking_tags(text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def load_mode_profiles() -> Dict[str, Any]:
    try:
        if MODE_PROFILE_PATH.exists():
            data = json.loads(MODE_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        debug(f"Failed to load mode_profiles.json: {e}")
    return DEFAULT_MODE_PROFILES


def load_profile_by_id(profile_id: str) -> Dict[str, Any]:
    if not profile_id:
        return {}
    try:
        profile_file = PROFILES_DIR / f"{profile_id}.json"
        if profile_file.exists():
            return json.loads(profile_file.read_text(encoding="utf-8"))
    except Exception as e:
        debug(f"Failed to load profile {profile_id}: {e}")
    return {}


def load_active_profile(profile_override: Optional[str] = None) -> Dict[str, Any]:
    if profile_override:
        profile = load_profile_by_id(profile_override)
        if profile:
            return profile
    try:
        if ACTIVE_PROFILE_PATH.exists():
            data = json.loads(ACTIVE_PROFILE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("active"):
                profile = load_profile_by_id(str(data.get("active")))
                if profile:
                    return profile
            if isinstance(data, dict) and data.get("systemPrompt"):
                return data
    except Exception as e:
        debug(f"Failed to load active profile: {e}")
    return {}


def get_profile_options(profile_override: Optional[str] = None) -> Dict[str, Any]:
    profile = load_active_profile(profile_override=profile_override)
    options: Dict[str, Any] = {}
    temperature = profile.get("temperature")
    if isinstance(temperature, (int, float)):
        options["temperature"] = temperature
    top_p = profile.get("topP")
    if isinstance(top_p, (int, float)):
        options["top_p"] = top_p
    return options

def return_chat_response(self, payload: dict, user_text: str, reply_text: str, route: str, model: str):
    write_chat_log("user", user_text, route=route, model=model)
    write_chat_log("assistant", reply_text, route=route, model=model)
    self._json_response(payload)

def resolve_runtime_mode(route: str, selected_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = load_mode_profiles()
    defaults = cfg.get("defaults", {})
    overrides = cfg.get("tool_overrides", [])

    tool_names = set()
    for t in selected_tools:
        try:
            tool_names.add(t["function"]["name"])
        except Exception:
            continue

    for override in overrides:
        if override.get("route") != route:
            continue
        tools_any = set(override.get("tools_any", []))
        if tools_any and (tool_names & tools_any):
            return {
                "mode":        override.get("mode", "conversation"),
                "persona":     override.get("persona", "jarvis"),
                "tts_engine":  override.get("tts_engine", "kokoro"),
                "tts_enabled": bool(override.get("tts_enabled", True)),
            }

    base = defaults.get(route, defaults.get("fast", {}))
    return {
        "mode":        base.get("mode", "conversation"),
        "persona":     base.get("persona", "jarvis"),
        "tts_engine":  base.get("tts_engine", "kokoro"),
        "tts_enabled": bool(base.get("tts_enabled", True)),
    }


def write_runtime_mode(route: str, model: str, selected_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    runtime = resolve_runtime_mode(route, selected_tools)
    payload = {
        **runtime,
        "route":      route,
        "brain":      model,
        "updated_at": now_iso(),
        "tools": [
            t["function"]["name"]
            for t in selected_tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        ],
    }
    try:
        ensure_dirs()
        RUNTIME_MODE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        debug(f"Failed writing runtime mode: {e}")
    return payload


def build_self_context(persona: Optional[str] = None) -> Dict[str, Any]:
    profile = load_active_profile(profile_override=persona)
    cfg = load_model_config()

    return {
        "identity": {"id": profile.get("id"), "label": profile.get("label"), "systemPrompt": profile.get("systemPrompt")},
        "models":   {"routes": cfg.get("models", {}), "planner_model": cfg.get("planner_model")},
        "tool_count":        len(TOOL_MAP),
        "available_routes":  list(MODE_PROMPTS.keys()),
    }
def build_last_exchange_context() -> str:
    try:
        from scripts.chat_context import read_last_messages
    except Exception:
        try:
            from chat_context import read_last_messages
        except Exception:
            return ""

    try:
        last_user, last_assistant = read_last_messages()
    except Exception:
        return ""

    blocks = []

    if last_user:
        blocks.append(
            "[LAST USER MESSAGE]\n"
            f"{last_user}\n"
            "[/LAST USER MESSAGE]"
        )

    if last_assistant:
        blocks.append(
            "[LAST ASSISTANT MESSAGE]\n"
            f"{last_assistant}\n"
            "[/LAST ASSISTANT MESSAGE]"
        )

    return "\n\n".join(blocks)

def build_self_context_prompt(persona: Optional[str] = None, max_tools: int = 20) -> str:
    ctx = build_self_context(persona=persona)
    identity     = ctx.get("identity", {})
    models       = ctx.get("models", {})
    capabilities = ctx.get("capabilities", [])
    parts = ["Runtime self-context:"]
    parts.append(f"- Persona: {identity.get('label') or identity.get('id') or 'JARVIS'}")
    if models.get("routes"):
        parts.append(f"- Model routes: {models['routes']}")
    if models.get("planner_model"):
        parts.append(f"- Planner model: {models['planner_model']}")
    parts.append("- Available tools:")
    for item in capabilities[:max_tools]:
        parts.append(f"  - {item.get('tool', '')}: {item.get('description', '')}")
    if len(capabilities) > max_tools:
        parts.append(f"  - ...and {len(capabilities) - max_tools} more tools available")
    return "\n".join(parts)

def build_system_prompt_for_route(route: str, persona: Optional[str] = None) -> str:
    profile = load_active_profile(profile_override=persona)

    profile_prompt = (
        profile.get("systemPrompt") or ""
    ).strip() or "You are JARVIS, a capable local assistant."

    external_prompt_by_route = {
        "live":   LIVE_CHAT_PROMPT_PATH,
        "fast":   LIVE_CHAT_PROMPT_PATH,
        "reason": PLANNER_PROMPT_PATH,
        "code":   CODER_PROMPT_PATH,
    }

    external_route_prompt = ""
    if route in external_prompt_by_route:
        external_route_prompt = load_prompt_file(external_prompt_by_route[route], "")

    if route == "code":
        coder_prompt = external_route_prompt or MODE_PROMPTS.get("code", "").strip()

        parts = [
            profile_prompt,
            coder_prompt,
            CODER_WORKSPACE_HINT.strip(),
            build_last_exchange_context(),
            build_short_term_context(),
            load_coder_memory(),
            build_self_context_prompt(persona=persona),
        ]
    else:
        mode_prompts = profile.get("modePrompts")
        profile_mode_prompt = ""

        if isinstance(mode_prompts, dict):
            profile_mode_prompt = (mode_prompts.get(route) or "").strip()

        route_prompt = (
            profile_mode_prompt
            or external_route_prompt
            or MODE_PROMPTS.get(route or "reason", "").strip()
        )
        parts = [
            profile_prompt,
            route_prompt,
            SYSTEM_ORCHESTRATOR_PROMPT.strip(),
            build_self_context_prompt(persona=persona),
        ]

    return "\n\n".join(part for part in parts if part and part.strip())
def save_coder_memory(summary: str, max_chars: int = 12000) -> None:
    CODER_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    old = ""
    if CODER_MEMORY_PATH.exists():
        old = CODER_MEMORY_PATH.read_text(encoding="utf-8", errors="ignore")

    new_text = (old.rstrip() + "\n\n" + summary.strip()).strip()

    if len(new_text) > max_chars:
        new_text = new_text[-max_chars:]

    CODER_MEMORY_PATH.write_text(new_text + "\n", encoding="utf-8")

def normalize_messages(messages: List[Dict[str, Any]], system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        out.append({"role": "system", "content": system_prompt or SYSTEM_ORCHESTRATOR_PROMPT})
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
    others  = [m for m in messages if m.get("role") != "system"]
    if len(others) <= max_messages:
        trimmed = others
    else:
        first_user = next((m for m in others if m.get("role") == "user"), None)
        extra = 1 if first_user else 0
        tail_count = max(0, max_messages - extra)
        tail = others[-tail_count:] if tail_count > 0 else []
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

def should_use_kokoro(route: str, model: str) -> bool:
    route = (route or "").strip().lower()
    model = (model or "").strip().lower()

    if not KOKORO_ENABLED:
        return False

    if route in {"code", "deep"}:
        return False

    if "30b" in model or "31b" in model:
        return False

    return route in {"live", "fast", "tools", "reason"}


def sync_kokoro_for_route(route: str, model: str) -> None:
    if not KOKORO_ENABLED:
        return

    use_kokoro = should_use_kokoro(route, model)

    emit_event(
        "status",
        "Syncing Kokoro policy",
        {
            "route":          route,
            "model":          model,
            "use_kokoro":     use_kokoro,
            "kokoro_running": is_kokoro_running(),
            "kokoro_host":    KOKORO_HOST,
        },
    )

    if use_kokoro and not is_kokoro_running():
        emit_event(
            "warning",
            "Kokoro selected but not reachable",
            {"kokoro_host": KOKORO_HOST},
        )

def is_coder_model(model: str) -> bool:
    return "coder" in (model or "").lower()


def get_coder_tool() -> Optional[Dict[str, Any]]:
    return (
         TOOLS_BY_NAME.get("code_edit")
    )


def guess_coding_paths(user_text: str) -> List[str]:
    text = user_text or ""
    lower = text.lower()

    explicit_file_patterns = [
        r"(?:save it to|save as|write to|create|make|to)\s+([A-Za-z0-9_.\-/]+\.(?:html|py|js|ts|tsx|jsx|css|json|md|txt))",
        r"\b([A-Za-z0-9_.\-/]+\.(?:html|py|js|ts|tsx|jsx|css|json|md|txt))\b",
    ]

    for pattern in explicit_file_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return [match.group(1).strip()]

    known_files = [
        "skills/news.py",
        "skills/radio.py",
        "skills/coding.py",
        "skills/loader.py",
        "scripts/react_server.py",
        "scripts/watcher.py",
        "config/models-config.json",
        "config/model_config.json",
        "config/models.json",
        "app/page.tsx",
    ]

    paths: List[str] = []

    for p in known_files:
        name = p.split("/")[-1].lower()
        stem = name.rsplit(".", 1)[0]
        if name in lower or stem in lower:
            paths.append(p)

    if "news" in lower and "skills/news.py" not in paths:
        paths.append("skills/news.py")

    if "radio" in lower and "skills/radio.py" not in paths:
        paths.append("skills/radio.py")

    if "skill" in lower and not paths:
        paths.append("skills")

    return paths or ["."]

def extract_tool_content(result: Any) -> str:
    if isinstance(result, str):
        try:
            data = json.loads(result)

            if isinstance(data, dict):
                ui = data.get("ui")

                if isinstance(ui, dict):
                    content = ui.get("content")
                    if isinstance(content, str):
                        return content

                speech = data.get("speech")
                if isinstance(speech, str):
                    return speech

                return json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )

            return result

        except Exception:
            return result

    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        default=str,
    )

def normalized_route(requested_route: Optional[str], selected_tools: List[Dict[str, Any]]) -> str:
    if requested_route in VALID_ROUTES:
        return requested_route
    return infer_route_from_tools(selected_tools)

def request_llama_cpp_chat_raw(
    payload: Dict[str, Any],
    timeout: int = CHAT_TIMEOUT_SEC,
):
    """POST an already-OpenAI-format payload to llama.cpp as-is.
    NOTE: must NOT be named request_llama_cpp_chat — that name is the
    Ollama→OpenAI translating version defined earlier; a same-name def here
    silently overrode it and broke request_chat_backend's payload format."""
    req = urllib.request.Request(
        f"{LLAMA_CPP_HOST}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)

def call_ollama_once(
    model: str,
    messages: List[Dict[str, Any]],
    route: str,
    persona: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
) -> Dict[str, Any]:
    final_messages = compact_context(
        normalize_messages(
            messages,
            system_prompt=build_system_prompt_for_route(
                route,
                persona=persona,
            ),
        )
    )

    if route in LLAMA_CPP_ROUTES:
        payload: Dict[str, Any] = {
            "model":       model,
            "messages":    final_messages,
            "stream":      False,
            "temperature": 0.3,
        }

        try:
            with request_llama_cpp_chat_raw(
                payload,
                timeout=CHAT_TIMEOUT_SEC,
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            return {
                "model":      model,
                "created_at": now_iso(),
                "message":    {
                    "role":    "assistant",
                    "content": content,
                },
                "done":     True,
                "route":    route,
                "provider": "llama.cpp",
                "raw":      data,
            }
        except (urllib.error.URLError, OSError) as e:
            # llama.cpp down → fall through to the Ollama path below.
            # The Ollama model guard replaces small gemma with qwen3:14b;
            # with the Claude proxy on :11434 this transparently goes cloud.
            print(f"[REACT] llama.cpp unavailable ({e}), route={route} → Ollama fallback")

    payload: Dict[str, Any] = {
        "model":    model,
        "messages": final_messages,
        "stream":   stream,
    }

    profile_options = get_profile_options(profile_override=persona)
    if profile_options:
        payload["options"] = profile_options

    if tools and model not in NO_TOOLS_MODELS and not is_coder_model(model):
        payload["tools"] = tools

    with request_ollama_chat(
        payload,
        timeout=CHAT_TIMEOUT_SEC,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))

# -----------------------------------------------------------------------------
# Tool selection
# -----------------------------------------------------------------------------
LAST_TELEGRAM_ACTION_AT = 0.0
def maybe_send_telegram_media(result: Any) -> bool:
    try:
        data = result
        if isinstance(result, str):
            data = json.loads(result)

        paths = []

        if isinstance(data, dict):
            for key in ["image_path", "path", "file", "filename"]:
                value = data.get(key)
                if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    paths.append(value)

            ui = data.get("ui")
            if isinstance(ui, dict):
                value = ui.get("path") or ui.get("image_path") or ui.get("file")
                if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    paths.append(value)

            images = data.get("images")
            if isinstance(images, list):
                for value in images:
                    if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        paths.append(value)

        for image_path in paths:
            p = Path(image_path).expanduser()
            if p.exists():
                TELEGRAM_GATEWAY.send_photo(
                    TELEGRAM_NOTIFY_CHAT_ID,
                    str(p),
                    caption="Generated image"
                )
                return True

    except Exception as e:
        emit_event("warning", "Telegram media send failed", {"error": str(e)})

    return False

def telegram_chat_action(action: str = "typing") -> None:
    global LAST_TELEGRAM_ACTION_AT

    if not TELEGRAM_NOTIFY_CHAT_ID:
        return

    now = time.time()

    if now - LAST_TELEGRAM_ACTION_AT < 4.0:
        return

    LAST_TELEGRAM_ACTION_AT = now

    try:
        TELEGRAM_GATEWAY.send_chat_action(TELEGRAM_NOTIFY_CHAT_ID, action)
    except Exception as e:
        debug(f"Telegram chat action failed: {e}")

def parse_plan_command(text: str) -> tuple[str, Optional[str]]:
    parts = (text or "").strip().split()
    if not parts:
        return "", None

    command = parts[0].lower()
    plan_id = parts[1] if len(parts) > 1 else None

    return command, plan_id

def build_planner_catalog() -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for tool in TOOLS:
        try:
            name        = tool["function"]["name"]
            description = tool["function"].get("description", "")
        except Exception:
            continue
        meta = TOOL_SKILL_META.get(name, {})
        catalog.append(
            {
                "name":           name,
                "description":    description,
                "intent_aliases": meta.get("intent_aliases", []),
                "keywords":       meta.get("keywords", []),
                "direct_match":   meta.get("direct_match", []),
                "route":          meta.get("route", "reason"),
            }
        )
    return catalog


def build_planner_prompt(user_text: str) -> str:
    compact_catalog = []
    for item in build_planner_catalog():
        compact_catalog.append(
            {
                "name":        item["name"],
                "description": item.get("description", ""),
                "aliases":     item.get("intent_aliases", []),
                "route":       item.get("route", "reason"),
                "keywords":    item.get("keywords", [])[:12],
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

def summarize_step_result(content: str, limit: int = 600) -> str:
    text = strip_thinking_tags(content or "").strip()
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL).strip()

    if "APPLY FAILED" in text:
        return "Patch generation completed, but applying the patch failed."

    if "--- FILE:" in text:
        files = re.findall(r"--- FILE:\s*(.+)", text)
        if files:
            return "Updated: " + ", ".join(f.strip() for f in files[:5])

    if len(text) > limit:
        text = text[:limit].rstrip() + "..."

    return text or "Step completed."

def parse_planner_response(answer: str) -> List[str]:
    data = parse_json_object_from_text(answer)
    if data:
        tools = data.get("tools", [])
        if isinstance(tools, list):
            return [item.strip() for item in tools if isinstance(item, str) and item.strip()]
    text = strip_thinking_tags(answer or "").strip()
    if not text:
        return []
    return [p.strip() for p in text.split(",") if p.strip()]


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
        for candidate in INTENT_TOOL_CANDIDATES.get(name, []):
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
    return dedupe_tools([TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME])

def build_live_tool_catalog(max_tools: int = 40) -> str:
    catalog = []

    for tool_name, tool in sorted(TOOLS_BY_NAME.items()):
        fn   = tool.get("function", {})
        meta = TOOL_SKILL_META.get(tool_name, {})

        catalog.append({
            "name":           tool_name,
            "description":    fn.get("description", "")[:300],
            "parameters":     fn.get("parameters", {}),
            "intent_aliases": meta.get("intent_aliases", []),
            "keywords":       meta.get("keywords", []),
            "direct_match":   meta.get("direct_match", []),
        })

    return json.dumps(catalog[:max_tools], ensure_ascii=False)

def select_tools_by_hints(user_text: str) -> List[Dict[str, Any]]:
    text = (user_text or "").lower()
    matched_tool_names: List[str] = []
    for tool_name, hints in TOOL_HINTS.items():
        if any(hint in text for hint in hints):
            matched_tool_names.append(tool_name)
    for tool_name, keywords in TOOL_KEYWORDS.items():
        if any((kw or "").lower() in text for kw in keywords):
            matched_tool_names.append(tool_name)
    return dedupe_tools([TOOLS_BY_NAME[name] for name in matched_tool_names if name in TOOLS_BY_NAME])


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


def get_effective_planner_model(user_text: str, requested_route: Optional[str], requested_model: Optional[str]) -> str:
    text = (user_text or "").strip().lower()
    words = len(text.split())
    simple_patterns = ["weather", "forecast", "news", "volume", "timer", "radio", "open", "play", "pause", "stop", "mute", "unmute"]
    if requested_route == "fast" or words <= 12:
        if any(p in text for p in simple_patterns):
            cfg = load_model_config()
            return str((cfg.get("models") or {}).get("fast", "qwen3:14b"))
    return get_planner_model()

def get_active_task(task_graph_path: Path) -> Optional[dict]:
    graph = load_task_graph()
    active_id = graph.get("active_task_id")
    if not active_id:
        return None
    return graph.get("tasks", {}).get(active_id)


def get_task_by_id(task_graph_path: Path, task_id: str) -> Optional[dict]:
    graph = load_task_graph()
    return graph.get("tasks", {}).get(task_id)

def select_tools_via_llm(user_text: str, requested_route: Optional[str] = None, requested_model: Optional[str] = None) -> List[Dict[str, Any]]:
    planner_model = get_effective_planner_model(user_text=user_text, requested_route=requested_route, requested_model=requested_model)
    prompt = build_planner_prompt(user_text)
    payload = {
        "model":    planner_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "think":    False,
        "options":  {"num_predict": 192, "temperature": 0},
    }
    try:
        emit_event("plan", "Selecting tools", {"planner_model": planner_model})
        with request_ollama_chat(payload, timeout=PLANNER_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            emit_event(
                "code_phase",
                "Coding planner full response",
                {"route":          "code",
                 "model":          planner_model,
                 "planner_model":  planner_model,
                 "data":           data,
                },
            )
        answer = strip_thinking_tags(data.get("message", {}).get("content", "")).strip()

        selected_names = parse_planner_response(answer)
        if not selected_names:
            emit_event("plan", "Planner selected no tools",  {"route": "code",
                    "model": planner_model,
                    "planner_model": planner_model,
                    "data": data,
                })
            return []
        selected: List[Dict[str, Any]] = []
        selected_names_seen = set()
        for name in selected_names:
            lowered = name.strip().lower()
            if not lowered or lowered in selected_names_seen:
                continue
            selected_names_seen.add(lowered)
            if lowered in TOOLS_BY_NAME:
                selected.append(TOOLS_BY_NAME[lowered])
                continue
            for tool in resolve_intent_or_tool_names([lowered]):
                try:
                    tool_name = tool["function"]["name"]
                except Exception:
                    continue
                if tool_name not in {t["function"]["name"] for t in selected}:
                    selected.append(tool)
        if not selected:
            emit_event("warning", "Planner returned no resolvable tools, using keyword fallback", {"raw_answer": answer})
            return select_tools_keyword(user_text)
        selected = dedupe_tools(selected)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Planner selected tools", {"tools": [t["function"]["name"] for t in selected], "raw_answer": answer, "planner_model": planner_model})
        return selected
    except urllib.error.HTTPError as e:
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = "<no error body>"
        emit_event("warning", "Planner failed, using keyword fallback", {"error": f"HTTP {e.code} {e.reason}", "body": error_body, "planner_model": planner_model})
        return select_tools_keyword(user_text)
    except Exception as e:
        emit_event("warning", "Planner failed, using keyword fallback", {"error": str(e), "planner_model": planner_model})
        return select_tools_keyword(user_text)


def choose_tools(user_text: str, requested_route: Optional[str] = None, requested_model: Optional[str] = None) -> List[Dict[str, Any]]:
    if requested_route == "code":
        coder_tool = get_coder_tool()
        return [coder_tool] if coder_tool else []

    text = user_text or ""
    direct = direct_tools_for_text(text)
    if direct:
        direct = dedupe_tools(direct)[:MAX_TOOL_SELECTION]
        emit_event("plan", "Direct tool selection from metadata", {"tools": [t["function"]["name"] for t in direct]})
        return direct
    selected = select_tools_via_llm(text, requested_route=requested_route, requested_model=requested_model)
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


def should_select_tools(user_text: str, requested_route: Optional[str], requested_model: Optional[str]) -> bool:
    text = (user_text or "").strip()
    lower = text.lower()
    if not text:
        return False
    if requested_route == "code" and "coder" in (requested_model or "").lower():
        return False
    if len(text.split()) <= 12 and not likely_needs_tools(lower):
        return False
    if requested_route == "fast" and not likely_needs_tools(lower):
        return False
    return likely_needs_tools(lower)

def extract_last_patch_from_anything(value: Any) -> str:
    text = extract_tool_content(value)

    try:
        data = json.loads(text)
        observations = data.get("observations", [])
        if isinstance(observations, list):
            for obs in reversed(observations):
                raw = obs.get("observation")
                if not raw:
                    continue
                raw_data = json.loads(raw) if isinstance(raw, str) else raw
                ui = raw_data.get("ui") if isinstance(raw_data, dict) else None
                patch = ui.get("content") if isinstance(ui, dict) else None
                if isinstance(patch, str) and "--- FILE:" in patch:
                    return normalize_patch_text(patch)
    except Exception:
        pass

    return normalize_patch_text(text)

def is_simple_direct_chat(user_text: str, selected_tools: List[Dict[str, Any]], route: str) -> bool:
    return not selected_tools and route == "fast" and len((user_text or "").split()) <= 12

# -----------------------------------------------------------------------------
# Route inference and tool execution
# -----------------------------------------------------------------------------


def detect_route(message: str, source: str = "") -> str:
    text = (message or "").lower()
    source = (source or "").lower()
    if source in {"codex", "codex_ui", "code_ui"}:
        return "code"
    code_keywords = [
        "code", "python", "javascript", "typescript", "next.js", "react", "bug", "error",
        "stack trace", "traceback", "function", "class", "api", "endpoint", "compile", "fix this",
        "refactor", "implement", "write script", "patch", "diff", "git", "repo", "file", "server", "skill",
    ]
    if any(k in text for k in code_keywords):
        return "code"
    if is_research_shaped(text):
        return "deep"
    return "reason"


# Research-shaped goals: answering well needs evidence from several
# sources (web + market data + news/calendar), so they belong in the
# deep agent loop, not a single-tool pass or an inline chat answer.
DEEP_KEYWORDS = [
    "forecast", "outlook", "predict", "next week", "coming week",
    "next month", "coming month", "research", "compare", "deep dive",
    "analysis", "analyse", "analyze", "should i buy", "should i sell",
    "good time to", "market look", "markets look",
]


def is_research_shaped(message: str) -> bool:
    text = (message or "").lower()
    return any(k in text for k in DEEP_KEYWORDS)


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
    if "tools" in routes:
        return "tools"
    if "fast" in routes:
        return "fast"
    return "tools"


def make_tool_message(name: str, result: Any, call_id: str = "") -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "tool", "name": name, "content": truncate_text(result)}
    if call_id:
        msg["tool_call_id"] = call_id
    return msg


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
        normalized.append({"id": call.get("id", f"tool_{idx}"), "type": "function", "function": {"name": fn_name, "arguments": fn_args}})
    return normalized

def execute_tool(fn_name: str, fn_args: Dict[str, Any]) -> str:
    executor = TOOL_MAP.get(fn_name)
    if not executor:
        emit_event("warning", f"Unknown tool {fn_name}")
        return f"Unknown tool: {fn_name}"

    started = time.time()
    tool_payload = {
        "tool": fn_name,
        "args": fn_args,
    }

    if fn_name == "code_edit":
        tool_payload["coder_task"] = fn_args.get("task")
        tool_payload["coder_path"] = fn_args.get("path")
        tool_payload["coder_mode"] = fn_args.get("mode")

    emit_event("tool_start", f"Running tool {fn_name}", tool_payload)

    try:
        result = executor(**fn_args)
        
        increment_tool_usage(fn_name)
        if fn_name == "code_edit":
            emit_event(
                "code_edit_output",
                "Coder tool returned output",
                {
                    "tool":           fn_name,
                    "result_preview": truncate_text(result, 4000),
                    "path":           fn_args.get("path"),
                    "mode":           fn_args.get("mode"),
                },
            )

        elapsed = time.time() - started
        preview = truncate_text(extract_tool_content(result), 3000)

        debug(f"Tool ok: {fn_name} in {elapsed:.2f}s")

        emit_event(
            "tool_result",
            f"Tool {fn_name} completed",
            {
                "tool":           fn_name,
                "elapsed_sec":    round(elapsed, 3),
                "result_preview": preview,
            },
        )

        if isinstance(result, dict):
            emit_event(
                "skill_result",
                f"Skill {fn_name} returned structured result",
                {"tool": fn_name, "result": result},
            )
            return json.dumps(result, ensure_ascii=False)

        return truncate_text(result)

    except Exception as e:
        elapsed = time.time() - started
        debug(f"Tool failed: {fn_name} in {elapsed:.2f}s :: {e}")
        emit_event(
            "warning",
            f"Tool {fn_name} failed",
            {
                "tool":        fn_name,
                "elapsed_sec": round(elapsed, 3),
                "error":       str(e),
            },
        )
        return truncate_text({
            "error":     str(e),
            "tool":      fn_name,
            "traceback": traceback.format_exc(limit=3),
        })
    
def send_flux_result_to_telegram(result: Any) -> bool:
    try:
        data = result

        if isinstance(result, str):
            data = json.loads(result)

        if not isinstance(data, dict):
            return False

        image_path = (
            data.get("image_path")
            or data.get("path")
            or data.get("file")
            or data.get("output")
        )

        if not image_path:
            ui = data.get("ui")
            if isinstance(ui, dict):
                image_path = (
                    ui.get("image_path")
                    or ui.get("path")
                    or ui.get("file")
                    or ui.get("output")
                )

        if not image_path:
            emit_event("warning", "Flux result had no image path", {"result": data})
            return False

        path = Path(str(image_path)).expanduser()

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        path = path.resolve()

        if not path.exists():
            emit_event("warning", "Flux image path does not exist", {"path": str(path)})
            return False

        TELEGRAM_GATEWAY.send_photo(
            TELEGRAM_NOTIFY_CHAT_ID,
            str(path),
            caption="🎨 Flux image generated",
        )

        emit_event("status", "Flux image sent to Telegram", {"path": str(path)})
        return True

    except Exception as e:
        emit_event("warning", "Flux Telegram image send failed", {"error": str(e)})
        return False
    
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


def react_chat(model: str, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None, route: str = "reason", persona: Optional[str] = None) -> Dict[str, Any]:
    tools = tools or []
    system_prompt = build_system_prompt_for_route(route, persona=persona)
    normalized_messages = compact_context(normalize_messages(messages, system_prompt=system_prompt))

    use_tools = (not is_coder_model(model)) and model not in NO_TOOLS_MODELS and len(tools) > 0

    run = ChatRun(request_id=str(uuid.uuid4())[:8], model=model, selected_tools=[t["function"]["name"] for t in tools])
    debug(f"run={run.request_id} model={model} route={route} persona={persona} selected_tools={run.selected_tools} use_tools={use_tools}")
    emit_event("status", "Chat run started", {"request_id": run.request_id, "model": model, "route": route, "persona": persona, "tools": run.selected_tools, "use_tools": use_tools})

    last_data: Dict[str, Any] = {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": "No response generated."}, "done": True}

    for iteration in range(1, MAX_ITERATIONS + 1):
        run.iterations = iteration
        body: Dict[str, Any] = {"model": model, "messages": normalized_messages, "stream": False}
        profile_options = get_profile_options(profile_override=persona)
        if profile_options:
            body["options"] = profile_options
        if use_tools:
            body["tools"] = tools

        try:
            emit_event("status", "Calling Ollama", {"request_id": run.request_id, "iteration": iteration, "model": model, "route": route, "persona": persona, "use_tools": use_tools})
            with request_chat_backend(body, timeout=CHAT_TIMEOUT_SEC, route=route) as resp:
                raw = resp.read().decode("utf-8")
                data = normalize_chat_response(json.loads(raw))
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = "<no error body>"
            if e.code == 400 and use_tools:
                debug(f"{model} rejected tools. Marking as no-tools model. body={error_body}")
                emit_event("warning", f"{model} rejected tools, retrying without tools", {"request_id": run.request_id, "iteration": iteration, "body": error_body})
                NO_TOOLS_MODELS.add(model)
                use_tools = False
                continue
            emit_event("warning", "Ollama HTTP error", {"request_id": run.request_id, "code": e.code, "reason": e.reason, "body": error_body})
            return {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Error calling Ollama: HTTP {e.code} {e.reason}"}, "done": True}
        except Exception as e:
            emit_event("warning", "Ollama request failed", {"request_id": run.request_id, "error": str(e)})
            return {"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Error calling Ollama: {e}"}, "done": True}

        last_data = data
        assistant_msg = data.get("message", {}) or {}
        tool_calls = normalize_tool_calls(assistant_msg) if use_tools else []
        content_preview = (assistant_msg.get("content") or "")[:120].replace("\n", " ")
        debug(f"run={run.request_id} iter={iteration} tool_calls={len(tool_calls)} preview={content_preview!r}")
        emit_event("status", "Model replied", {"request_id": run.request_id, "iteration": iteration, "tool_call_count": len(tool_calls), "content_preview": content_preview})

        if not tool_calls:
            content = data.get("message", {}).get("content", "")
            if isinstance(content, str):
                data["message"]["content"] = content.replace("**", "")
            append_log(f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} done model={model} route={route} persona={persona} iterations={run.iterations} duration_ms={run.duration_ms()}")
            emit_event("final", "Final response ready", {"request_id": run.request_id, "duration_ms": run.duration_ms(), "route": route, "model": model})
            return data

        normalized_messages.append({"role": "assistant", "content": assistant_msg.get("content", ""), "tool_calls": tool_calls})
        run.used_tools = True
        for call in tool_calls:
            fn_name = call["function"]["name"]
            fn_args = call["function"]["arguments"]
            call_id = call.get("id", f"call_{fn_name}_{iteration}")
            # Skip re-executing a tool that already returned a result this run
            already_ran = any(
                m.get("role") == "tool" and m.get("name") == fn_name
                for m in normalized_messages
            )
            if already_ran:
                emit_event("warning", f"Tool {fn_name} already ran this turn — skipping duplicate", {"call_id": call_id})
                normalized_messages.append(make_tool_message(fn_name, "Already executed this turn. Use the result already provided.", call_id=call_id))
                continue
            debug(f"run={run.request_id} tool={fn_name} args={safe_json_dumps(fn_args)[:180]}")
            result = execute_tool(fn_name, fn_args)
            debug(f"run={run.request_id} tool={fn_name} result={result[:180]!r}")
            normalized_messages.append(make_tool_message(fn_name, result, call_id=call_id))

    append_log(f"[{datetime.now().strftime('%H:%M:%S')}] run={run.request_id} max_iterations model={model} route={route} persona={persona} iterations={run.iterations} duration_ms={run.duration_ms()}")
    emit_event("warning", "Max iterations reached", {"request_id": run.request_id, "duration_ms": run.duration_ms(), "route": route, "model": model})
    return last_data

# -----------------------------------------------------------------------------
# Streaming support
# -----------------------------------------------------------------------------

def stream_direct_chat(handler: "ReactHandler", model: str, messages: List[Dict[str, Any]], selected_tools: Optional[List[Dict[str, Any]]] = None, route: str = "reason", persona: Optional[str] = None) -> None:
    user_text = get_last_user_text(messages)
    user_text = clean_telegram_prefix(user_text)
    if selected_tools is None:
        selected_tools = choose_tools(user_text, requested_route=route, requested_model=model) if should_select_tools(user_text, route, model) else []

    tool_names = [t["function"]["name"] for t in selected_tools]
    debug(f"Streaming selected tools: {tool_names}")
    emit_event("status", "Streaming chat started", {"model": model, "route": route, "persona": persona, "tools": tool_names})

    if selected_tools and not is_coder_model(model):
        ack = random.choice(ACKS)
        write_bridge_status("thinking", ack)
        speak_ack(ack)
        if ENABLE_STREAM_STATUS:
            handler._write_sse_json({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": ""}, "done": False, "status": f"Using tools: {', '.join(tool_names)}"})
        result = react_chat(model, messages, selected_tools, route=route, persona=persona)
        handler._write_sse_json(result)
        return

    body = {
        "model":    model,
        "messages": compact_context(normalize_messages(messages, system_prompt=build_system_prompt_for_route(route, persona=persona))),
        "stream":   True,
    }
    profile_options = get_profile_options(profile_override=persona)
    if profile_options:
        body["options"] = profile_options
    try:
        
        with request_chat_backend(body, timeout=CHAT_TIMEOUT_SEC, route=route) as resp:
            for raw_line in resp:
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                handler.wfile.write((line + "\n").encode("utf-8"))
                handler.wfile.flush()
    except Exception as e:
        emit_event("warning", "Streaming error", {"error": str(e), "model": model, "route": route, "persona": persona})
        handler._write_sse_json({"model": model, "created_at": now_iso(), "message": {"role": "assistant", "content": f"Streaming error: {e}"}, "done": True})

# -----------------------------------------------------------------------------
# HTTP handler
# -----------------------------------------------------------------------------


class ReactHandler(BaseHTTPRequestHandler):
    server_version = "JarvisReact/3.0"

    def do_POST(self) -> None:
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket_upgrade()
            return

        self._do_POST_impl()

    def handle_live_router(
        self,
        body: dict,
        user_text: str,
        requested_model: str | None,
        requested_route: str | None,
        source: str,
        messages: list,
    ) -> tuple[bool, str | None]:
        return handle_live_router(
            self,
            body,
            user_text,
            requested_model,
            requested_route,
            source,
            messages,
        )

    def handle_full_pipeline(
        self,
        body: dict,
        user_text: str,
        requested_model: str | None,
        requested_route: str | None,
        source: str,
        messages: list,
        stream: bool,
    ) -> None:
        return handle_full_pipeline(
            self,
            body,
            user_text,
            requested_model,
            requested_route,
            source,
            messages,
            stream,
        )
    
    def _handle_websocket_upgrade(self) -> None:
        """Upgrade HTTP connection to WebSocket and hand off to _run_live_ws."""
        import hashlib

        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            self.send_error(400, "Missing Sec-WebSocket-Key")
            return

        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()

        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _run_live_ws(self.rfile, self.wfile)
            )
        except Exception as e:
            debug(f"WebSocket handler error: {e}")
        finally:
            loop.close()

    def _parse_request_body(self) -> tuple[dict, str]:
        """Parse POST body, return (body_dict, error_str)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            return json.loads(raw_body), ""
        except Exception as e:
            return {}, str(e)
    

    def _do_POST_impl(self) -> None:
        path = urlparse(self.path).path

        # ── n8n inbound webhook: POST /api/events ────────────────────────────
        # n8n calls this to push events, completed workflow results, or tasks
        # back into Jarvis. Events are logged and optionally queued as tasks.
        if path == "/api/events":
            body, err = self._parse_request_body()
            if err:
                self._json_response({"error": "Invalid JSON"}, code=400)
                return
            event_type = body.get("type", "n8n_event")
            source      = body.get("source", "n8n")
            message     = body.get("message", "")
            data        = body.get("data", {})
            task_text   = body.get("task") or body.get("goal") or body.get("description", "")

            # Log to events file
            emit_event(event_type, message or task_text, data={
                "source": source, **data,
                **({"task": task_text} if task_text else {}),
            })

            # If n8n sends a task/goal, queue it directly to Jarvis plan queue
            if task_text:
                r = _get_redis()
                if r:
                    import uuid as _uuid
                    task_payload = json.dumps({
                        "id":     str(_uuid.uuid4())[:8],
                        "task":   task_text,
                        "skill":  body.get("skill", "coding"),
                        "tool":   body.get("tool", "code_edit"),
                        "source": source,
                        "args":   data,
                    })
                    r.rpush("jarvis:tasks", task_payload)
                    self._json_response({"ok": True, "queued": True, "task": task_text})
                    return

            self._json_response({"ok": True, "logged": event_type})
            return

        # ── Plan approve endpoint ─────────────────────────────────────────────
        if path.startswith("/api/plans/") and path.endswith("/approve"):
            import shutil
            pid = path[len("/api/plans/"):-len("/approve")]
            staging_root = Path("/mnt/e/coding/staging")
            src  = staging_root / "tested"   / pid
            dest = staging_root / "approved" / pid
            if not src.exists():
                self._json_response({"error": f"staging/tested/{pid} not found"}, code=404)
                return
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                self._json_response({"ok": True, "approved": str(dest), "plan_id": pid})
            except Exception as e:
                self._json_response({"error": str(e)}, code=500)
            return

        if path != "/api/chat":
            self.send_error(404)
            return

        body, err = self._parse_request_body()
        if err:
            self._json_response({"error": "Invalid JSON body"}, code=400)
            return

        requested_model = body.get("model")
        requested_route = body.get("route")
        source = body.get("source", "")
        messages = body.get("messages", [])
        stream = bool(body.get("stream", False))

        if not isinstance(messages, list):
            self._json_response({"error": "messages must be a list"}, code=400)
            return

        # Support top-level user_text shorthand (normalise into messages)
        top_level_text = body.get("user_text", "")
        if top_level_text and not messages:
            messages = [{"role": "user", "content": top_level_text}]

        user_text = get_last_user_text(messages)
        user_text = clean_telegram_prefix(user_text)

        # --- memory_router fast path (replaces old live_router) ---
        handled, route_override = self.handle_live_router(
            body=body,
            user_text=user_text,
            requested_model=requested_model,
            requested_route=requested_route,
            source=source,
            messages=messages,
        )
        if handled:
            return

        # update user_text from transcript if memory_router rewrote it
        user_text = body.get("_user_text", user_text)
        if route_override:
            requested_route = route_override

        # --- full pipeline ---
        self.handle_full_pipeline(
            body=body,
            user_text=user_text,
            requested_model=requested_model,
            requested_route=requested_route,
            source=source,
            messages=messages,
            stream=stream,
        )

    def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/api/plan-status":
                # GET /api/plan-status?plan_id=xxx
                from urllib.parse import urlparse as _up, parse_qs
                qs = parse_qs(_up(self.path).query)
                plan_id = (qs.get("plan_id") or [None])[0]
                if not plan_id:
                    self._json_response({"error": "plan_id required"}, code=400)
                    return
                r = _get_redis()
                if not r:
                    self._json_response({"error": "Redis unavailable"}, code=503)
                    return
                tasks_raw = r.hget(REDIS_PLANS_KEY, plan_id)
                if not tasks_raw:
                    self._json_response({"error": "plan not found"}, code=404)
                    return
                plan  = json.loads(tasks_raw)
                tasks = plan.get("tasks", [])
                task_statuses = []
                done = 0
                for t in tasks:
                    uid    = f"{plan_id}:{t.get('task_id', 0)}"
                    status = r.hget(REDIS_STATUS_KEY, uid)
                    result = r.hget(REDIS_RESULTS_KEY, uid)
                    st     = json.loads(status) if status else {"status": "queued"}
                    task_statuses.append({
                        "task_id": t.get("task_id"),
                        "task":    t.get("task", "")[:80],
                        "status":  st.get("status", "queued"),
                        "result":  result[:200] if result else None,
                    })
                    if st.get("status") == "done":
                        done += 1
                self._json_response({
                    "plan_id":    plan_id,
                    "total":      len(tasks),
                    "done":       done,
                    "complete":   done == len(tasks),
                    "tasks":      task_statuses,
                })
                return

            if path == "/api/plans":
                # List all plans from Redis task_status, grouped by plan_id
                r = _get_redis()
                if not r:
                    self._json_response({"plans": []})
                    return
                all_statuses = r.hgetall(REDIS_STATUS_KEY) or {}
                all_plans_raw = r.hgetall(REDIS_PLANS_KEY) or {}
                # Group task keys by plan_id
                plan_map: dict = {}
                for key, val in all_statuses.items():
                    parts = key.rsplit(":", 1)
                    if len(parts) != 2:
                        continue
                    pid, _ = parts
                    if not pid.startswith("PLAN-"):
                        continue
                    if pid not in plan_map:
                        plan_map[pid] = {"plan_id": pid, "steps": [], "done": 0, "failed": 0, "total": 0, "summary": ""}
                    try:
                        st = json.loads(val)
                    except Exception:
                        st = {}
                    plan_map[pid]["steps"].append(st)
                    plan_map[pid]["total"] += 1
                    if st.get("status") == "done":
                        plan_map[pid]["done"] += 1
                    elif st.get("status") == "failed":
                        plan_map[pid]["failed"] += 1
                # Enrich with plan summary from jarvis:plans
                for pid, pdata in plan_map.items():
                    raw = all_plans_raw.get(pid)
                    if raw:
                        try:
                            p = json.loads(raw)
                            pdata["summary"] = p.get("summary", "")[:80]
                            pdata["goal"] = p.get("goal", "")[:80]
                        except Exception:
                            pass
                    # Check staging dirs
                    staging_root = Path("/mnt/e/coding/staging")
                    pdata["has_dev"]    = (staging_root / "dev"      / pid).exists()
                    pdata["has_tested"] = (staging_root / "tested"   / pid).exists()
                    pdata["has_approved"]= (staging_root / "approved" / pid).exists()
                plans_list = sorted(plan_map.values(), key=lambda x: x["plan_id"], reverse=True)
                self._json_response({"plans": plans_list[:30]})
                return

            if path.startswith("/api/plans/") and path.endswith("/files"):
                # GET /api/plans/{id}/files — list staging files
                pid = path[len("/api/plans/"):-len("/files")]
                staging_root = Path("/mnt/e/coding/staging")
                result: dict = {"plan_id": pid, "dev": [], "tested": [], "approved": []}
                for stage in ("dev", "tested", "approved"):
                    d = staging_root / stage / pid
                    if d.exists():
                        result[stage] = sorted(str(f.relative_to(d)) for f in d.rglob("*") if f.is_file())
                self._json_response(result)
                return

            if path.startswith("/api/plans/") and path.endswith("/read"):
                # GET /api/plans/{id}/read?file=relative/path
                from urllib.parse import urlparse as _up2, parse_qs as _pqs2
                qs2 = _pqs2(_up2(self.path).query)
                pid = path[len("/api/plans/"):-len("/read")]
                rel = (qs2.get("file") or [None])[0]
                if not rel:
                    self._json_response({"error": "file param required"}, code=400)
                    return
                stage = (qs2.get("stage") or ["dev"])[0]
                fpath = Path("/mnt/e/coding/staging") / stage / pid / rel
                if not fpath.exists():
                    self._json_response({"error": "File not found"}, code=404)
                    return
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    self._json_response({"ok": True, "content": content, "path": str(fpath)})
                except Exception as e:
                    self._json_response({"error": str(e)}, code=500)
                return

            if path == "/api/history/plans":
                plans_root = VAULT_DIR / ".jarvis" / "history" / "plans"
                plans = []
                if plans_root.exists():
                    for p in sorted(plans_root.iterdir(), reverse=True):
                        if p.is_dir():
                            plan_file = p / "plan.json"
                            status_file = p / "status.json"
                            item = {"plan_id": p.name}
                            try:
                                if status_file.exists():
                                    item.update(json.loads(status_file.read_text(encoding="utf-8")))
                                elif plan_file.exists():
                                    item.update(json.loads(plan_file.read_text(encoding="utf-8")))
                            except Exception as e:
                                item["error"] = str(e)
                            plans.append(item)
                self._json_response({"plans": plans[:50]})
                return

            if path.startswith("/api/history/plan/"):
                plan_id = path.rsplit("/", 1)[-1]
                d = VAULT_DIR / ".jarvis" / "history" / "plans" / plan_id

                if not d.exists():
                    self._json_response({"error": "Plan not found", "plan_id": plan_id}, code=404)
                    return

                def read_json(name: str):
                    f = d / name
                    if not f.exists():
                        return None
                    return json.loads(f.read_text(encoding="utf-8"))

                events = []
                events_file = d / "events.jsonl"
                if events_file.exists():
                    for line in events_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.strip():
                            try:
                                events.append(json.loads(line))
                            except Exception:
                                pass

                self._json_response(
                    {
                        "plan_id": plan_id,
                        "plan":    read_json("plan.json"),
                        "status":  read_json("status.json"),
                        "events":  events,
                    }
                )
                return
            if path == "/api/coding-log":
                self._json_response({"events": recent_coding_events(120)})
                return
            if path == "/ws":
                self._handle_websocket_upgrade()
                return
            if path == "/api/gpu":
                self._json_response({
                    "gpus": get_gpu_stats()
                })
                return
            if path == "/api/flux/status":
                try:
                    result_file = BRIDGE_DIR / "flux_result.json"

                    if result_file.exists():
                        with open(result_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    else:
                        data = {"status": "idle"}

                    self._json_response(data)
                except Exception as e:
                    self._json_response(
                        {
                            "status":  "error",
                            "message": str(e),
                        },
                        500,
                    )
                return
            if path == "/api/flux":
                data=read_json_body(self)
                prompt = str(data.get("prompt", "")).strip()

                if not prompt:
                    self._json_response({"error": "No prompt"}, 400)
                    return

                width  = int(data.get("width", 1024) or 1024)
                height = int(data.get("height", 1024) or 1024)

                result_file = BRIDGE_DIR / "flux_result.json"
                result_file.parent.mkdir(parents=True, exist_ok=True)
                result_file.write_text(
                    json.dumps({"status": "generating"}, ensure_ascii=False),
                    encoding="utf-8",
                )

                def _generate():
                    try:
                        emit_event("flux", "FLUX generation started", {
                            "prompt": prompt[:200],
                            "width":  width,
                            "height": height,
                        })

                        import importlib
                        flux_mod = importlib.import_module("skills.flux")

                        result = flux_mod.exec_generate_image(
                            prompt,
                            enhance="no",
                        )

                        result_file.write_text(
                            json.dumps(
                                {
                                    "status":  "done",
                                    "message": result,
                                    "prompt":  prompt,
                                    "width":   width,
                                    "height":  height,
                                },
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )

                        emit_event("flux", "FLUX generation finished", {
                            "result": str(result)[:300],
                        })

                    except Exception as e:
                        result_file.write_text(
                            json.dumps(
                                {
                                    "status":  "error",
                                    "message": str(e),
                                },
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )

                        emit_event("warning", "FLUX generation failed", {
                            "error": str(e),
                        })

                threading.Thread(target=_generate, daemon=True).start()

                self._json_response({
                    "status": "generating",
                    "poll":   "/api/flux/status",
                })
                return
            if path == "/api/health":
                try:
                    tags = request_ollama_tags()
                    ollama_ready = True
                    ollama_models = len(tags.get("models", []))
                except Exception:
                    ollama_ready = False
                    ollama_models = 0
                profile = load_active_profile()
                redis_ok = _redis_available()
                redis_state = read_state() if redis_ok else {}
                self._json_response(
                    {
                        "status":              "ok",
                        "service":             "jarvis-react-v3",
                        "time":                now_iso(),
                        "ollama_host":         OLLAMA_HOST,
                        "ollama_ready":        ollama_ready,
                        "ollama_model_count":  ollama_models,
                        "loaded_skills":       len(get_loaded_skills()),
                        "tool_count":          len(TOOL_MAP),
                        "active_profile":      {"id": profile.get("id"), "label": profile.get("label")},
                        "models":              load_model_config().get("models", {}),
                        "planner_model":       get_planner_model(),
                        "redis_ok":            redis_ok,
                        "redis_loop_count":    redis_state.get("loop_count", 0),
                        "redis_task":          redis_state.get("task", ""),
                    }
                )
                return

            if path == "/api/skills":
                self._json_response(
                    {
                        "skills":                get_loaded_skills(),
                        "tools":                 list(TOOL_MAP.keys()),
                        "tool_keywords":         TOOL_KEYWORDS,
                        "tool_skill_meta":       TOOL_SKILL_META,
                        "intent_tool_candidates": INTENT_TOOL_CANDIDATES,
                        "tool_route_hints":      TOOL_ROUTE_HINTS,
                        "no_tools_models":       sorted(NO_TOOLS_MODELS),
                    }
                )
                return

            if path == "/api/models":
                cfg = load_model_config()
                self._json_response({"models": cfg.get("models", {}), "planner_model": get_planner_model()})
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
                    self._json_response({**get_radio_state(), "stations": get_stations(), "now_playing": get_now_playing()})
                except ImportError:
                    self._json_response({"playing": False, "stations": {}})
                return
            
            if path == "/api/tts/health":
                try:
                    with urllib.request.urlopen(
                        f"{KOKORO_HOST}/tts/health",
                        timeout=KOKORO_TIMEOUT_SEC,
                    ) as resp:
                        data = json.loads(resp.read().decode("utf-8"))

                    self._json_response(data)

                except Exception as e:
                    self._json_response({
                        "status":     "error",
                        "error":      str(e),
                        "kokoro_host": KOKORO_HOST,
                    }, code=500)

                return
            if path == "/api/tts/test":
                try:
                    payload = {
                        "text":  "Systems online. JARVIS is ready.",
                        "voice": KOKORO_VOICE,
                    }

                    req = urllib.request.Request(
                        f"{KOKORO_HOST}/tts/speak",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )

                    with urllib.request.urlopen(req, timeout=KOKORO_TIMEOUT_SEC) as resp:
                        data = json.loads(resp.read().decode("utf-8"))

                    self._json_response(data)

                except Exception as e:
                    self._json_response({
                        "status":     "error",
                        "error":      str(e),
                        "kokoro_host": KOKORO_HOST,
                    }, code=500)

                return
            if path == "/api/reload":
                try:
                    result = reload_all_skills()
                    self._json_response(result)
                except Exception as e:
                    self._json_response({"error": str(e)}, code=500)
                return

            if path == "/api/network":
                try:
                    from skills.network import get_topology  # type: ignore
                    self._json_response(get_topology())
                except ImportError:
                    self._json_response({"devices": [], "gateway": "192.168.0.1"})
                return

            if path == "/api/self":
                try:
                    runtime_persona = None
                    if RUNTIME_MODE_PATH.exists():
                        runtime_persona = json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8")).get("persona")
                except Exception:
                    runtime_persona = None
                self._json_response(build_self_context(persona=runtime_persona))
                return

            if path == "/api/runtime-mode":
                try:
                    if RUNTIME_MODE_PATH.exists():
                        self._json_response(json.loads(RUNTIME_MODE_PATH.read_text(encoding="utf-8")))
                    else:
                        self._json_response({"mode": "conversation", "persona": "jarvis"})
                except Exception as e:
                    self._json_response({"error": str(e)}, code=500)
                return

            if path == "/api/redis":
                try:
                    redis_ok = _redis_available()
                    state    = read_state() if redis_ok else {}
                    memory   = read_memory() if redis_ok else []
                    tools_h  = read_tools() if redis_ok else {}
                    self._json_response({
                        "redis_ok":      redis_ok,
                        "state":         state,
                        "working_memory": memory[-20:],
                        "tools":         tools_h,
                        "loop_count":    read_loop() if redis_ok else 0,
                    })
                except Exception as e:
                    self._json_response({"error": str(e)}, code=500)
                return

            self.send_error(404)


    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json_response(self, payload: Dict[str, Any], code: int = 200) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError:
            emit_event(
                "warning",
                "Client disconnected before response could be sent",
                {"code": code},
            )
        except Exception as e:
            emit_event(
                "warning",
                "Failed sending JSON response",
                {"error": str(e), "code": code},
            )

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
    if KOKORO_ENABLED:
        try:
            sync_kokoro_for_route("fast", resolve_model(requested_model=None, route="fast"))
        except Exception as e:
            emit_event("warning", "Initial Kokoro warm start failed", {"error": str(e)})

    # Initialise Redis agent state
    try:
        if _redis_available():
            write_state(
                "JARVIS",
                task="idle",
                tools={name: True for name in (read_tools() or {}).keys()},
                confidence="high",
                notes="react_server startup",
            )
            write_tools({name: True for name in TOOL_MAP.keys()})
            emit_event("status", "Redis state initialised", {"tool_count": len(TOOL_MAP)})
        else:
            emit_event("warning", "Redis unavailable at startup — state persistence disabled", {})
    except Exception as e:
        emit_event("warning", "Redis init failed", {"error": str(e)})

    server = ThreadingHTTPServer(("127.0.0.1", PORT), ReactHandler)
    print(f"[REACT] ReAct server v3 on http://127.0.0.1:{PORT}")

    # Optional extra bind for container access (e.g. n8n → POST /api/events).
    # Set JARVIS_BIND_EXTRA to the podman bridge gateway (e.g. 10.89.0.1) so
    # containers on jarvis-net can reach the API. This interface is NOT
    # LAN-routable, so it does not expose the API beyond the podman bridge.
    _extra_host = os.environ.get("JARVIS_BIND_EXTRA", "").strip()
    if _extra_host:
        try:
            import threading as _threading
            _extra_server = ThreadingHTTPServer((_extra_host, PORT), ReactHandler)
            _threading.Thread(target=_extra_server.serve_forever, daemon=True).start()
            print(f"[REACT] Extra bind for containers: http://{_extra_host}:{PORT}")
        except Exception as _e:
            print(f"[REACT] Extra bind on {_extra_host}:{PORT} failed: {_e}")
    print(f"[REACT] Ollama backend: {OLLAMA_HOST}")
    print(f"[REACT] Vault: {VAULT_DIR}")
    print(f"[REACT] Bridge: {BRIDGE_DIR}")
    print(f"[REACT] Active profile path: {ACTIVE_PROFILE_PATH}")
    print(f"[REACT] Profiles dir: {PROFILES_DIR}")
    print(f"[REACT] Runtime mode path: {RUNTIME_MODE_PATH}")
    print(f"[REACT] Tools ({len(TOOL_MAP)}): {', '.join(TOOL_MAP.keys())}")
    print(f"[REACT] Redis: {'✓' if _redis_available() else '✗ (degraded mode)'}")
    print("[REACT] READY")
    emit_event("status", "React server ready", {"port": PORT, "tool_count": len(TOOL_MAP)})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[REACT] Server stopped")
        emit_event("status", "React server stopped")
        server.server_close()