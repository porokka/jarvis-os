# Model Skill

Switch the active Ollama model slot at runtime without restarting.

**File:** `skills/model_skill.py`

---

## Tools

### switch_model

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `slot` | string | yes | `fast`, `reason`, `code`, `deep`, `router` |
| `model` | string | yes | Ollama model name, e.g. `qwen3:14b`, `gemma4:26b` |

**Slots:**

| Slot | Default | Use Case |
|------|---------|----------|
| `fast` | `qwen3:14b` | Casual chat, quick answers |
| `reason` | `qwen3:14b` | Planning, analysis, tool use |
| `code` | `qwen3.6:27b` | Code generation, file writes |
| `deep` | `qwen3.6:27b` | Strategy, deep analysis |
| `router` | `gemma4:4b` | Memory router (llama.cpp) |

**Examples:**
```
"Switch reason model to gemma4:26b"
"Use qwen3.6:27b for reasoning"
"Switch code model to deepseek-coder:33b"
"What model is active"
```

Changes persist until restart. To make permanent, edit `config/models-config.json`.
