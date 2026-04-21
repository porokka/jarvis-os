"""
JARVIS Skill — SMS via Twilio.

Send and receive text messages. Incoming SMS can trigger JARVIS
processing and auto-reply.

Config: config/twilio.json (shared with phone skill)
"""

import json
import base64
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional


SKILL_NAME = "sms"
SKILL_DESCRIPTION = "SMS — send/receive text messages via Twilio"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "communication"
SKILL_TAGS = ["sms", "twilio", "text-message", "messaging", "phone"]
SKILL_REQUIREMENTS = ["config/twilio.json", "Twilio account", "Twilio phone number"]
SKILL_CAPABILITIES = [
    "send_sms",
    "recent_sms",
    "sms_status",
    "sms_logging",
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
    "writes_files": True,
    "reads_files": True,
    "network_access": True,
    "entrypoint": "exec_sms",
    "config_file": "config/twilio.json",
}

CONFIG_FILE = Path(__file__).parent.parent / "config" / "twilio.json"
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
SMS_LOG = VAULT_DIR / "Daily" / "sms"


def _load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _validate_config(cfg: dict) -> Optional[str]:
    if not cfg.get("account_sid"):
        return "Twilio not configured. Missing account_sid in config/twilio.json"
    if not cfg.get("auth_token"):
        return "Twilio not configured. Missing auth_token in config/twilio.json"
    return None


def _is_valid_e164(number: str) -> bool:
    return bool(re.fullmatch(r"\+[1-9]\d{7,14}", (number or "").strip()))


def _twilio_api(method: str, path: str = "", data: dict = None) -> dict:
    cfg = _load_config()
    err = _validate_config(cfg)
    if err:
        return {"error": err}

    sid = str(cfg.get("account_sid", "")).strip()
    token = str(cfg.get("auth_token", "")).strip()

    base_url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
    clean_path = (path or "").strip().lstrip("/")
    url = f"{base_url}/{clean_path}.json" if clean_path else f"{base_url}.json"

    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")

    try:
        encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=encoded, method=method.upper())
        req.add_header("Authorization", f"Basic {auth}")
        if data:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = str(e)
        return {"error": f"Twilio API {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": f"Network error calling Twilio: {e}"}
    except Exception as e:
        return {"error": str(e)}


def _log_sms(direction: str, number: str, body: str) -> None:
    try:
        SMS_LOG.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = SMS_LOG / f"{date_str}.md"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n## {ts} — {direction} {number}\n{body.strip()}\n")
    except Exception:
        pass


def exec_sms(action: str, number: str = "", message: str = "") -> str:
    """SMS management."""
    action = (action or "").lower().strip()
    cfg = _load_config()

    err = _validate_config(cfg)
    if err:
        return err

    if action == "send":
        if not number or not message:
            return "Specify number and message. Example: send +358401234567 'Meeting at 3pm'"
        if not _is_valid_e164(number):
            return "Invalid number format. Use E.164 format, for example: +358401234567"

        from_number = str(cfg.get("phone_number", "")).strip()
        if not from_number:
            return "Twilio not configured. Missing phone_number in config/twilio.json"
        if not _is_valid_e164(from_number):
            return "Configured Twilio phone_number is not valid E.164 format."

        result = _twilio_api(
            "POST",
            "Messages",
            {
                "To": number.strip(),
                "From": from_number,
                "Body": message.strip(),
            },
        )

        if "error" in result:
            return result["error"]

        sid = result.get("sid", "?")
        status = result.get("status", "queued")
        _log_sms("SENT", number.strip(), message.strip())
        return f"SMS sent to {number.strip()} ({status}, SID: {sid})"

    elif action in ("recent", "inbox"):
        result = _twilio_api("GET", "Messages?PageSize=10")
        if "error" in result:
            return result["error"]

        messages = result.get("messages", [])
        if not messages:
            return "No recent messages."

        lines = []
        for m in messages:
            direction_raw = str(m.get("direction", "")).lower()
            direction = "IN" if direction_raw == "inbound" else "OUT"
            peer_number = m.get("from") if direction == "IN" else m.get("to")
            peer_number = str(peer_number or "?")
            body = str(m.get("body", "") or "").replace("\n", " ")[:80]
            date = str(m.get("date_sent", m.get("date_created", "")) or "")[:25]
            status = str(m.get("status", "?"))
            lines.append(f"  {date}  {direction:3s}  {peer_number:16s}  {status:10s}  {body}")

        return "Recent messages:\n" + "\n".join(lines)

    elif action == "status":
        phone = str(cfg.get("phone_number", "not set")).strip() or "not set"
        return f"SMS configured.\nPhone: {phone}"

    else:
        return "Available actions: send, recent, inbox, status"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sms",
            "description": (
                "Send and receive SMS text messages via Twilio. "
                "Actions: send (number + message), recent/inbox (recent messages), status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send", "recent", "inbox", "status"],
                        "description": "Action: send, recent, inbox, status",
                    },
                    "number": {
                        "type": "string",
                        "description": "Phone number in E.164 format, e.g. +358401234567",
                    },
                    "message": {
                        "type": "string",
                        "description": "SMS text to send",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "sms": exec_sms,
}

KEYWORDS = {
    "sms": [
        "sms",
        "text",
        "message",
        "send text",
        "send message",
        "text message",
        "inbox",
        "recent messages",
        "twilio",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "send text to +358401234567",
        "tool": "sms",
        "args": {
            "action": "send",
            "number": "+358401234567",
            "message": "Meeting at 3 pm.",
        },
    },
    {
        "command": "show recent sms",
        "tool": "sms",
        "args": {
            "action": "recent",
        },
    },
    {
        "command": "show sms inbox",
        "tool": "sms",
        "args": {
            "action": "inbox",
        },
    },
    {
        "command": "sms status",
        "tool": "sms",
        "args": {
            "action": "status",
        },
    },
]