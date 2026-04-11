#!/bin/bash
# ============================================================
# JARVIS OS — Single control script
# Usage: jarvis.sh start | stop | restart | status
# ============================================================

JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="/mnt/d/Jarvis_vault"
BRIDGE="/tmp/jarvis"
PIDFILE="$BRIDGE/jarvis.pids"
LOG="$VAULT/jarvis.log"

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

do_stop() {
  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — SHUTTING DOWN   ║"
  echo "╚══════════════════════════════════════╝"

  # Kill tracked PIDs
  if [ -f "$PIDFILE" ]; then
    while read -r pid name; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        log "Stopped $name (PID $pid)"
      fi
    done < "$PIDFILE"
    rm -f "$PIDFILE"
  fi

  # Kill by name as fallback
  pkill -f "watcher.sh" 2>/dev/null
  pkill -f "react_server.py" 2>/dev/null
  pkill -f "scripts/server.py" 2>/dev/null
  powershell.exe -Command 'Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue' 2>/dev/null

  # Reset bridge state
  mkdir -p "$BRIDGE"
  echo "standby" > "$BRIDGE/state.txt"
  echo "neutral" > "$BRIDGE/emotion.txt"
  > "$BRIDGE/input.txt"

  log "=== JARVIS OS OFFLINE ==="
  echo ""
  echo "  Systems offline. Goodbye, sir."
  echo ""
}

do_start() {
  # Kill anything lingering first
  pkill -f "watcher.sh" 2>/dev/null
  pkill -f "react_server.py" 2>/dev/null
  pkill -f "scripts/server.py" 2>/dev/null
  sleep 1

  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — BOOTING        ║"
  echo "╚══════════════════════════════════════╝"

  mkdir -p "$BRIDGE" "$VAULT/tts"
  > "$BRIDGE/input.txt"
  echo "standby" > "$BRIDGE/state.txt"
  echo "neutral" > "$BRIDGE/emotion.txt"
  > "$PIDFILE"

  # ── 1. Ollama ─────────────────────────────────────────────
  if ! pgrep -x ollama > /dev/null; then
    log "Starting Ollama serve..."
    ollama serve > /dev/null 2>&1 &
    sleep 2
  fi

  log "Loading qwen3:30b-a3b (main brain — permanent)..."
  ollama run qwen3:30b-a3b --keepalive -1 "" > /dev/null 2>&1 &
  echo "$! qwen3-main" >> "$PIDFILE"

  # Coder loads on demand (swaps with main when code keywords detected)
  # llama3.1:70b loads only on explicit "deep" requests (needs 42GB, will offload to CPU)

  sleep 2

  # ── 2. ReAct tool server (:7900) ──────────────────────────
  log "Starting ReAct tool server on :7900..."
  python3 -u "$JARVIS_DIR/scripts/react_server.py" > /tmp/react.log 2>&1 &
  echo "$! react-server" >> "$PIDFILE"
  sleep 2

  # ── 3. Watcher ────────────────────────────────────────────
  log "Starting watcher..."
  bash "$JARVIS_DIR/scripts/watcher.sh" &
  echo "$! watcher" >> "$PIDFILE"

  # ── 4. Browser bridge server (:4000) ──────────────────────
  log "Starting browser bridge on :4000..."
  python3 "$JARVIS_DIR/scripts/server.py" > /dev/null 2>&1 &
  echo "$! bridge-server" >> "$PIDFILE"

  # ── 5. Voice capture (always-on mic with wake word) ───────
  if python3 -c "import sounddevice" 2>/dev/null; then
    log "Starting voice capture (wake word mode)..."
    CUDA_VISIBLE_DEVICES="" python3 "$JARVIS_DIR/scripts/voice_capture.py" --wake > /tmp/jarvis-voice.log 2>&1 &
    echo "$! voice-capture" >> "$PIDFILE"
  else
    log "Voice capture skipped (install: pip install sounddevice soundfile numpy openai-whisper)"
  fi

  sleep 2

  # ── Summary ───────────────────────────────────────────────
  echo ""
  echo "╔══════════════════════════════════════╗"
  echo "║     JARVIS OS ONLINE                 ║"
  echo "║                                      ║"
  echo "║  Browser UI    → http://localhost:4000║"
  echo "║  ReAct tools   → http://localhost:7900║"
  echo "║  Fast model    → phi4:14b             ║"
  echo "║  Tool model    → qwen3:30b-a3b        ║"
  echo "║  Code model    → qwen3-coder:30b      ║"
  echo "║  Deep model    → llama3.1:70b          ║"
  echo "║  MemPalace     → 2241 memories         ║"
  echo "║  Skills        → 34 loaded             ║"
  echo "║  Tools         → 12 available          ║"
  echo "║  Audio         → Denon 5.1 (HDMI)      ║"
  echo "╚══════════════════════════════════════╝"
  echo ""
  log "All systems nominal. Good morning, sir."
}

do_status() {
  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — STATUS         ║"
  echo "╚══════════════════════════════════════╝"
  echo ""

  # Ollama
  if pgrep -x ollama > /dev/null; then
    echo "  ✓ Ollama serve"
    ollama ps 2>/dev/null | tail -n +2 | while read -r line; do
      echo "    $line"
    done
  else
    echo "  ✗ Ollama serve"
  fi

  # ReAct server
  if curl -sf --max-time 1 http://localhost:7900/api/health > /dev/null 2>&1; then
    echo "  ✓ ReAct server (:7900)"
  else
    echo "  ✗ ReAct server (:7900)"
  fi

  # Watcher
  if pgrep -f "watcher.sh" > /dev/null; then
    echo "  ✓ Watcher"
  else
    echo "  ✗ Watcher"
  fi

  # Bridge server
  if curl -sf --max-time 1 http://localhost:4000/api/state > /dev/null 2>&1; then
    echo "  ✓ Browser bridge (:4000)"
  else
    echo "  ✗ Browser bridge (:4000)"
  fi

  # Orpheus TTS
  if curl -sf --max-time 1 http://localhost:5100/health > /dev/null 2>&1; then
    echo "  ✓ Orpheus TTS (:5100)"
  else
    echo "  ○ Orpheus TTS (offline)"
  fi

  # GPU
  echo ""
  echo "  GPU:"
  nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r name temp util mem_used mem_total power; do
    echo "    $name | ${temp}°C | GPU ${util}% | VRAM ${mem_used}/${mem_total}MB | ${power}W"
  done

  # Bridge state
  echo ""
  echo "  State: $(cat $BRIDGE/state.txt 2>/dev/null || echo 'unknown')"
  echo "  Brain: $(cat $BRIDGE/brain.txt 2>/dev/null || echo 'none')"
  echo "  Last:  $(cat $BRIDGE/output.txt 2>/dev/null | head -1 | cut -c1-60)"
  echo ""
}

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; sleep 2; do_start ;;
  status)  do_status ;;
  *)
    echo "Usage: jarvis.sh {start|stop|restart|status}"
    echo ""
    echo "  start    Boot all JARVIS systems"
    echo "  stop     Shut down everything"
    echo "  restart  Stop then start"
    echo "  status   Show what's running"
    exit 1
    ;;
esac
