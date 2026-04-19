#!/bin/bash
# ============================================================
# JARVIS OS — Single control script
# Usage: bash jarvis.sh start | stop | restart | status
# ============================================================

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_DIR="/mnt/d/Jarvis_vault"
BRIDGE_DIR="/tmp/jarvis"
PIDFILE="$BRIDGE_DIR/jarvis.pids"
LOG="$VAULT_DIR/jarvis.log"
MODEL_CONFIG="$PROJECT_DIR/config/models-config.json"
SKILLS_CONFIG="$PROJECT_DIR/config/skills.json"
export OLLAMA_MODELS="/mnt/e/ollama_models"
OLLAMA_HOST="http://127.0.0.1:11434"
REACT_HOST="http://127.0.0.1:7900"
BROWSER_HOST="http://127.0.0.1:4000"

export OLLAMA_MODELS
export OLLAMA_HOST

mkdir -p "$VAULT_DIR" "$VAULT_DIR/tts" "$BRIDGE_DIR"
touch "$LOG"

log() {
  echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"
}

load_models_from_config() {
  eval "$(
    python3 - "$MODEL_CONFIG" <<'PY'
import json, shlex, sys
from pathlib import Path

cfg = Path(sys.argv[1])
defaults = {
    'fast': 'qwen3:8b',
    'reason': 'qwen3:14b',
    'code': 'qwen3-coder:14b',
    'deep': 'qwen3:30b-a3b',
}

try:
    data = json.loads(cfg.read_text(encoding='utf-8'))
    models = data.get('models', {}) if isinstance(data, dict) else {}
except Exception:
    models = {}

for key in ['fast', 'reason', 'code', 'deep']:
    value = models.get(key, defaults[key])
    print(f"OLLAMA_{key.upper()}={shlex.quote(value)}")
PY
  )"
}
load_models_from_config
get_mem_count() {
  local count
  count=$(mempalace status 2>/dev/null | grep -m1 -oE '[0-9]+ drawers' | grep -oE '[0-9]+')
  echo "${count:-?}"
}

get_skill_count() {
  python3 - "$SKILLS_CONFIG" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    enabled = data.get('enabled', {}) if isinstance(data, dict) else {}
    print(sum(1 for v in enabled.values() if v))
except Exception:
    print('?')
PY
}

get_tool_count() {
  local count
  count=$(curl -sf --max-time 2 "$REACT_HOST/api/skills" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("tools", [])))' 2>/dev/null)
  echo "${count:-?}"
}

reset_bridge_state() {
  mkdir -p "$BRIDGE_DIR"
  echo "standby" > "$BRIDGE_DIR/state.txt"
  echo "neutral" > "$BRIDGE_DIR/emotion.txt"
  : > "$BRIDGE_DIR/input.txt"
}

stop_pidfile_processes() {
  if [ -f "$PIDFILE" ]; then
    while read -r pid name; do
      [ -z "${pid:-}" ] && continue
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        log "Stopped $name (PID $pid)"
      fi
    done < "$PIDFILE"
    rm -f "$PIDFILE"
  fi
}

stop_named_processes() {
  pkill -f "watcher.sh" 2>/dev/null || true
  pkill -f "react_server.py" 2>/dev/null || true
  pkill -f "scripts/server.py" 2>/dev/null || true
  pkill -f "voice_capture.py" 2>/dev/null || true
  powershell.exe -Command 'Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue' 2>/dev/null || true

  # Ollama may be running under another user/service.
  sudo pkill -f "/usr/local/bin/ollama serve" 2>/dev/null || true
  sudo pkill -f "/usr/local/bin/ollama runner" 2>/dev/null || true
}

ensure_ollama() {
  if curl -sf --max-time 1 "$OLLAMA_HOST/" >/dev/null 2>&1; then
    log "Ollama already responding on $OLLAMA_HOST"
    return 0
  fi

  log "Starting Ollama serve with models at $OLLAMA_MODELS"
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  local pid=$!
  echo "$pid ollama-serve" >> "$PIDFILE"

  for _ in $(seq 1 20); do
    if curl -sf --max-time 1 "$OLLAMA_HOST/" >/dev/null 2>&1; then
      log "Ollama online"
      return 0
    fi
    sleep 1
  done

  log "WARN: Ollama did not come online in time"
  return 1
}

preload_model() {
  
  local model="$1"
  [ -z "$model" ] && return 0

  log "Preloading model=$model via $OLLAMA_HOST"

  local response
  response=$(curl -sS --max-time 240 "$OLLAMA_HOST/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":-1,\"stream\":false}" \
    2>&1)
  local exit_code=$?

  if [ $exit_code -ne 0 ]; then
    log "WARN: preload curl failed for $model (exit=$exit_code)"
    log "WARN: preload curl output: $response"
    return 1
  fi

  log "Preload response for $model: $(echo "$response" | head -c 300)"
  return 0
}

