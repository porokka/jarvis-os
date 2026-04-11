"""
JARVIS Skill — NVIDIA Shield TV control per room.

Controls Shield TVs via ADB + HDMI-CEC. Launches apps, navigates,
controls playback, and coordinates with Denon for input switching.

Config files (editable by AI):
  config/rooms.json       — room name → IP mapping
  config/shield_apps.json — app name → ADB launch command
"""

import json
import subprocess
import time
from pathlib import Path

SKILL_NAME = "shield"
SKILL_DESCRIPTION = "NVIDIA Shield TV — apps, playback, navigation, HDMI-CEC, per-room control"

# -- Config paths --

CONFIG_DIR = Path(__file__).parent.parent / "config"
ROOMS_CONFIG = CONFIG_DIR / "rooms.json"
APPS_CONFIG = CONFIG_DIR / "shield_apps.json"


def _load_rooms() -> dict:
    """Load rooms from config file (re-read each call so AI edits take effect)."""
    try:
        return json.loads(ROOMS_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {"livingroom": {"ip": "192.168.0.31", "name": "Living Room Shield Pro"}}


def _load_apps() -> dict:
    """Load app commands from config file."""
    try:
        return json.loads(APPS_CONFIG.read_text(encoding="utf-8"))
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
    "hdmi-cec-on": "input keyevent KEYCODE_TV",
    "tv-on": "input keyevent KEYCODE_WAKEUP && input keyevent KEYCODE_TV",
    "volume-up": "input keyevent KEYCODE_VOLUME_UP",
    "volume-down": "input keyevent KEYCODE_VOLUME_DOWN",
    "mute": "input keyevent KEYCODE_VOLUME_MUTE",
}

NAV_COMMANDS = {
    "home", "back", "up", "down", "left", "right", "select", "ok",
    "play", "pause", "stop", "next", "previous", "menu",
    "volume-up", "volume-down", "mute",
}


# -- ADB helper --

def _adb(ip: str, cmd: str) -> str:
    """Run an ADB command on a Shield."""
    try:
        subprocess.run(["adb", "connect", f"{ip}:5555"], capture_output=True, timeout=5)
        result = subprocess.run(
            ["adb", "-s", f"{ip}:5555", "shell", cmd],
            capture_output=True, text=True, timeout=10,
        )
        return (result.stdout + result.stderr).strip() or "OK"
    except subprocess.TimeoutExpired:
        return "ADB command timed out"
    except Exception as e:
        return f"ADB error: {e}"


def _denon_switch_input(input_name: str) -> str:
    """Switch Denon input — delegates to denon skill if loaded."""
    try:
        from skills.denon import exec_denon_input
        return exec_denon_input(input_name)
    except ImportError:
        return "Denon skill not loaded"


def _denon_preset(preset: str) -> str:
    """Execute Denon preset — delegates to denon skill if loaded."""
    try:
        from skills.denon import exec_denon_preset
        return exec_denon_preset(preset)
    except ImportError:
        return "Denon skill not loaded"


# -- Tool executors --

