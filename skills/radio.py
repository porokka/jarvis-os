"""
JARVIS Skill — Internet radio streaming.

Streams via HTML5 audio in the HUD (primary) or mpv/browser (fallback).
Tracks playback state so the HUD widget can poll it.
Supports cached now-playing metadata so title stays visible until next update.
Adds persistent memory hooks for preferences, recent context, and events.
"""

import json
import subprocess
import time
import uuid
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple


SKILL_NAME = "radio"
SKILL_DESCRIPTION = "Internet radio — Finnish stations (Nova, SuomiPop, Rock, YLE) + custom streams"
SKILL_VERSION = "1.3.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "media"
SKILL_TAGS = ["radio", "streaming", "audio", "internet-radio", "hud", "mpv", "metadata", "memory"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "play_radio",
    "stop_radio",
    "list_stations",
    "radio_state",
    "now_playing_metadata",
    "fallback_modes",
    "stream_refresh",
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
    "network_access": True,
    "entrypoint": "exec_radio",
    "config_file": "config/radio.json",
}

RADIO_CONFIG = Path(__file__).parent.parent / "config" / "radio.json"

_DEFAULT_STATIONS = {
    "nova": {
        "type": "bauer",
        "id": "fi_radionova",
        "label": "Radio Nova",
    },
    "lofi": {
        "type": "url",
        "url": "https://play.streamafrica.net/lofiradio",
        "label": "Lo-Fi Radio",
    },
}

MPV_PATH = r"C:\Program Files\MPV Player\mpv.exe"

# Bauer URLs can expire; refresh them periodically
BAUER_REFRESH_SECONDS = 60 * 25

# How long we keep showing old metadata if stream gives no new ICY block
NOW_PLAYING_TTL_SECONDS = 60 * 60 * 6

_radio_state = {
    "playing": False,
    "station": None,
    "label": None,
    "station_type": None,
    "stream_url": None,
    "fallback_mode": "hud",
    "started_at": None,
    "last_stream_refresh": None,
    "refresh_after": None,
    "now_playing": {
        "title": None,
        "artist": None,
        "text": None,
        "last_meta_update": None,
    },
}


def _now() -> float:
    return time.time()


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
    """
    Reads preference directly from memory state if memory skill exists.
    This avoids parsing exec_memory string responses.
    """
    try:
        from skills.memory import _load_state  # type: ignore
        state = _load_state()
        value = state.get("identity", {}).get(key)
        return str(value) if value is not None else None
    except Exception:
        return None


# -- Station config --

def _load_stations() -> Dict[str, dict]:
    """Load stations from config file (re-read each call so AI edits take effect)."""
    try:
        data = json.loads(RADIO_CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULT_STATIONS)

        clean = {}
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue

            station_key = key.strip().lower()
            if not station_key:
                continue

            stype = value.get("type")
            label = str(value.get("label", station_key)).strip()

            if stype == "bauer" and value.get("id"):
                clean[station_key] = {
                    "type": "bauer",
                    "id": str(value["id"]).strip(),
                    "label": label,
                    "fallback": value.get("fallback"),
                }
            elif stype == "url" and value.get("url"):
                clean[station_key] = {
                    "type": "url",
                    "url": str(value["url"]).strip(),
                    "label": label,
                    "fallback": value.get("fallback"),
                }

        return clean or dict(_DEFAULT_STATIONS)
    except Exception:
        return dict(_DEFAULT_STATIONS)


