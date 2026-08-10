# JARVIS Skill System

Skills are self-contained Python modules in `skills/`. Drop a file in, restart — it's live. The agent automatically uses your tools via the memory router and ReAct loop.

---

## How It Works

```
jarvis.sh start
    │
react_server.py → load_skills()
    │
    ├── scan skills/*.py
    ├── check config/skills.json (enabled/disabled)
    ├── import module → read TOOLS, TOOL_MAP, KEYWORDS, SKILL_META
    ├── call init() if defined
    └── merge into tool registry
```

Every incoming request goes through the **4-pass memory router** (Gemma4:4b) which classifies intent, fetches memory context, and selects the relevant tools — before the ReAct loop even starts.

---

## Quick Start — Write a Skill

Create `skills/my_device.py`:

```python
SKILL_NAME        = "my_device"
SKILL_DESCRIPTION = "Controls my custom device"
SKILL_VERSION     = "1.0.0"
SKILL_CATEGORY    = "hardware"
SKILL_TAGS        = ["device", "control"]

SKILL_META = {
    "name":          SKILL_NAME,
    "description":   SKILL_DESCRIPTION,
    "entrypoint":    "exec_my_command",
    "route":         "tools",
    "intent_aliases": ["my device", "device on", "device off"],
    "keywords":      ["my device", "turn on", "turn off"],
    "direct_match":  ["my device"],
}

def exec_my_command(action: str) -> dict:
    if action == "on":
        return {"ok": True, "speech": {"text": "Device on."}}
    return {"ok": True, "speech": {"text": f"Action: {action}"}}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "my_command",
            "description": "Control my device. Actions: on, off, status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "on / off / status"}
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {"my_command": exec_my_command}

KEYWORDS = {"my_command": ["my device", "turn on", "turn off"]}
```

Restart → `bash jarvis.sh restart` → your skill is live.

---

## Module API Reference

### Required Variables

| Variable | Type | Description |
|----------|------|-------------|
| `SKILL_NAME` | `str` | Unique identifier (no spaces) |
| `TOOLS` | `list[dict]` | Ollama function-calling format tool definitions |
| `TOOL_MAP` | `dict[str, callable]` | `{"tool_name": executor_fn}` |
| `KEYWORDS` | `dict[str, list[str]]` | Fallback keyword trigger phrases |

### Optional Variables

| Variable | Type | Description |
|----------|------|-------------|
| `SKILL_DESCRIPTION` | `str` | One-line description shown in `/api/skills` |
| `SKILL_VERSION` | `str` | Semver string |
| `SKILL_CATEGORY` | `str` | `automation`, `hardware`, `productivity`, etc. |
| `SKILL_TAGS` | `list[str]` | Search tags |
| `SKILL_META` | `dict` | Full metadata including `intent_aliases`, `direct_match`, `route` |
| `init()` | `function` | Called once after import — load configs, connect to devices |

### SKILL_META Fields

```python
SKILL_META = {
    "name":           "my_skill",
    "description":    "What it does",
    "entrypoint":     "exec_fn_name",   # main executor function name
    "route":          "tools",          # tools / code / reason / chat
    "intent_aliases": ["..."],          # memory router intent matching
    "keywords":       ["..."],          # fallback keyword matching
    "direct_match":   ["exact phrase"], # exact trigger phrases
    "writes_files":   False,            # declares file write capability
    "reads_files":    False,
    "network_access": True,
    "response_style": {
        "default": "structured_status_ui",  # or "plain", "markdown"
        "avoid_raw_dump": True,
    },
}
```

### Tool Definition Format

```python
{
    "type": "function",
    "function": {
        "name": "tool_name",          # unique across all skills
        "description": "...",          # LLM reads this to decide when to call
        "parameters": {
            "type": "object",
            "properties": {
                "param": {
                    "type": "string",  # string / number / boolean / object / array
                    "description": "...",
                    "enum": ["a", "b"] # optional allowed values
                }
            },
            "required": ["param"],
            "additionalProperties": False,
        },
    },
}
```

### Executor Return Format

