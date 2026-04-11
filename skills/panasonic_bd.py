"""
JARVIS Skill — Panasonic DP-UB9000 4K Blu-ray player control.

Controls via Panasonic SOAP API on port 9080.
"""

import urllib.request

SKILL_NAME = "panasonic_bd"
SKILL_DESCRIPTION = "Panasonic UB9000 4K Blu-ray — power, play, pause, eject, menu, navigation"

BD_IP = "192.168.0.209"
BD_PORT = 9080
CONTROL_URL = f"http://{BD_IP}:{BD_PORT}/nrc/control_0"

# Panasonic NRC key codes for Blu-ray players
KEYS = {
    # Power
    "power": "NRC_POWER-ONOFF",
    "power_on": "NRC_POWER-ONOFF",
    "power_off": "NRC_POWER-ONOFF",
    # Playback
    "play": "NRC_PLAY-ONOFF",
    "pause": "NRC_PAUSE-ONOFF",
    "stop": "NRC_STOP-ONOFF",
    "next": "NRC_SKIP_NEXT-ONOFF",
    "previous": "NRC_SKIP_PREV-ONOFF",
    "fast_forward": "NRC_FF-ONOFF",
    "rewind": "NRC_REW-ONOFF",
    # Disc
    "eject": "NRC_OP_CL-ONOFF",
    "open": "NRC_OP_CL-ONOFF",
    "close": "NRC_OP_CL-ONOFF",
    # Navigation
    "up": "NRC_UP-ONOFF",
    "down": "NRC_DOWN-ONOFF",
    "left": "NRC_LEFT-ONOFF",
    "right": "NRC_RIGHT-ONOFF",
    "ok": "NRC_ENTER-ONOFF",
    "enter": "NRC_ENTER-ONOFF",
    "back": "NRC_RETURN-ONOFF",
    "return": "NRC_RETURN-ONOFF",
    "home": "NRC_HOME-ONOFF",
    "menu": "NRC_MENU-ONOFF",
    "top_menu": "NRC_TOP_MENU-ONOFF",
    "popup_menu": "NRC_POPUP_MENU-ONOFF",
    "option": "NRC_SUBMENU-ONOFF",
    # Display
    "info": "NRC_DISP_MODE-ONOFF",
    "subtitle": "NRC_STTL-ONOFF",
    "audio": "NRC_AUDIO-ONOFF",
    # Numbers
    "0": "NRC_D0-ONOFF", "1": "NRC_D1-ONOFF", "2": "NRC_D2-ONOFF",
    "3": "NRC_D3-ONOFF", "4": "NRC_D4-ONOFF", "5": "NRC_D5-ONOFF",
    "6": "NRC_D6-ONOFF", "7": "NRC_D7-ONOFF", "8": "NRC_D8-ONOFF",
    "9": "NRC_D9-ONOFF",
    # Color buttons
    "red": "NRC_RED-ONOFF",
    "green": "NRC_GREEN-ONOFF",
    "yellow": "NRC_YELLOW-ONOFF",
    "blue": "NRC_BLUE-ONOFF",
}


def _send_key(key_event: str) -> str:
    """Send a NRC key command to the Panasonic player."""
    soap = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body>'
        '<u:X_SendKey xmlns:u="urn:panasonic-com:service:p00NetworkControl:1">'
        f'<X_KeyEvent>{key_event}</X_KeyEvent>'
        '</u:X_SendKey>'
        '</s:Body>'
        '</s:Envelope>'
    )
    try:
        req = urllib.request.Request(
            CONTROL_URL,
            data=soap.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": '"urn:panasonic-com:service:p00NetworkControl:1#X_SendKey"',
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error: {e}"


def exec_bluray(action: str) -> str:
    """Control the Panasonic UB9000 Blu-ray player."""
    action_lower = action.lower().strip().replace(" ", "_")

    key = KEYS.get(action_lower)
    if not key:
        # Try fuzzy match
        for k, v in KEYS.items():
            if action_lower in k or k in action_lower:
                key = v
                break

    if not key:
        available = ", ".join(sorted(KEYS.keys()))
        return f"Unknown action '{action}'. Available: {available}"

    result = _send_key(key)
    if "Error" in result:
        return result

    return f"Blu-ray: {action}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bluray",
            "description": "Control the Panasonic UB9000 4K Blu-ray player. Actions: power, play, pause, stop, eject, next, previous, fast_forward, rewind, up/down/left/right, ok/enter, back, home, menu, top_menu, popup_menu, subtitle, audio, info, red/green/yellow/blue buttons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: power, play, pause, stop, eject, next, previous, fast_forward, rewind, up, down, left, right, ok, back, home, menu, top_menu, subtitle, audio, info",
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
        "blu-ray", "bluray", "blu ray", "panasonic", "ub9000", "disc", "eject",
        "play disc", "play movie", "4k", "uhd",
    ],
}
