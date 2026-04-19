"""
Jarvis Local HTTP Server — browser bridge + local control API.

Serves the browser voice UI and provides API endpoints for bridge files,
live logs, model config visibility, and local helper actions.

Endpoints:
  GET  /                 -> jarvis_browser.html
  GET  /api/state        -> current bridge state
  GET  /api/output       -> current output
  GET  /api/gpu          -> GPU stats
  GET  /api/logs         -> tail of jarvis.log
  GET  /api/models       -> current model-config.json + react model info
  GET  /api/react-events -> recent ReAct activity events
  GET  /api/file         -> serve allowed local files
  GET  /api/flux/status  -> image generation status
  POST /api/input        -> write to input.txt / internal commands
  POST /api/settings     -> persist UI settings
  POST /api/state-override -> force bridge state
  POST /api/transcribe   -> whisper transcription
  POST /api/flux         -> start FLUX generation

Usage:
  python scripts/server.py [--port 4000]
"""

from __future__ import annotations

import http.server
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

# -- Add project root to sys.path so shared helpers are importable --
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.model_config import get_models, get_planner_model, load_model_config

BRIDGE_DIR = Path(os.environ.get("JARVIS_BRIDGE_DIR", "/tmp/jarvis"))
VAULT_DIR = Path(os.environ.get("JARVIS_VAULT_DIR", "D:/Jarvis_vault" if os.name == "nt" else "/mnt/d/Jarvis_vault"))
SCRIPTS_DIR = Path(__file__).resolve().parent
MODEL_CONFIG_PATH = PROJECT_ROOT / "config/models-config.json"
REACT_EVENTS_PATH = BRIDGE_DIR / "react_events.jsonl"
REACT_HOST = os.environ.get("JARVIS_REACT_HOST", "http://127.0.0.1:7900")
OLLAMA_HOST = os.environ.get("JARVIS_OLLAMA_API", "http://127.0.0.1:11434")
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 4000

TRANSLATIONS: Dict[str, str] = {}
TRANSLATIONS_FILE = VAULT_DIR / "References" / "voice-translations.md"
_whisper_model = None


# -----------------------------------------------------------------------------
# Logging / utilities
# -----------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"



def log(msg: str) -> None:
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        with open(VAULT_DIR / "jarvis.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] [HTTP] {msg}\n")
    except Exception:
        pass
    print(f"[JARVIS HTTP] {msg}")



def read_file(name: str) -> str:
    path = BRIDGE_DIR / name
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""



def write_file(name: str, content: str) -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    (BRIDGE_DIR / name).write_text(content, encoding="utf-8")



def read_json_file(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"JSON read error for {path}: {e}")
    return default



def recent_react_events(limit: int = 100) -> List[Dict[str, Any]]:
    if not REACT_EVENTS_PATH.exists():
        return []
    try:
        lines = REACT_EVENTS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception as e:
        log(f"Failed reading react events: {e}")
        return []



def get_gpu_stats() -> list:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gpus = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 10:
                continue
            gpus.append(
                {
                    "name": parts[0],
                    "temp": int(parts[1]),
                    "utilization": int(parts[2]),
                    "memUsed": int(parts[3]),
                    "memTotal": int(parts[4]),
                    "power": float(parts[5]),
                    "powerLimit": float(parts[6]),
                    "fan": int(parts[7]) if parts[7] != "[N/A]" else None,
                    "clockCore": int(parts[8]),
                    "clockMem": int(parts[9]),
                }
            )
        return gpus
    except Exception as e:
        log(f"GPU stats failed: {e}")
        return []


# -----------------------------------------------------------------------------
# Models / service visibility
# -----------------------------------------------------------------------------


def get_live_model_info() -> Dict[str, Any]:
    cfg = load_model_config()
    out: Dict[str, Any] = {
        "config": cfg,
        "models": get_models(),
        "planner_model": get_planner_model(),
        "react_host": REACT_HOST,
        "ollama_host": OLLAMA_HOST,
        "react": {"ok": False},
        "ollama": {"ok": False},
    }

    try:
        import urllib.request

        with urllib.request.urlopen(f"{REACT_HOST}/api/health", timeout=2) as resp:
            out["react"] = json.loads(resp.read().decode("utf-8"))
            out["react"]["ok"] = True
    except Exception as e:
        out["react"] = {"ok": False, "error": str(e)}

    try:
        import urllib.request

        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
            out["ollama"] = {
                "ok": True,
                "model_count": len(tags.get("models", [])),
                "models": [m.get("name") for m in tags.get("models", [])],
            }
    except Exception as e:
        out["ollama"] = {"ok": False, "error": str(e)}

    return out


