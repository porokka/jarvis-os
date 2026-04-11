"""
JARVIS Skill — Panasonic DP-UB9000 4K Blu-ray player control.

Controls via UPnP/DLNA AVTransport on port 60606.
Also supports Panasonic DIAL on port 61118 for app launching.
MAC: B4:6C:47:62:1B:BF (Wake-on-LAN supported)
"""

import json
import urllib.request
import re
from pathlib import Path

SKILL_NAME = "panasonic_bd"
SKILL_DESCRIPTION = "Panasonic UB9000 4K Blu-ray — play, pause, stop, status, volume"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "panasonic_bd.json"

def _load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"ip": "", "mac": ""}

_cfg = _load_config()
BD_IP = _cfg.get("ip", "")
BD_MAC = _cfg.get("mac", "")
AVT_URL = f"http://{BD_IP}:60606/Server0/AVT_control"
RCS_URL = f"http://{BD_IP}:60606/Server0/RCS_control"


def _soap(url: str, service: str, action: str, args: str = "") -> str:
    """Send a UPnP SOAP command."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body>'
        f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
        '<InstanceID>0</InstanceID>'
        f'{args}'
        f'</u:{action}>'
        '</s:Body>'
        '</s:Envelope>'
    )
    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error: {e}"


def _extract_xml(text: str, tag: str) -> str:
    """Extract value from XML tag."""
    m = re.search(f"<{tag}>([^<]*)</{tag}>", text)
    return m.group(1) if m else ""


def _wake_on_lan():
    """Send Wake-on-LAN magic packet."""
    import socket
    import struct
    mac_bytes = bytes.fromhex(BD_MAC.replace(":", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(magic, ("255.255.255.255", 9))
    s.close()


def exec_bluray(action: str) -> str:
    """Control the Panasonic UB9000 Blu-ray player."""
    action = action.lower().strip()

    if action in ("status", "info"):
        result = _soap(AVT_URL, "AVTransport", "GetTransportInfo")
        state = _extract_xml(result, "CurrentTransportState")
        status = _extract_xml(result, "CurrentTransportStatus")

        # Also get position if playing
        pos_result = _soap(AVT_URL, "AVTransport", "GetPositionInfo")
        track = _extract_xml(pos_result, "Track")
        duration = _extract_xml(pos_result, "TrackDuration")
        position = _extract_xml(pos_result, "RelTime")
        title = _extract_xml(pos_result, "TrackMetaData")

        info = f"Blu-ray status: {state}"
        if status and status != "OK":
            info += f" ({status})"
        if state == "PLAYING" or state == "PAUSED_PLAYBACK":
            info += f"\nTrack {track}: {position} / {duration}"
        return info

    elif action == "play":
        result = _soap(AVT_URL, "AVTransport", "Play", "<Speed>1</Speed>")
        if "701" in result:
            return "No disc in the player."
        if "Error" in result:
            return result
        return "Blu-ray playing."

    elif action == "pause":
        result = _soap(AVT_URL, "AVTransport", "Pause")
        return "Blu-ray paused."

    elif action == "stop":
        result = _soap(AVT_URL, "AVTransport", "Stop")
        return "Blu-ray stopped."

    elif action in ("next", "skip"):
        _soap(AVT_URL, "AVTransport", "Next")
        return "Next chapter."

    elif action in ("previous", "prev"):
        _soap(AVT_URL, "AVTransport", "Previous")
        return "Previous chapter."

    elif action in ("power_on", "wake"):
        _wake_on_lan()
        return "Wake-on-LAN sent to Blu-ray."

    elif action in ("get_volume", "volume"):
        result = _soap(RCS_URL, "RenderingControl", "GetVolume", "<Channel>Master</Channel>")
        vol = _extract_xml(result, "CurrentVolume")
        return f"Blu-ray volume: {vol}"

    elif action.startswith("volume_"):
        try:
            level = int(action.split("_")[1])
            _soap(RCS_URL, "RenderingControl", "SetVolume",
                  f"<Channel>Master</Channel><DesiredVolume>{level}</DesiredVolume>")
            return f"Blu-ray volume set to {level}."
        except (ValueError, IndexError):
            return "Usage: volume_50 (0-100)"

    elif action == "mute":
        _soap(RCS_URL, "RenderingControl", "SetMute",
              "<Channel>Master</Channel><DesiredMute>1</DesiredMute>")
        return "Blu-ray muted."

    elif action == "unmute":
        _soap(RCS_URL, "RenderingControl", "SetMute",
              "<Channel>Master</Channel><DesiredMute>0</DesiredMute>")
        return "Blu-ray unmuted."

    else:
        return (
            f"Unknown action '{action}'. Available: "
            "status, play, pause, stop, next, previous, "
            "power_on, volume, volume_50, mute, unmute"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bluray",
            "description": "Control the Panasonic UB9000 4K Blu-ray player. Actions: status (current state), play, pause, stop, next (chapter), previous, power_on (wake-on-LAN), volume, mute, unmute.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: status, play, pause, stop, next, previous, power_on, volume, mute, unmute",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "bluray": exec_bluray,
}

KEYWORDS = {
    "bluray": [
        "blu-ray", "bluray", "blu ray", "panasonic", "ub9000", "disc",
        "play disc", "play movie", "4k", "uhd", "eject",
    ],
}