print_summary() {
  local mem_count skill_count tool_count
  mem_count=$(get_mem_count)
  skill_count=$(get_skill_count)
  tool_count=$(get_tool_count)
  
  echo ""
  echo "╔══════════════════════════════════════════════╗"
  echo "║     JARVIS OS ONLINE                         ║"
  echo "║                                              ║"
  echo "║  Browser UI    → http://localhost:4000       ║"
  echo "║  ReAct tools   → http://localhost:7900       ║"
  printf "║  Fast model    → %-28s ║\n" "$OLLAMA_FAST"
  printf "║  Tool model    → %-28s ║\n" "$OLLAMA_REASON"
  printf "║  Code model    → %-28s ║\n" "$OLLAMA_CODE"
  printf "║  Deep model    → %-28s ║\n" "$OLLAMA_DEEP"
  printf "║  MemPalace     → %-28s ║\n" "$mem_count drawers"
  printf "║  Skills        → %-28s ║\n" "$skill_count loaded"
  printf "║  Tools         → %-28s ║\n" "$tool_count available"
  echo "║  Audio         → Denon 5.1 (HDMI)            ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""
}

do_stop() {
  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — SHUTTING DOWN   ║"
  echo "╚══════════════════════════════════════╝"

  stop_pidfile_processes
  stop_named_processes
  reset_bridge_state

  log "=== JARVIS OS OFFLINE ==="
  echo ""
  echo "  Systems offline. Goodbye, sir."
  echo ""
}

do_start() {
  load_models_from_config

  stop_named_processes
  sleep 1

  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — BOOTING         ║"
  echo "╚══════════════════════════════════════╝"

  mkdir -p "$BRIDGE_DIR" "$VAULT_DIR/tts"
  reset_bridge_state
  : > "$PIDFILE"

  ensure_ollama || true
  preload_model "$OLLAMA_FAST"

  log "Starting ReAct tool server on :7900"
  python3 -u "$PROJECT_DIR/scripts/react_server.py" > /tmp/react.log 2>&1 &
  echo "$! react-server" >> "$PIDFILE"
  sleep 2

  log "Starting watcher"
  bash "$PROJECT_DIR/scripts/watcher.sh" > /tmp/watcher.log 2>&1 &
  echo "$! watcher" >> "$PIDFILE"

  log "Starting browser bridge on :4000"
  python3 "$PROJECT_DIR/scripts/server.py" > /tmp/jarvis-browser.log 2>&1 &
  echo "$! bridge-server" >> "$PIDFILE"

  if python3 -c "import sounddevice" 2>/dev/null; then
    log "Starting voice capture (wake word mode)"
    CUDA_VISIBLE_DEVICES="" python3 "$PROJECT_DIR/scripts/voice_capture.py" --wake > /tmp/jarvis-voice.log 2>&1 &
    echo "$! voice-capture" >> "$PIDFILE"
  else
    log "Voice capture skipped (install: pip install sounddevice soundfile numpy openai-whisper)"
  fi

  sleep 2
  print_summary
  log "All systems nominal. Good morning, sir."
}

do_status() {
  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — STATUS          ║"
  echo "╚══════════════════════════════════════╝"
  echo ""

  if pgrep -f "/usr/local/bin/ollama serve|ollama serve" > /dev/null; then
    echo "  ✓ Ollama serve"
    ollama ps 2>/dev/null | tail -n +2 | while read -r line; do
      echo "    $line"
    done
  else
    echo "  ✗ Ollama serve"
  fi

  if curl -sf --max-time 1 "$REACT_HOST/api/health" > /dev/null 2>&1; then
    echo "  ✓ ReAct server (:7900)"
  else
    echo "  ✗ ReAct server (:7900)"
  fi

  if pgrep -f "watcher.sh" > /dev/null; then
    echo "  ✓ Watcher"
  else
    echo "  ✗ Watcher"
  fi

  if curl -sf --max-time 1 "$BROWSER_HOST/api/state" > /dev/null 2>&1; then
    echo "  ✓ Browser bridge (:4000)"
  else
    echo "  ✗ Browser bridge (:4000)"
  fi

  if curl -sf --max-time 1 http://localhost:5100/health > /dev/null 2>&1; then
    echo "  ✓ Orpheus TTS (:5100)"
  else
    echo "  ○ Orpheus TTS (offline)"
  fi

  echo ""
  echo "  GPU:"
  nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r name temp util mem_used mem_total power; do
    echo "    $name | ${temp}°C | GPU ${util}% | VRAM ${mem_used}/${mem_total}MB | ${power}W"
  done

  echo ""
  echo "  State: $(cat "$BRIDGE_DIR/state.txt" 2>/dev/null || echo 'unknown')"
  echo "  Brain: $(cat "$BRIDGE_DIR/brain.txt" 2>/dev/null || echo 'none')"
  echo "  Last:  $(cat "$BRIDGE_DIR/output.txt" 2>/dev/null | head -1 | cut -c1-60)"
  echo ""
}

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; sleep 2; do_start ;;
  status)  do_status ;;
  *)
    echo "Usage: bash jarvis.sh {start|stop|restart|status}"
    echo ""
    echo "  start    Boot all JARVIS systems"
    echo "  stop     Shut down everything"
    echo "  restart  Stop then start"
    echo "  status   Show what's running"
    exit 1
    ;;
esac
