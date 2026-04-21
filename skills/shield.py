"""
JARVIS Skill — NVIDIA Shield TV control per room.

Controls Shield TVs via ADB + HDMI-CEC. Launches apps, navigates,
controls playback, and coordinates with Denon for input switching.

Config files (editable by AI):
  config/rooms.json       — room name → IP mapping
  config/shield_apps.json — app name → ADB launch command
"""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional


SKILL_NAME = "shield"
SKILL_DESCRIPTION = "NVIDIA Shield TV — apps, playback, navigation, HDMI-CEC, per-room control"
SKILL_VERSION = "1.2.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "media"
SKILL_TAGS = ["shield", "nvidia", "adb", "tv", "android-tv", "denon", "hdmi-cec", "memory"]
SKILL_REQUIREMENTS = ["adb", "config/rooms.json", "config/shield_apps.json"]
SKILL_CAPABILITIES = [
    "room_control",
    "app_launch",
    "navigation",
    "playback_control",
    "input_switching",
    "denon_preset",
    "room_listing",
    "app_listing",
    "device_status",
    "memory_integration",
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
    "entrypoint": "exec_room_command",
    "config_dir": "config",
    "config_files": ["config/rooms.json", "config/shield_apps.json"],
}


# -- Config paths --

CONFIG_DIR = Path(__file__).parent.parent / "config"
ROOMS_CONFIG = CONFIG_DIR / "rooms.json"
APPS_CONFIG = CONFIG_DIR / "shield_apps.json"


# -- Memory helpers --

def _memory_call(action: str, key: str = "", value: str = "", event_type: str = "", data: dict = None, query: str = ""):
    """
    Best-effort bridge to memory skill.
    Returns None if memory skill is unavailable or errors.
    """
    try:
        from skills.memory import exec_memory
        return exec_memory(
            action=action,
            key=key,
            value=value,
            event_type=event_type,
            data=data,
            query=query,
        )
    except Exception:
        return None


def _remember_preference(key: str, value: str) -> None:
    _memory_call("set_preference", key=key, value=value)


def _remember_recent(key: str, value: str) -> None:
    _memory_call("set_recent", key=key, value=value)


def _log_memory_event(event_type: str, data: dict) -> None:
    _memory_call("log_event", event_type=event_type, data=data or {})


def _get_memory_preference(key: str) -> Optional[str]:
    try:
        from skills.memory import _load_state  # type: ignore
        state = _load_state()
        value = state.get("identity", {}).get(key)
        return str(value) if value is not None else None
    except Exception:
        return None


# -- Config loading --

def _normalize_room_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _load_rooms() -> dict:
    """Load rooms from config file (re-read each call so AI edits take effect)."""
    fallback = {
        "livingroom": {
            "ip": "192.168.0.31",
            "name": "Living Room Shield Pro",
        }
    }

    try:
        data = json.loads(ROOMS_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return fallback

        clean = {}
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            room_key = _normalize_room_name(key)
            if not room_key:
                continue

            ip = str(value.get("ip", "")).strip()
            name = str(value.get("name", key)).strip()
            clean[room_key] = {"ip": ip, "name": name}

        return clean or fallback
    except Exception:
        return fallback


def _load_apps() -> dict:
    """Load app commands from config file."""
    try:
        data = json.loads(APPS_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}

        clean = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str):
                clean[key.lower().strip()] = value.strip()
        return clean
    except Exception:
        return {}


# -- Navigation commands (built-in, not configurable) --

