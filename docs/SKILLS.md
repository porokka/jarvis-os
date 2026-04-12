# JARVIS Skill System

The skill system lets you add, remove, and configure JARVIS capabilities as self-contained Python modules. Each skill registers its own tools, keywords, and executors — the ReAct server discovers them automatically.

---

## How It Works

```
jarvis-os/skills/
├── __init__.py          # Package init
├── loader.py            # Discovery + import engine
├── denon.py             # ← Each file = one skill
├── shield.py
├── radio.py
└── ...
```

On startup, `react_server.py` calls `load_skills()` which:

1. Scans `skills/*.py` (skips `__init__.py`, `loader.py`, `_private.py`)
2. Checks `config/skills.json` — skips disabled skills
3. Imports each module and reads: `TOOLS`, `TOOL_MAP`, `KEYWORDS`
4. Calls `init()` if the skill defines one (for config loading, etc.)
5. Merges everything into the ReAct server's tool registry

---

## Quick Start

### Add a new skill

Create `skills/my_device.py`:

```python
SKILL_NAME = "my_device"
SKILL_DESCRIPTION = "Controls my custom device"

def exec_my_command(action: str) -> str:
    """Do something with the device."""
    return f"Executed: {action}"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "my_command",
            "description": "Control my device. Actions: on, off, status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: on, off, status",
                    }
                },
                "required": ["action"],
            },
        },
    },
]

TOOL_MAP = {
    "my_command": exec_my_command,
}

KEYWORDS = {
    "my_command": ["my device", "turn on", "turn off"],
}
```

Restart the server — your skill is live. The planner and keyword matcher automatically include your new tools.

### Disable a skill

Edit `config/skills.json`:

```json
{
  "enabled": {
    "denon": true,
    "shield": true,
    "radio": false,
    "my_device": true
  }
}
```

Skills not listed default to **enabled**.

---

## Skill Module API

Every skill module must define these top-level variables:

### Required

| Variable | Type | Description |
|----------|------|-------------|
| `SKILL_NAME` | `str` | Unique skill identifier |
| `TOOLS` | `list[dict]` | Ollama-format tool definitions |
| `TOOL_MAP` | `dict[str, callable]` | `{tool_name: executor_function}` |
| `KEYWORDS` | `dict[str, list[str]]` | `{tool_name: [trigger_keywords]}` for fallback routing |

### Optional

| Variable / Function | Type | Description |
|---------------------|------|-------------|
| `SKILL_DESCRIPTION` | `str` | One-line description (shown in `/api/skills`) |
| `init()` | `function` | Called once after import — load configs, validate deps |

### Tool Definition Format

Tools use the Ollama function-calling format:

```python
{
    "type": "function",
    "function": {
        "name": "tool_name",           # Unique across all skills
        "description": "What it does",  # LLM reads this to decide when to call
        "parameters": {
            "type": "object",
            "properties": {
                "param_name": {
                    "type": "string",   # string, number, boolean
                    "description": "What this param is for",
                }
            },
            "required": ["param_name"],
        },
    },
}
```

### Executor Function Signature

Executor functions receive keyword arguments matching the tool's `parameters.properties`:

```python
def exec_my_tool(param_name: str) -> str:
    # Do work...
    return "Result string shown to LLM"
```

- **Always return a string** — the LLM sees this as the tool result
- Keep results under 4000 chars for context efficiency
- Return clear error messages on failure (the LLM may retry)

---

## Cross-Skill Communication

Skills can import from each other. For example, `shield.py` delegates to `denon.py`:

```python
def _denon_switch_input(input_name: str) -> str:
    try:
        from skills.denon import exec_denon_input
        return exec_denon_input(input_name)
    except ImportError:
        return "Denon skill not loaded"
```

Use `try/except ImportError` so the skill still works if the dependency is disabled.

---

## Config Loading Pattern

For skills that need device configs, use an `init()` function:

