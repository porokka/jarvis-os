"""
JARVIS Skill — Internet radio streaming.

Streams via HTML5 audio in the HUD (primary) or mpv (fallback).
Tracks playback state so the HUD widget can poll it.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

SKILL_NAME = "radio"
SKILL_DESCRIPTION = "Internet radio — Finnish stations (Nova, SuomiPop, Rock, YLE) + custom streams"

# -- Station registry (loaded from config/radio.json) --

RADIO_CONFIG = Path(__file__).parent.parent / "config" / "radio.json"

# Fallback if config file doesn't exist
_DEFAULT_STATIONS = {
    "nova": {"type": "bauer", "id": "fi_radionova", "label": "Radio Nova"},
    "lofi": {"type": "url", "url": "https://play.streamafrica.net/lofiradio", "label": "Lo-Fi Radio"},
}


def _load_stations() -> dict:
    """Load stations from config file (re-read each call so AI edits take effect)."""
    try:
        return json.loads(RADIO_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return _DEFAULT_STATIONS

MPV_PATH = r"C:\Program Files\MPV Player\mpv.exe"

# -- Playback state (polled by HUD) --

_radio_state = {
    "playing": False,
    "station": None,
    "label": None,
    "stream_url": None,
    "started_at": None,
}


def get_radio_state() -> dict:
    """Return current radio state for the API."""
    return dict(_radio_state)


def get_stations() -> dict:
    """Return station list for the HUD."""
    stations = _load_stations()
    return {k: {"label": v["label"], "type": v["type"]} for k, v in stations.items()}


def get_now_playing() -> dict:
    """Fetch ICY metadata (song title) from the active stream."""
    if not _radio_state["playing"] or not _radio_state["stream_url"]:
        return {"title": None, "artist": None}

    url = _radio_state["stream_url"]
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"Icy-MetaData": "1"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            metaint_str = resp.headers.get("icy-metaint")
            if not metaint_str:
                return {"title": None, "artist": None}

            metaint = int(metaint_str)
            # Read past audio data to reach first metadata block
            resp.read(metaint)
            # Read metadata length byte (length * 16 = actual size)
            meta_len_byte = resp.read(1)
            if not meta_len_byte:
                return {"title": None, "artist": None}
            meta_len = meta_len_byte[0] * 16
            if meta_len == 0:
                return {"title": None, "artist": None}

            meta_raw = resp.read(meta_len).decode("utf-8", errors="replace").rstrip("\x00")

            # Parse "StreamTitle='Artist - Title';"
            title = None
            artist = None
            if "StreamTitle='" in meta_raw:
                start = meta_raw.index("StreamTitle='") + 13
                end = meta_raw.index("';", start)
                stream_title = meta_raw[start:end].strip()
                if " - " in stream_title:
                    artist, title = stream_title.split(" - ", 1)
                    artist = artist.strip()
                    title = title.strip()
                elif stream_title:
                    title = stream_title

            return {"title": title, "artist": artist}
    except Exception as e:
        print(f"[RADIO] Now-playing error: {e}")
        return {"title": None, "artist": None}


# -- Stream URL helpers --

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


def resolve_stream_url(station_key: str) -> tuple[str | None, str | None, str | None]:
    """Resolve station key to (stream_url, label, fallback). Returns (None,None,None) if unknown."""
    stations = _load_stations()
    cfg = stations.get(station_key.lower().strip())
    if cfg:
        if cfg["type"] == "bauer":
            url = _get_bauer_stream(cfg["id"])
        else:
            url = cfg["url"]
        return url, cfg["label"], cfg.get("fallback")
    elif station_key.startswith("http"):
        return station_key, "Custom Stream", None
    return None, None, None


# -- mpv helpers (fallback when HUD isn't available) --

def _kill_mpv():
    subprocess.run(
        ['powershell.exe', '-Command', 'Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue'],
        capture_output=True,
    )


def _start_mpv(url: str) -> bool:
    subprocess.Popen(
        ['powershell.exe', '-Command',
         f'Start-Process "{MPV_PATH}" -ArgumentList \'--no-video\',\'--really-quiet\',\'{url}\''],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    check = subprocess.run(
        ['powershell.exe', '-Command', 'Get-Process mpv -ErrorAction SilentlyContinue'],
        capture_output=True, text=True,
    )
    return "mpv" in check.stdout


def _open_browser(url: str):
    subprocess.Popen(
        ['powershell.exe', '-Command', f'Start-Process "{url}"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# -- Tool executor --

def exec_play_radio(station: str) -> str:
    """Play internet radio or stop current playback."""
    global _radio_state

    if station.lower() == "stop":
        _kill_mpv()
        _radio_state = {"playing": False, "station": None, "label": None, "stream_url": None, "started_at": None}
        return "Radio stopped."

    url, label, fallback = resolve_stream_url(station)
    if not url:
        available = ", ".join(_load_stations().keys())
        return f"Unknown station '{station}'. Available: {available}. Or provide a stream URL."

    station_key = station.lower().strip() if station.lower().strip() in _load_stations() else "custom"

    # Kill existing mpv
    _kill_mpv()

    # Update state — HUD will pick this up and play via HTML5 audio
    _radio_state = {
        "playing": True,
        "station": station_key,
        "label": label,
        "stream_url": url,
        "started_at": time.time(),
    }

    return f"Now playing: {label}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "play_radio",
            "description": "Play internet radio or stop current playback. Finnish stations: nova, suomipop, rock, yle1, ylex, lofi, chillhop. Or provide a direct stream URL. Use 'stop' to stop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "station": {
                        "type": "string",
                        "description": "Station name (nova, suomipop, rock, yle1, ylex, lofi, chillhop) or stream URL. Use 'stop' to stop.",
                    }
                },
                "required": ["station"],
            },
        },
    },
]

TOOL_MAP = {
    "play_radio": exec_play_radio,
}

KEYWORDS = {
    "play_radio": ["play", "radio", "music", "nova", "suomipop", "rock", "yle", "lofi", "stop radio", "stop music"],
}
