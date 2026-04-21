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
import base64
import html
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional


SKILL_NAME = "phone"
SKILL_DESCRIPTION = "Phone calls via Twilio — make calls, check messages, call log"
SKILL_VERSION = "1.1.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "communication"
SKILL_TAGS = ["twilio", "phone", "calls", "voicemail", "telephony", "sms"]
SKILL_REQUIREMENTS = ["twilio account", "twilio phone number", "config/twilio.json"]
SKILL_CAPABILITIES = [
    "make_call",
    "recent_calls",
    "voicemail_list",
    "account_status",
    "call_logging",
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
    "entrypoint": "exec_phone",
    "config_file": "config/twilio.json",
}

CONFIG_FILE = Path(__file__).parent.parent / "config" / "twilio.json"
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
CALL_LOG = VAULT_DIR / "Daily" / "calls"


def _load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _validate_config(cfg: dict) -> Optional[str]:
    if not cfg.get("account_sid"):
        return "Twilio not configured. Missing account_sid in config/twilio.json"
    if not cfg.get("auth_token"):
        return "Twilio not configured. Missing auth_token in config/twilio.json"
    return None


def _is_valid_e164(number: str) -> bool:
    """
    Accepts a practical E.164 subset:
    + followed by 8 to 15 digits.
    """
    return bool(re.fullmatch(r"\+[1-9]\d{7,14}", (number or "").strip()))


def _twilio_api(method: str, path: str = "", data: dict = None) -> dict:
    """Call Twilio REST API."""
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
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)

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


def _log_call(direction: str, number: str, summary: str) -> None:
    """Log call to vault."""
    try:
        CALL_LOG.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = CALL_LOG / f"{date_str}.md"

        entry = (
            f"\n## {ts} — {direction} {number}\n"
            f"{summary.strip()}\n"
        )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        # Logging failure should not break call handling
        pass


def _build_twiml_say(message: str) -> str:
    safe = html.escape((message or "").strip())
    return f'<Response><Say voice="alice">{safe}</Say></Response>'


def exec_phone(action: str, number: str = "", message: str = "") -> str:
    """Phone call management."""
    action = (action or "").lower().strip()
    cfg = _load_config()

    err = _validate_config(cfg)
    if err:
        return err

    if action == "call":
        if not number:
            return "Specify a number to call."
        if not _is_valid_e164(number):
            return "Invalid number format. Use E.164 format, for example: +358401234567"

        from_number = str(cfg.get("phone_number", "")).strip()
        if not from_number:
            return "Twilio not configured. Missing phone_number in config/twilio.json"
        if not _is_valid_e164(from_number):
            return "Configured Twilio phone_number is not valid E.164 format."

        spoken_message = (
            message.strip()
            if message and message.strip()
            else "Hello, this is JARVIS calling on behalf of my employer. How may I help you?"
        )

        result = _twilio_api(
            "POST",
            "Calls",
            {
                "To": number.strip(),
                "From": from_number,
                "Twiml": _build_twiml_say(spoken_message),
            },
        )

        if "error" in result:
            return result["error"]

        sid = result.get("sid", "?")
        status = result.get("status", "queued")
        _log_call("OUTGOING", number.strip(), spoken_message)
        return f"Calling {number.strip()}... Call SID: {sid} ({status})"

    elif action == "recent":
        result = _twilio_api("GET", "Calls?PageSize=10")
        if "error" in result:
            return result["error"]

        calls = result.get("calls", [])
        if not calls:
            return "No recent calls."

        lines = []
        for c in calls:
            direction = str(c.get("direction", "?"))
            number_value = c.get("from") if "inbound" in direction else c.get("to")
            number_value = str(number_value or "?")
            status = str(c.get("status", "?"))
            duration = str(c.get("duration", "0") or "0")
            date = str(c.get("date_created", "?"))[:25]
            lines.append(f"  {date}  {direction:12s}  {number_value:16s}  {status} ({duration}s)")

        return "Recent calls:\n" + "\n".join(lines)

    elif action in ("voicemail", "messages"):
        result = _twilio_api("GET", "Recordings?PageSize=10")
        if "error" in result:
            return result["error"]

        recordings = result.get("recordings", [])
        if not recordings:
            return "No voicemail recordings."

        lines = []
        for r in recordings:
            date = str(r.get("date_created", "?"))[:25]
            duration = str(r.get("duration", "0") or "0")
            call_sid = str(r.get("call_sid", "?"))
            recording_sid = str(r.get("sid", "?"))
            lines.append(
                f"  {date}  {duration}s  recording:{recording_sid[:10]}...  call:{call_sid[:10]}..."
            )

        return "Voicemail recordings:\n" + "\n".join(lines)

    elif action == "status":
        result = _twilio_api("GET")
        if "error" in result:
            return result["error"]

        name = result.get("friendly_name", "?")
        status = result.get("status", "?")
        phone = str(cfg.get("phone_number", "not set")).strip() or "not set"
        return f"Twilio account: {name}\nStatus: {status}\nPhone: {phone}"

    else:
        return "Available actions: call, recent, voicemail, status"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "phone",
            "description": (
                "Make phone calls and check call history via Twilio. "
                "Actions: call (number + optional message), recent (call log), "
                "voicemail (recordings), status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["call", "recent", "voicemail", "messages", "status"],
                        "description": "Action: call, recent, voicemail, messages, status",
                    },
                    "number": {
                        "type": "string",
                        "description": "Phone number in E.164 format, e.g. +358401234567",
                    },
                    "message": {
                        "type": "string",
                        "description": "Optional spoken message for outbound calls",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "phone": exec_phone,
}

KEYWORDS = {
    "phone": [
        "call",
        "phone",
        "ring",
        "dial",
        "voicemail",
        "missed calls",
        "recent calls",
        "make a call",
        "call history",
        "recordings",
        "twilio",
    ],
}