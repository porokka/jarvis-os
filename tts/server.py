"""
Orpheus TTS Server — Local HTTP API

Endpoints:
  POST /v1/audio/speech    → OpenAI-compatible TTS endpoint
  POST /speak              → Simple text-to-speech, returns WAV
  GET  /voices             → List available voices
  GET  /health             → Server health check

Usage: python tts/server.py [--port 5100] [--voice tara] [--gpu-layers -1]
"""

import argparse
import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from engine import OrpheusEngine, SAMPLE_RATE

VOICES = ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]
EMOTIONS = ["<laugh>", "<chuckle>", "<sigh>", "<gasp>", "<yawn>", "<groan>", "<cough>", "<sniffle>"]

engine: OrpheusEngine | None = None


class TTSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._json({"status": "ok", "model": "orpheus-3b-q4_k_m", "voice": engine.voice})
            return

        if path == "/voices":
            self._json({"voices": VOICES, "emotions": EMOTIONS})
            return

        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/speak":
            self._handle_speak(body)
            return

        if path == "/v1/audio/speech":
            self._handle_openai_speech(body)
            return

        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _handle_speak(self, body: dict):
        """Simple speak endpoint: { text, voice?, save_path? }"""
        text = body.get("text", "").strip()
        if not text:
            self._json({"error": "No text provided"}, 400)
            return

        voice = body.get("voice", engine.voice)
        old_voice = engine.voice
        engine.voice = voice

        start = time.time()
        wav_bytes = engine.synthesize_to_bytes(text)
        elapsed = time.time() - start

        engine.voice = old_voice

        # Optionally save to file
        save_path = body.get("save_path")
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(wav_bytes)

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self.send_header("X-Generation-Time", f"{elapsed:.2f}s")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(wav_bytes)

    def _handle_openai_speech(self, body: dict):
        """OpenAI-compatible /v1/audio/speech endpoint."""
        text = body.get("input", "").strip()
        voice = body.get("voice", engine.voice)

        if not text:
            self._json({"error": {"message": "No input provided"}}, 400)
            return

        if voice not in VOICES:
            voice = engine.voice

        old_voice = engine.voice
        engine.voice = voice

        wav_bytes = engine.synthesize_to_bytes(text)

        engine.voice = old_voice

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(wav_bytes)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw}

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format, *args):
        print(f"[TTS] {args[0]}")


def main():
    global engine

    parser = argparse.ArgumentParser(description="Orpheus TTS Server")
    parser.add_argument("--port", type=int, default=5100)
    parser.add_argument("--voice", default="tara", choices=VOICES)
    parser.add_argument("--gpu-layers", type=int, default=-1, help="-1 = all layers on GPU")
    parser.add_argument("--model", type=str, default=None, help="Path to GGUF model")
    args = parser.parse_args()

    print("=" * 50)
    print("Orpheus TTS Server — Operation Jarvis")
    print("=" * 50)

    engine = OrpheusEngine(
        model_path=args.model,
        n_gpu_layers=args.gpu_layers,
        voice=args.voice,
    )

    server = HTTPServer(("127.0.0.1", args.port), TTSHandler)
    print(f"[TTS] Server running on http://localhost:{args.port}")
    print(f"[TTS] Voice: {args.voice}")
    print(f"[TTS] Endpoints:")
    print(f"  POST /speak          — Simple TTS")
    print(f"  POST /v1/audio/speech — OpenAI-compatible")
    print(f"  GET  /voices         — List voices")
    print(f"  GET  /health         — Health check")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[TTS] Server stopped")


if __name__ == "__main__":
    main()
