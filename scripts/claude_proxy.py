"""
JARVIS Claude Proxy — Ollama/llama.cpp-compatible server backed by the Claude API.

Lets the whole JARVIS stack (react_server, memory_router, plan_runner,
coding_qwen3_coder, agent_loop, …) run on the Claude API with ZERO changes:
it speaks Ollama's /api/chat + /api/tags + /api/embeddings AND llama.cpp's
/v1/chat/completions, translating to Anthropic /v1/messages.

Usage (Ollama off — proxy takes its port):
    python3 scripts/claude_proxy.py                  # listens on :11434
    LLAMA_CPP_HOST=http://127.0.0.1:11434 python3 scripts/react_server.py

Or on a different port with env overrides:
    CLAUDE_PROXY_PORT=11435 python3 scripts/claude_proxy.py
    OLLAMA_HOST=http://127.0.0.1:11435 LLAMA_CPP_HOST=http://127.0.0.1:11435 ...

API key: ANTHROPIC_API_KEY env var, or config/cloud_llm.json {"anthropic": {"api_key": ...}}.

Model mapping (local name → Claude):
    gemma*/live/fast names        → JARVIS_CLAUDE_FAST_MODEL (default claude-haiku-4-5)
    everything else               → JARVIS_CLAUDE_MODEL      (default claude-sonnet-5)

Embeddings: Claude has no embeddings API — /api/embeddings returns an empty
embedding so callers (memory_router, index_vault) degrade gracefully.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("CLAUDE_PROXY_PORT", "11434"))
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

MODEL_DEFAULT = os.environ.get("JARVIS_CLAUDE_MODEL", "claude-sonnet-5")
MODEL_FAST = os.environ.get("JARVIS_CLAUDE_FAST_MODEL", "claude-haiku-4-5-20251001")
FAST_HINTS = ("gemma", "live", "fast", "phi", "tiny", "mini", "1b", "3b", "4b")

# Optional embeddings backend (Claude API has none):
# set VOYAGE_API_KEY to enable Voyage AI; otherwise /api/embeddings returns
# an empty embedding and semantic search degrades gracefully.
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "").strip()
VOYAGE_MODEL = os.environ.get("VOYAGE_MODEL", "voyage-3-lite")
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "cloud_llm.json"

# Fake local model list so /api/tags satisfies readiness checks
FAKE_TAGS = ["gemma4:e4b", "qwen3:14b", "qwen3.6:27b", "qwen3.6:27b", "nomic-embed-text"]


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return str(cfg.get("anthropic", {}).get("api_key", "")).strip()
    except Exception:
        return ""


def _map_model(name: str) -> str:
    n = (name or "").lower()
    if any(h in n for h in FAST_HINTS):
        return MODEL_FAST
    return MODEL_DEFAULT


def _tools_to_anthropic(tools: list) -> list:
    """Ollama/OpenAI tool format → Anthropic tool format."""
    out = []
    for t in tools or []:
        fn = t.get("function", {}) if isinstance(t, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        out.append({
            "name": name,
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _messages_to_anthropic(messages: list) -> tuple[str, list]:
    """
    Ollama/OpenAI messages → (system_text, anthropic_messages).
    Ollama tool messages carry no IDs, so IDs are assigned in order and
    matched FIFO against the preceding assistant tool_calls.
    """
    system_parts: list[str] = []
    out: list[dict] = []
    pending_ids: list[str] = []

    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "") or ""

        if role == "system":
            if content:
                system_parts.append(str(content))
            continue

        if role == "assistant":
            blocks: list[dict] = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"raw": args}
                tid = tc.get("id") or f"toolu_{uuid.uuid4().hex[:12]}"
                pending_ids.append(tid)
                blocks.append({"type": "tool_use", "id": tid,
                               "name": fn.get("name", ""), "input": args or {}})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            continue

        if role == "tool":
            tid = m.get("tool_call_id") or (pending_ids.pop(0) if pending_ids else f"toolu_{uuid.uuid4().hex[:12]}")
            out.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tid, "content": str(content)[:50000],
            }]})
            continue

        # user (and anything else)
        out.append({"role": "user", "content": str(content)})

    # Anthropic requires alternating roles starting with user
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(continue)"})

    return "\n\n".join(system_parts), out


def _call_claude(model: str, system: str, messages: list, tools: list,
                 max_tokens: int, temperature: float, timeout: int = 300) -> dict:
    key = _api_key()
    if not key:
        raise RuntimeError("No Anthropic API key: set ANTHROPIC_API_KEY or config/cloud_llm.json")

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _claude_to_parts(data: dict) -> tuple[str, list]:
    """Anthropic response → (text, ollama_style_tool_calls)."""
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "function": {
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}) or {},
                },
            })
    return "".join(text_parts), tool_calls


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # quieter default logging
        print(f"[PROXY] {self.address_string()} {fmt % args}")

    def _json(self, obj: dict, status: int = 200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ── GET ────────────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path.startswith("/api/tags"):
            self._json({"models": [
                {"name": n, "model": n, "modified_at": _now_iso(),
                 "size": 0, "details": {"family": "claude-proxy"}}
                for n in FAKE_TAGS
            ]})
        elif self.path.startswith("/health") or self.path == "/":
            self._json({"ok": True, "backend": "claude",
                        "default_model": MODEL_DEFAULT, "fast_model": MODEL_FAST,
                        "api_key_configured": bool(_api_key())})
        else:
            self._json({"error": f"unknown path {self.path}"}, 404)

    # ── POST ───────────────────────────────────────────────────────────────
    def do_POST(self):
        body = self.event_body = self._read_body()

        try:
            if self.path.startswith("/api/chat"):
                self._handle_ollama_chat(body)
            elif self.path.startswith("/v1/chat/completions"):
                self._handle_openai_chat(body)
            elif self.path.startswith("/api/embeddings") or self.path.startswith("/api/embed"):
                self._handle_embeddings(body)
            elif self.path.startswith("/api/generate"):
                self._handle_ollama_generate(body)
            else:
                self._json({"error": f"unknown path {self.path}"}, 404)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            print(f"[PROXY] Anthropic HTTP {e.code}: {detail}")
            self._json({"error": f"Anthropic API {e.code}: {detail}"}, 502)
        except Exception as e:
            print(f"[PROXY] error: {e}")
            self._json({"error": str(e)}, 500)

    def _options_of(self, body: dict) -> tuple[int, float]:
        opts = body.get("options", {}) if isinstance(body.get("options"), dict) else {}
        max_tokens = int(opts.get("num_predict") or body.get("max_tokens") or 4096)
        if max_tokens <= 0:
            max_tokens = 4096
        temperature = float(opts.get("temperature", body.get("temperature", 0.3)) or 0.0)
        return max_tokens, temperature

    def _handle_ollama_chat(self, body: dict):
        requested = body.get("model", "")
        model = _map_model(requested)
        system, messages = _messages_to_anthropic(body.get("messages", []))
        tools = _tools_to_anthropic(body.get("tools", []))
        max_tokens, temperature = self._options_of(body)

        data = _call_claude(model, system, messages, tools, max_tokens, temperature)
        text, tool_calls = _claude_to_parts(data)

        message: dict = {"role": "assistant", "content": text}
        if tool_calls:
            message["tool_calls"] = tool_calls

        usage = data.get("usage", {})
        self._json({
            "model": requested or model,
            "created_at": _now_iso(),
            "message": message,
            "done": True,
            "done_reason": data.get("stop_reason", "stop"),
            "prompt_eval_count": usage.get("input_tokens", 0),
            "eval_count": usage.get("output_tokens", 0),
        })

    def _handle_embeddings(self, body: dict):
        """Ollama embeddings format. Backed by Voyage AI when VOYAGE_API_KEY is
        set; otherwise returns an empty embedding so callers degrade gracefully
        (Claude API has no embeddings endpoint)."""
        prompt = str(body.get("prompt") or body.get("input") or "")
        if not (VOYAGE_API_KEY and prompt):
            self._json({"embedding": []})
            return

        req = urllib.request.Request(
            VOYAGE_URL,
            data=json.dumps({"model": VOYAGE_MODEL, "input": [prompt[:16000]]}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {VOYAGE_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            embedding = (data.get("data") or [{}])[0].get("embedding") or []
            self._json({"embedding": embedding})
        except Exception as e:
            print(f"[PROXY] voyage embeddings failed: {e}")
            self._json({"embedding": []})

    def _handle_ollama_generate(self, body: dict):
        requested = body.get("model", "")
        model = _map_model(requested)
        prompt = str(body.get("prompt", ""))
        system = str(body.get("system", ""))
        max_tokens, temperature = self._options_of(body)

        data = _call_claude(model, system, [{"role": "user", "content": prompt}],
                            [], max_tokens, temperature)
        text, _ = _claude_to_parts(data)
        self._json({
            "model": requested or model,
            "created_at": _now_iso(),
            "response": text,
            "done": True,
        })

    def _handle_openai_chat(self, body: dict):
        requested = body.get("model", "")
        model = _map_model(requested)
        system, messages = _messages_to_anthropic(body.get("messages", []))
        tools = _tools_to_anthropic(body.get("tools", []))
        max_tokens, temperature = self._options_of(body)

        data = _call_claude(model, system, messages, tools, max_tokens, temperature)
        text, tool_calls = _claude_to_parts(data)

        message: dict = {"role": "assistant", "content": text}
        if tool_calls:
            message["tool_calls"] = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["function"]["name"],
                              "arguments": json.dumps(tc["function"]["arguments"])}}
                for tc in tool_calls
            ]

        usage = data.get("usage", {})
        self._json({
            "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": requested or model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        })


def main():
    key_state = "configured" if _api_key() else "MISSING — set ANTHROPIC_API_KEY"
    print(f"[PROXY] Claude proxy listening on :{PORT}")
    print(f"[PROXY] default model: {MODEL_DEFAULT}   fast model: {MODEL_FAST}")
    print(f"[PROXY] API key: {key_state}")
    print(f"[PROXY] endpoints: /api/chat /api/generate /api/tags /api/embeddings /v1/chat/completions")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), ProxyHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