Return a **dict** for rich responses, or a plain **str** for simple text:

```python
def exec_my_tool(param: str) -> dict:
    return {
        "ok": True,
        "speech": {
            "text": "Done.",           # spoken by TTS
            "priority": "normal",      # normal / high / low
        },
        "ui": {
            "placement": "right-side-hud",
            "format": "status",        # status / list / code / markdown
            "title": "My Tool",
            "summary": "Result summary",
            "ttl_seconds": 60,
        },
        "data": {"key": "value"},      # raw data for downstream use
    }
```

### Disable a Skill

Edit `config/skills.json`:

```json
{
  "enabled": {
    "radio": false,
    "lg_tv": false
  }
}
```

Skills not listed default to **enabled**.

---

## Skill Catalog

### Coding & Plans

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **coding** | `coding.py` | `coding` | Code generation and editing — diff/patch format |
| **coding_qwen3_coder** | `coding_qwen3_coder.py` | `code_edit` | qwen3.6:27b direct executor for plan_runner |
| **plan** | `plan.py` | `plan_create` `plan_proceed` `plan_cancel` | Agentic multi-step plan system with staging pipeline |
| **shell** | `shell.py` | `shell_command` `read_file` | Safe shell execution + file reading in WSL |
| **git** | `git.py` | `git` | Git — status, diff, commit, push, pull, branch, PR |
| **podman** | `podman.py` | `podman` | Podman container management — run, build, ps, logs |
| **app_scaff_skill** | `app_scaff_skill.py` | `scaffold_app` | Project scaffolding from templates |
| **project_ops** | `project_ops.py` | `project_ops` | Project management — create, archive, list projects |

### Automation & Integration

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **n8n** | `n8n.py` | `n8n` | n8n workflow control — trigger webhooks, add tasks, list executions, bidirectional event push |
| **claude_skills** | `claude_skills.py` | `use_skill` | Load and run 34 Claude Code skills on demand |
| **cloud_llm** | `cloud_llm.py` | `cloud_llm` | Cloud LLM APIs — Claude, GPT-4, Gemini, Groq, Mistral, OpenRouter |
| **model_skill** | `model_skill.py` | `switch_model` | Switch active Ollama model slot at runtime |

### Information & Research

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **web** | `web.py` | `web_search` `open_url` | DuckDuckGo search + browser open |
| **news** | `news.py` | `get_news` | Live news headlines via RSS / newsapi |
| **weather** | `weather.py` | `weather` | Current weather and multi-day forecasts |
| **flux** | `flux.py` | `flux` | FLUX text-to-image generation with Qwen3 prompt enhancement |
| **flights** | `amadeus_flights.py` | `flight_search` | Flight prices via Amadeus API (see [monitor.md](skills/monitor.md)) |
| **monitor** | `monitor_skill.py` | `monitor_flights` `monitor_condition` `monitor_list` `monitor_remove` | Background watches run by task_loop — flight fares or any web-observable condition, alerts via Telegram/email ([docs](skills/monitor.md)) |

### Memory & Knowledge

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **memory** | `memory.py` | `memory_search` `memory_add` `memory_status` | MemPalace long-term vector memory (2000+ entries) |
| **memory_core** | `memory_core.py` | `remember` `recall` | Working memory in Redis — fast in-session recall |
| **vault** | `vault.py` | `read_vault_file` `list_vault_dir` | Obsidian vault file access and search |
| **notes** | `notes.py` | `create_note` `search_notes` | Quick note creation and search in vault |
| **mindmap** | `mindmap.py` | `mindmap` | Generate structured mind maps from topics |
| **document_editor** | `document_editor.py` | `edit_document` | Edit and format structured documents |
| **chat_log** | `chat_log.py` | `chat_log` | Read and search conversation history |
| **accounting** | `accounting.py` | `accounting` | Financial queries, invoices, and basic bookkeeping |

