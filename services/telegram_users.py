"""
Telegram user registry — identity, enrollment, approval.

Users are keyed by Telegram user id (== chat id for 1:1 chats) in
config/telegram_users.json:

    {
      "6987301428": {"name": "Sami", "role": "owner", "status": "approved"}
    }

Enrollment flow (wired in telegram_gateway.poll_forever):
  unknown user sends an intro ("Hi, this is Inga")
    -> create_pending() + owner gets Approve/Deny inline buttons
    -> usr:approve:<id> callback -> resolve_pending() -> user is in.
Approved users pass gateway.is_allowed() like env-allowlisted chats.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_PATH = Path(__file__).parent.parent / "config" / "telegram_users.json"

DEFAULT_USERS: Dict[str, Dict[str, Any]] = {
    "6987301428": {"name": "Sami", "role": "owner", "status": "approved"},
}

_INTRO_PATTERNS = [
    re.compile(r"\bthis is ([a-zA-ZÀ-ž][a-zA-ZÀ-ž' -]{1,31})", re.IGNORECASE),
    re.compile(r"\bi am ([a-zA-ZÀ-ž][a-zA-ZÀ-ž' -]{1,31})", re.IGNORECASE),
    re.compile(r"\bi'?m ([a-zA-ZÀ-ž][a-zA-ZÀ-ž' -]{1,31})", re.IGNORECASE),
]

# words that follow "I'm ..." but are clearly not a name
_NOT_NAMES = {
    "sorry", "back", "here", "home", "ready", "done", "ok", "okay", "fine",
    "good", "sure", "not", "just", "still", "going", "trying", "looking",
}


def load_users() -> Dict[str, Dict[str, Any]]:
    if not CONFIG_PATH.exists():
        save_users(dict(DEFAULT_USERS))
        return dict(DEFAULT_USERS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(DEFAULT_USERS)


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def get_user(user_id: str | int) -> Optional[Dict[str, Any]]:
    return load_users().get(str(user_id))


def is_approved(user_id: str | int) -> bool:
    user = get_user(user_id)
    return bool(user and user.get("status") == "approved")


def owner_chat_ids() -> List[str]:
    return [
        uid for uid, u in load_users().items()
        if u.get("role") == "owner" and u.get("status") == "approved"
    ]


def parse_intro(text: str) -> Optional[str]:
    """Extract a name from a self-introduction, or None."""
    for pattern in _INTRO_PATTERNS:
        m = pattern.search(text or "")
        if m:
            name = m.group(1).strip().strip("'").split()[0]
            if name.lower() in _NOT_NAMES or len(name) < 2:
                continue
            return name.capitalize()
    return None


def create_pending(user_id: str | int, name: str, username: str = "") -> Dict[str, Any]:
    users = load_users()
    entry = {
        "name": name,
        "role": "family",
        "status": "pending",
        "username": username,
        "requested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    users[str(user_id)] = entry
    save_users(users)
    return entry


def resolve_pending(user_id: str | int, verdict: str) -> str:
    """verdict: 'approve' | 'deny'. Returns a status line for the owner."""
    users = load_users()
    user = users.get(str(user_id))
    if not user:
        return f"No pending user with id {user_id}."
    name = user.get("name", user_id)
    if verdict == "approve":
        user["status"] = "approved"
        user["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_users(users)
        return f"✅ {name} approved — they can now talk to JARVIS."
    users.pop(str(user_id), None)
    save_users(users)
    return f"❌ {name} denied and removed."


def identity_context(user_id: str | int, fallback_name: str = "") -> str:
    """System-message line describing the sender, for personalized replies."""
    user = get_user(user_id)
    if user and user.get("status") == "approved":
        name = user.get("name", "")
        role = user.get("role", "user")
        if role == "owner":
            return f"Telegram sender: {name} (owner). Address him by name."
        return (
            f"Telegram sender: {name} ({role}). Address them by name and "
            "personalize the reply for them."
        )
    if fallback_name:
        return f"Telegram sender: {fallback_name} (unregistered)."
    return ""
