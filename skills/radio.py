"""
JARVIS Skill — Internet radio streaming.

Streams via HTML5 audio in the HUD (primary) or mpv (fallback).
Tracks playback state so the HUD widget can poll it.
"""

import subprocess
import time
import uuid

SKILL_NAME = "radio"
SKILL_DESCRIPTION = "Internet radio — Finnish stations (Nova, SuomiPop, Rock, YLE) + custom streams"

# -- Station registry --

STATIONS = {
    "nova": {"type": "bauer", "id": "fi_radionova", "label": "Radio Nova", "fallback": "https://rayo.fi/radio-nova"},
    "suomipop": {"type": "url", "url": "https://www.supla.fi/radiosuomipop", "label": "Radio Suomipop", "fallback": "https://rayo.fi/radio-suomipop"},
    "rock": {"type": "url", "url": "https://www.supla.fi/radiorock", "label": "Radio Rock", "fallback": "https://rayo.fi/radio-rock"},
    "yle1": {"type": "url", "url": "https://yleradiolive.akamaized.net/hls/live/2027671/in-YleRadio1/master.m3u8", "label": "YLE Radio 1"},
    "ylex": {"type": "url", "url": "https://yleradiolive.akamaized.net/hls/live/2027673/in-YleX/master.m3u8", "label": "YLE X"},
    "lofi": {"type": "url", "url": "https://play.streamafrica.net/lofiradio", "label": "Lo-Fi Radio"},
    "chillhop": {"type": "url", "url": "http://stream.zeno.fm/fyn8eh3h5f8uv", "label": "Chillhop"},
}

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
    return {k: {"label": v["label"], "type": v["type"]} for k, v in STATIONS.items()}


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
    cfg = STATIONS.get(station_key.lower().strip())
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
        available = ", ".join(STATIONS.keys())
        return f"Unknown station '{station}'. Available: {available}. Or provide a stream URL."

    station_key = station.lower().strip() if station.lower().strip() in STATIONS else "custom"

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
