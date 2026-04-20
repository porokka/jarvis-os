"""
JARVIS Skill — Countdown timers with TTS alerts.
"""

import os
import subprocess
import threading
import time
from itertools import count
from pathlib import Path
from typing import Dict, List, Optional


SKILL_NAME = "timer"
SKILL_DESCRIPTION = "Countdown timers with voice alerts"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "productivity"
SKILL_TAGS = ["timer", "countdown", "tts", "alert", "reminder"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "set_timer",
    "list_timers",
    "cancel_timer",
    "timer_alert",
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
    "network_access": False,
    "entrypoint": "exec_timer",
}

VAULT_DIR = Path("D:/Jarvis_vault") if os.name == "nt" else Path("/mnt/d/Jarvis_vault")
BRIDGE_DIR = Path("/tmp/jarvis") if os.name != "nt" else Path("D:/Jarvis_bridge")

ACTIVE_TIMERS: List[Dict] = []
TIMERS_LOCK = threading.Lock()
TIMER_ID_COUNTER = count(1)


def _ensure_dirs() -> None:
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _log_timer_event(text: str) -> None:
    try:
        _ensure_dirs()
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except Exception:
        pass


def _set_bridge_state(output: Optional[str] = None, state: Optional[str] = None, emotion: Optional[str] = None) -> None:
    try:
        _ensure_dirs()
        if output is not None:
            (BRIDGE_DIR / "output.txt").write_text(output, encoding="utf-8")
        if state is not None:
            (BRIDGE_DIR / "state.txt").write_text(state, encoding="utf-8")
        if emotion is not None:
            (BRIDGE_DIR / "emotion.txt").write_text(emotion, encoding="utf-8")
    except Exception:
        pass


def _remove_timer(timer_id: int) -> None:
    with TIMERS_LOCK:
        ACTIVE_TIMERS[:] = [t for t in ACTIVE_TIMERS if t["id"] != timer_id]


def _find_timer(timer_id: int) -> Optional[Dict]:
    with TIMERS_LOCK:
        for t in ACTIVE_TIMERS:
            if t["id"] == timer_id:
                return t
    return None


def _escape_powershell_single_quoted(text: str) -> str:
    return (text or "").replace("'", "''")


def _speak_text(text: str) -> None:
    safe = _escape_powershell_single_quoted(text)

    if os.name == "nt":
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Speech; "
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "$s.Rate = 0; "
                        f"$s.Speak('{safe}')"
                    ),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    else:
        # Non-Windows fallback: no direct TTS, but bridge/log still update
        pass


def _timer_callback(message: str, timer_id: int) -> None:
    """Called when a timer fires — speaks directly, bypasses LLM."""
    alert = f"Sir, your timer has gone off. {message}".strip()

    try:
        _set_bridge_state(output=alert, state="speaking", emotion="neutral")
        _log_timer_event(f"TIMER ALERT: {message}")
        _speak_text(alert)
        print(f"[TIMER] Timer {timer_id} fired: {message}")
    except Exception as e:
        print(f"[TIMER] Error: {e}")

    def reset_state() -> None:
        time.sleep(5)
        _set_bridge_state(state="standby")

    threading.Thread(target=reset_state, daemon=True).start()
    _remove_timer(timer_id)


def _format_time_str(minutes: float, seconds: int) -> str:
    if minutes < 1:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if float(minutes).is_integer():
        whole = int(minutes)
        return f"{whole} minute{'s' if whole != 1 else ''}"
    return f"{minutes} minutes"


def exec_set_timer(minutes: float, message: str) -> str:
    try:
        minutes = float(minutes)
    except Exception:
        return "Error: minutes must be a number"

    if minutes <= 0:
        return "Error: timer must be greater than 0 minutes"

    seconds = max(1, int(minutes * 60))
    timer_id = next(TIMER_ID_COUNTER)

    timer = threading.Timer(seconds, _timer_callback, args=[message, timer_id])
    timer.daemon = True
    timer.start()

    with TIMERS_LOCK:
        ACTIVE_TIMERS.append(
            {
                "id": timer_id,
                "message": message,
                "seconds": seconds,
                "start": time.time(),
                "timer": timer,
            }
        )

    time_str = _format_time_str(minutes, seconds)
    _log_timer_event(f"TIMER SET #{timer_id}: {message} in {time_str}")
    return f"Timer #{timer_id} set: {message} in {time_str}."


def get_active_timers() -> list:
    """Return active timers for the API."""
    now = time.time()
    result = []

    with TIMERS_LOCK:
        for t in ACTIVE_TIMERS:
            remaining = int(t["seconds"] - (now - t["start"]))
            if remaining > 0:
                result.append(
                    {
                        "id": t["id"],
                        "message": t["message"],
                        "remaining": remaining,
                        "total": t["seconds"],
                    }
                )

    return result


def exec_cancel_timer(timer_id: int) -> str:
    try:
        timer_id = int(timer_id)
    except Exception:
        return "Error: timer_id must be an integer"

    target = _find_timer(timer_id)
    if not target:
        return f"Timer #{timer_id} not found."

    try:
        target["timer"].cancel()
    except Exception:
        pass

    _remove_timer(timer_id)
    _log_timer_event(f"TIMER CANCELED #{timer_id}: {target['message']}")
    return f"Canceled timer #{timer_id}."


def exec_list_timers() -> str:
    timers = get_active_timers()
    if not timers:
        return "No active timers."

    lines = []
    for t in timers:
        lines.append(
            f"  #{t['id']} — {t['message']} ({t['remaining']}s remaining)"
        )
    return "Active timers:\n" + "\n".join(lines)


def exec_timer(action: str, minutes: float = 0, message: str = "", timer_id: int = 0) -> str:
    action = (action or "").strip().lower()

    if action == "set":
        if not message:
            return "Error: message is required"
        return exec_set_timer(minutes=minutes, message=message)

    if action == "list":
        return exec_list_timers()

    if action == "cancel":
        if not timer_id:
            return "Error: timer_id is required for cancel"
        return exec_cancel_timer(timer_id)

    return "Available actions: set, list, cancel"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "timer",
            "description": "Manage countdown timers with voice alerts. Actions: set, list, cancel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["set", "list", "cancel"],
                        "description": "Timer action to perform.",
                    },
                    "minutes": {
                        "type": "number",
                        "description": "Minutes from now for action=set. Example: 5, 0.5 for 30 seconds, 60 for 1 hour.",
                    },
                    "message": {
                        "type": "string",
                        "description": "What to say when timer goes off. Used with action=set.",
                    },
                    "timer_id": {
                        "type": "integer",
                        "description": "Timer ID for action=cancel.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "timer": exec_timer,
}

KEYWORDS = {
    "timer": [
        "timer",
        "alarm",
        "remind",
        "minutes",
        "seconds",
        "wake me",
        "alert me",
        "countdown",
        "cancel timer",
        "list timers",
    ],
}

SKILL_EXAMPLES = [
    {"command": "set a timer for 5 minutes", "tool": "timer", "args": {"action": "set", "minutes": 5, "message": "5 minute timer"}},
    {"command": "set a timer for 30 seconds", "tool": "timer", "args": {"action": "set", "minutes": 0.5, "message": "30 second timer"}},
    {"command": "show active timers", "tool": "timer", "args": {"action": "list"}},
    {"command": "cancel timer 2", "tool": "timer", "args": {"action": "cancel", "timer_id": 2}},
]