# JARVIS OS — System Architecture

---

## Hardware

```
RTX 3090 (24GB VRAM)          RTX 2080 (8GB VRAM)
─────────────────────         ──────────────────────
qwen3.6:27b (code)        gemma4:4b (memory router, llama.cpp :8081)
qwen3:14b (planner)           Whisper STT (voice transcription)
qwen3.6:27b (reason/deep)   Kokoro TTS (speech synthesis :5100)
Ollama :11434
FLUX image gen
```

---

## Request Flow

```
User Input
(Voice / HUD / Telegram / API / n8n webhook)
          │
          ▼
  ┌─────────────────────────────────────┐
  │        Memory Router                │
  │        memory/memory_router.py      │
  │                                     │
  │  Pass 1: Ambiguity classifier       │
  │  Pass 2: Memory context fetch       │  Redis working memory
  │  Pass 3: Tool/skill selector        │  → skill, tool, args
  │  Pass 4: Route classifier           │  → fast/reason/code/tools/chat
  │                                     │
  │  force_correct_common_tool()        │  post-router overrides
  │  plan command short-circuit         │  proceed/cancel bypass router
  └──────────────┬──────────────────────┘
                 │
          ┌──────▼──────────────────────────────┐
          │       react_server.py  :7900          │
          │                                       │
          │  handle_live_router()                 │
          │    ├─ chat_only → respond immediately │
          │    └─ pass to handle_full_pipeline    │
          │                                       │
          │  handle_full_pipeline()               │
          │    ├─ route=code   → plan or code     │
          │    ├─ route=tools  → ReAct loop       │
          │    ├─ route=reason → qwen3:14b        │
          │    └─ route=fast   → qwen3:14b         │
          └──────┬──────────────────────────────┘
                 │
     ┌───────────┴────────────────┐
     │                            │
     ▼                            ▼
┌──────────┐              ┌───────────────────┐
│  Ollama   │              │  Plan System       │
│  :11434   │              │                   │
│           │              │  build_simple_     │
│  qwen3:*  │              │  code_plan()       │
│  qwen3-   │              │    qwen3:14b →     │
│  coder:*  │              │    PLAN-ID + steps │
│  gemma4:* │              │                   │
└──────────┘              │  queue_plan_to_    │
                          │  redis()            │
                          │    → jarvis:tasks   │
                          └────────┬──────────┘
                                   │
                          ┌────────▼──────────┐
                          │  plan_runner.py    │
                          │  (daemon)          │
                          │                   │
                          │  exec_code_step()  │ qwen3.6:27b
                          │    → staging/dev/  │ writes files
                          │                   │
                          │  _build_test_cmd() │
                          │    → Playwright    │ simple (≤8 files)
                          │    → Podman        │ complex
                          │                   │
                          │  cp dev→tested     │ auto after tests
                          └────────┬──────────┘
                                   │
                          Human gate (HUD or Telegram)
                                   │
                          staging/tested → staging/approved
```

---

## Component Map

| Component | File | Port | Description |
|-----------|------|------|-------------|
| Agent Server | `scripts/react_server.py` | 7900 | Main entry point, ReAct loop, plan system |
| Plan Runner | `scripts/plan_runner.py` | — | Redis consumer, code execution, tests |
| Memory Router | `memory/memory_router.py` | — | 4-pass Gemma4 classifier |
| Redis Memory | `memory/redis_memory.py` | — | Working memory helpers |
| llama.cpp | external | 8081 | Gemma4:4b for memory routing |
| Ollama | external | 11434 | All local LLM inference |
| Kokoro TTS | `tts/server.py` | 5100 | Text-to-speech synthesis |
| PTY Bridge | `scripts/pty_server.py` | 4010 | Terminal WebSocket for Codex UI |
| Stark HUD | `app/` | 3000 | Next.js dashboard |
| n8n | `infra/podman-compose.n8n.yml` | 5678 | Workflow automation |

---

## Memory Architecture

```
Input text
    │
    ├── Redis: agent:memory:working (last N interactions)
    │   └── read by memory_router Pass 2
    │
    ├── MemPalace vector DB
    │   └── semantic search for relevant memories
    │
    └── Obsidian vault (D:/Jarvis_vault)
        └── structured notes, projects, decisions
```

