"""
JARVIS Skill — Countdown timers with TTS alerts.
"""

import subprocess
import threading
import time
from pathlib import Path

SKILL_NAME = "timer"
SKILL_DESCRIPTION = "Countdown timers with voice alerts"

VAULT_DIR = Path("D:/Jarvis_vault") if __import__("os").name == "nt" else Path("/mnt/d/Jarvis_vault")
BRIDGE_DIR = Path("/tmp/jarvis")

ACTIVE_TIMERS = []


def _timer_callback(message: str, timer_id: int):
    """Called when a timer fires — speaks directly, bypasses LLM."""
    alert = f"Sir, your timer has gone off. {message}"
    try:
        (BRIDGE_DIR / "output.txt").write_text(alert)
        (BRIDGE_DIR / "state.txt").write_text("speaking")
        (BRIDGE_DIR / "emotion.txt").write_text("neutral")

        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        with open(VAULT_DIR / "jarvis.log", "a") as f:
            f.write(f"[{ts}] TIMER ALERT: {message}\n")

        safe = message.replace("'", "''")
        subprocess.Popen(
            ['powershell.exe', '-Command',
             f"Add-Type -AssemblyName System.Speech; "
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             f"$s.Rate = 0; $s.Speak('Sir, your timer has gone off. {safe}')"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[TIMER] Timer {timer_id} fired: {message}")
    except Exception as e:
        print(f"[TIMER] Error: {e}")

    def reset_state():
        time.sleep(5)
        try:
            (BRIDGE_DIR / "state.txt").write_text("standby")
        except:
            pass

    threading.Thread(target=reset_state, daemon=True).start()
    ACTIVE_TIMERS[:] = [t for t in ACTIVE_TIMERS if t["id"] != timer_id]


def exec_set_timer(minutes: float, message: str) -> str:
    seconds = int(float(minutes) * 60)
    timer_id = len(ACTIVE_TIMERS) + 1
    t = threading.Timer(seconds, _timer_callback, args=[message, timer_id])
    t.daemon = True
    t.start()
    ACTIVE_TIMERS.append({
        "id": timer_id, "message": message,
        "seconds": seconds, "start": time.time(), "timer": t,
    })

    if minutes < 1:
        time_str = f"{seconds} seconds"
    elif minutes == int(minutes):
        time_str = f"{int(minutes)} minute{'s' if minutes != 1 else ''}"
    else:
        time_str = f"{minutes} minutes"

    return f"Timer set: {message} in {time_str}. Do not ask follow-up questions about timers."


def get_active_timers() -> list:
    """Return active timers for the API."""
    now = time.time()
    return [
        {"id": t["id"], "message": t["message"],
         "remaining": int(t["seconds"] - (now - t["start"])),
         "total": t["seconds"]}
        for t in ACTIVE_TIMERS
        if t["seconds"] - (now - t["start"]) > 0
    ]


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a countdown timer or alarm. When it goes off, JARVIS speaks the message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "number",
                        "description": "Minutes from now (e.g. 5, 0.5 for 30 seconds, 60 for 1 hour)",
                    },
                    "message": {
                        "type": "string",
                        "description": "What to say when timer goes off",
                    },
                },
                "required": ["minutes", "message"],
            },
        },
    },
]

TOOL_MAP = {"set_timer": exec_set_timer}

KEYWORDS = {
    "set_timer": ["timer", "alarm", "remind", "minutes", "seconds", "wake me", "alert me", "countdown"],
}
