#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_VAULT = Path("/mnt/d/Jarvis_vault")
POLL_SECONDS = 10


def vault_root() -> Path:
    return Path(os.environ.get("JARVIS_VAULT", DEFAULT_VAULT))


def task_dir() -> Path:
    p = vault_root() / ".jarvis" / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tasks_path() -> Path:
    return task_dir() / "tasks.json"


def results_path() -> Path:
    return task_dir() / "results.jsonl"


def now_ts() -> float:
    return time.time()


def log_result(task_id: str, status: str, message: str, extra: dict[str, Any] | None = None) -> None:
    row = {
        "ts": now_ts(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": task_id,
        "status": status,
        "message": message,
        "extra": extra or {},
    }

    with results_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def default_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "update_aaak_context",
            "type": "system",
            "enabled": True,
            "interval_seconds": 300,
            "action": "update_aaak_context",
            "args": {
                "minutes": 15,
                "model": "qwen3:14b",
            },
            "last_run": 0,
        }
    ]


def load_tasks() -> list[dict[str, Any]]:
    path = tasks_path()

    if not path.exists():
        tasks = default_tasks()
        save_tasks(tasks)
        return tasks

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
    except Exception as e:
        log_result("task_loop", "error", f"Failed to read tasks.json: {e}")

    return []


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    tmp = tasks_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(tasks_path())


def merge_run_state(tasks: list[dict[str, Any]]) -> None:
    """Persist run-state without clobbering tasks the monitor skill added or
    removed while this tick was executing (both sides do read-modify-write
    on the same tasks.json)."""
    current = load_tasks()
    by_id = {str(t.get("id")): t for t in tasks}
    changed = False

    for task in current:
        src = by_id.get(str(task.get("id")))
        if src is None:
            continue
        for field in ("last_run", "last_status", "last_message", "state"):
            if field in src and task.get(field) != src[field]:
                task[field] = src[field]
                changed = True

    if changed:
        save_tasks(current)


def should_run(task: dict[str, Any], ts: float) -> bool:
    if not task.get("enabled", True):
        return False

    interval = int(task.get("interval_seconds", 0))
    if interval <= 0:
        return False

    last_run = float(task.get("last_run", 0))
    return ts - last_run >= interval


def run_update_aaak_context(task: dict[str, Any]) -> str:
    from chat_context import update_aaak_context

    args = task.get("args") or {}
    minutes = int(args.get("minutes", 15))
    model = str(args.get("model", "qwen3:14b"))

    path = update_aaak_context(minutes=minutes, model=model)
    return f"AAAK context updated: {path}"


def _send_telegram(chat_id: str, text: str) -> None:
    from services.telegram_gateway import TelegramGateway

    TelegramGateway(vault_root()).send_message(chat_id, text)


def run_flight_monitor(task: dict[str, Any]) -> str:
    """Check cheapest fare via Duffel; alert Telegram when under max_price.

    Re-alerts only when the price drops below the last notified price, so a
    fare sitting under the threshold doesn't spam every interval.
    """
    from skills.duffel_flights import cheapest_offer

    args = task.get("args") or {}
    origin = args["origin"]
    destination = args["destination"]
    depart_date = args["depart_date"]
    return_date = args.get("return_date")
    max_price = float(args.get("max_price", 0))

    offer = cheapest_offer(origin, destination, depart_date, return_date=return_date)
    if offer is None:
        return "no offers found"

    # Duffel returns its own settlement currency per offer — it isn't a
    # request parameter — so max_price is only meaningful if it was set in
    # that same currency (monitor_flights records args["currency"] as a
    # label, not a conversion; mismatches will under/over-trigger).
    price = float(offer["price"])
    currency = offer.get("currency", args.get("currency", "EUR"))
    state = task.setdefault("state", {})
    state["last_price"] = price
    state["last_currency"] = currency
    state["last_checked"] = time.strftime("%Y-%m-%d %H:%M:%S")

    last_notified = state.get("last_notified_price")
    if price <= max_price and (last_notified is None or price < float(last_notified)):
        trip = f"{origin}→{destination} {depart_date}"
        if return_date:
            trip += f" (return {return_date})"
        stops = "direct" if offer.get("stops") == 0 else f"{offer.get('stops')} stop(s)"
        _notify(
            args,
            f"✈️ Fare alert: {trip}",
            (
                f"Now {price:.0f} {currency} ({offer.get('carrier', '?')}, {stops}) "
                f"— your target was {max_price:.0f} {args.get('currency', currency)}."
            ),
        )
        state["last_notified_price"] = price
        return f"ALERT sent: {price:.0f} {currency}"

    return f"cheapest {price:.0f} {currency} (target {max_price:.0f} {args.get('currency', '')})"


