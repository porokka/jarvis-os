"""
JARVIS Skill — Monitors: recurring background watches run by task_loop.

Creating a monitor writes a task into the shared task_loop store
(Jarvis_vault/.jarvis/tasks/tasks.json). task_loop.py executes it on its
interval and sends a Telegram notification when the condition triggers.

v1 monitor type: flight price watch (Amadeus API).
  "watch flights HEL to BKK on 2026-10-05, alert under 500"
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

SKILL_NAME = "monitor"
SKILL_DESCRIPTION = (
    "Create and manage background monitors — recurring watches that alert via "
    "Telegram or email when a condition is met. Use for: 'watch flight prices "
    "X to Y', 'alert me when <anything> happens', 'monitor if X', "
    "'list monitors', 'remove monitor'."
)

KEYWORDS = {
    "monitor_flights": [
        "monitor flight", "watch flight", "flight alert", "price alert",
        "cheap flight alert", "monitor price", "watch price", "track flight",
    ],
    "monitor_condition": [
        "monitor if", "watch if", "alert me when", "alert when", "notify me when",
        "notify when", "let me know when", "watch for", "keep an eye on",
    ],
    "monitor_list": ["list monitors", "show monitors", "active monitors", "my monitors"],
    "monitor_remove": ["remove monitor", "delete monitor", "stop monitor", "cancel monitor"],
}

SKILL_META = {
    "route": "tools",
}

DEFAULT_VAULT = Path("/mnt/d/Jarvis_vault")
DEFAULT_NOTIFY_CHAT = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "6987301428")


def _tasks_path() -> Path:
    vault = Path(os.environ.get("JARVIS_VAULT", DEFAULT_VAULT))
    p = vault / ".jarvis" / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p / "tasks.json"


def _load_tasks() -> List[Dict[str, Any]]:
    path = _tasks_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
    except Exception:
        pass
    return []


def _save_tasks(tasks: List[Dict[str, Any]]) -> None:
    path = _tasks_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _monitors(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [t for t in tasks if t.get("type") == "monitor"]


def exec_monitor_flights(args: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    args = {**(args or {}), **kwargs}
    origin = str(args.get("origin", "")).strip().upper()
    destination = str(args.get("destination", "")).strip().upper()
    depart_date = str(args.get("depart_date", "")).strip()
    return_date = str(args.get("return_date", "")).strip() or None
    currency = str(args.get("currency", "EUR")).strip().upper() or "EUR"
    interval_hours = float(args.get("interval_hours", 6) or 6)

    try:
        max_price = float(args.get("max_price"))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "speech": "I need a max price to alert on (e.g. 'alert under 500').",
            "error": "missing_max_price",
        }

    if not (origin and destination and depart_date):
        return {
            "ok": False,
            "speech": "I need origin, destination (IATA codes) and a departure date (YYYY-MM-DD).",
            "error": "missing_args",
        }
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", depart_date):
        return {
            "ok": False,
            "speech": f"Departure date must be YYYY-MM-DD, got '{depart_date}'.",
            "error": "bad_date",
        }

    monitor_id = f"flight_{origin}_{destination}_{depart_date}".lower()
    tasks = _load_tasks()
    tasks = [t for t in tasks if t.get("id") != monitor_id]  # replace same watch
    tasks.append({
        "id": monitor_id,
        "type": "monitor",
        "enabled": True,
        "interval_seconds": int(interval_hours * 3600),
        "action": "flight_monitor",
        "args": {
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "return_date": return_date,
            "max_price": max_price,
            "currency": currency,
            "notify_chat_id": str(args.get("notify_chat_id") or DEFAULT_NOTIFY_CHAT),
        },
        "state": {},
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": 0,
    })
    _save_tasks(tasks)

    trip = f"{origin} → {destination} {depart_date}" + (f" (return {return_date})" if return_date else "")
    return {
        "ok": True,
        "speech": (
            f"Monitoring {trip}. I'll check every {interval_hours:g}h and alert you on "
            f"Telegram when a fare drops under {max_price:.0f} {currency}."
        ),
        "data": {"id": monitor_id},
        "error": None,
    }


def exec_monitor_condition(args: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    """Universal monitor: watch a topic via web search, alert when a
    natural-language condition is met (judged by the local LLM)."""
    args = {**(args or {}), **kwargs}
    watch = str(args.get("watch", "")).strip()
    condition = str(args.get("condition", "")).strip()
    notify = str(args.get("notify", "telegram")).strip().lower() or "telegram"
    email_to = str(args.get("email_to", "")).strip()
    interval_hours = float(args.get("interval_hours", 6) or 6)
    cooldown_hours = float(args.get("cooldown_hours", 24) or 24)

    if not (watch and condition):
        return {
            "ok": False,
            "speech": "I need what to watch (a search topic) and the condition to alert on.",
            "error": "missing_args",
        }
    if notify not in ("telegram", "email"):
        return {"ok": False, "speech": "notify must be 'telegram' or 'email'.", "error": "bad_notify"}
    if notify == "email" and not email_to:
        return {"ok": False, "speech": "Email notify needs email_to.", "error": "missing_email"}

    slug = re.sub(r"[^a-z0-9]+", "_", (str(args.get("label", "")) or watch).lower()).strip("_")[:48]
    monitor_id = f"cond_{slug}"
    tasks = _load_tasks()
    tasks = [t for t in tasks if t.get("id") != monitor_id]
    tasks.append({
        "id": monitor_id,
        "type": "monitor",
        "enabled": True,
        "interval_seconds": int(interval_hours * 3600),
        "action": "condition_monitor",
        "args": {
            "watch": watch,
            "condition": condition,
            "notify": notify,
            "email_to": email_to or None,
            "cooldown_hours": cooldown_hours,
            "notify_chat_id": str(args.get("notify_chat_id") or DEFAULT_NOTIFY_CHAT),
        },
        "state": {},
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_run": 0,
    })
    _save_tasks(tasks)

    via = f"email ({email_to})" if notify == "email" else "Telegram"
    return {
        "ok": True,
        "speech": (
            f"Watching '{watch}' every {interval_hours:g}h. When it looks like "
            f"'{condition}', I'll alert you via {via}."
        ),
        "data": {"id": monitor_id},
        "error": None,
    }


def _describe_monitor(t: Dict[str, Any]) -> str:
    a = t.get("args", {})
    action = t.get("action", "")
    enabled = "" if t.get("enabled", True) else " [paused]"
    status = t.get("last_message") or "not checked yet"
    every = f"every {int(t.get('interval_seconds', 0)) // 3600}h"

    if action == "flight_monitor":
        what = (
            f"{a.get('origin')}→{a.get('destination')} {a.get('depart_date')} "
            f"under {float(a.get('max_price', 0)):.0f} {a.get('currency', 'EUR')}"
        )
    elif action == "condition_monitor":
        what = f"'{a.get('watch')}' when '{a.get('condition')}' (via {a.get('notify', 'telegram')})"
    else:
        what = action or "?"

    return f"  {t['id']}{enabled}: {what} {every} — {status}"


def exec_monitor_list(args: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    monitors = _monitors(_load_tasks())
    if not monitors:
        return {"ok": True, "speech": "No active monitors.", "data": {"monitors": []}, "error": None}

    lines = ["Active monitors:"] + [_describe_monitor(t) for t in monitors]
    return {"ok": True, "speech": "\n".join(lines), "data": {"monitors": monitors}, "error": None}


def exec_monitor_remove(args: Dict[str, Any] | None = None, **kwargs: Any) -> Dict[str, Any]:
    args = {**(args or {}), **kwargs}
    monitor_id = str(args.get("id", "")).strip().lower()
    if not monitor_id:
        return {"ok": False, "speech": "Which monitor? Give me its id (see 'list monitors').", "error": "missing_id"}

    tasks = _load_tasks()
    matching = [t for t in tasks if t.get("type") == "monitor" and monitor_id in t.get("id", "")]
    if not matching:
        return {"ok": False, "speech": f"No monitor matching '{monitor_id}'.", "error": "not_found"}
    if len(matching) > 1:
        ids = ", ".join(t["id"] for t in matching)
        return {"ok": False, "speech": f"Multiple monitors match: {ids}. Be more specific.", "error": "ambiguous"}

    tasks = [t for t in tasks if t is not matching[0]]
    _save_tasks(tasks)
    return {"ok": True, "speech": f"Removed monitor {matching[0]['id']}.", "data": {"id": matching[0]["id"]}, "error": None}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "monitor_flights",
            "description": (
                "Create a recurring flight-price watch. Alerts via Telegram when a fare "
                "drops under max_price. IATA codes (HEL, BKK), dates YYYY-MM-DD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "IATA code, e.g. HEL"},
                    "destination": {"type": "string", "description": "IATA code, e.g. BKK"},
                    "depart_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "return_date": {"type": "string", "description": "YYYY-MM-DD, omit for one-way"},
                    "max_price": {"type": "number", "description": "Alert when price drops under this"},
                    "currency": {"type": "string", "description": "Default EUR"},
                    "interval_hours": {"type": "number", "description": "Check interval, default 6"},
                },
                "required": ["origin", "destination", "depart_date", "max_price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monitor_condition",
            "description": (
                "Create a universal recurring watch: web-search a topic on an interval, "
                "and when the given condition is met, alert via Telegram or email. "
                "Use for 'alert me when X happens' requests that aren't flight prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "watch": {"type": "string", "description": "What to search/watch, e.g. 'Oasis reunion tour Helsinki tickets'"},
                    "condition": {"type": "string", "description": "Condition that triggers the alert, e.g. 'tickets go on sale'"},
                    "notify": {"type": "string", "enum": ["telegram", "email"], "description": "Default telegram"},
                    "email_to": {"type": "string", "description": "Required when notify=email"},
                    "interval_hours": {"type": "number", "description": "Check interval, default 6"},
                    "cooldown_hours": {"type": "number", "description": "Quiet period after an alert, default 24"},
                    "label": {"type": "string", "description": "Short name for the monitor id"},
                },
                "required": ["watch", "condition"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monitor_list",
            "description": "List all active background monitors and their last status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monitor_remove",
            "description": "Remove a background monitor by id (or unique id fragment).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Monitor id or fragment, e.g. flight_hel_bkk"},
                },
                "required": ["id"],
            },
        },
    },
]

TOOL_MAP = {
    "monitor_flights": exec_monitor_flights,
    "monitor_condition": exec_monitor_condition,
    "monitor_list": exec_monitor_list,
    "monitor_remove": exec_monitor_remove,
}