**Redis keys:**
| Key | Type | Purpose |
|-----|------|---------|
| `agent:memory:working` | list | Rolling recent interactions |
| `agent:state` | hash | Current task/agent/route state |
| `jarvis:tasks` | list | Plan step queue (plan_runner reads) |
| `jarvis:plans` | hash | Full plan JSON keyed by PLAN-ID |
| `jarvis:task_status` | hash | Step status keyed by PLAN-ID:step |
| `jarvis:task_results` | hash | Step outputs |

---

## Plan Execution Detail

```
build_simple_code_plan(goal, model="qwen3:14b")
    │
    ├── Calls Ollama: structured JSON with 8-10 steps
    │   Each step: { goal, target_files, tool }
    │
    ├── Replaces <PLAN_ID> placeholder with actual ID
    │
    ├── Stores in Redis jarvis:plans
    │
    └── Returns rendered plan for human review

queue_plan_to_redis(plan_id)
    │
    ├── For each step → build task dict:
    │   { plan_id, task_id, task, skill, tool,
    │     target_files, args, depends_on }
    │
    └── rpush jarvis:tasks

plan_runner.py (daemon loop)
    │
    ├── blpop jarvis:tasks
    │
    ├── Check dependency: wait for depends_on task to complete
    │
    ├── skill == coding → exec_code_step()
    │   ├── Build prompt with goal + context
    │   ├── POST to Ollama qwen3.6:27b
    │   ├── Strip markdown fences
    │   └── Write to /mnt/e/coding/staging/dev/PLAN-ID/file
    │
    ├── skill == shell → dispatch_via_executor()
    │   ├── cmd missing → _build_test_cmd()
    │   │   ├── ≤8 files + has index.html → Playwright
    │   │   └── complex → Podman node:20-alpine
    │   └── subprocess.run() fallback if executor offline
    │
    └── Update jarvis:task_status[PLAN-ID:task_id]
```

---

## HUD Architecture (Next.js)

```
app/app/page.tsx
    │
    ├── JarvisScene (Three.js)
    │   └── LatticeFace
    │       ├── amplitude-driven mouth (analyserRef)
    │       └── amplitude ring (pulses with TTS volume)
    │
    ├── CodingWorkspace
    │   ├── Plan picker (polls /api/plans every 5s)
    │   ├── Stage tabs: dev / tested / approved
    │   ├── File browser (staging files for active plan)
    │   ├── Step status (✓ / ✗ / … per step)
    │   ├── Approve button → POST /api/plans/{id}
    │   ├── Agent input → POST /api/chat route=code
    │   └── PTY terminal → ws://localhost:4010
    │
    ├── ApprovalPanel (SSE stream)
    │   └── /api/approvals/stream → approve / deny
    │
    └── Voice pipeline
        ├── Microphone → Whisper STT → /api/chat
        ├── Response → Kokoro TTS → AudioContext
        └── AudioContext → analyserRef → LatticeFace
```

---

## n8n Integration

```
Jarvis → n8n:
  exec_n8n(action="add_task", payload={task, callback_url})
  → POST N8N_TASK_WEBHOOK
  → n8n workflow runs
  → n8n POSTs result to JARVIS_API_URL/api/events

n8n → Jarvis:
  POST /api/events { type, task, source, data }
  → log_event()
  → if task field: rpush jarvis:tasks (plan_runner picks up)
```

---

## Voice Pipeline

```
Microphone
    │
    ├── Always-on: voice_capture.py streams to Whisper
    │   └── Wake word "Hey JARVIS" (optional)
    │
    ├── Whisper transcription → text
    │
    ├── POST /api/chat { messages, source: "voice" }
    │
    ├── Response text → Kokoro TTS server :5100
    │   └── Returns WAV audio
    │
    ├── WebSocket "tts_blob" → browser
    │
    └── AudioContext graph:
        AudioBufferSource → analyserRef → destination (speakers)
                                ↑
                          LatticeFace reads amplitude
                          → drives mouth vertices
                          → drives amplitude ring opacity
```
