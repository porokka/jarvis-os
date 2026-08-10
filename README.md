# J.A.R.V.I.S OS

**Just A Rather Very Intelligent System** — A fully local AI assistant with modular skill architecture, agentic plan execution, and a holographic HUD.

Built by [Sami Porokka](https://poro-it.com) / Poro-IT OÜ

---

## Features

- **4-Pass Memory Router** — Ambiguity, memory, tool selection, and route classification in one fast Gemma4 pass
- **Agentic Plan System** — `build X` → structured 8-10 step plan → human approval → plan_runner executes → staging pipeline
- **Self-Healing Plan Runner** — 4 parallel workers, crash auto-recovery (orphaned tasks re-queued at boot), dep-timeout re-queue, retry backoff, and an LLM failure-diagnosis loop (CAUSE/FIX logged to the vault + one diagnosis-guided retry)
- **Plan Rerun & Versioning** — `POST /rerun/{plan_id}` clones any plan under a versioned ID (`PLAN-X-001` → `-2` → `-3`)
- **systemd Services** — 17 units + installer; everything auto-starts at WSL boot via linger (`systemctl --user start jarvis.target`)
- **Claude API Mode** — `claude_proxy.py` emulates Ollama + llama.cpp APIs over the Claude API; the whole stack runs cloud-only with zero code changes (optional Voyage AI embeddings)
- **Backend Fallback Chain** — llama.cpp down → automatic Ollama fallback (with a minimum-model guard) → or the Claude proxy if that's what is on :11434
- **Multi-Message Telegram** — any skill or model reply containing a `---next---` line is auto-split into separate Telegram messages; long replies chunk instead of truncating
- **Staging Pipeline** — `staging/dev/` → Playwright/Podman testing → `staging/tested/` → human approval → `staging/approved/`
- **Codex UI** — In-browser coding workspace with plan picker, step status, file browser, PTY terminal, and approve button
- **ReAct Agent Loop** — Think → Tool → Observe → Repeat until task complete (max 8 iterations)
- **Modular Skills** — 35+ plug-and-play skill modules, enable/disable via config, drop a file in and restart
- **Multi-Model Routing** — Fast (8b) / Reason (30b) / Code (qwen3.6:27b) / Deep / Cloud per request
- **Voice I/O** — Wake word "Hey JARVIS", Whisper STT, Kokoro/Orpheus TTS with 5.1 center-channel output
- **Persistent Memory** — MemPalace vector DB + Obsidian vault (2000+ memories), working memory in Redis
- **Stark Industries HUD** — Next.js holographic dashboard with GPU monitor, lattice face, live system log
- **Home Automation** — Denon AVR, NVIDIA Shield, LG TV, Panasonic Blu-ray, Philips Hue, internet radio
- **n8n Integration** — Bidirectional: Jarvis triggers n8n workflows, n8n pushes tasks/events back to Jarvis
- **Cloud LLMs** — Claude, GPT-4, Gemini, Groq, Mistral, OpenRouter via unified skill
- **AI Image Gen** — FLUX text-to-image with Qwen3 prompt enhancement + VRAM auto-swap
- **Phone / SMS / Email** — Twilio calls + SMS, SMTP/IMAP email
- **Telegram Gateway** — Mobile control, plan approvals, and Telegram-triggered tasks
- **Companion App** — [JARVIS Mobile](https://github.com/porokka/jarvis-mobile) — React Native (Expo) mobile client with on-device Gemma routing and Telegram dispatch
- **Unreal Engine 5.8 MCP** — Native MCP plugin connects Claude Code directly to the UE editor: spawn actors, drive MetaHuman expressions, control lighting, trigger animations — replaces the file bridge with live tool calls
- **Android Testing** — Build and test React Native / Expo apps on an Android emulator via Gradle + Playwright/Podman, wired into the plan system

---

## Architecture

```
User Input (Voice / HUD / Telegram / API)
          │
    ┌─────▼──────────┐
    │ Memory Router   │  4-pass Gemma4:4b classifier
    │  Pass 1: Ambi   │  → is this ambiguous / follow-up?
    │  Pass 2: Memory │  → fetch relevant memory context
    │  Pass 3: Tool   │  → which skill/tool is needed?
    │  Pass 4: Route  │  → fast / reason / code / tools / chat
    └─────┬──────────┘
          │
    ┌─────▼──────────────────────────┐
    │  react_server.py  :7900         │
    │  ├ handle_live_router            │  fast path (plan cmds bypass router)
    │  ├ handle_full_pipeline          │  full ReAct loop
    │  ├ build_simple_code_plan        │  qwen3:14b plan generator
    │  └ queue_plan_to_redis           │  push steps to jarvis:tasks
    └─────┬──────────────────────────┘
          │                    │
    ┌─────▼──────┐     ┌──────▼──────────────┐
    │   Ollama    │     │  plan_runner.py       │
    │   :11434    │     │  ├ exec_code_step     │  qwen3.6:27b → writes files
    │  qwen3 fam. │     │  ├ Playwright tests   │  simple sites
    └────────────┘     │  ├ Podman tests       │  complex projects
                       │  └ staging pipeline    │  dev → tested → approved
                       └──────────────────────┘
          │
    ┌─────▼──────────────────────────┐
    │  Stark HUD  :3000  (Next.js)   │
    │  ├ Lattice face (Three.js)      │  amplitude-driven mouth
    │  ├ Codex UI + plan picker       │  approve/reject staging
    │  ├ GPU monitor, system log      │
    │  └ Approval panel               │  SSE-streamed approval requests
    └────────────────────────────────┘
          │
    ┌─────▼──────────────────────────┐
    │  Unreal Engine 5.8  (MCP)      │
    │  ├ HTTP JSON-RPC :3000/mcp     │  built-in UE MCP plugin
    │  ├ TCP bridge :55557           │  custom MetaHuman tools
    │  ├ MetaHuman face control      │  emotion presets + morph targets
    │  ├ Actor / lighting / material │  scene manipulation
    │  └ Automation test runner      │  UE test framework
    └────────────────────────────────┘
```

---

## Unreal Engine 5.8 Integration

UE 5.8 ships a native **Model Context Protocol (MCP) plugin** that embeds an MCP server inside the editor process. Jarvis connects to it over local HTTP and drives the editor directly — no file polling, no bridge scripts.

```
Agent loop says: "set Jarvis emotion to thinking"
          │
    skills/unreal.py
          │
          ├── HTTP POST localhost:3000/mcp  (built-in UE plugin)
          │   spawn_actor, set_transform, lighting, materials, automation tests
          │
          └── TCP :55557  (custom C++ bridge for MetaHuman)
              set_morph_target("CTRL_expressions_browInnerUp_L", 0.6)
              set_morph_target("CTRL_expressions_eyeLookUp_L", 0.3)
```

### UE Side Setup

1. `Edit → Plugins` → search **Unreal MCP** → enable → restart editor
2. Console: `ModelContextProtocol.GenerateClientConfig` — note the port from Output Log
3. Optionally add to Claude Code directly: `claude mcp add unreal --transport http http://localhost:3000/mcp`

### What the Skill Can Do

| Category | Tools |
|----------|-------|
| **Actors** | `spawn_actor`, `set_transform`, `get_actors`, `delete_actor` |
| **Scene** | `set_lighting`, `set_material` |
| **MetaHuman** | `set_emotion` (6 presets), `set_morph` (individual CTRL targets), `set_amplitude` (TTS mouth sync) |
| **Animation** | `play_animation` — trigger named sequences on the MetaHuman |
| **Automation** | `run_test` — execute UE automation tests from the agent loop |
| **Raw** | `mcp_call`, `tcp_call` — pass-through for any UE tool |

### Emotion Presets

```python
"set Jarvis emotion to happy"     → mouthSmile + cheekSquint morphs
"set Jarvis emotion to thinking"  → browInnerUp + eyeLookUp morphs
"set Jarvis emotion to focused"   → browDown + eyeSquint morphs
"set Jarvis emotion to surprised" → browOuterUp + eyeWide morphs
```

TTS amplitude is piped directly: every audio frame the Kokoro TTS produces feeds `set_amplitude` so the MetaHuman mouth moves in real time with speech — same signal drives both the Three.js lattice face in the HUD and the UE MetaHuman.

**Full docs:** [docs/skills/unreal.md](docs/skills/unreal.md)

---

## Plan System

The plan system lets Jarvis execute multi-step coding projects autonomously with human gates.

```
User: "build a lottery website with 7x7 grid"
          │
   build_simple_code_plan()  ← qwen3:14b
          │
   PLAN-20260619-001 displayed (8-10 steps, filenames, tool tags)
          │
   User: "proceed"  ← bypasses memory_router entirely → code route
          │
   queue_plan_to_redis()  → jarvis:tasks Redis list
          │
   plan_runner.py consumes tasks:
     Step 1-6:  exec_code_step() → qwen3.6:27b → writes to staging/dev/
     Step 7-8:  _build_test_cmd() → Playwright (simple) or Podman (complex)
     Step 9:    exec_code_step() → adds features
     Step 10:   cp staging/dev/ → staging/tested/
          │
   Human approval (HUD or Telegram)
          │
   staging/tested/ → staging/approved/
```

### Staging Directories

| Path | Stage | Meaning |
|------|-------|---------|
| `staging/dev/PLAN-ID/` | Development | Files written by plan_runner |
| `staging/tested/PLAN-ID/` | Tested | Passed automated tests |
| `staging/approved/PLAN-ID/` | Approved | Human-reviewed, ready for deploy |

---

## Skills

JARVIS uses a modular skill system. Each skill is a self-contained Python module in `skills/` that registers its own tools, keywords, and executors.

| Skill | Key Tools | Description |
|-------|-----------|-------------|
| **coding** | `coding`, `code_edit` | Code generation via qwen3.6:27b — plans, diffs, file writes |
| **plan** | `plan_create`, `plan_proceed` | Agentic multi-step plan creation and execution |
| **n8n** | `n8n` | n8n workflow control — trigger webhooks, list executions, add tasks |
| **shell** | `shell_command`, `read_file` | Safe shell execution + file reading |
| **git** | `git` | Git — status, diff, commit, push, pull, branch |
| **web** | `web_search`, `open_url` | DuckDuckGo search + browser open |
| **news** | `get_news` | Live news headlines via RSS/newsapi |
| **weather** | `weather` | Current weather and forecasts |
| **memory** | `memory_search`, `memory_add` | MemPalace long-term vector memory |
| **memory_core** | `remember`, `recall` | Working memory in Redis |
| **vault** | `read_vault_file`, `list_vault_dir` | Obsidian vault file access |
| **notes** | `create_note`, `search_notes` | Quick note creation in vault |
| **mindmap** | `mindmap` | Generate mind maps from topics |
| **document_editor** | `edit_document` | Edit structured documents |
| **accounting** | `accounting` | Financial queries and calculations |
| **chat_log** | `chat_log` | Read/search conversation history |
| **dictate** | `dictate` | Continuous dictation mode |
| **cloud_llm** | `cloud_llm` | Claude, GPT-4, Gemini, Groq, Mistral |
| **flux** | `flux` | FLUX AI image generation |
| **model_skill** | `switch_model` | Switch active model at runtime |
| **project_ops** | `project_ops` | Project management operations |
| **podman** | `podman` | Podman container management |
| **app_scaff_skill** | `scaffold_app` | Scaffold new projects from templates |
| **email** | `email` | Send, read, search email via SMTP/IMAP |
| **phone** | `phone` | Twilio calls — make/receive, voicemail |
| **sms** | `sms` | Twilio SMS text messages |
| **denon** | `denon_input`, `denon_volume`, `denon_preset` | Denon AVR-X4100W receiver |
| **shield** | `room_command` | NVIDIA Shield per-room control |
| **lg_tv** | `lg_tv` | LG webOS TV — power, inputs, apps |
| **panasonic_bd** | `bluray` | Panasonic UB9000 4K Blu-ray |
| **hue** | `hue` | Philips Hue lighting — scenes, colors |
| **plex** | `plex` | Plex Media Server — browse, playback |
| **radio** | `play_radio` | Internet radio via mpv |
| **volume** | `set_volume` | Windows system volume |
| **timer** | `set_timer` | Countdown timers with voice alerts |
| **network** | `scan_network` | Network scan + topology map |
| **unreal** | `unreal` | Unreal Engine 5.8 MCP — spawn actors, MetaHuman emotions, lighting, animations |
| **android** | `android` | Android emulator — build Expo/Gradle, run tests, screenshot, deploy APK |
| **claude_skills** | `use_skill` | Load 34 Claude Code skills on demand |

**Full skill docs:** [docs/SKILLS.md](docs/SKILLS.md)

---

## Models

| Slot | Model | Size | Use Case |
|------|-------|------|----------|
| Router | gemma4:4b | 2.5 GB | Memory routing (llama.cpp :8081) |
| Fast | qwen3:14b | 5 GB | Casual chat, quick answers |
| Reason | qwen3:14b | 9 GB | Planning, analysis, tool use |
| Code | qwen3.6:27b | 18 GB | Code generation, file writing |
| Deep | qwen3.6:27b | 18 GB | Strategy, deep analysis |
| Cloud | Claude Sonnet | API | Complex code, multi-step tasks |

---

## Prerequisites

- **NVIDIA GPU** with CUDA (tested on RTX 3090 24GB)
- **Windows 11 + WSL2** (recommended) or Ubuntu 22.04+
- **Node.js 20+**
- **Python 3.12+**
- **Ollama** with models pulled
- **Redis** (for plan queue, working memory, task status)
- **Unreal Engine 5.8** *(optional)* — for MetaHuman face and 3D scene control via MCP
- **Android Studio + SDK** *(optional)* — for Android emulator testing (Pixel_6 AVD)

---

## Installation

### Windows 11 + WSL2 (Recommended)

```powershell
git clone https://github.com/porokka/jarvis-os.git
cd jarvis-os
.\install-windows.ps1
```

### Native Linux (Ubuntu 22.04+ / Debian 12+)

```bash
git clone https://github.com/porokka/jarvis-os.git
cd jarvis-os
bash install-linux.sh
```

### Post-Install

```bash
# Start all services
bash jarvis.sh start

# Start HUD (separate terminal)
cd app && npm run dev
# Open http://localhost:3000

# Optional: TTS server (Kokoro)
python3 tts/server.py   # :5100
```

### Unreal Engine 5.8 MCP (optional)

1. Open your UE 5.8 project
2. `Edit → Plugins` → search **Unreal MCP** → enable → restart editor
3. UE Output Log console: `ModelContextProtocol.GenerateClientConfig` — note the port
4. Add to `.env` in jarvis-os root:
   ```bash
   UE_MCP_URL=http://localhost:3000/mcp
   UE_TCP_PORT=55557
   ```
5. Restart jarvis — the `unreal` skill loads automatically

### Android Emulator (optional)

1. Install [Android Studio](https://developer.android.com/studio) + Android SDK
2. Create a **Pixel_6** AVD (API 33+) in the AVD Manager
3. Add to `.env`:
   ```bash
   ANDROID_HOME=C:/Users/yourname/AppData/Local/Android/Sdk
   JAVA_HOME=C:/Program Files/Microsoft/jdk-21
   ```
4. The `android` skill handles emulator start/stop automatically on build

---

## Usage

### Start / Stop / Status

**systemd (recommended — auto-starts at WSL boot):**

```bash
bash systemd/install.sh --start        # one-time install + enable + start
systemctl --user start jarvis.target   # start everything
systemctl --user stop jarvis.target    # stop everything (snapshots memory first)
systemctl --user status 'jarvis-*'     # health of all services
journalctl --user -u jarvis-react -f   # follow a service log
```

> **WSL note:** WSL2 shuts its VM down when the last `wsl.exe` client exits — services inside don't keep it alive. The installer docs cover a keep-alive (`wsl.exe -e sleep infinity` from the Windows Startup folder); without it Jarvis only lives while a WSL terminal is open.

**Classic script (still works):**

```bash
bash jarvis.sh start     # Boot everything (react_server, plan_runner, watcher)
bash jarvis.sh stop      # Shut down
bash jarvis.sh status    # Health check all services
bash jarvis.sh restart   # Restart all services
```

### Claude API Mode (no local models)

```bash
export ANTHROPIC_API_KEY=sk-ant-...             # or config/cloud_llm.json
sudo systemctl stop ollama                       # free :11434
systemctl --user stop jarvis-llama               # stop llama.cpp
systemctl --user enable --now jarvis-claude-proxy
```

The proxy speaks Ollama (`/api/chat`, `/api/tags`, `/api/embeddings`) and llama.cpp (`/v1/chat/completions`) formats and forwards to Anthropic. Model mapping: small/fast names → Haiku, everything else → Sonnet (`JARVIS_CLAUDE_MODEL` / `JARVIS_CLAUDE_FAST_MODEL`). Embeddings via Voyage AI when `VOYAGE_API_KEY` is set, otherwise semantic search degrades gracefully.

### Plan Rerun

```bash
curl -X POST http://127.0.0.1:8766/rerun/PLAN-20260629-001
# → clones as PLAN-20260629-001-2 and queues all tasks fresh
```

Failed tasks are auto-diagnosed (CAUSE/FIX via qwen3:14b), logged to `<vault>/.jarvis/plan_failures.md`, and retried once with the diagnosis injected into the coder prompt.

### Plan Commands

```
"build a todo app with local storage"   → creates plan → awaits approval
"proceed PLAN-20260619-001"             → queues to plan_runner
"cancel PLAN-20260619-001"             → cancels active plan
"modify plan — add dark mode"          → updates plan before execution
```

### Voice

```bash
python3 scripts/voice_capture.py          # Always-on mode
python3 scripts/voice_capture.py --wake   # Wake word mode ("Hey JARVIS")
```

---

## Interfaces

| Interface | URL | Description |
|-----------|-----|-------------|
| **Stark HUD** | http://localhost:3000 | Next.js holographic dashboard |
| **ReAct API** | http://localhost:7900 | Main agent server |
| **Plan API** | http://localhost:8766 | Plan status + `/rerun/{plan_id}` |
| **Kokoro TTS** | http://localhost:5100 | Local TTS (Kokoro/Orpheus) |
| **PTY Bridge** | ws://localhost:4010 | Terminal WebSocket |
| **llama.cpp** | http://localhost:8091 | Memory router model (gemma4) |
| **Claude Proxy** | http://localhost:11434 | Optional — Ollama-compatible Claude API backend |
| **UE MCP** | http://localhost:3000/mcp | Unreal Engine 5.8 built-in MCP server |
| **UE TCP Bridge** | localhost:55557 | Custom MetaHuman / Blueprint tools |

### API Endpoints

```
POST /api/chat              ReAct loop — main entry point
GET  /api/health            Health check + service status
GET  /api/skills            All loaded skills and tools
GET  /api/plans             List all plans with step statuses
GET  /api/plans/{id}        Plan step detail (task status)
GET  /api/plans/{id}/files  Staging file listing (dev/tested/approved)
GET  /api/plans/{id}/read   Read a staging file
POST /api/plans/{id}/approve Promote tested → approved
GET  /api/events            Recent system events
POST /api/events            Inbound from n8n (task/event push)
GET  /api/coding-log        Live agent loop events
GET  /api/plan-status       Step status for a plan
GET  /api/timers            Active countdown timers
```

---

## File Structure

```
jarvis-os/
├── jarvis.sh                  # Start/stop/restart/status (classic)
├── systemd/                   # systemd user units + install.sh (recommended)
│   ├── jarvis.target          # Umbrella target — start/stop everything
│   ├── jarvis-*.service       # One unit per service (17 units)
│   └── install.sh             # Installer (--start / --uninstall)
├── JARVIS.md                  # Personality and persona file
├── scripts/
│   ├── react_server.py        # Main agent server :7900
│   ├── plan_runner.py         # Plan execution daemon (self-healing, 4 workers)
│   ├── claude_proxy.py        # Ollama/llama.cpp-compatible Claude API proxy
│   ├── jarvis_boot_init.py    # One-shot boot init (staging, redis, snapshots)
│   ├── memory/
│   │   ├── memory_router.py   # 4-pass Gemma4 classifier
│   │   └── redis_memory.py    # Working memory helpers
│   ├── watcher.py             # File/event watcher
│   ├── voice_capture.py       # Whisper STT + wake word
│   └── twilio_webhook.py      # Phone/SMS Twilio handler
├── skills/                    # Modular skill modules (35+)
│   ├── loader.py              # Dynamic discovery + import
│   ├── coding.py              # Code generation
│   ├── coding_qwen3_coder.py  # qwen3.6:27b executor
│   ├── plan.py                # Plan create/proceed/cancel
│   ├── n8n.py                 # n8n workflow integration
│   ├── shell.py               # Shell + file reading
│   ├── git.py                 # Git operations
│   ├── web.py                 # Web search + URLs
│   ├── news.py                # Live news
│   ├── weather.py             # Weather forecasts
│   ├── memory.py              # MemPalace vector memory
│   ├── memory_core.py         # Working memory (Redis)
│   ├── vault.py               # Obsidian vault
│   ├── notes.py               # Quick notes
│   ├── cloud_llm.py           # Cloud LLM APIs
│   ├── flux.py                # FLUX image generation
│   ├── email.py               # SMTP/IMAP email
│   ├── phone.py               # Twilio calls
│   ├── sms.py                 # Twilio SMS
│   ├── denon.py               # Denon AVR receiver
│   ├── shield.py              # NVIDIA Shield
│   ├── lg_tv.py               # LG TV
│   ├── hue.py                 # Philips Hue
│   ├── plex.py                # Plex Media Server
│   ├── radio.py               # Internet radio
│   ├── timer.py               # Countdown timers
│   └── ...                    # More skills
├── config/
│   ├── skills.json            # Enable/disable skills
│   └── models-config.json     # Model slot assignments
├── infra/
│   ├── podman-compose.n8n.yml # n8n container setup
│   ├── .env.n8n               # n8n env template
│   └── .env.n8n.local         # Local overrides (gitignored)
├── app/                       # Next.js Stark HUD
│   ├── app/
│   │   ├── page.tsx           # Main HUD — voice, face, controls
│   │   ├── components/
│   │   │   ├── coding-workspace.tsx  # Codex UI + plan picker
│   │   │   ├── face/                 # Three.js lattice face
│   │   │   ├── approval-panel.tsx    # SSE approval requests
│   │   │   └── ...
│   │   └── api/               # Next.js API proxy routes
│   │       ├── plans/         # Plan status, files, approve
│   │       ├── approvals/     # Approval request SSE stream
│   │       └── ...
│   └── lib/
│       └── tts.ts             # Kokoro TTS client
├── staging/                   # Plan execution output
│   ├── dev/PLAN-ID/           # In-progress files
│   ├── tested/PLAN-ID/        # Passed automated tests
│   └── approved/PLAN-ID/      # Human-approved
├── tts/                       # Kokoro/Orpheus TTS server
├── docs/
│   ├── ARCHITECTURE.md        # Detailed system architecture
│   ├── SKILLS.md              # Skill system guide + catalog
│   └── skills/                # Per-skill documentation
└── memory/                    # MemPalace vector store
```

---

## n8n Integration

Jarvis and n8n communicate bidirectionally:

**Jarvis → n8n** (trigger workflows):
```
"add task to n8n: research competitor pricing"
→ n8n skill: add_task
→ POST /webhook/jarvis-task { task, callback_url }
→ n8n runs workflow → POSTs result back to /api/events
```

**n8n → Jarvis** (push tasks/events):
```
POST http://jarvis:7900/api/events
{ "type": "workflow_done", "task": "build X", "data": {...} }
→ Logged as event
→ If task field present → queued to Redis plan_runner
```

Configure in `infra/.env.n8n.local`:
```bash
N8N_TASK_WEBHOOK=/webhook/jarvis-task
N8N_EVENT_WEBHOOK=/webhook/jarvis-event
JARVIS_API_URL=http://<wsl-ip>:7900
```

---

## Personality Modes

| Mode | Character | Address |
|------|-----------|---------|
| J.A.R.V.I.S | British butler, dry wit | "sir" |
| F.R.I.D.A.Y | Casual, friendly | First name |
| E.D.I.T.H | Direct, tactical | "boss" |
| HAL 9000 | Calm, unsettling | "Dave" |

---

## Example Commands

```
"build a lottery website with a 7x7 number grid"
"proceed PLAN-20260619-001"
"add task to n8n: send weekly report to team"
"Play Nova radio"
"Switch Denon to PC"
"Set a timer for 10 minutes"
"Search for latest Next.js 15 features"
"What do you remember about StockWatch?"
"Turn the lights blue in the living room"
"Scan the network for devices"
"Generate an image of a cyberpunk cityscape at dawn"
```

---

## Companion App

**[JARVIS Mobile](https://github.com/porokka/jarvis-mobile)** — React Native (Expo) mobile client for JARVIS OS.

- On-device Gemma4 model routes requests locally before dispatching to the desktop
- Communicates with jarvis-os via Telegram bot and direct API
- Plan approvals, voice commands, and status from your phone
- Camera input for visual context
- Built with Expo 52 + React Native

```
Phone mic → Gemma4 (on-device) → route decision
                                    ├── simple: answer on-device
                                    └── complex: dispatch to jarvis-os via Telegram
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
