"""
JARVIS Skill — Cloud LLM API calls.

Supports multiple providers via a unified interface.
Config: config/cloud_llm.json

Supported providers:
  - anthropic (Claude)
  - openai (GPT-4, o1, etc.)
  - groq (Llama, Mixtral on Groq)
  - together (Together.ai models)
  - mistral (Mistral API)
  - google (Gemini)
  - openrouter (any model via OpenRouter)
"""

import json
import urllib.request
from pathlib import Path

SKILL_NAME = "cloud_llm"
SKILL_DESCRIPTION = "Cloud LLM APIs — Claude, GPT-4, Gemini, Groq, Mistral, OpenRouter"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "cloud_llm.json"

# Provider endpoints and formats
PROVIDERS = {
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "auth_header": "x-api-key",
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "format": "anthropic",
        "default_model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "format": "openai",
        "default_model": "gpt-4o",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "format": "openai",
        "default_model": "llama-3.3-70b-versatile",
    },
    "together": {
        "url": "https://api.together.xyz/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "format": "openai",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "format": "openai",
        "default_model": "mistral-large-latest",
    },
    "google": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "auth_header": None,  # uses query param
        "format": "google",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "format": "openai",
        "default_model": "anthropic/claude-sonnet-4",
    },
}


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _call_openai_format(url: str, headers: dict, model: str, prompt: str, system: str = "") -> str:
    """Call OpenAI-compatible API (OpenAI, Groq, Together, Mistral, OpenRouter)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 2000,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _call_anthropic(url: str, headers: dict, model: str, prompt: str, system: str = "") -> str:
    """Call Anthropic Claude API."""
    body = {
        "model": model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["content"][0]["text"]


def _call_google(url: str, api_key: str, model: str, prompt: str, system: str = "") -> str:
    """Call Google Gemini API."""
    actual_url = url.replace("{model}", model) + f"?key={api_key}"
    contents = []
    if system:
        contents.append({"role": "user", "parts": [{"text": system}]})
        contents.append({"role": "model", "parts": [{"text": "Understood."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    payload = json.dumps({"contents": contents}).encode("utf-8")
    req = urllib.request.Request(actual_url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def exec_cloud_llm(provider: str, prompt: str, model: str = "", system: str = "", use_tools: str = "no") -> str:
    """Call a cloud LLM provider. Set use_tools=yes for tool-augmented calls."""
    provider = provider.lower().strip()

    # Tool-augmented call via cloud_react.py
    if use_tools.lower() in ("yes", "true", "1"):
        import subprocess
        scripts_dir = Path(__file__).parent.parent / "scripts"
        try:
            result = subprocess.run(
                ["python3", str(scripts_dir / "cloud_react.py"),
                 "--provider", provider,
                 "--prompt", prompt,
                 "--system", system or "You are JARVIS. Use tools when needed. Concise responses.",
                 ] + (["--model", model] if model else []),
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout.strip()
            if output:
                return output
            return f"Cloud ReAct error: {result.stderr[:300]}"
        except Exception as e:
            return f"Cloud ReAct error: {e}"

    if provider == "list":
        cfg = _load_config()
        lines = []
        for name, info in PROVIDERS.items():
            configured = "configured" if cfg.get(name, {}).get("api_key") else "no key"
            lines.append(f"  {name}: {info['default_model']} ({configured})")
        return "Available providers:\n" + "\n".join(lines)

    if provider not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        return f"Unknown provider '{provider}'. Available: {available}, list"

    cfg = _load_config()
    provider_cfg = cfg.get(provider, {})
    api_key = provider_cfg.get("api_key", "")

    if not api_key:
        return f"No API key for {provider}. Add it to config/cloud_llm.json"

    prov = PROVIDERS[provider]
    model = model or provider_cfg.get("model") or prov["default_model"]

    # Build headers
    headers = {"Content-Type": "application/json"}
    if prov.get("auth_header"):
        prefix = prov.get("auth_prefix", "")
        headers[prov["auth_header"]] = f"{prefix}{api_key}"
    if prov.get("extra_headers"):
        headers.update(prov["extra_headers"])

    try:
        fmt = prov["format"]
        if fmt == "openai":
            result = _call_openai_format(prov["url"], headers, model, prompt, system)
        elif fmt == "anthropic":
            result = _call_anthropic(prov["url"], headers, model, prompt, system)
        elif fmt == "google":
            result = _call_google(prov["url"], api_key, model, prompt, system)
        else:
            return f"Unsupported format: {fmt}"

        return result

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return f"{provider} API error {e.code}: {body}"
    except Exception as e:
        return f"{provider} error: {e}"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cloud_llm",
            "description": "Call a cloud LLM API. Providers: anthropic (Claude), openai (GPT-4), groq (Llama/Mixtral), together, mistral, google (Gemini), openrouter. Use 'list' as provider to see configured keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Provider: anthropic, openai, groq, together, mistral, google, openrouter, list",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The prompt/question to send",
                    },
                    "model": {
                        "type": "string",
                        "description": "Model override (optional — uses default if empty)",
                    },
                    "system": {
                        "type": "string",
                        "description": "System prompt (optional)",
                    },
                },
                "required": ["provider", "prompt"],
            },
        },
    },
]

TOOL_MAP = {
    "cloud_llm": exec_cloud_llm,
}

KEYWORDS = {
    "cloud_llm": [
        "claude", "gpt", "gemini", "groq", "mistral", "openai",
        "cloud", "api", "ask claude", "ask gpt",
    ],
}
