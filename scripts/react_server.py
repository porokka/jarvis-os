"""
JARVIS ReAct Server — Tool-augmented Ollama proxy

Wraps Ollama's /api/chat with a ReAct loop that gives models
access to tools loaded dynamically from skills/ modules.

Both watcher.sh and bridge.ts call this instead of Ollama directly.

Endpoints:
  POST /api/chat     -> ReAct loop with tools (same format as Ollama)
  GET  /api/health   -> Health check
  GET  /api/timers   -> Active timer list
  GET  /api/skills   -> Loaded skill list

Usage: python scripts/react_server.py [--port 7900]
"""

import json
import os
import random
import subprocess
import sys
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# -- Add project root to sys.path so `skills` package is importable --
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.loader import load_skills, get_all_tools, get_all_tool_map, get_all_keywords, get_loaded_skills

OLLAMA_HOST = "http://localhost:11434"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 7900
MAX_ITERATIONS = 5

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")


def speak_ack(text: str):
    """Speak ACK via PowerShell TTS in background thread — non-blocking."""
    def _speak():
        try:
            safe = text.replace("'", "''")
            subprocess.run(
                ['powershell.exe', '-Command',
                 f"Add-Type -AssemblyName System.Speech; "
                 f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                 f"$s.Rate = 2; $s.Speak('{safe}')"],
                timeout=10, capture_output=True,
            )
        except Exception:
            pass
    threading.Thread(target=_speak, daemon=True).start()

# -- Load all skills --

print(f"[REACT] Loading skills from {PROJECT_ROOT / 'skills'}...")
load_skills()

# Build references from loaded skills
TOOLS = get_all_tools()
TOOL_MAP = get_all_tool_map()
TOOL_KEYWORDS = get_all_keywords()
TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS}

TOOL_LIST_TEXT = "\n".join(
    f"- {t['function']['name']}: {t['function']['description']}"
    for t in TOOLS
)

# -- ReAct loop --

NO_TOOLS_MODELS = set()
PLANNER_MODEL = "qwen3:30b-a3b"


def select_tools_via_llm(user_text: str) -> list:
    """Ask the fast model which tools are needed for this task."""
    import urllib.request

    prompt = f"""/no_think
Pick tools for this request. Reply ONLY with tool names, comma-separated. No explanation.

Tools:
{TOOL_LIST_TEXT}

Request: {user_text}

Tools needed:"""

    payload = json.dumps({
        "model": PLANNER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 100},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        answer = data.get("message", {}).get("content", "").strip()

        # Clean thinking tags
        import re
        if "<think>" in answer:
            answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL).strip()
        if "</think>" in answer:
            answer = answer.split("</think>")[-1].strip()

        print(f"[REACT] Planner says: {answer}")

        if "none" in answer.lower():
            return []

        selected = []
        for name in TOOLS_BY_NAME:
            if name in answer:
                selected.append(TOOLS_BY_NAME[name])

        if not selected and "memory_search" in TOOLS_BY_NAME:
            selected.append(TOOLS_BY_NAME["memory_search"])

        return selected[:4]
    except Exception as e:
        print(f"[REACT] Planner error: {e}")
        return select_tools_keyword(user_text)


def select_tools_keyword(user_text: str, max_tools: int = 4) -> list:
    """Fallback: keyword-based tool selection."""
    scores = {}
    for tool_name, keywords in TOOL_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in user_text)
        if score > 0:
            scores[tool_name] = score

    if not scores:
        scores["memory_search"] = 1

    top = sorted(scores, key=scores.get, reverse=True)[:max_tools]
    return [TOOLS_BY_NAME[name] for name in top if name in TOOLS_BY_NAME]