```python
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config" / "my_device.json"
CONFIG = {}

def init():
    global CONFIG
    CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    print(f"[MY_DEVICE] Loaded config: {CONFIG.get('name')}")
```

Store device configs in `config/` as JSON or YAML files.

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/skills` | GET | List all loaded skills with their tools |
| `/api/health` | GET | Server health check |
| `/api/timers` | GET | Active countdown timers (from timer skill) |

### Example: GET /api/skills

```json
{
  "skills": [
    {
      "name": "denon",
      "description": "Denon AVR-X4100W receiver — inputs, volume, presets, surround, zones",
      "tools": ["denon_input", "denon_volume", "denon_preset", "denon_surround", "denon_power"]
    },
    {
      "name": "radio",
      "description": "Internet radio — Finnish stations + custom streams via mpv",
      "tools": ["play_radio"]
    }
  ]
}
```

---

## Tool Selection

The ReAct server picks tools for each request using a two-stage process:

1. **LLM Planner** (primary) — Asks `qwen3:30b-a3b` which tools are needed
2. **Keyword Fallback** — If the planner fails, scores tools by keyword matches

Each skill's `KEYWORDS` dict feeds the fallback matcher. Write keywords as lowercase phrases the user might say.

---

## Debugging

Skill loading is logged at startup:

```
[SKILLS] Loaded: denon — 5 tools (denon_input, denon_volume, denon_preset, denon_surround, denon_power)
[SKILLS] Loaded: shield — 2 tools (room_command, scan_network)
[SKILLS] Loaded: radio — 1 tools (play_radio)
[SKILLS] Skipping disabled skill: my_broken_skill
[SKILLS] Failed to load bad_skill: ModuleNotFoundError: No module named 'foo'
[SKILLS] Total: 10 skills, 20 tools
```

Tool calls are logged during execution:

```
[REACT] Tool: denon_input({"input_name": "pc"})
[REACT] Result: Switched Denon to pc
```

---

## Skill Index

| Skill | File | Guide |
|-------|------|-------|
| Denon AVR | `skills/denon.py` | [docs/skills/denon.md](skills/denon.md) |
| NVIDIA Shield | `skills/shield.py` | [docs/skills/shield.md](skills/shield.md) |
| Internet Radio | `skills/radio.py` | [docs/skills/radio.md](skills/radio.md) |
| System Volume | `skills/volume.py` | [docs/skills/volume.md](skills/volume.md) |
| Timers | `skills/timer.py` | [docs/skills/timer.md](skills/timer.md) |
| Memory | `skills/memory.py` | [docs/skills/memory.md](skills/memory.md) |
| Vault | `skills/vault.py` | [docs/skills/vault.md](skills/vault.md) |
| Web Search | `skills/web.py` | [docs/skills/web.md](skills/web.md) |
| Shell | `skills/shell.py` | [docs/skills/shell.md](skills/shell.md) |
| Claude Skills | `skills/claude_skills.py` | [docs/skills/claude_skills.md](skills/claude_skills.md) |
| LG TV | `skills/lg_tv.py` | [docs/skills/lg_tv.md](skills/lg_tv.md) |
| Panasonic Blu-ray | `skills/panasonic_bd.py` | [docs/skills/panasonic_bd.md](skills/panasonic_bd.md) |
| Network | `skills/network.py` | [docs/skills/network.md](skills/network.md) |
| Git | `skills/git.py` | [docs/skills/git.md](skills/git.md) |
| FLUX Image Gen | `skills/flux.py` | [docs/skills/flux.md](skills/flux.md) |
| Plex | `skills/plex.py` | [docs/skills/plex.md](skills/plex.md) |
| Philips Hue | `skills/hue.py` | [docs/skills/hue.md](skills/hue.md) |
| Cloud LLM | `skills/cloud_llm.py` | [docs/skills/cloud_llm.md](skills/cloud_llm.md) |
