"""
JARVIS Skill — SMS via Twilio.

Send and receive text messages. Incoming SMS can trigger JARVIS
processing and auto-reply.

Config: config/twilio.json (shared with phone skill)
"""

import json
import urllib.request
import urllib.parse
import base64
from datetime import datetime
from pathlib import Path

SKILL_NAME = "sms"
SKILL_DESCRIPTION = "SMS — send/receive text messages via Twilio"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "twilio.json"
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if __import__("os").name != "nt" else Path("D:/Jarvis_vault")
SMS_LOG = VAULT_DIR / "Daily" / "sms"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _twilio_api(method: str, path: str, data: dict = None) -> dict:
    cfg = _load_config()
    sid = cfg.get("account_sid", "")
    token = cfg.get("auth_token", "")

    if not sid or not token:
        return {"error": "Twilio not configured."}

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


def _log_sms(direction: str, number: str, body: str):
    SMS_LOG.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = SMS_LOG / f"{date_str}.md"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {direction} {number}\n{body}\n")


def exec_sms(action: str, number: str = "", message: str = "") -> str:
    """SMS management."""
    action = action.lower().strip()
    cfg = _load_config()

    if not cfg.get("account_sid"):
        return "Twilio not configured. Add credentials to config/twilio.json"

    if action == "send":
        if not number or not message:
            return "Specify number and message. Example: send +358401234567 'Meeting at 3pm'"

        from_number = cfg.get("phone_number", "")
        result = _twilio_api("POST", "Messages", {
            "To": number,
            "From": from_number,
            "Body": message,
        })

        if "error" in result:
            return result["error"]

        _log_sms("SENT", number, message)
        return f"SMS sent to {number}: {message[:50]}..."

    elif action == "recent" or action == "inbox":
        result = _twilio_api("GET", "Messages?PageSize=10")
        if "error" in result:
            return result["error"]

        messages = result.get("messages", [])
        if not messages:
            return "No recent messages."

        lines = []
        for m in messages:
            direction = "IN" if m.get("direction") == "inbound" else "OUT"
            number = m.get("from") if direction == "IN" else m.get("to")
            body = m.get("body", "")[:60]
            date = m.get("date_sent", m.get("date_created", ""))[:16]
            lines.append(f"  {date} {direction:3s} {number:15s} {body}")

        return "Recent messages:\n" + "\n".join(lines)

    elif action == "status":
        phone = cfg.get("phone_number", "not set")
        return f"SMS configured. Phone: {phone}"

    else:
        return "Available actions: send, recent, inbox, status"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sms",
            "description": "Send and receive SMS text messages via Twilio. Actions: send (number + message), recent/inbox (recent messages), status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: send, recent, inbox, status",
                    },
                    "number": {
                        "type": "string",
                        "description": "Phone number (e.g. +358401234567)",
                    },
                    "message": {
                        "type": "string",
                        "description": "SMS text to send",
                    },
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {"sms": exec_sms}

KEYWORDS = {
    "sms": ["sms", "text", "message", "send text", "send message", "inbox"],
}