def react_chat(model: str, messages: list, tools: list = None) -> dict:
    """
    ReAct loop: send messages + tools to Ollama, execute tool calls,
    feed results back, repeat until final text response.
    """
    import urllib.request
    import urllib.error

    if tools is None:
        tools = TOOLS
    use_tools = model not in NO_TOOLS_MODELS and len(tools) > 0

    for iteration in range(MAX_ITERATIONS):
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if use_tools:
            body["tools"] = tools

        payload = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 400 and use_tools:
                print(f"[REACT] {model} rejected tools, caching as no-tools model")
                NO_TOOLS_MODELS.add(model)
                use_tools = False
                continue
            return {"message": {"role": "assistant", "content": f"Error calling Ollama: {e}"}}
        except Exception as e:
            return {"message": {"role": "assistant", "content": f"Error calling Ollama: {e}"}}

        assistant_msg = data.get("message", {})
        tool_calls = assistant_msg.get("tool_calls")

        if not tool_calls:
            return data

        messages.append(assistant_msg)

        for call in tool_calls:
            fn_name = call.get("function", {}).get("name", "")
            fn_args = call.get("function", {}).get("arguments", {})
            executor = TOOL_MAP.get(fn_name)

            print(f"[REACT] Tool: {fn_name}({json.dumps(fn_args)[:100]})")

            if executor:
                try:
                    result = executor(**fn_args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {fn_name}"

            print(f"[REACT] Result: {result[:200]}")

            messages.append({"role": "tool", "content": result})

    return data


# -- HTTP Server --

class ReactHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            model = body.get("model", "mistral-nemo")
            messages = body.get("messages", [])

            user_text = ""
            for m in reversed(messages):
                if m["role"] == "user":
                    user_text = m.get("content", "").lower()
                    break

            selected_tools = select_tools_via_llm(user_text)
            tool_names = [t['function']['name'] for t in selected_tools]
            print(f"[REACT] Selected {len(selected_tools)} tools: {tool_names}")

            if selected_tools:
                acks = ["Right away, sir.", "On it, sir.", "Yes sir, working on it.",
                        "Understood, sir. Processing.", "One moment, sir."]
                ack = random.choice(acks)
                bridge = Path("/tmp/jarvis")
                try:
                    (bridge / "output.txt").write_text(ack)
                    (bridge / "state.txt").write_text("thinking")
                    ts = datetime.now().strftime("%H:%M:%S")
                    with open(str(VAULT_DIR / "jarvis.log"), "a") as f:
                        f.write(f"[{ts}] ACK: {ack}\n")
                    speak_ack(ack)
                except:
                    pass

                fresh_messages = []
                for m in messages:
                    if m["role"] == "system":
                        fresh_messages.append(m)
                non_system = [m for m in messages if m["role"] != "system"]
                fresh_messages.extend(non_system[-4:])
                if not fresh_messages or fresh_messages[-1].get("content", "").lower() != user_text:
                    fresh_messages.append({"role": "user", "content": user_text})
                print(f"[REACT] Trimmed to {len(fresh_messages)} msgs — tools will provide fresh data")
                result = react_chat(model, fresh_messages, selected_tools)
            else:
                result = react_chat(model, messages, [])

            self._json_response(result)
            return

        self.send_error(404)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/health":
            self._json_response({"status": "ok", "service": "jarvis-react"})
            return

        if path == "/api/timers":
            try:
                from skills.timer import get_active_timers
                self._json_response({"timers": get_active_timers()})
            except ImportError:
                self._json_response({"timers": []})
            return

        if path == "/api/radio":
            try:
                from skills.radio import get_radio_state, get_stations, get_now_playing
                self._json_response({
                    **get_radio_state(),
                    "stations": get_stations(),
                    "now_playing": get_now_playing(),
                })
            except ImportError:
                self._json_response({"playing": False, "stations": {}})
            return

        if path == "/api/skills":
            self._json_response({"skills": get_loaded_skills()})
            return

        self.send_error(404)

    def _json_response(self, data: dict, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[REACT] {args[0]}")


if __name__ == "__main__":
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
    sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)

    server = HTTPServer(("127.0.0.1", PORT), ReactHandler)
    print(f"[REACT] ReAct server on http://localhost:{PORT}")
    print(f"[REACT] Ollama backend: {OLLAMA_HOST}")
    print(f"[REACT] Vault: {VAULT_DIR}")
    print(f"[REACT] Tools: {', '.join(TOOL_MAP.keys())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[REACT] Server stopped")
