"""
JARVIS Skill — Philips Hue lighting control.

Controls lights, rooms, and scenes via the Hue Bridge REST API.
First use requires pressing the bridge button for pairing.

Config: config/hue.json
Setup:
  1. Press the button on your Hue Bridge
  2. Within 30 seconds, ask JARVIS: "hue pair"
  3. The bridge IP and username are saved automatically
"""

import json
import urllib.request
from pathlib import Path

SKILL_NAME = "hue"
SKILL_DESCRIPTION = "Philips Hue — lights, rooms, colors, scenes, brightness"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "hue.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _api(method: str, path: str, body: dict | None = None) -> dict | list | str:
    """Call Hue Bridge API."""
    cfg = _load_config()
    ip = cfg.get("ip", "")
    username = cfg.get("username", "")

    if not ip:
        return "Hue Bridge not configured. Set IP in config/hue.json or run 'hue discover'."
    if not username and path != "":
        return "Not paired. Press the Hue Bridge button, then run 'hue pair'."

    url = f"http://{ip}/api/{username}/{path}" if username else f"http://{ip}/api"

    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"Hue API error: {e}"


# ─── Discovery ───

def _discover_bridge() -> str:
    """Find Hue Bridge on network."""
    try:
        # Try meethue cloud discovery
        req = urllib.request.Request("https://discovery.meethue.com/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            bridges = json.loads(resp.read().decode("utf-8"))
        if bridges:
            ip = bridges[0].get("internalipaddress", "")
            if ip:
                cfg = _load_config()
                cfg["ip"] = ip
                _save_config(cfg)
                return f"Found Hue Bridge at {ip}. Now press the bridge button and run 'hue pair'."
    except Exception:
        pass

    # Try mDNS / common IPs
    for ip in ["192.168.0.1", "192.168.1.1"]:
        # Can't scan without nmap here
        pass

    return "No Hue Bridge found. Set IP manually in config/hue.json: {\"ip\": \"192.168.x.x\"}"


def _pair() -> str:
    """Pair with Hue Bridge — press button first!"""
    cfg = _load_config()
    ip = cfg.get("ip", "")
    if not ip:
        return "Set bridge IP first: config/hue.json or run 'hue discover'."

    result = _api("POST", "", {"devicetype": "jarvis_os#jarvis"})

    if isinstance(result, list) and len(result) > 0:
        if "success" in result[0]:
            username = result[0]["success"]["username"]
            cfg["username"] = username
            _save_config(cfg)
            return f"Paired! Username saved. You can now control lights."
        elif "error" in result[0]:
            err = result[0]["error"]
            if err.get("type") == 101:
                return "Press the button on the Hue Bridge, then try 'hue pair' again within 30 seconds."
            return f"Pairing error: {err.get('description', str(err))}"

    return f"Unexpected response: {result}"


# ─── Light Control ───

def _list_lights() -> str:
    result = _api("GET", "lights")
    if isinstance(result, str):
        return result
    if not result:
        return "No lights found."

    lines = []
    for lid, light in result.items():
        state = light.get("state", {})
        on = "ON" if state.get("on") else "OFF"
        bri = state.get("bri", 0)
        name = light.get("name", f"Light {lid}")
        pct = round(bri / 254 * 100)
        lines.append(f"  {lid}: {name} — {on} ({pct}%)")

    return "Lights:\n" + "\n".join(lines)


def _set_light(target: str, state: dict) -> str:
    """Set light state by name or ID."""
    # Find light by name or ID
    lights = _api("GET", "lights")
    if isinstance(lights, str):
        return lights

    light_id = None
    for lid, light in lights.items():
        if lid == target or target.lower() in light.get("name", "").lower():
            light_id = lid
            break

    if not light_id:
        names = [f"{lid}: {l.get('name', '?')}" for lid, l in lights.items()]
        return f"Light '{target}' not found. Available:\n" + "\n".join(f"  {n}" for n in names)

    result = _api("PUT", f"lights/{light_id}/state", state)
    return f"OK — {lights[light_id].get('name', light_id)}"


def _list_groups() -> str:
    result = _api("GET", "groups")
    if isinstance(result, str):
        return result
    if not result:
        return "No rooms/groups found."

    lines = []
    for gid, group in result.items():
        name = group.get("name", f"Group {gid}")
        gtype = group.get("type", "")
        on = "ON" if group.get("action", {}).get("on") else "OFF"
        lights_count = len(group.get("lights", []))
        lines.append(f"  {gid}: {name} ({gtype}) — {on}, {lights_count} lights")

    return "Rooms/Groups:\n" + "\n".join(lines)


def _set_group(target: str, state: dict) -> str:
    """Set group/room state by name or ID."""
    groups = _api("GET", "groups")
    if isinstance(groups, str):
        return groups

    group_id = None
    for gid, group in groups.items():
        if gid == target or target.lower() in group.get("name", "").lower():
            group_id = gid
            break

    if not group_id:
        names = [f"{gid}: {g.get('name', '?')}" for gid, g in groups.items()]
        return f"Room '{target}' not found. Available:\n" + "\n".join(f"  {n}" for n in names)

    result = _api("PUT", f"groups/{group_id}/action", state)
    return f"OK — {groups[group_id].get('name', group_id)}"


def _list_scenes() -> str:
    result = _api("GET", "scenes")
    if isinstance(result, str):
        return result
    if not result:
        return "No scenes found."

    lines = []
    for sid, scene in result.items():
        name = scene.get("name", f"Scene {sid}")
        group = scene.get("group", "?")
        lines.append(f"  {name} (group {group})")

    return "Scenes:\n" + "\n".join(lines[:20])


def _activate_scene(target: str) -> str:
    scenes = _api("GET", "scenes")
    if isinstance(scenes, str):
        return scenes

    for sid, scene in scenes.items():
        if target.lower() in scene.get("name", "").lower():
            group_id = scene.get("group", "0")
            _api("PUT", f"groups/{group_id}/action", {"scene": sid})
            return f"Scene activated: {scene.get('name', sid)}"

    return f"Scene '{target}' not found. Use 'hue scenes' to list available."


# ─── Color helpers ───

COLORS = {
    "red": {"hue": 0, "sat": 254},
    "orange": {"hue": 5000, "sat": 254},
    "yellow": {"hue": 10000, "sat": 254},
    "green": {"hue": 25500, "sat": 254},
    "cyan": {"hue": 35000, "sat": 254},
    "blue": {"hue": 46920, "sat": 254},
    "purple": {"hue": 50000, "sat": 254},
    "pink": {"hue": 56100, "sat": 254},
    "white": {"hue": 34000, "sat": 20},
    "warm": {"ct": 400},
    "cool": {"ct": 200},
    "daylight": {"ct": 250},
    "candle": {"ct": 500},
}


# ─── Main dispatcher ───

def exec_hue(action: str, target: str = "", value: str = "") -> str:
    action = action.lower().strip()

    if action == "discover":
        return _discover_bridge()

    elif action == "pair":
        return _pair()

    elif action in ("lights", "list"):
        return _list_lights()

    elif action in ("rooms", "groups"):
        return _list_groups()

    elif action == "scenes":
        return _list_scenes()

    elif action == "scene":
        if not target:
            return "Specify a scene name. Use 'hue scenes' to list."
        return _activate_scene(target)

    elif action == "on":
        if target:
            return _set_light(target, {"on": True})
        return _set_group("0", {"on": True})  # group 0 = all lights

    elif action == "off":
        if target:
            return _set_light(target, {"on": False})
        return _set_group("0", {"on": False})

    elif action in ("brightness", "dim", "bright"):
        bri = 254
        if value:
            try:
                pct = int(value.replace("%", ""))
                bri = max(1, min(254, round(pct / 100 * 254)))
            except ValueError:
                return f"Invalid brightness: {value}. Use 0-100."
        elif action == "dim":
            bri = 50
        if target:
            return _set_light(target, {"on": True, "bri": bri})
        return _set_group("0", {"on": True, "bri": bri})

    elif action == "color":
        if not value:
            available = ", ".join(COLORS.keys())
            return f"Specify a color: {available}"
        color = COLORS.get(value.lower())
        if not color:
            available = ", ".join(COLORS.keys())
            return f"Unknown color '{value}'. Available: {available}"
        state = {"on": True, **color}
        if target:
            return _set_light(target, state)
        return _set_group("0", state)

    elif action == "status":
        cfg = _load_config()
        ip = cfg.get("ip", "not set")
        paired = "yes" if cfg.get("username") else "no"
        lights = _api("GET", "lights") if cfg.get("username") else {}
        count = len(lights) if isinstance(lights, dict) else 0
        return f"Hue Bridge: {ip}\nPaired: {paired}\nLights: {count}"

    else:
        return (
            f"Unknown action '{action}'. Available: "
            "discover, pair, lights, rooms, scenes, scene, "
            "on, off, brightness, dim, color, status"
        )


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "hue",
            "description": "Control Philips Hue lights. Actions: discover (find bridge), pair (press button first), lights (list), rooms (list), on/off (target: light or room name), brightness/dim (value: 0-100), color (value: red/blue/green/warm/cool/candle), scene (target: scene name), scenes (list), status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: discover, pair, lights, rooms, on, off, brightness, dim, color, scene, scenes, status",
                    },
                    "target": {
                        "type": "string",
                        "description": "Light name, room name, or scene name",
                    },
                    "value": {
                        "type": "string",
                        "description": "Brightness (0-100) or color name (red, blue, warm, cool, candle)",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "hue": exec_hue,
}

KEYWORDS = {
    "hue": [
        "hue", "lights", "light", "lamp", "bulb", "dim", "bright",
        "color", "scene", "living room lights", "bedroom lights",
        "turn on lights", "turn off lights",
    ],
}
