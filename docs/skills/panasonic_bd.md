# Panasonic Blu-ray Skill

Controls the Panasonic DP-UB9000 4K UHD Blu-ray player via UPnP/DLNA.

**File:** `skills/panasonic_bd.py`
**Protocol:** UPnP AVTransport + RenderingControl on port 60606
**Device:** Panasonic DP-UB9000/9004 at 192.168.0.209

---

## Prerequisites

- Panasonic UB9000 on the same LAN
- **Network Control** enabled on the player: Setup > Network > Network Service Settings > Network Control > On
- No additional libraries needed (uses standard HTTP/SOAP)

---

## Tools

### bluray

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | Command to execute |

**Actions:**

| Action | Description |
|--------|-------------|
| `status` | Current state — playing, paused, stopped, no disc |
| `play` | Play disc |
| `pause` | Pause playback |
| `stop` | Stop playback |
| `next` | Next chapter |
| `previous` | Previous chapter |
| `power_on` | Wake-on-LAN (MAC: B4:6C:47:62:1B:BF) |
| `volume` | Get current volume |
| `volume_50` | Set volume to 50 (0-100) |
| `mute` / `unmute` | Toggle mute |

**Examples:**
```
"Play the Blu-ray"
"Pause the disc"
"Blu-ray status"
"Next chapter"
"Wake up the Blu-ray"
```

---

## Protocol

Uses standard UPnP/DLNA SOAP commands:
- **AVTransport** (`/Server0/AVT_control`) — play, pause, stop, seek, chapter navigation
- **RenderingControl** (`/Server0/RCS_control`) — volume, mute
- **DIAL** (port 61118) — app launching (Netflix, etc.)
