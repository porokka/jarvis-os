"""
JARVIS Skill — Plex Media Server control.

Controls Plex via HTTP API. Requires a Plex token.
Config: config/plex.json

Setup:
  1. Get your Plex token: https://support.plex.tv/articles/204059436
  2. Create config/plex.json: {"ip": "192.168.1.100", "port": 32400, "token": "YOUR_TOKEN"}
"""

import json
import urllib.request
import urllib.parse
import re
from pathlib import Path

SKILL_NAME = "plex"
SKILL_DESCRIPTION = "Plex Media Server — browse, play, search, control playback"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "plex.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api(path: str, method: str = "GET") -> str:
    """Call Plex API."""
    cfg = _load_config()
    ip = cfg.get("ip", "")
    port = cfg.get("port", 32400)
    token = cfg.get("token", "")

    if not ip or not token:
        return "Error: Plex not configured. Create config/plex.json with ip, port, token."

    url = f"http://{ip}:{port}{path}"
    sep = "&" if "?" in url else "?"
    url += f"{sep}X-Plex-Token={token}"

    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Plex error: {e}"


def _extract(text: str, key: str) -> str:
    m = re.search(f'"{key}"\\s*:\\s*"([^"]*)"', text)
    return m.group(1) if m else ""


def exec_plex(action: str, query: str = "") -> str:
    """Control Plex Media Server."""
    action = action.lower().strip()

    if action == "status":
        result = _api("/identity")
        name = _extract(result, "friendlyName")
        version = _extract(result, "version")
        if name:
            # Get active sessions
            sessions = _api("/status/sessions")
            session_count = sessions.count('"Player"')
            return f"Plex server: {name} v{version}\nActive streams: {session_count}"
        return result

    elif action == "libraries":
        result = _api("/library/sections")
        libs = re.findall(r'"title"\s*:\s*"([^"]*)".*?"type"\s*:\s*"([^"]*)"', result)
        if libs:
            lines = [f"  {title} ({ltype})" for title, ltype in libs]
            return "Libraries:\n" + "\n".join(lines)
        return "No libraries found."

    elif action == "search":
        if not query:
            return "Usage: search <query>"
        encoded = urllib.parse.quote(query)
        result = _api(f"/hubs/search?query={encoded}&limit=10")
        titles = re.findall(r'"title"\s*:\s*"([^"]*)"', result)
        # Remove duplicates, keep order
        seen = set()
        unique = []
        for t in titles:
            if t not in seen and t != query:
                seen.add(t)
                unique.append(t)
        if unique:
            return f"Search '{query}':\n" + "\n".join(f"  {t}" for t in unique[:10])
        return f"No results for '{query}'."

    elif action == "recent":
        result = _api("/library/recentlyAdded?X-Plex-Container-Start=0&X-Plex-Container-Size=10")
        titles = re.findall(r'"title"\s*:\s*"([^"]*)"', result)
        if titles:
            return "Recently added:\n" + "\n".join(f"  {t}" for t in titles[:10])
        return "Nothing recently added."

    elif action == "ondeck":
        result = _api("/library/onDeck?X-Plex-Container-Start=0&X-Plex-Container-Size=10")
        titles = re.findall(r'"title"\s*:\s*"([^"]*)"', result)
        if titles:
            return "On Deck:\n" + "\n".join(f"  {t}" for t in titles[:10])
        return "Nothing on deck."

    elif action == "sessions":
        result = _api("/status/sessions")
        # Parse active sessions
        players = re.findall(r'"title"\s*:\s*"([^"]*)".*?"Player".*?"title"\s*:\s*"([^"]*)"', result)
        if players:
            lines = [f"  {media} on {player}" for media, player in players]
            return "Now playing:\n" + "\n".join(lines)
        return "Nothing playing."

    elif action == "play":
        # Play on a specific client — needs client identifier
        return "To play media, use the Shield: 'play plex in the living room'"

    elif action == "pause":
        # Pause all active sessions
        sessions = _api("/status/sessions")
        session_ids = re.findall(r'"sessionKey"\s*:\s*"(\d+)"', sessions)
        if not session_ids:
            return "Nothing playing to pause."
        for sid in session_ids:
            _api(f"/player/playback/pause?sessionId={sid}", method="PUT")
        return "Paused."

    elif action == "resume":
        sessions = _api("/status/sessions")
        session_ids = re.findall(r'"sessionKey"\s*:\s*"(\d+)"', sessions)
        if not session_ids:
            return "Nothing to resume."
        for sid in session_ids:
            _api(f"/player/playback/play?sessionId={sid}", method="PUT")
        return "Resumed."

    elif action == "stop":
        sessions = _api("/status/sessions")
        session_ids = re.findall(r'"sessionKey"\s*:\s*"(\d+)"', sessions)
        if not session_ids:
            return "Nothing playing to stop."
        for sid in session_ids:
            _api(f"/player/playback/stop?sessionId={sid}", method="PUT")
        return "Stopped."

    else:
        return (
            f"Unknown action '{action}'. Available: "
            "status, libraries, search, recent, ondeck, sessions, "
            "pause, resume, stop"
        )


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "plex",
            "description": "Control Plex Media Server. Actions: status (server info), libraries (list), search (find media), recent (recently added), ondeck (continue watching), sessions (what's playing), pause, resume, stop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: status, libraries, search, recent, ondeck, sessions, pause, resume, stop",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (for search action)",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "plex": exec_plex,
}

KEYWORDS = {
    "plex": [
        "plex", "media server", "movies", "tv shows", "recently added",
        "on deck", "what's playing", "search movie", "search show",
    ],
}