NAV_COMMANDS_MAP = {
    "home": "input keyevent KEYCODE_HOME",
    "back": "input keyevent KEYCODE_BACK",
    "play": "input keyevent KEYCODE_MEDIA_PLAY_PAUSE",
    "pause": "input keyevent KEYCODE_MEDIA_PLAY_PAUSE",
    "stop": "input keyevent KEYCODE_MEDIA_STOP",
    "next": "input keyevent KEYCODE_MEDIA_NEXT",
    "previous": "input keyevent KEYCODE_MEDIA_PREVIOUS",
    "up": "input keyevent KEYCODE_DPAD_UP",
    "down": "input keyevent KEYCODE_DPAD_DOWN",
    "left": "input keyevent KEYCODE_DPAD_LEFT",
    "right": "input keyevent KEYCODE_DPAD_RIGHT",
    "select": "input keyevent KEYCODE_DPAD_CENTER",
    "ok": "input keyevent KEYCODE_DPAD_CENTER",
    "menu": "input keyevent KEYCODE_MENU",
    "settings": "am start -n com.android.tv.settings/.MainSettings",
    "sleep": "input keyevent KEYCODE_SLEEP",
    "power": "input keyevent KEYCODE_POWER",
    "wake": "input keyevent KEYCODE_WAKEUP",
    "hdmi-cec-on": "cmd hdmi_control onetouchplay",
    "tv-on": "input keyevent KEYCODE_WAKEUP && cmd hdmi_control onetouchplay",
    "volume-up": "input keyevent KEYCODE_VOLUME_UP",
    "volume-down": "input keyevent KEYCODE_VOLUME_DOWN",
    "mute": "input keyevent KEYCODE_VOLUME_MUTE",
}

NAV_COMMANDS = {
    "home", "back", "up", "down", "left", "right", "select", "ok",
    "play", "pause", "stop", "next", "previous", "menu",
    "volume-up", "volume-down", "mute", "wake", "sleep", "power",
}


def _split_shell_chain(cmd: str):
    """Split simple adb shell command chains joined by &&."""
    return [part.strip() for part in cmd.split("&&") if part.strip()]


# -- ADB helper --

