"""
JARVIS Twilio Webhook Server — Answers calls and SMS with AI.

Incoming call flow:
  1. Twilio POSTs to /voice
  2. JARVIS answers with greeting
  3. Caller speaks → Twilio transcribes via <Gather>
  4. Transcription POSTs to /voice/respond
  5. JARVIS processes through ReAct, sends TwiML <Say> response
  6. Loop until caller hangs up

Incoming SMS flow:
  1. Twilio POSTs to /sms
  2. JARVIS processes message through ReAct
  3. Sends reply via TwiML <Message>

Usage:
  python3 scripts/twilio_webhook.py [--port 5050]

Expose to internet:
  ngrok http 5050
  Set Twilio webhook to ngrok URL
"""

import json
import os
import sys
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
CONFIG_FILE = PROJECT_ROOT / "config" / "twilio.json"
CALL_LOG = VAULT_DIR / "Daily" / "calls"
SMS_LOG = VAULT_DIR / "Daily" / "sms"
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5050


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def process_with_jarvis(text: str, context: str = "") -> str:
    """Send text through cloud_react or ReAct for processing."""
    try:
        result = subprocess.run(
            ["python3", str(PROJECT_ROOT / "scripts" / "cloud_react.py"),
             "--provider", "anthropic",
             "--prompt", text,
             "--system", (
                 "You are JARVIS, an AI phone assistant. You are speaking to someone on the phone. "
                 "Be concise and natural — this will be spoken aloud. "
                 "Max 2 sentences. No markdown. Use tools if needed. "
                 f"{context}"
             )],
            capture_output=True, text=True, timeout=30,
        )
        response = result.stdout.strip()
        if response:
            return response
    except Exception:
        pass

    # Fallback: try Ollama via ReAct
    try:
        import urllib.request
        payload = json.dumps({
            "model": "qwen3:30b-a3b",
            "messages": [
                {"role": "system", "content": "You are JARVIS on the phone. Be concise. Max 2 sentences."},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://localhost:7900/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("message", {}).get("content", "I apologize, I'm having trouble processing that.")
    except Exception:
        return "I apologize, I'm having trouble processing that right now. Please try again."


def log_interaction(log_dir: Path, direction: str, number: str, text: str):
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = datetime.now().strftime("%Y-%m-%d")
    with open(log_dir / f"{date_str}.md", "a", encoding="utf-8") as f:
        f.write(f"\n## {ts} — {direction} {number}\n{text}\n")


class TwilioHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        params = parse_qs(body)

        # Helper to get single value
        def p(key):
            return params.get(key, [""])[0]

        if path == "/voice":
            # Incoming call — answer with greeting
            caller = p("From")
            log(f"Incoming call from {caller}")
            log_interaction(CALL_LOG, "INCOMING", caller, "Call started")

            cfg = load_config()
            greeting = cfg.get("greeting", "Hello, this is JARVIS. How may I assist you?")

            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{greeting}</Say>
    <Gather input="speech" action="/voice/respond" speechTimeout="3" language="en-US">
        <Say voice="alice">Please go ahead.</Say>
    </Gather>
    <Say voice="alice">I didn't hear anything. Goodbye.</Say>
</Response>"""
            self._twiml_response(twiml)

        elif path == "/voice/respond":
            # Caller said something — process and respond
            speech = p("SpeechResult")
            caller = p("From")
            confidence = p("Confidence")

            log(f"Caller ({caller}): {speech} (confidence: {confidence})")
            log_interaction(CALL_LOG, "CALLER", caller, speech)

            # Process with JARVIS
            response = process_with_jarvis(speech, f"Caller number: {caller}")
            log(f"JARVIS: {response}")
            log_interaction(CALL_LOG, "JARVIS", caller, response)

            # Continue conversation
            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">{response}</Say>
    <Gather input="speech" action="/voice/respond" speechTimeout="3" language="en-US">
        <Say voice="alice">Is there anything else?</Say>
    </Gather>
    <Say voice="alice">Thank you for calling. Goodbye.</Say>
</Response>"""
            self._twiml_response(twiml)

        elif path == "/sms":
            # Incoming SMS
            sender = p("From")
            body_text = p("Body")

            log(f"SMS from {sender}: {body_text}")
            log_interaction(SMS_LOG, "INCOMING", sender, body_text)

            # Process with JARVIS
            response = process_with_jarvis(
                body_text,
                f"This is an SMS from {sender}. Reply concisely.",
            )
            log(f"JARVIS reply: {response}")
            log_interaction(SMS_LOG, "REPLY", sender, response)

            twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{response}</Message>
</Response>"""
            self._twiml_response(twiml)

        elif path == "/status":
            # Health check
            self._twiml_response(json.dumps({"status": "ok", "service": "jarvis-twilio"}),
                                  content_type="application/json")

        else:
            self.send_error(404)

    def do_GET(self):
        if urlparse(self.path).path == "/status":
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def _twiml_response(self, twiml: str, content_type: str = "text/xml"):
        body = twiml.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), TwilioHandler)
    log(f"Twilio webhook server on http://0.0.0.0:{PORT}")
    log("Endpoints:")
    log(f"  POST /voice     — Incoming call handler")
    log(f"  POST /voice/respond — Speech response handler")
    log(f"  POST /sms       — Incoming SMS handler")
    log(f"  GET  /status    — Health check")
    log("")
    log("To expose: ngrok http 5050")
    log("Set Twilio webhook: https://YOUR-NGROK.ngrok.io/voice")
    log("Set Twilio SMS webhook: https://YOUR-NGROK.ngrok.io/sms")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped")
