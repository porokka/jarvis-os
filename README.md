# J.A.R.V.I.S OS

**Just A Rather Very Intelligent System** — A fully local AI assistant inspired by the MCU JARVIS.

Built by Sami Porokka / Poro-IT OÜ

## What It Does

- **Multi-model AI** — Routes queries to the best local model (fast/reason/code/deep)
- **ReAct Agent Loop** — Think → Tool → Observe → Repeat until task complete
- **15 Tools** — Web search, memory, vault files, radio, timers, volume, network scan, room control, skills
- **Voice I/O** — Wake word "Hey JARVIS", Whisper STT, TTS with center-channel 5.1 output
- **Persistent Memory** — MemPalace (2000+ memories) + Obsidian vault
- **Stark Industries HUD** — Next.js dashboard with holographic UI, GPU monitor, live system log
- **Home Control** — NVIDIA Shield rooms (livingroom/office/bedroom), radio streaming, volume
- **34 Skills** — Frontend design, SEO, Playwright, React, and more loaded on demand

## Architecture

```
Voice / Browser / Text
        │
   ┌────▼────┐
   │ Watcher  │──── input.txt ──── server.py (:4000)
   └────┬────┘                     Browser UI
        │
   ┌────▼────────┐
   │ Router       │ Keywords → fast/reason/code/deep/claude
   └────┬────────┘
        │
   ┌────▼────────────┐
   │ ReAct Server     │ (:7900) — Tool-augmented Ollama proxy
   │  ├ Planner (8b)  │ Picks which tools are needed
   │  ├ Tools (15)    │ Execute tools, feed results back
   │  └ Loop (max 5)  │ Repeat until final answer
   └────┬────────────┘
        │
   ┌────▼────┐    ┌──────────┐
   │ Ollama   │    │ Claude   │
   │ :11434   │    │ --print  │
   └─────────┘    └──────────┘
```

## Models

| Slot | Model | Size | Tools | Use Case |
|------|-------|------|-------|----------|
| Fast | qwen3:8b | 5 GB | Via ReAct | Casual chat, quick answers |
| Reason | qwen3:30b-a3b | 18 GB | Yes | Analysis, research, tool use |
| Code | qwen3-coder:30b | 18 GB | Yes | Code tasks, debugging |
| Deep | qwen3:30b-a3b | 18 GB | Yes | Strategy, deep analysis |
| Cloud | Claude Code | API | Full | Complex code tasks |

## Tools

| Tool | Description |
|------|-------------|
| `memory_search` | Search MemPalace long-term memory |
| `memory_add` | Save new memories (Obsidian + MemPalace) |
| `memory_status` | Show memory stats |
| `read_vault_file` | Read Obsidian vault files |
| `list_vault_dir` | List vault directories |
| `web_search` | DuckDuckGo web search |
| `read_file` | Read source code files |
| `shell_command` | Run shell commands (safety filtered) |
| `play_radio` | Stream radio (Nova, SuomiPop, Rock, YLE, lofi) |
| `open_url` | Open URLs in browser |
| `set_volume` | Control system volume |
| `set_timer` | Set countdown timers/alarms |
| `scan_network` | Discover network devices |
| `room_command` | Control NVIDIA Shield per room |
| `list_skills` / `use_skill` | Load 34 Claude skills on demand |

## Prerequisites

- **NVIDIA GPU** with CUDA (tested on RTX 3090 24GB)
- **Node.js 20+**
- **Python 3.12+**
- **Ollama**

## Installation

### Option A: Windows 11 + WSL2 (Recommended)

```powershell
# Clone
git clone https://github.com/your-repo/jarvis-os.git
cd jarvis-os

# Run the Windows installer (PowerShell as Admin)
.\install-windows.ps1
```

This will:
1. Install mpv, ffmpeg via winget
2. Set up WSL with all Python/Ollama deps
3. Pull AI models
4. Install Next.js app
5. Set up MemPalace

**Manual steps after install:**
```powershell
# Start backend (WSL terminal)
wsl bash /mnt/e/coding/jarvis-os/jarvis.sh start

# Start HUD (PowerShell)
cd app
npm run dev
# Open http://localhost:3000
```

### Option B: Native Linux (Ubuntu 22.04+ / Debian 12+)

```bash
# Clone
git clone https://github.com/your-repo/jarvis-os.git
cd jarvis-os

# Run installer
bash install-linux.sh
```

