# FLUX Image Generation Skill

Text-to-image generation using FLUX from Black Forest Labs.

**File:** `skills/flux.py`
**Config:** `config/flux.json`

---

## Prerequisites

- FLUX installed: `cd /mnt/e/coding/flux && pip install -e '.[all]'`
- FLUX model at `E:\models\flux1-dev-fp8.safetensors`

---

## Tools

### flux

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | yes | generate, status, recent |
| `prompt` | string | for generate | Image description |
| `enhance` | string | no | Enhance with AI? yes/no |

**Examples:**
```
"Generate an image of a robot butler serving tea"
"Flux status"
"Show recent images"
```

---

## VRAM Management

Automatically swaps Ollama models during generation:
1. qwen3:30b enhances the prompt
2. Swaps to qwen3:8b (5GB)
3. FLUX generates (17GB)
4. Restores qwen3:30b

Images saved to `D:/Jarvis_vault/Daily/images/`.
