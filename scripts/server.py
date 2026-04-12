"""
Jarvis Local HTTP Server

Serves the browser voice UI and provides API endpoints
for the bridge files. No cloud, no external dependencies.

Endpoints:
  GET  /                → jarvis_browser.html
  GET  /api/state       → { state, emotion, lastOutput }
  POST /api/input       → write to input.txt
  GET  /api/output      → current output.txt content

Usage: python scripts/server.py [--port 4000]
"""

import http.server
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

BRIDGE_DIR = Path("/tmp/jarvis")
VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
SCRIPTS_DIR = Path(__file__).resolve().parent
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 4000


def read_file(name: str) -> str:
    path = BRIDGE_DIR / name
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def write_file(name: str, content: str):
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    (BRIDGE_DIR / name).write_text(content, encoding="utf-8")


def get_gpu_stats() -> list:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        gpus = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            gpus.append({
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
            })
        return gpus
    except Exception:
        return []


# ── Whisper (lazy-loaded on first transcribe request) ──

_whisper_model = None

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU only — GPU for Ollama
        import whisper
        print("[JARVIS] Loading Whisper base model...")
        _whisper_model = whisper.load_model("base")
        print("[JARVIS] Whisper ready")
    return _whisper_model


def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe WAV audio bytes using Whisper."""
    model = get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = model.transcribe(
            tmp_path, language="en", fp16=False,
            initial_prompt="Hey JARVIS, OK JARVIS, play radio, check my projects, Suomipop, Radio Nova, StockWatch",
        )
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)


# ── Voice corrections (same as voice_capture.py) ──

TRANSLATIONS = {}
TRANSLATIONS_FILE = Path("/mnt/d/Jarvis_vault/References/voice-translations.md")

def load_translations():
    global TRANSLATIONS
    try:
        with open(TRANSLATIONS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("|") and "|" in line[1:] and "Heard" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) == 2:
                        TRANSLATIONS[parts[0].lower()] = parts[1]
    except:
        pass

load_translations()


def correct_text(text: str) -> str:
    """Apply voice corrections from vault translations."""
    lower = text.lower()
    for heard, corrected in TRANSLATIONS.items():
        if heard in lower:
            lower = lower.replace(heard, corrected.lower())
    # Capitalize first letter
    return lower[0].upper() + lower[1:] if lower else text


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

        if path == "/api/file":
            # Serve a file from allowed paths (for generated images)
            from urllib.parse import parse_qs
            params = parse_qs(urlparse(self.path).query)
            file_path = params.get("path", [""])[0]
            target = Path(file_path).resolve()
            allowed = [str(VAULT_DIR.resolve()), str(Path("/mnt/e/coding").resolve())]
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
                ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif"}.get(ext[1:], "application/octet-stream")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
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
                    self._json_response({"lines": lines[-50:]})
                else:
                    self._json_response({"lines": []})
            except:
                self._json_response({"lines": []})
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
                write_file("settings_voice.txt", data["voice"])
            if "personality" in data:
                write_file("settings_personality.txt", data["personality"])
            self._json_response({"status": "ok"})
            return

        if path == "/api/state-override":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                if "state" in data:
                    write_file("state.txt", data["state"])
            except:
                pass
            self._json_response({"status": "ok"})
            return

        if path == "/api/transcribe":
            length = int(self.headers.get("Content-Length", 0))
            audio_bytes = self.rfile.read(length)
            try:
                text = transcribe_audio(audio_bytes)
                if text:
                    corrected = correct_text(text)
                    # Echo detection — check against last output
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
                self._json_response({"error": str(e)}, 500)
            return

        if path == "/api/input":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                text = data.get("text", "").strip()
            except json.JSONDecodeError:
                text = body.strip()

            if text and not text.startswith("__"):
                write_file("input.txt", text)
                self._json_response({"status": "ok", "input": text})
            elif text.startswith("__tts:"):
                # Speak without processing as command
                tts_text = text[6:]
                write_file("output.txt", tts_text)
                write_file("state.txt", "speaking")
                import threading
                def _speak_tts():
                    try:
                        safe = tts_text.replace("'", "''")
                        ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
                        subprocess.run(
                            [ps, "-Command",
                             f"Add-Type -AssemblyName System.Speech; "
                             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                             f"$s.Rate = 1; $s.Speak('{safe}')"],
                            timeout=15, capture_output=True,
                        )
                    except Exception:
                        pass
                    write_file("state.txt", "standby")
                threading.Thread(target=_speak_tts, daemon=True).start()
                self._json_response({"status": "ok", "tts": tts_text})
            elif text.startswith("__exec:"):
                # Execute safe system command (internal only)
                cmd = text[7:]
                # Whitelist: only allow specific commands
                allowed = ["pkill -f 'python3 main.py'", "pkill -f comfyui"]
                if cmd in allowed:
                    import threading
                    threading.Thread(
                        target=lambda: subprocess.run(cmd, shell=True, timeout=10, capture_output=True),
                        daemon=True,
                    ).start()
                    self._json_response({"status": "ok", "exec": cmd})
                else:
                    self._json_response({"status": "error", "message": "Command not allowed"}, 403)
            elif text.startswith("__"):
                self._json_response({"status": "ok", "internal": True})
            else:
                self._json_response({"status": "error", "message": "Empty input"}, 400)
            return

        self.send_error(404)

    def _json_response(self, data: dict, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
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
        print(f"[JARVIS HTTP] {args[0]}")


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", PORT), JarvisHandler)
    print(f"[JARVIS] HTTP server on http://localhost:{PORT}")
    print(f"[JARVIS] Serving HTML from {SCRIPTS_DIR}")
    print(f"[JARVIS] Bridge files at {BRIDGE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[JARVIS] Server stopped")
