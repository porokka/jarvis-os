"""
JARVIS Skill — Phone calls via Twilio.

Receive and make phone calls. Incoming calls are answered by JARVIS,
transcribed, processed, and responded to via TTS.

Config: config/twilio.json
Setup:
  1. Create Twilio account at twilio.com
  2. Get a phone number (~$1/month)
  3. Set webhook URL to your server's /api/twilio/voice
  4. Add credentials to config/twilio.json

Requires: pip install twilio
"""

import json
import urllib.request
import urllib.parse
import base64
from datetime import datetime
from pathlib import Path

SKILL_NAME = "phone"
SKILL_DESCRIPTION = "Phone calls via Twilio — make calls, check messages, call log"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "twilio.json"
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if __import__("os").name != "nt" else Path("D:/Jarvis_vault")
CALL_LOG = VAULT_DIR / "Daily" / "calls"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _twilio_api(method: str, path: str, data: dict = None) -> dict:
    """Call Twilio REST API."""
    cfg = _load_config()
    sid = cfg.get("account_sid", "")
    token = cfg.get("auth_token", "")

    if not sid or not token:
        return {"error": "Twilio not configured. Add account_sid and auth_token to config/twilio.json"}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/{path}.json"
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()

    try:
        encoded = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=encoded, method=method)
        req.add_header("Authorization", f"Basic {auth}")
        if data:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return {"error": f"Twilio API {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def _log_call(direction: str, number: str, summary: str):
    """Log call to vault."""
    CALL_LOG.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = CALL_LOG / f"{date_str}.md"

    entry = f"\n## {ts} — {direction} {number}\n{summary}\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)


def exec_phone(action: str, number: str = "", message: str = "") -> str:
    """Phone call management."""
    action = action.lower().strip()
    cfg = _load_config()

    if not cfg.get("account_sid"):
        return "Twilio not configured. Create config/twilio.json with account_sid, auth_token, phone_number."

    if action == "call":
        if not number:
            return "Specify a number to call."
        from_number = cfg.get("phone_number", "")
        twiml = message or "Hello, this is JARVIS calling on behalf of my employer. How may I help you?"

        result = _twilio_api("POST", "Calls", {
            "To": number,
            "From": from_number,
            "Twiml": f'<Response><Say voice="alice">{twiml}</Say></Response>',
        })

        if "error" in result:
            return result["error"]

        _log_call("OUTGOING", number, twiml)
        return f"Calling {number}... Call SID: {result.get('sid', '?')}"

    elif action == "recent":
        result = _twilio_api("GET", "Calls?PageSize=10")
        if "error" in result:
            return result["error"]

        calls = result.get("calls", [])
        if not calls:
            return "No recent calls."

        lines = []
        for c in calls:
            direction = c.get("direction", "?")
            number = c.get("from") if direction == "inbound" else c.get("to")
            status = c.get("status", "?")
            duration = c.get("duration", "0")
            date = c.get("date_created", "?")[:16]
            lines.append(f"  {date} {direction:8s} {number:15s} {status} ({duration}s)")

        return "Recent calls:\n" + "\n".join(lines)

    elif action == "voicemail" or action == "messages":
        result = _twilio_api("GET", "Recordings?PageSize=10")
        if "error" in result:
            return result["error"]

        recordings = result.get("recordings", [])
        if not recordings:
            return "No voicemail recordings."

        lines = []
        for r in recordings:
            date = r.get("date_created", "?")[:16]
            duration = r.get("duration", "0")
            call_sid = r.get("call_sid", "?")
            lines.append(f"  {date} {duration}s (call: {call_sid[:8]}...)")

        return "Voicemail recordings:\n" + "\n".join(lines)

    elif action == "status":
        result = _twilio_api("GET", "")
        if "error" in result:
            return result["error"]

        name = result.get("friendly_name", "?")
        phone = cfg.get("phone_number", "not set")
        balance = "check twilio.com"
        return f"Twilio account: {name}\nPhone: {phone}\nBalance: {balance}"

    else:
        return "Available actions: call, recent, voicemail, status"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "phone",
            "description": "Make phone calls and check call history via Twilio. Actions: call (number + optional message), recent (call log), voicemail (recordings), status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: call, recent, voicemail, status",
                    },
                    "number": {
                        "type": "string",
                        "description": "Phone number for call (e.g. +358401234567)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to say on the call",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {"phone": exec_phone}

KEYWORDS = {
    "phone": ["call", "phone", "ring", "dial", "voicemail", "missed calls"],
}