### Communication

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **email** | `email.py` | `email` | Send, read inbox, search — SMTP/IMAP |
| **phone** | `phone.py` | `phone` | Twilio calls — make/receive, voicemail, call log |
| **sms** | `sms.py` | `sms` | Twilio SMS — send messages, read inbox |
| **dictate** | `dictate.py` | `dictate` | Continuous dictation mode — transcribe to file |

### Home Automation

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **denon** | `denon.py` | `denon_input` `denon_volume` `denon_preset` `denon_surround` `denon_power` | Denon AVR-X4100W receiver — inputs, volume, surround modes, zones |
| **shield** | `shield.py` | `room_command` | NVIDIA Shield TV per-room control via network |
| **lg_tv** | `lg_tv.py` | `lg_tv` | LG webOS TV — power, volume, inputs, apps, cursor |
| **panasonic_bd** | `panasonic_bd.py` | `bluray` | Panasonic UB9000 4K Blu-ray — play, pause, skip chapters |
| **hue** | `hue.py` | `hue` | Philips Hue — on/off, brightness, colors, scenes, rooms |
| **radio** | `radio.py` | `play_radio` | Internet radio streaming via mpv |
| **volume** | `volume.py` | `set_volume` | Windows system volume (0-100%) |
| **plex** | `plex.py` | `plex` | Plex Media Server — browse library, search, control playback |

### System

| Skill | File | Key Tools | Description |
|-------|------|-----------|-------------|
| **timer** | `timer.py` | `set_timer` | Countdown timers with TTS alerts |
| **network** | `network.py` | `scan_network` | Network scan with device identification and topology map |

---

## Cross-Skill Communication

Skills can call each other. Use `try/except ImportError` so the skill still loads if the dependency is disabled:

```python
def exec_room_av(room: str, input_name: str) -> dict:
    try:
        from skills.denon import exec_denon_input
        exec_denon_input(input_name)
    except ImportError:
        pass
    # ... rest of logic
```

---

## Config Loading Pattern

```python
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "my_device.json"
CONFIG: dict = {}

def init() -> None:
    global CONFIG
    if CONFIG_PATH.exists():
        CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
```

Device configs live in `config/` as JSON files. The `init()` function is called once at startup.

---

## n8n Skill — Bidirectional Integration

The `n8n` skill supports full bidirectional communication:

**Jarvis → n8n:**
```python
exec_n8n(action="add_task", payload={
    "task": "research competitor pricing",
    "assignee": "sami"
})
# POSTs to N8N_TASK_WEBHOOK with callback_url pointing to /api/events
```

**n8n → Jarvis** (n8n calls `/api/events` when workflow completes):
```json
POST http://jarvis:7900/api/events
{
  "type": "workflow_done",
  "task": "build invoice PDF",
  "source": "n8n",
  "data": { "file": "/tmp/invoice.pdf" }
}
```
If the payload includes a `task` field, it gets queued to `jarvis:tasks` Redis list and executed by `plan_runner.py`.

Configure webhook paths in `infra/.env.n8n.local`:
```bash
N8N_TASK_WEBHOOK=/webhook/jarvis-task
N8N_EVENT_WEBHOOK=/webhook/jarvis-event
JARVIS_API_URL=http://<wsl-ip>:7900
```

---

## Debugging

**Skill loading** is logged at startup:
```
[SKILLS] Loaded: n8n — 1 tools (n8n) [automation]
[SKILLS] Loaded: coding — 1 tools (coding) [code]
[SKILLS] Skipping disabled skill: lg_tv
[SKILLS] Failed to load bad_skill: ModuleNotFoundError
[SKILLS] Total: 35 skills, 64 tools
```

**Tool calls** during execution:
```
[REACT] Tool: n8n({"action": "add_task", "payload": {"task": "..."}})
[REACT] Result: Task sent to n8n: research competitor pricing
```

**Live events** at `/api/coding-log` (also shown in Codex UI AGENT panel).

---

## API: Skill Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/skills` | GET | All loaded skills with tool names |
| `/api/health` | GET | Server health including skill count |
| `/api/events` | GET | Recent system events |
| `/api/events` | POST | Inbound from n8n or external services |
| `/api/coding-log` | GET | Live agent loop events (last 120) |
