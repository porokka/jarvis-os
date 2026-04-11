# Denon AVR Skill

Controls the Denon AVR-X4100W receiver — input switching, volume, presets, surround modes, power, and zones.

**File:** `skills/denon.py`
**Config:** `config/denon.json`

---

## Prerequisites

- Denon AVR with network HTTP control (AVR-X series)
- Receiver on the same LAN as JARVIS
- IP address configured in `config/denon.json`

---

## Setup

The skill auto-loads config from `config/denon.json` on startup. Edit the IP if your receiver is at a different address:

```json
{
  "name": "Denon AVR-X4100W",
  "ip": "192.168.0.188",
  ...
}
```

To find your Denon's IP: check your router's DHCP list, or use `nmap -p 80 192.168.0.0/24`.

---

## Tools

### denon_input

Switch the receiver's active input source.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input_name` | string | yes | Input name or alias |

**Available inputs and aliases:**

| Input | Aliases |
|-------|---------|
| Game | `pc`, `computer`, `monitor`, `game`, `gaming` |
| Media Player | `shield`, `mediaplayer`, `multimedia`, `streaming` |
| Phono | `vinyl`, `turntable`, `record`, `records`, `phono` |
| TV Audio | `tv`, `tv audio`, `arc` |
| Bluetooth | `bluetooth`, `bt`, `phone` |
| Network | `network`, `airplay`, `spotify connect`, `stream` |
| Tuner | `tuner`, `fm`, `am`, `radio tuner` |
| USB | `usb` |
| DVD | `dvd` |
| Blu-ray | `bluray` |
| CBL/SAT | `cbl/sat` |
| AUX1 | `aux1` |
| AUX2 | `aux2` |

**Examples:**
```
"Switch Denon to PC"
"Switch input to vinyl"
"Put on Bluetooth"
```

---

### denon_volume

Control receiver volume.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `level` | string | yes | `up`, `down`, `mute`, `unmute`, or number 0-98 |

**Examples:**
```
"Turn up the Denon"
"Denon volume to 45"
"Mute the receiver"
```

---

### denon_preset

Execute audio output presets.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `preset` | string | yes | Preset name |

**Available presets:**

| Preset | What it does |
|--------|-------------|
| `headphones` | Mute speakers, enable zone 2 (wireless headset) |
| `speakers` | Unmute speakers, disable zone 2 |
| `both` | Both speakers and headset active |
| `quiet` | Mute everything |
| `night` | Headset only, speakers muted (late night) |

**Examples:**
```
"Switch to headphones"
"Put on speakers mode"
"Night mode"
```

---

### denon_surround

Set surround sound processing mode.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `mode` | string | yes | Surround mode name |

**Available modes:** `auto`, `stereo`, `dolby`, `dts`, `movie`, `music`, `game`, `direct`, `pure_direct`

**Examples:**
```
"Set surround to stereo"
"Switch to movie mode"
"Pure direct mode"
```

---

### denon_power

Control receiver power state.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | `on`, `off`, or `status` |

---

## Config Reference

The full `config/denon.json` supports:

- **inputs** — Name, command, device alias, aliases list
- **volume** — Min/max/step, up/down/mute commands
- **power** — On/off/status commands
- **zones** — Zone 1 (speakers) and Zone 2 (headset) with independent power/volume/mute
- **presets** — Named command sequences
- **surround** — Mode name → command mapping
- **eco** — Eco mode on/off/auto

### Adding a new input

Edit `config/denon.json`:

```json
"inputs": {
  "My Device": {
    "command": "SIAUX1",
    "description": "My custom device on AUX1",
    "device": "mydevice",
    "aliases": ["mydevice", "my thing"]
  }
}
```

### Adding a new preset

```json
"presets": {
  "movie_night": {
    "description": "Shield + surround + dim volume",
    "commands": ["SIMPLAY", "MSMOVIE", "MV40"]
  }
}
```

---

## Protocol Reference

The Denon HTTP API uses:
```
GET http://{ip}/goform/formiPhoneAppDirect.xml?{COMMAND}
```

Common command prefixes:
- `SI` — Source Input select
- `MV` — Master Volume
- `MU` — Mute
- `PW` — Power
- `MS` — Main zone Surround mode
- `Z2` — Zone 2 control
- `EC` — Eco mode
