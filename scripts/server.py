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
