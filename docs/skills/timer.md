# Timer Skill

Countdown timers with voice alerts. When a timer fires, JARVIS speaks the message via Windows Speech Synthesis and updates the bridge state.

**File:** `skills/timer.py`

---

## Prerequisites

- Windows with PowerShell and `System.Speech` (built-in on Windows 10/11)
- Bridge directory at `/tmp/jarvis` (created by watcher.sh)

---

## Tools

### set_timer

Set a countdown timer with a custom alert message.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `minutes` | number | yes | Time in minutes (0.5 = 30 seconds, 60 = 1 hour) |
| `message` | string | yes | What JARVIS says when the timer fires |

**Examples:**
```
"Set a timer for 10 minutes — pasta is ready"
"Remind me in 30 seconds to check the build"
"Set a 1 hour timer for the meeting"
"Timer 5 minutes — take a break"
```

---

## API

Active timers are available via:

```
GET http://localhost:7900/api/timers
```

Response:
```json
{
  "timers": [
    {
      "id": 1,
      "message": "Pasta is ready",
      "remaining": 342,
      "total": 600
    }
  ]
}
```

The HUD's timers widget polls this endpoint to show countdown progress.

---

## How It Works

1. Creates a Python `threading.Timer` with the specified delay
2. When fired, writes alert to `bridge/output.txt` and sets state to `speaking`
3. Triggers Windows TTS via PowerShell SAPI
4. Logs the alert to `jarvis.log`
5. Resets bridge state to `standby` after 5 seconds