def exec_room_command(room: str, action: str) -> str:
    """Control a room's NVIDIA Shield + Denon receiver."""
    rooms = _load_rooms()
    room = room.lower().replace(" ", "")
    if room not in rooms:
        return f"Unknown room '{room}'. Available: {', '.join(rooms.keys())}"

    ip = rooms[room]["ip"]
    if not ip:
        return f"No Shield IP configured for {room}. Run scan_network first."

    # Handle search
    if action.startswith("search:"):
        query = action[7:].strip()
        cmd = f'am start -a android.intent.action.VIEW -d "https://www.netflix.com/search?q={query}"'
        _adb(ip, cmd)
        return f"Searching '{query}' on {ROOMS[room]['name']}"

    # Spotify search/play
    if action.startswith("spotify:"):
        query = action[8:].strip()
        _adb(ip, "input keyevent KEYCODE_WAKEUP")
        time.sleep(0.5)
        _denon_switch_input("shield")
        time.sleep(0.5)
        cmd = f'am start -a android.intent.action.VIEW -d "spotify:search:{query}"'
        _adb(ip, cmd)
        return f"Playing '{query}' on Spotify"

    action_lower = action.lower()

    # Denon presets
    if action_lower in ("headphones", "headset", "night", "speakers", "quiet", "both"):
        return _denon_preset(action_lower)

    # Switch to PC
    if action_lower in ("pc", "computer", "monitor"):
        _denon_switch_input("pc")
        return "Switched to PC, sir. Monitor is yours."

    # Activate Shield (wake + CEC + Denon input)
    if action_lower in ("activate", "switch", "focus", "tv"):
        _adb(ip, "input keyevent KEYCODE_WAKEUP")
        time.sleep(1)
        _adb(ip, "cmd hdmi_control onetouchplay")
        _denon_switch_input("shield")
        return f"Activated {rooms[room]['name']} — Shield on, Denon switched"

    # Check nav commands first, then apps from config
    cmd = NAV_COMMANDS_MAP.get(action_lower)
    if not cmd:
        apps = _load_apps()
        cmd = apps.get(action_lower)

    if not cmd:
        apps = _load_apps()
        available = ", ".join(sorted(set(list(NAV_COMMANDS_MAP.keys()) + list(apps.keys()))))
        return f"Unknown action '{action}'. Available: {available}"

    # For app launches, wake + switch Denon
    if action_lower not in NAV_COMMANDS:
        _adb(ip, "input keyevent KEYCODE_WAKEUP")
        time.sleep(0.5)
        _denon_switch_input("shield")
        time.sleep(0.3)

    _adb(ip, cmd)
    return f"{action.capitalize()} on {rooms[room]['name']}"


def exec_scan_network() -> str:
    """Scan LAN for NVIDIA Shields and Cast devices."""
    try:
        result = subprocess.run(
            ["nmap", "-p", "5555,8008,8443", "--open", "-oG", "-", "192.168.0.0/24"],
            capture_output=True, text=True, timeout=60,
        )
        devices = []
        for line in result.stdout.split("\n"):
            if "/open" in line:
                parts = line.split()
                ip = parts[1] if len(parts) > 1 else "?"
                ports = [p for p in line.split() if "/open" in p]
                devices.append(f"{ip} — ports: {', '.join(ports)}")

        if not devices:
            return "No Shields found with ADB enabled. Enable: Settings > Developer Options > Network debugging"

        report = "Devices with open ADB/Cast ports:\n" + "\n".join(f"  {d}" for d in devices)
        report += "\n\nTo assign to rooms, tell me which IP is which room."
        return report
    except Exception as e:
        return f"Scan error: {e}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "room_command",
            "description": "Control a room's NVIDIA Shield TV and Denon receiver. Default room is livingroom. When user says 'play [artist/song]' without specifying a service, use spotify:[artist] action. Can open apps, control playback, switch inputs. Also handles headphones/speakers/denon presets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Room name: livingroom (default), office, or bedroom",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action: netflix, youtube, spotify, plex, disney, prime, play, pause, next, previous, home, back, activate, headphones, speakers, sleep, search:QUERY, spotify:ARTIST_OR_SONG",
                    },
                },
                "required": ["room", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_network",
            "description": "Scan the local network for NVIDIA Shields, smart TVs, and Cast devices.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

TOOL_MAP = {
    "room_command": exec_room_command,
    "scan_network": exec_scan_network,
}

KEYWORDS = {
    "room_command": [
        "livingroom", "living room", "office", "bedroom", "shield",
        "netflix", "watch", "tv", "plex", "disney", "hbo", "spotify",
        "prime", "youtube", "twitch", "apple tv", "activate",
        "headphones", "speakers", "denon", "vinyl", "phono",
    ],
    "scan_network": ["scan", "network", "devices", "find shield", "what devices", "discover"],
}
