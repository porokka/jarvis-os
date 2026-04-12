# Cloud LLM Skill

Unified API for calling cloud language models from any provider.

**File:** `skills/cloud_llm.py`
**Config:** `config/cloud_llm.json`

---

## Setup

```bash
cp config/cloud_llm.json.example config/cloud_llm.json
```

Add your API keys for the providers you want:

```json
{
  "anthropic": { "api_key": "sk-ant-..." },
  "openai": { "api_key": "sk-..." },
  "groq": { "api_key": "gsk_..." }
}
```

---

## Providers

| Provider | Models | Key format |
|----------|--------|------------|
| `anthropic` | Claude Sonnet, Opus, Haiku | `sk-ant-...` |
| `openai` | GPT-4o, o1, GPT-4-turbo | `sk-...` |
| `groq` | Llama 3.3 70B, Mixtral | `gsk_...` |
| `together` | Llama, Qwen, DeepSeek | `...` |
| `mistral` | Mistral Large, Medium | `...` |
| `google` | Gemini 2.5 Flash/Pro | `AIza...` |
| `openrouter` | Any model via OpenRouter | `sk-or-...` |

---

## Tools

### cloud_llm

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider` | string | yes | Provider name or `list` |
| `prompt` | string | yes | The prompt to send |
| `model` | string | no | Model override |
| `system` | string | no | System prompt |

**Examples:**
```
"Ask Claude to explain quantum computing"
"Use GPT-4 to write a haiku about coding"
"Ask Groq to summarize this article"
"List cloud providers"
```

---

## Core Integration

When `config/cloud_llm.json` has an Anthropic API key, the watcher automatically uses the Claude API directly instead of `claude --print` CLI. Faster response times, no CLI dependency.