def _ollama_json(system: str, prompt: str, model: str = "qwen3:14b") -> dict[str, Any]:
    """Small non-thinking Ollama call that must return a JSON object."""
    import urllib.request

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    payload = json.dumps({
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.1, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{host}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = json.loads(resp.read())["message"]["content"]

    start = raw.index("{")
    end = raw.rindex("}") + 1
    return json.loads(raw[start:end])


def _notify(args: dict[str, Any], subject: str, body: str) -> str:
    """Send an alert via telegram (default) or email, per monitor args."""
    via = str(args.get("notify", "telegram")).lower()
    if via == "email":
        from skills.email_skill import _send_email

        to = str(args.get("email_to", "")).strip()
        if not to:
            raise ValueError("email notify requested but no email_to set")
        return _send_email(to, subject, body)
    _send_telegram(str(args.get("notify_chat_id", "6987301428")), f"{subject}\n{body}")
    return "telegram sent"


def run_condition_monitor(task: dict[str, Any]) -> str:
    """Universal monitor: web-search a topic, LLM-judge a condition, notify.

    args: watch (search query), condition (natural language), notify
    ("telegram"|"email"), email_to, cooldown_hours (default 24 — how long
    to stay quiet after an alert while the condition remains true).
    """
    from skills.web import exec_web_search

    args = task.get("args") or {}
    watch = args["watch"]
    condition = args["condition"]

    evidence = exec_web_search(watch)

    verdict = _ollama_json(
        system=(
            "You judge whether a monitoring condition is met based on web search "
            "results. Be strict: only report met=true when the evidence clearly "
            "shows it. Respond ONLY with JSON: "
            '{"met": true|false, "summary": "<one sentence of the key evidence>"}'
        ),
        prompt=(
            f"Watched topic: {watch}\n"
            f"Condition to detect: {condition}\n\n"
            f"Search results:\n{evidence[:6000]}"
        ),
        model=str(args.get("model", "qwen3:14b")),
    )

    met = bool(verdict.get("met"))
    summary = str(verdict.get("summary", ""))[:500]

    state = task.setdefault("state", {})
    state["last_checked"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["last_met"] = met
    state["last_summary"] = summary

    if not met:
        return f"condition not met — {summary or 'no evidence'}"

    cooldown_s = float(args.get("cooldown_hours", 24)) * 3600
    last_alert = float(state.get("last_alert_ts", 0))
    if time.time() - last_alert < cooldown_s:
        return f"condition met, within cooldown — {summary}"

    _notify(
        args,
        f"🔔 Monitor triggered: {task.get('id')}",
        f"Condition: {condition}\n{summary}",
    )
    state["last_alert_ts"] = time.time()
    return f"ALERT sent — {summary}"


def run_task(task: dict[str, Any]) -> str:
    action = task.get("action")

    if action == "update_aaak_context":
        return run_update_aaak_context(task)

    if action == "flight_monitor":
        return run_flight_monitor(task)

    if action == "condition_monitor":
        return run_condition_monitor(task)

    raise ValueError(f"Unknown task action: {action}")


def main() -> None:
    print("[TASK_LOOP] started")
    print(f"[TASK_LOOP] vault={vault_root()}")
    print(f"[TASK_LOOP] tasks={tasks_path()}")

    while True:
        tasks = load_tasks()
        ts = now_ts()
        changed = False

        for task in tasks:
            task_id = str(task.get("id", "unknown"))

            if not should_run(task, ts):
                continue

            print(f"[TASK_LOOP] running {task_id}")

            try:
                message = run_task(task)
                task["last_run"] = now_ts()
                task["last_status"] = "ok"
                task["last_message"] = message
                changed = True

                log_result(task_id, "ok", message)
                print(f"[TASK_LOOP] ok {task_id}: {message}")

            except Exception as e:
                err = str(e)
                task["last_run"] = now_ts()
                task["last_status"] = "error"
                task["last_message"] = err
                changed = True

                log_result(
                    task_id,
                    "error",
                    err,
                    {"traceback": traceback.format_exc()},
                )
                print(f"[TASK_LOOP] error {task_id}: {err}")

        if changed:
            merge_run_state(tasks)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()