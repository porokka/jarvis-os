# Monitor Skill

Background monitors — recurring watches executed by `scripts/task_loop.py`
(jarvis-task-loop.service) that alert via **Telegram or email** when a
condition is met.

**Files:** `skills/monitor_skill.py` (create/list/remove),
`scripts/task_loop.py` (execution), `skills/duffel_flights.py` (flight data)

---

## How It Works

```
"alert me when X happens"
    → monitor_condition / monitor_flights tool
    → writes task to Jarvis_vault/.jarvis/tasks/tasks.json
    → task_loop picks it up on its interval
        ├── flight_monitor    → Duffel cheapest fare vs max_price
        └── condition_monitor → web search → LLM judges condition (JSON verdict)
    → condition met → Telegram message or email
```

## Tools

| Tool | What |
|------|------|
| `monitor_flights` | Watch a route's cheapest fare; alert under `max_price`. Re-alerts only on new lows. |
| `monitor_condition` | Universal: web-search `watch` every interval, LLM checks `condition`, alert on match. `cooldown_hours` (default 24) prevents repeat alerts while the condition stays true. |
| `monitor_list` | Show all monitors + last status |
| `monitor_remove` | Remove by id or unique fragment |

## Examples

```
"watch flights HEL to BKK on 2026-10-05, alert under 500 euros"
"alert me when Oasis Helsinki tickets go on sale"
"monitor if the EU AI Act implementing acts are published, email me at x@y.z"
"list monitors"
"remove monitor oasis"
```

## Notify targets

- Telegram (default): `notify_chat_id`, defaults to owner chat (`JARVIS_TELEGRAM_CHAT_ID`)
- Email: `notify: "email"` + `email_to` — uses the email skill's SMTP config

## Duffel setup (flight monitors + `flight_search`)

Amadeus Self-Service was decommissioned 2026-07-17 (enterprise/IATA-accredited
only now). Duffel replaced it — self-serve signup at dashboard.duffel.com, no
accreditation needed. In `.env`:

```
DUFFEL_ACCESS_TOKEN=duffel_test_...     # switch to duffel_live_... when ready
```

Search cost: free up to a 1,500-searches-per-confirmed-order ratio; since
JARVIS never books, real cost is ~$0.005/search — a route checked every 6h
runs under $1/month.

IATA codes and YYYY-MM-DD dates (Helsinki=HEL, Bangkok=BKK, Tallinn=TLL).
Note: Duffel returns price in its own settlement currency per offer (not a
request parameter) — `max_price`/`currency` on a monitor are only accurate
if they match that currency; mismatches will under/over-trigger alerts.

## Task format (tasks.json)

```json
{
  "id": "cond_oasis_tickets",
  "type": "monitor",
  "enabled": true,
  "interval_seconds": 43200,
  "action": "condition_monitor",
  "args": {
    "watch": "Oasis Helsinki concert tickets",
    "condition": "tickets go on sale",
    "notify": "telegram",
    "cooldown_hours": 24,
    "notify_chat_id": "6987301428"
  },
  "state": {}
}
```

`task_loop` saves run-state with a merge (`merge_run_state`) so monitors
added while a tick executes are not lost.
