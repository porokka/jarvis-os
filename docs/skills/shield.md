# NVIDIA Shield Skill

Controls NVIDIA Shield TVs per room via ADB. Launches apps, navigates, controls playback, and coordinates with the Denon skill for input switching + HDMI-CEC.

**File:** `skills/shield.py`

---

## Prerequisites

- NVIDIA Shield TV (any model) with **Network Debugging** enabled
- Shield on the same LAN as JARVIS
- `adb` installed (comes with Android SDK Platform Tools)
- For network scanning: `nmap` installed

### Enable Network Debugging on Shield

1. Settings → Device Preferences → About → **Build** (click 7 times to enable Developer Options)
2. Settings → Device Preferences → Developer Options → **Network debugging: ON**

---

## Setup

Room IPs are configured in `skills/shield.py`:

```python
ROOMS = {
    "livingroom": {"ip": "192.168.0.31", "name": "Living Room Shield Pro"},
    "office": {"ip": "", "name": "Office Shield"},
    "bedroom": {"ip": "", "name": "Bedroom Shield"},
}
```

To discover Shield IPs, say **"Scan the network for devices"** or run:
```bash
nmap -p 5555 --open 192.168.0.0/24
```

---

## Tools

### room_command

Control a room's Shield TV + Denon receiver.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `room` | string | yes | `livingroom`, `office`, or `bedroom` |
| `action` | string | yes | App name, navigation command, or special action |

**Streaming apps:**

| Action | App |
|--------|-----|
| `netflix` | Netflix |
| `youtube` | YouTube |
| `spotify` | Spotify |
| `plex` | Plex |
| `disney` / `disney+` | Disney+ |
| `hbo` / `max` | HBO Max |
| `prime` / `amazon` | Prime Video |
| `apple` / `appletv` | Apple TV+ |
| `twitch` | Twitch |
| `crunchyroll` | Crunchyroll |
| `kodi` | Kodi |
| `vlc` | VLC |

**Navigation:**

| Action | What it does |
|--------|-------------|
| `home` | Home screen |
| `back` | Go back |
| `play` / `pause` | Toggle playback |
| `stop` | Stop playback |
| `next` / `previous` | Next/previous track |
| `up` / `down` / `left` / `right` | D-pad navigation |
| `select` / `ok` | Confirm selection |
| `menu` | Open menu |
| `settings` | Android TV settings |

**Power / HDMI:**

| Action | What it does |
|--------|-------------|
| `sleep` | Put Shield to sleep |
| `wake` | Wake up Shield |
| `power` | Toggle power |
| `hdmi-cec-on` | Turn on TV via CEC |
| `tv-on` | Wake + CEC TV on |
| `volume-up` / `volume-down` | CEC volume (→ Denon) |
| `mute` | CEC mute |

**Special actions:**

| Action | What it does |
|--------|-------------|
| `activate` / `switch` / `tv` | Wake Shield + CEC + switch Denon to Shield input |
| `pc` / `computer` / `monitor` | Switch Denon to PC input |
| `headphones` / `speakers` / `night` / `quiet` / `both` | Denon audio presets |
| `spotify:QUERY` | Open Spotify and search for artist/song |
| `search:QUERY` | Search Netflix |

**Examples:**
```
"Play Netflix in the living room"
"Open Spotify and play Metallica"       → room_command(livingroom, spotify:Metallica)
"Pause the living room"
"Switch to PC"
"Activate the bedroom Shield"
"Put on headphones"
```

---

### scan_network

Scan the LAN for NVIDIA Shields and Cast-enabled devices.

No parameters. Scans `192.168.0.0/24` for ports 5555 (ADB), 8008, 8443 (Cast).

---

## Denon Integration

When launching an app, the Shield skill automatically:

1. Wakes the Shield (`KEYCODE_WAKEUP`)
2. Switches the Denon receiver to the Shield input
3. Launches the app

This requires the **denon** skill to be enabled. If it's disabled, the Shield still works but won't switch the receiver input.

---

## Adding a New App

Edit `SHIELD_APPS` in `skills/shield.py`:

```python
SHIELD_APPS = {
    ...
    "myapp": "am start -n com.example.myapp/.MainActivity",
}
```

To find an app's package name, run on the Shield:
```bash
adb -s 192.168.0.31:5555 shell pm list packages | grep myapp
```

## Adding a New Room

Edit `ROOMS` in `skills/shield.py`:

```python
ROOMS = {
    ...
    "kitchen": {"ip": "192.168.0.50", "name": "Kitchen Shield"},
}
```
