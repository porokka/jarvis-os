# JARVIS OS — Full System Architecture

## Overview
A personal AI operating system built on:
- Obsidian vault as shared brain/memory
- Claude Code agent teams as specialist workers  
- Ollama (Qwen3-Coder + Mistral-Nemo) on dual GPU
- Next.js web UI as mission control
- Unreal Engine MetaHuman as avatar
- File bridge as nervous system

---

## Hardware Assignment

```
RTX 3090 (24GB)          RTX 2080 (8GB)
─────────────────        ──────────────────
Qwen3-Coder:30b          Mistral-Nemo (always on)
Unreal Engine            Whisper (voice transcription)
Audio2Face lipsync
```

```bash
# Pin models to GPUs via Ollama
CUDA_VISIBLE_DEVICES=0 ollama serve   # 3090 — Qwen3-Coder
CUDA_VISIBLE_DEVICES=1 ollama serve   # 2080 — Mistral-Nemo
```

---

## Obsidian Vault Structure

```
~/jarvis-vault/
│
├── .claude/                        ← Claude Code reads this
│   └── CLAUDE.md                   ← global agent instructions
│
├── jarvis/                         ← JARVIS file bridge
│   ├── input.txt                   ← voice commands in
│   ├── output.txt                  ← responses out
│   ├── state.txt                   ← standby/thinking/speaking
│   ├── brain.txt                   ← which model responded
│   └── history.md                  ← conversation log
│
├── context/                        ← shared knowledge base
│   ├── SAMI.md                     ← who you are
│   ├── STACK.md                    ← tech stack reference
│   ├── DECISIONS.md                ← architecture decisions
│   └── TODOS.md                    ← cross-project tasks
│
├── agents/                         ← agent definitions
│   ├── JARVIS.md                   ← orchestrator personality
│   ├── BULLISHBEAT.md              ← trading agent
│   ├── CASKRA.md                   ← brewery SaaS agent
│   ├── DRAVN.md                    ← API platform agent
│   ├── PAINTBALL.md                ← GPS game agent
│   ├── VARHA.md                    ← data engineering agent
│   └── RESEARCHER.md               ← web research agent
│
├── projects/
│   ├── bullishbeat/
│   │   ├── STATUS.md               ← current state
│   │   ├── TASKS.md                ← agent task queue
│   │   └── RESULTS.md              ← agent outputs
│   ├── caskra/
│   ├── dravn/
│   ├── gps-paintball/
│   └── varha/
│
├── memory/
│   ├── conversations.md            ← JARVIS chat history
│   ├── decisions.md                ← what was decided and why
│   └── learnings.md               ← things JARVIS has learned
│
└── ui/                             ← Next.js reads these
    ├── dashboard.json              ← project statuses
    ├── agents.json                 ← active agent states
    └── notifications.json         ← alerts from agents
```

---

## Agent Roster

### JARVIS (Orchestrator)
- Runs as Claude Code lead agent
- Reads voice input → decides which agent to route to
- Writes back to output.txt for Unreal/TTS
- Updates memory/conversations.md

### BullishBeat Agent
- Watches projects/bullishbeat/TASKS.md
- Has context: trading logic, Railway deployment, Polygon API
- Can read backtest results, suggest fixes, write code
- Specialist model: Claude Code (reasoning heavy)

### Caskra Agent  
- Watches projects/caskra/TASKS.md
- Knows: Nile.tech DB, RuuviTag sensors, brewery workflows
- Handles brewing calculations, batch tracking
- Specialist model: Qwen3-Coder (code tasks)

### DRAVN Agent
- Watches projects/dravn/TASKS.md
- Knows: Kafka, Redis, 28+ connectors, pipeline builder
- Handles connector development, API work
- Specialist model: Qwen3-Coder

### Varha Agent
- Watches projects/varha/TASKS.md
- Knows: PySpark, Cloudera CDP, Kerberos, Impala
- Handles ETL script generation and fixes
- Specialist model: Claude Code

### GPS Paintball Agent
- Watches projects/gps-paintball/TASKS.md
- Handles game design docs, architecture, prototyping
- Specialist model: Mistral-Nemo + Claude Code

### Researcher Agent
- Web search + summarization
- Writes findings to projects/*/RESULTS.md
- Always Mistral-Nemo (fast, lightweight)

---

## Agent Routing Logic

```
Voice/Text command
        ↓
JARVIS reads command
        ↓
    ROUTER
    ├── "how is bullishbeat" → BullishBeat Agent
    ├── "kombucha batch" → Caskra Agent
    ├── "dravn connector" → DRAVN Agent
    ├── "spark pipeline" → Varha Agent
    ├── "paintball game" → GPS Paintball Agent
    ├── "research X" → Researcher Agent
    └── everything else → Mistral-Nemo (fast reply)
```

---

## Next.js Web UI — Pages

```
/                    Mission Control dashboard
/agents              Live agent status + activity
/projects            All projects overview
/jarvis              Chat with JARVIS (text)
/memory              Browse vault conversations
/settings            GPU assignment, model config
```

### Data flow (UI ↔ Vault)
```
Next.js polls vault/ui/*.json every 2s
Agent activity → writes to vault/ui/agents.json
User sends command → writes to vault/jarvis/input.txt
JARVIS response → Next.js reads vault/jarvis/output.txt
```

---

## Claude Code Agent Teams Setup

```bash
# Enable experimental agent teams
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true

# Launch JARVIS as lead
cd ~/jarvis-vault
claude --lead

# JARVIS then spawns teammates as needed:
# /spawn bullishbeat "Review today's backtest results"
# /spawn researcher "Find latest Qwen3 benchmarks"
```

### CLAUDE.md (root, all agents read this)
```markdown
You are part of JARVIS OS — a personal AI system for Sami.
Always read context/SAMI.md for background.
Always read context/STACK.md for tech references.
Write task results to your project's RESULTS.md.
Update STATUS.md when work is complete.
Keep responses concise — Sami is busy.
```

---

## Next.js Stack

```
Framework:   Next.js 14 (App Router)
Styling:     Tailwind CSS
Components:  shadcn/ui
Real-time:   polling vault files via fs (local) or WebSocket
State:       Zustand
Charts:      Recharts (BullishBeat metrics)
Deploy:      Local only (localhost:3000)
```

### Key API routes
```
GET  /api/status          → reads vault/ui/dashboard.json
GET  /api/agents          → reads vault/ui/agents.json  
POST /api/command         → writes to vault/jarvis/input.txt
GET  /api/response        → reads vault/jarvis/output.txt
GET  /api/memory          → reads vault/memory/conversations.md
```

---

## Startup Sequence

```bash
# 1. Start Ollama on both GPUs
CUDA_VISIBLE_DEVICES=1 ollama run mistral-nemo &
CUDA_VISIBLE_DEVICES=0 ollama run qwen3-coder:30b &

# 2. Start JARVIS watcher
~/jarvis/scripts/watcher.sh &

# 3. Start bridge server (for browser UI)
python3 ~/jarvis/scripts/server.py &

# 4. Start Next.js UI
cd ~/jarvis-ui && npm run dev &

# 5. Launch Unreal Engine with MetaHuman scene
# (runs jarvis_bridge.py automatically on load)

echo "JARVIS OS online."
```

Or wrap in a single `start-jarvis.sh` script.
