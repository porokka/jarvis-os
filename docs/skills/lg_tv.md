# LG TV Skill

Controls the LG OLED65E6V via WebOS WebSocket API.

**File:** `skills/lg_tv.py`
**Library:** `aiowebostv`
**Device:** LG OLED65E6V at 192.168.0.130

---

## Prerequisites

- LG webOS TV on the same LAN
- `pip install aiowebostv`
- First run requires pairing — accept the prompt on the TV screen

---

## Tools

### lg_tv

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | Command to execute |
| `value` | string | no | Value for the action |

**Actions:**

| Action | Description |
|--------|-------------|
| `power_off` | Turn off the TV |
| `volume_up` / `volume_down` | Adjust volume |
| `volume_set` | Set volume (value: 0-100) |
| `mute` / `unmute` | Toggle mute |
| `play` / `pause` / `stop` | Media control |
| `channel_up` / `channel_down` | Change channel |
| `input` | Switch input (value: HDMI1, HDMI2, etc.) |
| `app` | Launch app (value: Netflix, YouTube, etc.) |
| `info` | Show TV info — model, volume, current app |
| `screen_off` / `screen_on` | Turn screen off/on (TV stays running) |
| `notification` | Show notification on TV (value: message text) |

**Examples:**
```
"Turn off the TV"
"TV volume to 20"
"Switch TV to HDMI 1"
"Open Netflix on TV"
"TV info"
```

---

## Pairing

First time the skill connects, the TV shows a pairing prompt. Accept it. The client key saves to `config/lg_tv_key.json` — subsequent connections are automatic.
