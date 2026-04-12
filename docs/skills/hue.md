# Philips Hue Skill

Control Philips Hue lights, rooms, and scenes.

**File:** `skills/hue.py`
**Config:** `config/hue.json`

---

## Setup

1. Run `hue discover` to find the bridge
2. Press the bridge button
3. Run `hue pair` within 30 seconds

---

## Tools

### hue

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | Command |
| `target` | string | no | Light/room/scene name |
| `value` | string | no | Brightness (0-100) or color |

**Actions:** `discover`, `pair`, `lights`, `rooms`, `on`, `off`, `brightness`, `dim`, `color`, `scene`, `scenes`, `status`

**Colors:** red, orange, yellow, green, cyan, blue, purple, pink, white, warm, cool, daylight, candle

**Examples:**
```
"Turn on the lights"
"Dim the living room to 30%"
"Set bedroom lights to warm"
"Activate movie scene"
```
