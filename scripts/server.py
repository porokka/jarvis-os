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
import sys
from pathlib import Path
from urllib.parse import urlparse

JARVIS_DIR = Path(__file__).resolve().parent.parent
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 4000


def read_file(name: str) -> str:
    path = JARVIS_DIR / name
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def write_file(name: str, content: str):
    (JARVIS_DIR / name).write_text(content, encoding="utf-8")


class JarvisHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(JARVIS_DIR / "scripts"), **kwargs)

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
            }
            self._json_response(data)
            return

        if path == "/api/output":
            self._json_response({"output": read_file("output.txt")})
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/input":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                text = data.get("text", "").strip()
            except json.JSONDecodeError:
                text = body.strip()

            if text:
                write_file("input.txt", text)
                self._json_response({"status": "ok", "input": text})
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
    print(f"[JARVIS] Serving from {JARVIS_DIR / 'scripts'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[JARVIS] Server stopped")