# -----------------------------------------------------------------------------
# Whisper (lazy-loaded on first transcribe request)
# -----------------------------------------------------------------------------


def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU only — GPU reserved for Ollama
        import whisper

        log("Loading Whisper base model")
        _whisper_model = whisper.load_model("base")
        log("Whisper ready")
    return _whisper_model



def transcribe_audio(audio_bytes: bytes) -> str:
    model = get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = model.transcribe(
            tmp_path,
            language="en",
            fp16=False,
            initial_prompt="Hey JARVIS, OK JARVIS, play radio, check my projects, Suomipop, Radio Nova, StockWatch",
        )
        return result["text"].strip()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Voice corrections
# -----------------------------------------------------------------------------


def load_translations() -> None:
    global TRANSLATIONS
    try:
        if not TRANSLATIONS_FILE.exists():
            return
        with open(TRANSLATIONS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("|") and "|" in line[1:] and "Heard" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) == 2:
                        TRANSLATIONS[parts[0].lower()] = parts[1]
        log(f"Loaded {len(TRANSLATIONS)} voice translations")
    except Exception as e:
        log(f"Failed loading translations: {e}")



def correct_text(text: str) -> str:
    lower = text.lower()
    for heard, corrected in TRANSLATIONS.items():
        if heard in lower:
            lower = lower.replace(heard, corrected.lower())
    return lower[0].upper() + lower[1:] if lower else text


load_translations()


# -----------------------------------------------------------------------------
# HTTP handler
# -----------------------------------------------------------------------------


class JarvisHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPTS_DIR), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self.path = "/jarvis_browser.html"
            return super().do_GET()

        if path == "/api/state":
            data = {
                "state": read_file("state.txt") or "standby",
                "emotion": read_file("emotion.txt") or "neutral",
                "lastOutput": read_file("output.txt"),
                "lastInput": read_file("last_input.txt"),
                "brain": read_file("brain.txt") or "—",
            }
            self._json_response(data)
            return

        if path == "/api/models":
            self._json_response(get_live_model_info())
            return

        if path == "/api/react-events":
            self._json_response({"events": recent_react_events(100)})
            return

        if path == "/api/file":
            params = parse_qs(urlparse(self.path).query)
            file_path = params.get("path", [""])[0]
            target = Path(file_path).resolve()
            allowed = [str(VAULT_DIR.resolve()), str(PROJECT_ROOT.resolve()), str(Path("/mnt/e/coding").resolve())]
            if not any(str(target).startswith(r) for r in allowed):
                self.send_error(403, "Path not allowed")
                return
            if not target.exists():
                self.send_error(404, "File not found")
                return
            try:
                data = target.read_bytes()
                self.send_response(200)
                ext = target.suffix.lower()
                ct = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                }.get(ext, "application/octet-stream")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
            return

        if path == "/api/flux/status":
            result_file = BRIDGE_DIR / "flux_result.json"
            if result_file.exists():
                self._json_response(read_json_file(result_file, {"status": "idle"}))
            else:
                self._json_response({"status": "idle"})
            return

        if path == "/api/output":
            self._json_response({"output": read_file("output.txt")})
            return

        if path == "/api/gpu":
            self._json_response({"gpus": get_gpu_stats()})
            return

        if path == "/api/logs":
            try:
                log_path = VAULT_DIR / "jarvis.log"
                if log_path.exists():
                    lines = log_path.read_text(encoding="utf-8", errors="replace").strip().split("\n")
                    self._json_response({"lines": lines[-100:]})
                else:
                    self._json_response({"lines": []})
            except Exception as e:
                self._json_response({"lines": [], "error": str(e)})
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/settings":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            if "voice" in data:
                write_file("settings_voice.txt", str(data["voice"]))
            if "personality" in data:
                write_file("settings_personality.txt", str(data["personality"]))
            log(f"Settings updated: keys={list(data.keys())}")
            self._json_response({"status": "ok"})
            return

        if path == "/api/state-override":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                if "state" in data:
                    write_file("state.txt", str(data["state"]))
                    log(f"State override -> {data['state']}")
            except Exception as e:
                log(f"State override failed: {e}")
            self._json_response({"status": "ok"})
            return

        if path == "/api/flux":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            prompt = body.get("prompt", "")

            if not prompt:
                self._json_response({"error": "No prompt"}, 400)
                return

            def _generate():
                try:
                    log(f"FLUX generation started: {prompt[:100]}")
                    flux_mod = importlib.import_module("skills.flux")
                    result = flux_mod.exec_generate_image(prompt, enhance="no")
                    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
                    (BRIDGE_DIR / "flux_result.json").write_text(
                        json.dumps({"status": "done", "message": result}),
                        encoding="utf-8",
                    )
                    log("FLUX generation finished")
                except Exception as e:
                    (BRIDGE_DIR / "flux_result.json").write_text(
                        json.dumps({"status": "error", "message": str(e)}),
                        encoding="utf-8",
                    )
                    log(f"FLUX generation failed: {e}")

            result_file = BRIDGE_DIR / "flux_result.json"
            result_file.write_text(json.dumps({"status": "generating"}), encoding="utf-8")
            threading.Thread(target=_generate, daemon=True).start()
            self._json_response({"status": "generating", "poll": "/api/flux/status"})
            return

        if path == "/api/transcribe":
            length = int(self.headers.get("Content-Length", 0))
            audio_bytes = self.rfile.read(length)
            try:
                log(f"Transcribe request: {len(audio_bytes)} bytes")
                text = transcribe_audio(audio_bytes)
                if text:
                    corrected = correct_text(text)
                    last_output = read_file("output.txt").lower()
                    heard_words = set(corrected.lower().split())
                    output_words = set(last_output.split()) if last_output else set()
                    overlap = len(heard_words & output_words) / max(len(heard_words), 1)
                    is_echo = overlap > 0.5
                    self._json_response({
                        "text": corrected,
                        "raw": text if corrected != text else None,
                        "echo": is_echo,
                    })
                else:
                    self._json_response({"text": "", "echo": False})
            except Exception as e:
                log(f"Transcribe failed: {e}")
                self._json_response({"error": str(e)}, 500)
            return

        if path == "/api/input":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                text = str(data.get("text", "")).strip()
            except json.JSONDecodeError:
                text = body.strip()

            if text and not text.startswith("__"):
                write_file("input.txt", text)
                log(f"Input accepted: {text[:120]}")
                self._json_response({"status": "ok", "input": text})
                return

            if text.startswith("__tts:"):
                tts_text = text[6:]
                write_file("output.txt", tts_text)
                write_file("state.txt", "speaking")
                log(f"Internal TTS: {tts_text[:120]}")

                def _speak_tts():
                    try:
                        safe = tts_text.replace("'", "''")
                        ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
                        subprocess.run(
                            [
                                ps,
                                "-Command",
                                f"Add-Type -AssemblyName System.Speech; "
                                f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                                f"$s.Rate = 1; $s.Speak('{safe}')",
                            ],
                            timeout=15,
                            capture_output=True,
                        )
                    except Exception as e:
                        log(f"Internal TTS failed: {e}")
                    write_file("state.txt", "standby")

                threading.Thread(target=_speak_tts, daemon=True).start()
                self._json_response({"status": "ok", "tts": tts_text})
                return

            if text.startswith("__exec:"):
                cmd = text[7:]
                allowed = ["pkill -f 'python3 main.py'", "pkill -f comfyui"]
                if cmd in allowed:
                    log(f"Internal exec allowed: {cmd}")
                    threading.Thread(
                        target=lambda: subprocess.run(cmd, shell=True, timeout=10, capture_output=True),
                        daemon=True,
                    ).start()
                    self._json_response({"status": "ok", "exec": cmd})
                else:
                    log(f"Internal exec blocked: {cmd}")
                    self._json_response({"status": "error", "message": "Command not allowed"}, 403)
                return

            if text.startswith("__"):
                self._json_response({"status": "ok", "internal": True})
                return

            self._json_response({"status": "error", "message": "Empty input"}, 400)
            return

        self.send_error(404)

    def _json_response(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        try:
            msg = format % args
        except Exception:
            msg = str(args[0]) if args else format
        log(msg)


if __name__ == "__main__":
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"HTTP server starting on http://127.0.0.1:{PORT}")
    log(f"Serving HTML from {SCRIPTS_DIR}")
    log(f"Bridge files at {BRIDGE_DIR}")
    log(f"Model config path: {MODEL_CONFIG_PATH}")

    server = http.server.HTTPServer(("127.0.0.1", PORT), JarvisHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("HTTP server stopped")