def _is_stream_url(value: str) -> bool:
    value = (value or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


def _get_bauer_stream(station_id: str) -> str:
    """Generate fresh Bauer Media stream URL with session tokens."""
    listener_id = uuid.uuid4().hex
    skey = str(int(time.time()))
    return (
        f"https://live-bauerfi.sharp-stream.com/{station_id}_64.aac"
        f"?direct=true&listenerid={listener_id}"
        f"&aw_0_1st.bauer_listenerid={listener_id}"
        f"&aw_0_1st.playerid=BMUK_inpage_html5"
        f"&aw_0_1st.skey={skey}"
        f"&aw_0_1st.bauer_loggedin=false"
    )


def resolve_stream_url(station_key: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Resolve station key to:
      (stream_url, label, fallback, station_type)
    Returns (None, None, None, None) if unknown.
    """
    key = (station_key or "").lower().strip()
    stations = _load_stations()
    cfg = stations.get(key)

    if cfg:
        if cfg["type"] == "bauer":
            url = _get_bauer_stream(cfg["id"])
        else:
            url = cfg["url"]
        return url, cfg["label"], cfg.get("fallback"), cfg["type"]

    if _is_stream_url(station_key):
        return station_key.strip(), "Custom Stream", None, "url"

    return None, None, None, None


# -- Playback helpers --

def _kill_mpv() -> None:
    try:
        subprocess.run(
            ["powershell.exe", "-Command", "Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def _start_mpv(url: str) -> bool:
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-Command",
                f'Start-Process "{MPV_PATH}" -ArgumentList \'--no-video\',\'--really-quiet\',\'{url}\'',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        check = subprocess.run(
            ["powershell.exe", "-Command", "Get-Process mpv -ErrorAction SilentlyContinue"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "mpv" in (check.stdout or "").lower()
    except Exception:
        return False


def _open_browser(url: str) -> bool:
    try:
        subprocess.Popen(
            ["powershell.exe", "-Command", f'Start-Process "{url}"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _reset_state() -> None:
    global _radio_state
    _radio_state = {
        "playing": False,
        "station": None,
        "label": None,
        "station_type": None,
        "stream_url": None,
        "fallback_mode": "hud",
        "started_at": None,
        "last_stream_refresh": None,
        "refresh_after": None,
        "now_playing": {
            "title": None,
            "artist": None,
            "text": None,
            "last_meta_update": None,
        },
    }


def _refresh_stream_if_needed() -> bool:
    """
    Refresh active stream URL if station uses expiring tokenized URLs.
    Returns True if stream URL changed.
    """
    global _radio_state

    if not _radio_state["playing"]:
        return False

    if _radio_state["station_type"] != "bauer":
        return False

    refresh_after = _radio_state.get("refresh_after")
    station = _radio_state.get("station")

    if not refresh_after or not station:
        return False

    if _now() < refresh_after:
        return False

    new_url, label, _fallback, stype = resolve_stream_url(station)
    if not new_url:
        return False

    _radio_state["stream_url"] = new_url
    _radio_state["last_stream_refresh"] = _now()
    _radio_state["refresh_after"] = _now() + BAUER_REFRESH_SECONDS

    mode = _radio_state.get("fallback_mode", "hud")
    if mode == "mpv":
        _kill_mpv()
        _start_mpv(new_url)
    elif mode == "browser":
        _open_browser(new_url)

    _log_memory_event(
        "radio_stream_refreshed",
        {
            "station": _radio_state.get("station"),
            "label": label,
            "station_type": stype,
            "fallback_mode": mode,
        },
    )
    return True


def get_radio_state() -> dict:
    """Return current radio state for the API."""
    _refresh_stream_if_needed()
    return dict(_radio_state)


def get_stations() -> dict:
    """Return station list for the HUD."""
    stations = _load_stations()
    return {
        k: {
            "label": v.get("label", k),
            "type": v.get("type", "url"),
        }
        for k, v in stations.items()
    }


def _update_now_playing_cache(title: Optional[str], artist: Optional[str]) -> None:
    """Only overwrite cache when new valid metadata exists."""
    global _radio_state

    if not title and not artist:
        return

    text = None
    if artist and title:
        text = f"{artist} - {title}"
    elif title:
        text = title
    elif artist:
        text = artist

    current_text = _radio_state["now_playing"].get("text")
    if current_text == text:
        return

    _radio_state["now_playing"] = {
        "title": title,
        "artist": artist,
        "text": text,
        "last_meta_update": _now(),
    }

    if text:
        _remember_recent("last_radio_now_playing", text)
        _log_memory_event(
            "radio_now_playing_updated",
            {
                "station": _radio_state.get("station"),
                "label": _radio_state.get("label"),
                "text": text,
                "artist": artist or "",
                "title": title or "",
            },
        )


def get_now_playing() -> dict:
    """
    Fetch ICY metadata from the active stream.
    Important behavior:
      - if stream has no new metadata right now, keep previous cached value
      - do not blank the HUD between updates
    """
    _refresh_stream_if_needed()

    if not _radio_state["playing"] or not _radio_state["stream_url"]:
        return dict(_radio_state["now_playing"])

    url = _radio_state["stream_url"]
    try:
        req = urllib.request.Request(url, headers={"Icy-MetaData": "1"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            metaint_str = resp.headers.get("icy-metaint")
            if not metaint_str:
                return dict(_radio_state["now_playing"])

            metaint = int(metaint_str)
            if metaint <= 0:
                return dict(_radio_state["now_playing"])

            resp.read(metaint)

            meta_len_byte = resp.read(1)
            if not meta_len_byte:
                return dict(_radio_state["now_playing"])

            meta_len = meta_len_byte[0] * 16
            if meta_len == 0:
                return dict(_radio_state["now_playing"])

            meta_raw = resp.read(meta_len).decode("utf-8", errors="replace").rstrip("\x00")

            title = None
            artist = None

            marker = "StreamTitle='"
            if marker in meta_raw:
                start = meta_raw.index(marker) + len(marker)
                end = meta_raw.find("';", start)
                if end != -1:
                    stream_title = meta_raw[start:end].strip()
                    if " - " in stream_title:
                        artist, title = stream_title.split(" - ", 1)
                        artist = artist.strip() or None
                        title = title.strip() or None
                    elif stream_title:
                        title = stream_title

            _update_now_playing_cache(title, artist)
            return dict(_radio_state["now_playing"])

    except Exception as e:
        print(f"[RADIO] Now-playing error: {e}")

    cached = dict(_radio_state["now_playing"])
    ts = cached.get("last_meta_update")
    if ts and (_now() - ts) <= NOW_PLAYING_TTL_SECONDS:
        return cached

    return cached


def _play_via_mode(url: str, fallback_mode: str) -> Tuple[bool, str]:
    """
    HUD mode:
      - just update state, HUD frontend handles actual playback
    MPV/browser mode:
      - try to launch local player/browser
    """
    mode = (fallback_mode or "hud").strip().lower()

    if mode == "hud":
        return True, "HUD playback selected."

    if mode == "mpv":
        ok = _start_mpv(url)
        return ok, "Started in mpv." if ok else "Failed to start mpv."

    if mode == "browser":
        ok = _open_browser(url)
        return ok, "Opened stream in browser." if ok else "Failed to open browser."

    return False, f"Unknown fallback_mode '{fallback_mode}'. Use hud, mpv, or browser."


def _resolve_play_mode(fallback_mode: str) -> str:
    """
    If caller omits/blank fallback_mode, try memory preference.
    """
    mode = (fallback_mode or "").strip().lower()
    if mode in {"hud", "mpv", "browser"}:
        return mode

    remembered = _get_memory_preference("preferred_radio_fallback_mode")
    if remembered in {"hud", "mpv", "browser"}:
        return remembered

    return "hud"


def _play_station(station: str, fallback_mode: str = "hud") -> str:
    global _radio_state

    station = (station or "").strip()
    if not station:
        return "Specify a station name or stream URL."

    effective_mode = _resolve_play_mode(fallback_mode)

    url, label, fallback, station_type = resolve_stream_url(station)
    if not url:
        available = ", ".join(sorted(_load_stations().keys()))
        return f"Unknown station '{station}'. Available: {available}. Or provide a stream URL."

    stations = _load_stations()
    station_key = station.lower().strip() if station.lower().strip() in stations else "custom"

    _kill_mpv()

    started_at = _now()
    refresh_after = started_at + BAUER_REFRESH_SECONDS if station_type == "bauer" else None

    _radio_state = {
        "playing": True,
        "station": station_key,
        "label": label,
        "station_type": station_type,
        "stream_url": url,
        "fallback_mode": effective_mode,
        "started_at": started_at,
        "last_stream_refresh": started_at if station_type == "bauer" else None,
        "refresh_after": refresh_after,
        "now_playing": {
            "title": None,
            "artist": None,
            "text": None,
            "last_meta_update": None,
        },
    }

    ok, mode_msg = _play_via_mode(url, effective_mode)
    if not ok:
        return mode_msg

    # Persistent memory updates
    _remember_preference("preferred_radio_fallback_mode", effective_mode)
    _remember_recent("last_radio_station", station_key)
    _remember_recent("last_radio_label", label)
    _remember_recent("last_radio_mode", effective_mode)
    if station_key == "custom":
        _remember_recent("last_radio_custom_stream", station)

    _log_memory_event(
        "radio_play_started",
        {
            "station": station_key,
            "label": label,
            "station_type": station_type,
            "fallback_mode": effective_mode,
            "custom_stream": station if station_key == "custom" else "",
        },
    )

    return f"Now playing: {label} ({effective_mode})"


def exec_radio(action: str, station: str = "", fallback_mode: str = "hud") -> str:
    """Play internet radio, stop playback, list stations, or inspect state."""
    action = (action or "").strip().lower()

    if action == "play":
        return _play_station(station=station, fallback_mode=fallback_mode)

    elif action == "stop":
        if _radio_state.get("playing"):
            _log_memory_event(
                "radio_stopped",
                {
                    "station": _radio_state.get("station") or "",
                    "label": _radio_state.get("label") or "",
                    "fallback_mode": _radio_state.get("fallback_mode") or "",
                    "now_playing": _radio_state.get("now_playing", {}).get("text") or "",
                },
            )
        _kill_mpv()
        _reset_state()
        return "Radio stopped."

    elif action == "stations":
        stations = get_stations()
        if not stations:
            return "No stations configured."

        lines = []
        for key, info in sorted(stations.items()):
            lines.append(f"  {key} — {info.get('label')} [{info.get('type')}]")
        return "Stations:\n" + "\n".join(lines)

    elif action == "state":
        state = get_radio_state()
        if not state["playing"]:
            return "Radio is stopped."

        age = ""
        if state.get("started_at"):
            age = f"\nStarted: {int(_now() - state['started_at'])}s ago"

        refresh = ""
        if state.get("refresh_after"):
            refresh_in = int(max(0, state["refresh_after"] - _now()))
            refresh = f"\nStream refresh in: {refresh_in}s"

        return (
            f"Radio state: playing\n"
            f"Station: {state.get('label') or state.get('station')}\n"
            f"Mode: {state.get('fallback_mode')}"
            f"{age}"
            f"{refresh}"
        )

    elif action == "now_playing":
        np = get_now_playing()
        if np.get("text"):
            age = ""
            if np.get("last_meta_update"):
                age = f" ({int(_now() - np['last_meta_update'])}s ago)"
            return f"Now playing: {np['text']}{age}"
        return "Now playing metadata unavailable."

    else:
        return "Available actions: play, stop, stations, state, now_playing"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "radio",
            "description": (
                "Internet radio control with memory. Actions: play, stop, stations, state, now_playing. "
                "Supports fallback_mode: hud, mpv, browser. Remembers last station and preferred playback mode."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["play", "stop", "stations", "state", "now_playing"],
                        "description": "Radio action to perform.",
                    },
                    "station": {
                        "type": "string",
                        "description": "Station key or direct stream URL. Used with action=play.",
                    },
                    "fallback_mode": {
                        "type": "string",
                        "enum": ["hud", "mpv", "browser"],
                        "description": "Playback mode for action=play. If omitted logically by planner, remembered preference can be used.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "radio": exec_radio,
}

KEYWORDS = {
    "radio": [
        "play",
        "radio",
        "music",
        "nova",
        "suomipop",
        "rock",
        "yle",
        "lofi",
        "stop radio",
        "stop music",
        "internet radio",
        "stream radio",
        "radio stations",
        "now playing",
    ],
}

SKILL_EXAMPLES = [
    {"command": "play radio nova", "tool": "radio", "args": {"action": "play", "station": "nova"}},
    {"command": "play lofi in mpv", "tool": "radio", "args": {"action": "play", "station": "lofi", "fallback_mode": "mpv"}},
    {"command": "show radio stations", "tool": "radio", "args": {"action": "stations"}},
    {"command": "radio status", "tool": "radio", "args": {"action": "state"}},
    {"command": "what song is playing", "tool": "radio", "args": {"action": "now_playing"}},
    {"command": "stop radio", "tool": "radio", "args": {"action": "stop"}},
]