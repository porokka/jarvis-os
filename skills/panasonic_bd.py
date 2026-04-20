"""
JARVIS Skill — Panasonic DP-UB9000 4K Blu-ray player control.

Controls via UPnP/DLNA AVTransport on port 60606.
Also supports Panasonic DIAL on port 61118 for app launching.
MAC: B4:6C:47:62:1B:BF (Wake-on-LAN supported)
"""

import json
import re
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET


SKILL_NAME = "panasonic_bd"
SKILL_DESCRIPTION = "Panasonic UB9000 4K Blu-ray — play, pause, stop, status, volume"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "OpenAI"
SKILL_CATEGORY = "media"
SKILL_TAGS = ["panasonic", "blu-ray", "uhd", "upnp", "dlna", "avtransport", "media-control"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = [
    "device_status",
    "playback_control",
    "volume_control",
    "mute_control",
    "wake_on_lan",
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
    "entrypoint": "exec_bluray",
    "config_file": "config/panasonic_bd.json",
}

CONFIG_FILE = Path(__file__).parent.parent / "config" / "panasonic_bd.json"


def _load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"ip": "", "mac": ""}
        return {
            "ip": str(data.get("ip", "")).strip(),
            "mac": str(data.get("mac", "")).strip(),
        }
    except Exception:
        return {"ip": "", "mac": ""}


_cfg = _load_config()
BD_IP = _cfg.get("ip", "")
BD_MAC = _cfg.get("mac", "")


def _has_ip() -> bool:
    return bool(BD_IP)


def _has_mac() -> bool:
    return bool(BD_MAC)


def _avt_url() -> str:
    return f"http://{BD_IP}:60606/Server0/AVT_control"


def _rcs_url() -> str:
    return f"http://{BD_IP}:60606/Server0/RCS_control"


def _device_ready() -> Optional[str]:
    if not _has_ip():
        return "Error: Blu-ray player IP is not configured in panasonic_bd.json"
    return None


