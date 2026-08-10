# Monitor Skill

Background monitors — recurring watches executed by `scripts/task_loop.py`
(jarvis-task-loop.service) that alert via **Telegram or email** when a
condition is met.

**Files:** `skills/monitor_skill.py` (create/list/remove),
`scripts/task_loop.py` (execution), `skills/amadeus_flights.py` (flight data)

---

## How It Works

```
"alert me when X happens"
    → monitor_condition / monitor_flights tool
    → writes task to Jarvis_vault/.jarvis/tasks/tasks.json
    → task_loop picks it up on its interval
        ├── flight_monitor    → Amadeus cheapest fare vs max_price
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

## Amadeus setup (flight monitors + `flight_search`)

Register free at developers.amadeus.com, then in `.env`:

```
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
AMADEUS_ENV=test        # test = free tier; prod for live data
```

IATA codes and YYYY-MM-DD dates (Helsinki=HEL, Bangkok=BKK, Tallinn=TLL).

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
