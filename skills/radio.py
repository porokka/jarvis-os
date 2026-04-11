"""
JARVIS Skill — Internet radio streaming via mpv.

Finnish stations + international streams. Uses mpv for playback,
with browser fallback for Bauer Media stations.
"""

import subprocess
import time
import uuid

SKILL_NAME = "radio"
SKILL_DESCRIPTION = "Internet radio — Finnish stations (Nova, SuomiPop, Rock, YLE) + custom streams via mpv"

# -- Station registry --

STATIONS = {
    "nova": {"type": "bauer", "id": "fi_radionova", "fallback": "https://rayo.fi/radio-nova"},
    "suomipop": {"type": "url", "url": "https://www.supla.fi/radiosuomipop", "fallback": "https://rayo.fi/radio-suomipop"},
    "rock": {"type": "url", "url": "https://www.supla.fi/radiorock", "fallback": "https://rayo.fi/radio-rock"},
    "yle1": {"type": "url", "url": "https://yleradiolive.akamaized.net/hls/live/2027671/in-YleRadio1/master.m3u8"},
    "ylex": {"type": "url", "url": "https://yleradiolive.akamaized.net/hls/live/2027673/in-YleX/master.m3u8"},
    "lofi": {"type": "url", "url": "https://play.streamafrica.net/lofiradio"},
    "chillhop": {"type": "url", "url": "http://stream.zeno.fm/fyn8eh3h5f8uv"},
}

MPV_PATH = r"C:\Program Files\MPV Player\mpv.exe"


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


def _kill_mpv():
    """Stop any running mpv process."""
    subprocess.run(
        ['powershell.exe', '-Command', 'Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue'],
        capture_output=True,
    )


def _start_mpv(url: str) -> bool:
    """Start mpv with stream URL. Returns True if mpv stays running."""
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
    """Open URL in default browser."""
    subprocess.Popen(
        ['powershell.exe', '-Command', f'Start-Process "{url}"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# -- Tool executor --

def exec_play_radio(station: str) -> str:
    """Play internet radio or stop current playback."""
    if station.lower() == "stop":
        _kill_mpv()
        return "Radio stopped."

    # Look up station or treat as direct URL
    station_key = station.lower().strip()
    station_cfg = STATIONS.get(station_key)

    if station_cfg:
        # Known station
        if station_cfg["type"] == "bauer":
            url = _get_bauer_stream(station_cfg["id"])
        else:
            url = station_cfg["url"]
        fallback = station_cfg.get("fallback")
        name = station_key
    elif station.startswith("http"):
        # Direct stream URL
        url = station
        fallback = None
        name = "custom stream"
    else:
        available = ", ".join(STATIONS.keys())
        return f"Unknown station '{station}'. Available: {available}. Or provide a stream URL."

    # Kill existing, start new
    _kill_mpv()

    if _start_mpv(url):
        return f"Now playing: {name}"
    elif fallback:
        _open_browser(fallback)
        return f"Stream expired, opened {name} in browser instead"
    else:
        return f"Failed to play {name} — stream may be expired"


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
