# Internet Radio Skill

Streams internet radio stations via mpv. Finnish stations (Nova, SuomiPop, Rock, YLE) plus custom stream URLs. Falls back to browser if mpv stream expires.

**File:** `skills/radio.py`

---

## Prerequisites

- **mpv** installed at `C:\Program Files\MPV Player\mpv.exe` (Windows)
- For Linux: `mpv` in PATH

### Install mpv (Windows)

```powershell
winget install mpv
```

Or download from https://mpv.io/installation/

---

## Tools

### play_radio

Play a radio station or stop current playback.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `station` | string | yes | Station name, stream URL, or `stop` |

**Built-in stations:**

| Station | Description | Type |
|---------|-------------|------|
| `nova` | Radio Nova (Finland) | Bauer Media (session tokens) |
| `suomipop` | Radio Suomipop | Supla stream |
| `rock` | Radio Rock | Supla stream |
| `yle1` | YLE Radio 1 | HLS stream |
| `ylex` | YLE X | HLS stream |
| `lofi` | Lo-Fi Radio | Direct stream |
| `chillhop` | Chillhop Radio | Zeno.fm stream |

**Examples:**
```
"Play Nova radio"
"Put on some lofi"
"Play YLE Radio 1"
"Stop the radio"
"Play https://stream.example.com/live.mp3"
```

---

## How It Works

1. Kills any existing mpv process
2. Resolves station name → stream URL
3. For Bauer stations (Nova): generates fresh session tokens
4. Starts mpv in audio-only mode (`--no-video --really-quiet`)
5. Waits 3 seconds, checks if mpv is still running
6. If mpv died (expired stream), opens browser fallback URL

---

## Adding a New Station

Edit `STATIONS` dict in `skills/radio.py`:

```python
STATIONS = {
    ...
    "mystation": {
        "type": "url",
        "url": "https://stream.mystation.com/live.mp3",
        "fallback": "https://mystation.com/listen"  # optional browser fallback
    },
}
```

For Bauer Media stations (require session tokens):

```python
"nova_se": {
    "type": "bauer",
    "id": "se_radionova",
    "fallback": "https://rayo.fi/radio-nova"
},
```

---

## Troubleshooting

**mpv not found:** Update `MPV_PATH` in `skills/radio.py` to match your install location.

**Stream expired:** Bauer stations rotate stream tokens. The skill generates fresh ones on each play, but the token URL format may change. Browser fallback kicks in automatically.

**No audio:** Check that mpv works manually:
```bash
mpv --no-video "https://yleradiolive.akamaized.net/hls/live/2027671/in-YleRadio1/master.m3u8"
```
