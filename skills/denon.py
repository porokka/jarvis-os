"""
JARVIS Skill — Denon AVR-X4100W receiver control.

Controls: input switching, volume, presets, surround modes, power, zones.
Config loaded from config/denon.json.
"""

import json
import time
import urllib.request
from pathlib import Path

SKILL_NAME = "denon"
SKILL_DESCRIPTION = "Denon AVR-X4100W receiver — inputs, volume, presets, surround, zones"

# -- Config (loaded on init) --

CONFIG_PATH = Path(__file__).parent.parent / "config" / "denon.json"
CONFIG = {}
IP = ""
INPUTS = {}  # alias → command mapping


def init():
    """Load Denon config from JSON."""
    global CONFIG, IP, INPUTS
    try:
        CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        IP = CONFIG["ip"]
        # Build input alias map
        for name, cfg in CONFIG.get("inputs", {}).items():
            cmd = cfg["command"]
            INPUTS[name.lower()] = cmd
            for alias in cfg.get("aliases", []):
                INPUTS[alias.lower()] = cmd
        print(f"[DENON] Loaded: {CONFIG['name']} at {IP} ({len(INPUTS)} input aliases)")
    except Exception as e:
        print(f"[DENON] Config error: {e}")


# -- Denon HTTP command --

def _send(cmd: str) -> str:
    """Send a command to Denon AVR via HTTP API."""
    try:
        url = f"http://{IP}/goform/formiPhoneAppDirect.xml?{cmd}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Denon error: {e}"


# -- Tool executors --

def exec_denon_input(input_name: str) -> str:
    """Switch Denon to a specific input."""
    cmd = INPUTS.get(input_name.lower())
    if not cmd:
        aliases = sorted(set(INPUTS.keys()))
        return f"Unknown input '{input_name}'. Known: {', '.join(aliases)}"
    _send(cmd)
    return f"Switched Denon to {input_name}"


def exec_denon_volume(level: str) -> str:
    """Set Denon volume. Accepts: up, down, mute, unmute, or a number (0-98)."""
    vol_cfg = CONFIG.get("volume", {}).get("commands", {})
    level_lower = level.lower().strip()

    if level_lower == "up":
        _send(vol_cfg.get("up", "MVUP"))
    elif level_lower == "down":
        _send(vol_cfg.get("down", "MVDOWN"))
    elif level_lower == "mute":
        _send(vol_cfg.get("mute_on", "MUON"))
    elif level_lower == "unmute":
        _send(vol_cfg.get("mute_off", "MUOFF"))
    else:
        try:
            num = int(float(level))
            _send(f"MV{num:02d}")
        except ValueError:
            return f"Invalid volume: {level}. Use up/down/mute/unmute or 0-98."
    return f"Denon volume: {level}"


def exec_denon_preset(preset: str) -> str:
    """Execute a Denon preset (headphones, speakers, quiet, night, both)."""
    presets = CONFIG.get("presets", {})
    p = presets.get(preset.lower())
    if not p:
        return f"Unknown preset. Available: {', '.join(presets.keys())}"
    for cmd in p.get("commands", []):
        _send(cmd)
        time.sleep(0.3)
    return f"Denon preset: {preset} — {p.get('description', '')}"


def exec_denon_surround(mode: str) -> str:
    """Set Denon surround mode."""
    modes = CONFIG.get("surround", {})
    cmd = modes.get(mode.lower())
    if not cmd:
        return f"Unknown surround mode. Available: {', '.join(modes.keys())}"
    _send(cmd)
    return f"Surround mode: {mode}"


def exec_denon_power(action: str) -> str:
    """Denon power control: on, off, status."""
    power = CONFIG.get("power", {})
    cmd = power.get(action.lower())
    if not cmd:
        return f"Unknown power action. Use: on, off, status"
    result = _send(cmd)
    return f"Denon power: {action}" + (f" ({result})" if action == "status" else "")


def exec_denon_zone(zone: str, action: str) -> str:
    """Control Denon zone (zone1/zone2): on, off, volume_up, volume_down, mute_on, mute_off."""
    zones = CONFIG.get("zones", {})
    z = zones.get(zone.lower())
    if not z:
        return f"Unknown zone. Available: {', '.join(zones.keys())}"
    cmd = z.get(action.lower())
    if not cmd:
        return f"Unknown action for {zone}. Available: {', '.join(z.keys())}"
    _send(cmd)
    return f"Denon {zone} {action}"


# -- Tool definitions (Ollama format) --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "denon_input",
            "description": "Switch Denon AVR input. Inputs: pc/game, shield/mediaplayer, vinyl/phono, tv, bluetooth, network, usb, dvd, bluray, tuner. Also try aliases like 'computer', 'monitor', 'turntable', 'record'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_name": {
                        "type": "string",
                        "description": "Input name or alias (e.g. pc, shield, vinyl, tv, bluetooth, network)",
                    }
                },
                "required": ["input_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "denon_volume",
            "description": "Set Denon receiver volume. Use 'up', 'down', 'mute', 'unmute', or a number 0-98.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "Volume: up, down, mute, unmute, or number 0-98",
                    }
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "denon_preset",
            "description": "Execute a Denon audio preset: headphones (zone2 only), speakers (zone1 only), both, quiet (all mute), night (headphones + mute speakers).",
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {
                        "type": "string",
                        "description": "Preset name: headphones, speakers, both, quiet, night",
                    }
                },
                "required": ["preset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "denon_surround",
            "description": "Set Denon surround sound mode: auto, stereo, dolby, dts, movie, music, game, direct, pure_direct.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "Surround mode: auto, stereo, dolby, dts, movie, music, game, direct, pure_direct",
                    }
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "denon_power",
            "description": "Control Denon power: on, off, or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Power action: on, off, status",
                    }
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "denon_input": exec_denon_input,
    "denon_volume": exec_denon_volume,
    "denon_preset": exec_denon_preset,
    "denon_surround": exec_denon_surround,
    "denon_power": exec_denon_power,
}

KEYWORDS = {
    "denon_input": ["denon", "receiver", "input", "switch to pc", "switch to shield", "vinyl", "phono", "turntable", "bluetooth", "network"],
    "denon_volume": ["denon volume", "receiver volume", "turn up denon", "turn down denon"],
    "denon_preset": ["headphones", "headset", "speakers", "quiet", "night mode", "both speakers"],
    "denon_surround": ["surround", "stereo", "dolby", "dts", "pure direct", "surround mode"],
    "denon_power": ["denon power", "receiver on", "receiver off", "turn on denon", "turn off denon"],
}