def _soap(url: str, service: str, action: str, args: str = "") -> str:
    """Send a UPnP SOAP command."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
        "<InstanceID>0</InstanceID>"
        f"{args}"
        f"</u:{action}>"
        "</s:Body>"
        "</s:Envelope>"
    )

    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")

    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(e)
        return f"Error: HTTP {e.code} while calling {action}: {detail}"

    except urllib.error.URLError as e:
        return f"Error: unable to reach Blu-ray player for {action}: {e}"

    except Exception as e:
        return f"Error: {e}"


def _extract_xml(text: str, tag: str) -> str:
    """Extract first matching XML tag value, namespace-agnostic fallback."""
    if not text or text.startswith("Error:"):
        return ""

    # Fast regex fallback for simple SOAP bodies
    m = re.search(rf"<(?:\w+:)?{re.escape(tag)}>(.*?)</(?:\w+:)?{re.escape(tag)}>", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Safer XML parse fallback
    try:
        root = ET.fromstring(text)
        for elem in root.iter():
            elem_tag = elem.tag.split("}", 1)[-1]
            if elem_tag == tag:
                return (elem.text or "").strip()
    except Exception:
        pass

    return ""


def _soap_ok(result: str) -> bool:
    return bool(result) and not result.startswith("Error:")


def _soap_fault_text(result: str) -> str:
    if not result:
        return "Unknown SOAP error."

    fault_string = _extract_xml(result, "faultstring")
    error_code = _extract_xml(result, "errorCode")
    error_desc = _extract_xml(result, "errorDescription")

    parts = []
    if fault_string:
        parts.append(fault_string)
    if error_code:
        parts.append(f"code {error_code}")
    if error_desc:
        parts.append(error_desc)

    return " — ".join(parts) if parts else result[:300]


def _wake_on_lan() -> str:
    """Send Wake-on-LAN magic packet."""
    if not _has_mac():
        return "Error: Blu-ray player MAC is not configured in panasonic_bd.json"

    mac_clean = BD_MAC.replace(":", "").replace("-", "").strip().lower()
    if len(mac_clean) != 12 or not re.fullmatch(r"[0-9a-f]{12}", mac_clean):
        return f"Error: invalid MAC address format: {BD_MAC}"

    try:
        mac_bytes = bytes.fromhex(mac_clean)
        magic = b"\xff" * 6 + mac_bytes * 16

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic, ("255.255.255.255", 9))
        finally:
            sock.close()

        return "Wake-on-LAN sent to Blu-ray."
    except Exception as e:
        return f"Error sending Wake-on-LAN: {e}"


def exec_bluray(action: str) -> str:
    """Control the Panasonic UB9000 Blu-ray player."""
    action = (action or "").lower().strip()

    if not action:
        return "Specify an action. Try: status, play, pause, stop, next, previous, power_on, volume, mute, unmute"

    if action in ("power_on", "wake"):
        return _wake_on_lan()

    readiness = _device_ready()
    if readiness:
        return readiness

    if action in ("status", "info"):
        result = _soap(_avt_url(), "AVTransport", "GetTransportInfo")
        if not _soap_ok(result):
            return result

        state = _extract_xml(result, "CurrentTransportState") or "UNKNOWN"
        status = _extract_xml(result, "CurrentTransportStatus") or "UNKNOWN"

        pos_result = _soap(_avt_url(), "AVTransport", "GetPositionInfo")
        track = _extract_xml(pos_result, "Track")
        duration = _extract_xml(pos_result, "TrackDuration")
        position = _extract_xml(pos_result, "RelTime")
        title = _extract_xml(pos_result, "TrackMetaData")

        info = f"Blu-ray status: {state}"
        if status and status != "OK":
            info += f" ({status})"

        if state in ("PLAYING", "PAUSED_PLAYBACK"):
            if track or position or duration:
                info += f"\nTrack {track or '?'}: {position or '?'} / {duration or '?'}"

        if title and title not in ("NOT_IMPLEMENTED",):
            info += f"\nMetadata: {title[:200]}"

        return info

    elif action == "play":
        result = _soap(_avt_url(), "AVTransport", "Play", "<Speed>1</Speed>")
        if not _soap_ok(result):
            return result
        if "701" in result or _extract_xml(result, "errorCode") == "701":
            return "No disc in the player."
        return "Blu-ray playing."

    elif action == "pause":
        result = _soap(_avt_url(), "AVTransport", "Pause")
        if not _soap_ok(result):
            return result
        return "Blu-ray paused."

    elif action == "stop":
        result = _soap(_avt_url(), "AVTransport", "Stop")
        if not _soap_ok(result):
            return result
        return "Blu-ray stopped."

    elif action in ("next", "skip"):
        result = _soap(_avt_url(), "AVTransport", "Next")
        if not _soap_ok(result):
            return result
        return "Next chapter."

    elif action in ("previous", "prev"):
        result = _soap(_avt_url(), "AVTransport", "Previous")
        if not _soap_ok(result):
            return result
        return "Previous chapter."

    elif action in ("get_volume", "volume"):
        result = _soap(_rcs_url(), "RenderingControl", "GetVolume", "<Channel>Master</Channel>")
        if not _soap_ok(result):
            return result

        vol = _extract_xml(result, "CurrentVolume")
        if vol == "":
            return "Could not read Blu-ray volume."
        return f"Blu-ray volume: {vol}"

    elif action.startswith("volume_"):
        try:
            level = int(action.split("_", 1)[1])
        except (ValueError, IndexError):
            return "Usage: volume_50 (0-100)"

        if level < 0 or level > 100:
            return "Volume must be between 0 and 100."

        result = _soap(
            _rcs_url(),
            "RenderingControl",
            "SetVolume",
            f"<Channel>Master</Channel><DesiredVolume>{level}</DesiredVolume>",
        )
        if not _soap_ok(result):
            return result

        # Some devices return empty successful SOAP body; also inspect if fault exists
        if "fault" in result.lower():
            return f"Failed to set volume: {_soap_fault_text(result)}"

        return f"Blu-ray volume set to {level}."

    elif action == "mute":
        result = _soap(
            _rcs_url(),
            "RenderingControl",
            "SetMute",
            "<Channel>Master</Channel><DesiredMute>1</DesiredMute>",
        )
        if not _soap_ok(result):
            return result
        return "Blu-ray muted."

    elif action == "unmute":
        result = _soap(
            _rcs_url(),
            "RenderingControl",
            "SetMute",
            "<Channel>Master</Channel><DesiredMute>0</DesiredMute>",
        )
        if not _soap_ok(result):
            return result
        return "Blu-ray unmuted."

    elif action == "eject":
        return "Eject is not implemented for this device via the current UPnP control path."

    else:
        return (
            f"Unknown action '{action}'. Available: "
            "status, play, pause, stop, next, previous, "
            "power_on, volume, volume_50, mute, unmute, eject"
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bluray",
            "description": (
                "Control the Panasonic UB9000 4K Blu-ray player. "
                "Actions: status, play, pause, stop, next, previous, "
                "power_on, volume, volume_50, mute, unmute, eject."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "Action to run. Examples: status, play, pause, stop, next, previous, "
                            "power_on, volume, volume_50, mute, unmute, eject"
                        ),
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "bluray": exec_bluray,
}

KEYWORDS = {
    "bluray": [
        "blu-ray",
        "bluray",
        "blu ray",
        "panasonic",
        "ub9000",
        "disc",
        "play disc",
        "play movie",
        "4k",
        "uhd",
        "eject",
        "pause movie",
        "stop disc",
        "player status",
        "volume",
        "mute",
    ],
}