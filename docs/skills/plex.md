# Plex Skill

Controls Plex Media Server — browse libraries, search, view sessions, control playback.

**File:** `skills/plex.py`
**Config:** `config/plex.json`

---

## Setup

1. Get your Plex token: https://support.plex.tv/articles/204059436
2. Copy the example config:
   ```bash
   cp config/plex.json.example config/plex.json
   ```
3. Edit with your server IP and token:
   ```json
   {"ip": "192.168.1.100", "port": 32400, "token": "YOUR_PLEX_TOKEN"}
   ```

---

## Tools

### plex

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | Command to execute |
| `query` | string | no | Search query (for search action) |

**Actions:**

| Action | Description |
|--------|-------------|
| `status` | Server info — name, version, active streams |
| `libraries` | List all libraries (Movies, TV Shows, Music) |
| `search` | Search for media (query required) |
| `recent` | Recently added media |
| `ondeck` | Continue watching (On Deck) |
| `sessions` | What's currently playing and where |
| `pause` | Pause all active streams |
| `resume` | Resume paused streams |
| `stop` | Stop all active streams |

**Examples:**
```
"What's on Plex?"          → status
"Search Plex for Inception" → search Inception
"What was recently added?"  → recent
"What's playing on Plex?"   → sessions
"Pause Plex"                → pause
```