def _adb(ip: str, cmd: str) -> str:
    """Run one or more ADB shell commands on a Shield."""
    try:
        subprocess.run(
            ["adb", "connect", f"{ip}:5555"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        outputs = []
        for part in _split_shell_chain(cmd):
            result = subprocess.run(
                ["adb", "-s", f"{ip}:5555", "shell", part],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = ((result.stdout or "") + (result.stderr or "")).strip()
            if result.returncode != 0:
                return f"ADB command failed: {text or f'exit {result.returncode}'}"
            if text:
                outputs.append(text)

        return "\n".join(outputs).strip() or "OK"

    except subprocess.TimeoutExpired:
        return "ADB command timed out"
    except Exception as e:
        return f"ADB error: {e}"


def _adb_ping(ip: str) -> str:
    """Basic connectivity/status check."""
    return _adb(ip, "echo shield-ok")


def _denon_switch_input(input_name: str) -> str:
    """Switch Denon input — delegates to denon skill if loaded."""
    try:
        from skills.denon import exec_denon_input
        return exec_denon_input(input_name)
    except ImportError:
        return "Denon skill not loaded"
    except Exception as e:
        return f"Denon error: {e}"


def _denon_preset(preset: str) -> str:
    """Execute Denon preset — delegates to denon skill if loaded."""
    try:
        from skills.denon import exec_denon_preset
        return exec_denon_preset(preset)
    except ImportError:
        return "Denon skill not loaded"
    except Exception as e:
        return f"Denon error: {e}"


def _maybe_wake_and_switch(ip: str) -> None:
    _adb(ip, "input keyevent KEYCODE_WAKEUP")
    time.sleep(0.5)
    _denon_switch_input("shield")
    time.sleep(0.3)


def _resolve_room(room: str) -> str:
    """
    If room omitted/blank, use remembered default room if available.
    """
    room_key = _normalize_room_name(room or "")
    if room_key:
        return room_key

    remembered = _get_memory_preference("default_shield_room")
    if remembered:
        return _normalize_room_name(remembered)

    return "livingroom"


# -- Tool executors --

def exec_room_command(room: str, action: str) -> str:
    """Control a room's NVIDIA Shield + Denon receiver."""
    rooms = _load_rooms()
    room_key = _resolve_room(room)
    action = (action or "").strip()

    if not action:
        return "Specify an action."

    action_lower = action.lower().strip()

    if action_lower == "rooms":
        lines = [f"  {key} — {value.get('name', key)} ({value.get('ip', 'no ip')})" for key, value in sorted(rooms.items())]
        return "Available rooms:\n" + "\n".join(lines)

    if action_lower == "apps":
        apps = _load_apps()
        if not apps:
            return "No Shield apps configured."
        lines = [f"  {name}" for name in sorted(apps.keys())]
        return "Configured apps:\n" + "\n".join(lines)

    if room_key not in rooms:
        return f"Unknown room '{room}'. Available: {', '.join(sorted(rooms.keys()))}"

    ip = str(rooms[room_key].get("ip", "")).strip()
    room_name = str(rooms[room_key].get("name", room_key)).strip()

    if not ip:
        return f"No Shield IP configured for {room_key}. Configure it in rooms.json."

    # Save room context early for successful room-targeted actions
    _remember_recent("last_shield_room", room_key)
    _remember_preference("default_shield_room", room_key)

    if action_lower == "status":
        result = _adb_ping(ip)
        _remember_recent("last_shield_status_room", room_key)
        _log_memory_event(
            "shield_status_checked",
            {
                "room": room_key,
                "room_name": room_name,
                "status": "online" if not result.startswith("ADB") else "offline",
                "details": result,
            },
        )
        if result.startswith("ADB"):
            return f"{room_name}: offline or unavailable\n{result}"
        return f"{room_name}: online"

    # Handle search
    if action_lower.startswith("search:"):
        query = action[7:].strip()
        if not query:
            return "Usage: search:QUERY"
        _maybe_wake_and_switch(ip)
        cmd = f'am start -a android.intent.action.VIEW -d "https://www.netflix.com/search?q={query}"'
        result = _adb(ip, cmd)
        if result.startswith("ADB"):
            return result

        _remember_recent("last_shield_action", "search")
        _remember_recent("last_shield_search", query)
        _log_memory_event(
            "shield_search_started",
            {
                "room": room_key,
                "room_name": room_name,
                "query": query,
                "service": "netflix",
            },
        )
        return f"Searching '{query}' on {room_name}"

    # Spotify search/play
    if action_lower.startswith("spotify:"):
        query = action[8:].strip()
        if not query:
            return "Usage: spotify:ARTIST_OR_SONG"
        _maybe_wake_and_switch(ip)
        cmd = f'am start -a android.intent.action.VIEW -d "spotify:search:{query}"'
        result = _adb(ip, cmd)
        if result.startswith("ADB"):
            return result

        _remember_recent("last_shield_action", "spotify")
        _remember_recent("last_shield_app", "spotify")
        _remember_recent("last_shield_spotify_query", query)
        _log_memory_event(
            "shield_spotify_started",
            {
                "room": room_key,
                "room_name": room_name,
                "query": query,
            },
        )
        return f"Playing '{query}' on Spotify in {room_name}"

    # Denon presets
    if action_lower in ("headphones", "headset", "night", "speakers", "quiet", "both"):
        denon_result = _denon_preset(action_lower)
        _remember_recent("last_shield_action", action_lower)
        _remember_recent("last_shield_denon_preset", action_lower)
        _log_memory_event(
            "shield_denon_preset",
            {
                "room": room_key,
                "room_name": room_name,
                "preset": action_lower,
                "result": denon_result,
            },
        )
        return denon_result

    # Switch to PC
    if action_lower in ("pc", "computer", "monitor"):
        denon = _denon_switch_input("pc")
        _remember_recent("last_shield_action", "pc")
        _remember_recent("last_shield_pc_room", room_key)
        _log_memory_event(
            "shield_switched_to_pc",
            {
                "room": room_key,
                "room_name": room_name,
                "denon_result": denon,
            },
        )
        return f"Switched to PC in {room_name}. {denon}"

    # Activate Shield (wake + CEC + Denon input)
    if action_lower in ("activate", "switch", "focus", "tv"):
        _adb(ip, "input keyevent KEYCODE_WAKEUP")
        time.sleep(1)
        _adb(ip, "cmd hdmi_control onetouchplay")
        denon = _denon_switch_input("shield")

        _remember_recent("last_shield_action", "activate")
        _log_memory_event(
            "shield_activated",
            {
                "room": room_key,
                "room_name": room_name,
                "denon_result": denon,
            },
        )
        return f"Activated {room_name} — Shield on, Denon switched. {denon}"

    # Check nav commands first, then apps from config
    cmd = NAV_COMMANDS_MAP.get(action_lower)
    is_nav = bool(cmd)

    if not cmd:
        apps = _load_apps()
        cmd = apps.get(action_lower)

    if not cmd:
        apps = _load_apps()
        available = ", ".join(sorted(set(list(NAV_COMMANDS_MAP.keys()) + list(apps.keys()) + ["rooms", "apps", "status"])))
        return f"Unknown action '{action}'. Available: {available}"

    # For app launches, wake + switch Denon
    if action_lower not in NAV_COMMANDS:
        _maybe_wake_and_switch(ip)

    result = _adb(ip, cmd)
    if result.startswith("ADB"):
        return result

    _remember_recent("last_shield_action", action_lower)
    if is_nav or action_lower in NAV_COMMANDS:
        _log_memory_event(
            "shield_navigation_action",
            {
                "room": room_key,
                "room_name": room_name,
                "action": action_lower,
            },
        )
    else:
        _remember_recent("last_shield_app", action_lower)
        _log_memory_event(
            "shield_app_launched",
            {
                "room": room_key,
                "room_name": room_name,
                "app": action_lower,
            },
        )

    return f"{action} on {room_name}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "room_command",
            "description": (
                "Control a room's NVIDIA Shield TV and optionally coordinate with Denon receiver input switching. "
                "Supports app launch, playback, navigation, room listing, app listing, and status checks. "
                "Remembers default room, last action, and recent app/search usage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Room name: livingroom, office, bedroom. If blank in planner usage, remembered default room can be used.",
                    },
                    "action": {
                        "type": "string",
                        "description": (
                            "Action such as netflix, youtube, spotify, plex, disney, prime, "
                            "play, pause, next, previous, home, back, activate, status, rooms, apps, "
                            "headphones, speakers, sleep, search:QUERY, spotify:ARTIST_OR_SONG"
                        ),
                    },
                },
                "required": ["room", "action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "room_command": exec_room_command,
}

KEYWORDS = {
    "room_command": [
        "livingroom", "living room", "office", "bedroom", "shield",
        "netflix", "watch", "tv", "plex", "disney", "hbo", "spotify",
        "prime", "youtube", "twitch", "apple tv", "activate",
        "headphones", "speakers", "denon", "vinyl", "phono",
        "shield status", "room apps", "room list",
    ],
}

SKILL_EXAMPLES = [
    {"command": "activate living room shield", "tool": "room_command", "args": {"room": "livingroom", "action": "activate"}},
    {"command": "open plex in bedroom", "tool": "room_command", "args": {"room": "bedroom", "action": "plex"}},
    {"command": "pause office shield", "tool": "room_command", "args": {"room": "office", "action": "pause"}},
    {"command": "search stranger things on living room netflix", "tool": "room_command", "args": {"room": "livingroom", "action": "search:Stranger Things"}},
    {"command": "play metallica on spotify in office", "tool": "room_command", "args": {"room": "office", "action": "spotify:Metallica"}},
    {"command": "show shield rooms", "tool": "room_command", "args": {"room": "livingroom", "action": "rooms"}},
]