This will:
1. Install all system packages (mpv, ffmpeg, nmap, adb)
2. Install NVIDIA drivers if missing
3. Install Python deps + Ollama + models
4. Set up Orpheus TTS, MemPalace, vault
5. Configure paths for native Linux
6. Add `jarvis` alias to .bashrc

**After install:**
```bash
jarvis start              # Start everything
cd app && npm run dev     # Start HUD
# Open http://localhost:3000
```

### Obsidian Vault

Both installers create/link a vault. Structure:
```
Jarvis_vault/
├── People/          # User profiles (sami.md, inga.md)
├── Projects/        # Project notes
├── References/      # Tools, services, voice translations
├── Daily/           # Daily logs + JARVIS memories
├── .claude/skills/  # 34 Claude skills
└── JARVIS.md        # Personality file
```

### TTS (Optional — Orpheus)

For high-quality local voice (requires ~3GB VRAM or CPU):
```bash
python3 tts/setup.py     # Download Orpheus 3B model
python3 tts/server.py    # Start on :5100
```
Falls back to Windows Speech / espeak if unavailable.

## Usage

### Start Everything

```bash
# From WSL
bash /mnt/e/coding/jarvis-os/jarvis.sh start
```

This boots:
1. Ollama + models
2. ReAct tool server (:7900)
3. Watcher (file bridge)
4. Browser bridge server (:4000)
5. Voice capture (if deps installed)

### Start Next.js HUD (Windows)

```powershell
cd E:\coding\jarvis-os\app
npm run dev
# Open http://localhost:3000
```

### Stop Everything

```bash
bash /mnt/e/coding/jarvis-os/jarvis.sh stop
```

### Check Status

```bash
bash /mnt/e/coding/jarvis-os/jarvis.sh status
```

### Voice

```bash
# Always-on mode
python3 scripts/voice_capture.py

# Wake word mode (say "Hey JARVIS")
python3 scripts/voice_capture.py --wake
```

## Interfaces

| Interface | URL | Description |
|-----------|-----|-------------|
| **Stark HUD** | http://localhost:3000 | Next.js holographic dashboard |
| **Browser UI** | http://localhost:4000 | Simple browser voice UI |
| **ReAct API** | http://localhost:7900 | Tool-augmented Ollama proxy |
| **Orpheus TTS** | http://localhost:5100 | Local TTS server (optional) |

## File Structure

```
jarvis-os/
├── jarvis.sh              # Start/stop/restart/status
├── JARVIS.md              # Personality file
├── scripts/
│   ├── watcher.sh         # Main nervous system (routes, TTS, wake word)
│   ├── react_server.py    # ReAct tool loop + planner
│   ├── server.py          # Browser bridge HTTP server
│   ├── voice_capture.py   # Whisper STT with wake word
│   ├── mic_test.py        # Mic level calibration
│   └── jarvis_browser.html # Simple browser UI
├── app/                   # Next.js Stark Industries HUD
│   ├── app/
│   │   ├── page.tsx       # Main HUD dashboard
│   │   ├── components/
│   │   │   ├── face/      # 3D lattice face (Three.js)
│   │   │   ├── gpu-monitor.tsx
│   │   │   ├── system-log.tsx
│   │   │   ├── hud-panel.tsx
│   │   │   └── input-bar.tsx
│   │   └── api/           # Next.js API routes
│   └── lib/
│       ├── bridge.ts      # Claude/Ollama bridge
│       └── tts.ts         # TTS client
├── tts/                   # Orpheus TTS server
│   ├── server.py
│   ├── engine.py
│   └── setup.py
└── unreal/                # UE5 MetaHuman bridge (planned)
```

## Personality Modes

Switch via browser settings or vault config:

| Mode | Character | Address |
|------|-----------|---------|
| J.A.R.V.I.S | British butler, dry wit | "sir" |
| F.R.I.D.A.Y | Casual, friendly | First name |
| E.D.I.T.H | Direct, tactical | "boss" |
| HAL 9000 | Calm, unsettling | "Dave" |

## Room Control (NVIDIA Shield)

Requires ADB Network Debugging enabled on each Shield.

```
"Play Netflix in the living room"
"Pause the bedroom TV"
"Open YouTube in the office"
```

## .gitignore

Add these to `.gitignore`:
```
node_modules/
.next/
__pycache__/
*.pyc
tts/models/
.env
.env.local
bridge/
*.log
*.wav
```

## License

Private project — Poro-IT OÜ
