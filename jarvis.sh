#!/bin/bash
# ============================================================
# JARVIS OS — Single control script
# Usage: bash jarvis.sh start | stop | restart | status
# ============================================================

set -u

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_DIR="/mnt/d/Jarvis_vault"
BRIDGE_DIR="/tmp/jarvis"
LOG_DIR='/tmp/'
PIDFILE="$BRIDGE_DIR/jarvis.pids"
LOG="$VAULT_DIR/jarvis.log"
MODEL_CONFIG="$PROJECT_DIR/config/models-config.json"
SKILLS_CONFIG="$PROJECT_DIR/config/skills.json"
export OLLAMA_MODELS="/mnt/e/ollama_models"
OLLAMA_HOST="http://127.0.0.1:11434"
REACT_HOST="http://127.0.0.1:7900"
BROWSER_HOST="http://127.0.0.1:4000"
LLAMA_CPP_HOST="http://127.0.0.1:8091"
STAGING_ROOT="${JARVIS_STAGING:-/mnt/e/coding/staging}"
source "$PROJECT_DIR/scripts/n8n.sh"
export OLLAMA_MODELS
export OLLAMA_HOST

mkdir -p "$VAULT_DIR" "$VAULT_DIR/tts" "$BRIDGE_DIR"
touch "$LOG"

log() {
  echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"
}
set -a
source /mnt/e/coding/jarvis-os/.env
set +a
LLAMA_SERVER_CMD="$PROJECT_DIR/../llama.cpp/build/bin/llama-server"
LLAMA_MODEL="/mnt/e/models/gemma4-e4b/gemma-4-E4B-it-UD-Q4_K_XL.gguf"
LLAMA_MMPROJ="/mnt/e/models/gemma4-e4b/mmproj-BF16.gguf"
LLAMA_PORT="8091"

# ── GPU auto-assignment ───────────────────────────────────────────────────────
# Decide, from live VRAM, which GPU each inference service runs on. Sets:
#   JARVIS_VISION_GPU_UUID / JARVIS_OLLAMA_GPU_UUID  → CUDA_VISIBLE_DEVICES pins
#   JARVIS_VISION_STOP  → 0 when vision has its own GPU (broker won't stop it)
# Pins are UUIDs so they survive CUDA index reshuffles when GPUs change.

assign_gpus() {
  local shell_out
  shell_out="$(python3 "$PROJECT_DIR/scripts/gpu_assign.py" --shell 2>/dev/null)"
  if [ -n "$shell_out" ]; then
    eval "$shell_out"
    export JARVIS_VISION_GPU_UUID JARVIS_OLLAMA_GPU_UUID JARVIS_VISION_STOP
    log "GPU assignment: vision=${JARVIS_VISION_GPU_UUID:-all} ollama=${JARVIS_OLLAMA_GPU_UUID:-all} vision_stop=${JARVIS_VISION_STOP:-1}"
    python3 "$PROJECT_DIR/scripts/gpu_assign.py" 2>/dev/null | tee -a "$LOG"
  else
    log "GPU assignment skipped (gpu_assign.py produced no output; using default GPU selection)"
  fi
}

# ── llama-server ──────────────────────────────────────────────────────────────

start_llama_server() {
  if pgrep -f "llama-server.*--port ${LLAMA_PORT}" >/dev/null 2>&1; then
    log "llama-server already running on port ${LLAMA_PORT}"
    return
  fi
  log "Starting llama-server on port ${LLAMA_PORT} (GPU=${JARVIS_VISION_GPU_UUID:-all})..."
  # Only pin when we have a UUID. An EMPTY CUDA_VISIBLE_DEVICES means CPU-only, so
  # when unset we must not export it at all — `env` with no assignment is a no-op.
  local cuda_pin=()
  [ -n "${JARVIS_VISION_GPU_UUID:-}" ] && cuda_pin=("CUDA_VISIBLE_DEVICES=${JARVIS_VISION_GPU_UUID}")
  nohup env "${cuda_pin[@]}" ${LLAMA_SERVER_CMD} \
    --model "${LLAMA_MODEL}" \
    --mmproj "${LLAMA_MMPROJ}" \
    --n-gpu-layers 99 \
    --ctx-size 8192 \
    --port "${LLAMA_PORT}" \
    > /tmp/jarvis_llama_server.log 2>&1 &
  echo $! > /tmp/jarvis_llama_server.pid
}

stop_llama_server() {
  log "Stopping llama-server..."
  if [ -f /tmp/jarvis_llama_server.pid ]; then
    kill "$(cat /tmp/jarvis_llama_server.pid)" 2>/dev/null || true
    rm -f /tmp/jarvis_llama_server.pid
  fi
  pkill -f "llama-server.*--port ${LLAMA_PORT}" 2>/dev/null || true
}

# ── Qdrant ────────────────────────────────────────────────────────────────────

start_qdrant() {
  if pgrep -f "qdrant" >/dev/null 2>&1; then
    log "Qdrant already running"
    return
  fi
  log "Starting qdrant on :6333"
  podman run -d \
    --name qdrant \
    -p 6333:6333 \
    -v /mnt/d/Jarvis_vault/qdrant_storage:/qdrant/storage \
    qdrant/qdrant:latest > /tmp/qdrant.log 2>&1
  sleep 2
  if curl -s http://127.0.0.1:6333 >/dev/null; then
    log "Qdrant started successfully"
  else
    log "WARNING: Qdrant failed to start"
  fi
}

stop_qdrant() {
  log "Stopping qdrant"
  podman stop qdrant >/dev/null 2>&1
  podman rm qdrant >/dev/null 2>&1
}

# ── Redis ─────────────────────────────────────────────────────────────────────

start_redis() {
  log "Starting Redis..."
  if podman ps --format '{{.Names}}' | grep -q '^jarvis-redis$'; then
    log "Redis already running"
    return
  fi
  if podman ps -a --format '{{.Names}}' | grep -q '^jarvis-redis$'; then
    podman start jarvis-redis
  else
    podman run -d \
      --name jarvis-redis \
      -p 6379:6379 \
      -v jarvis_redis:/data \
      docker.io/library/redis:7  \
      redis-server --appendonly yes
  fi
  # Wait for Redis to be ready
  for _ in $(seq 1 10); do
    if redis-cli ping >/dev/null 2>&1; then
      log "Redis ready"
      return
    fi
    sleep 1
  done
  log "WARNING: Redis may not be ready yet"
}

stop_redis() {
  log "Stopping Redis..."
  if podman ps --format '{{.Names}}' | grep -q '^jarvis-redis$'; then
    podman stop jarvis-redis
    log "Redis stopped"
  else
    log "Redis not running"
  fi
}

# ── Kokoro TTS ────────────────────────────────────────────────────────────────

start_kokoro() {
  if pgrep -f "kokoro_server.py" >/dev/null; then
    log "Kokoro already running"
    return
  fi
  log "Starting Kokoro TTS..."
  nohup python3 "$PROJECT_DIR/scripts/kokoro_server.py" \
    > "$LOG_DIR/kokoro.log" 2>&1 &
  sleep 2
  if pgrep -f "kokoro_server.py" >/dev/null; then
    log "Kokoro started"
  else
    log "WARNING: Kokoro failed to start"
  fi
}

stop_kokoro() {
  log "Stopping Kokoro..."
  pkill -f "kokoro_server.py" || true
}

# ── Plan runner (Redis task consumer) ────────────────────────────────────────

start_plan_runner() {
  if pgrep -f "plan_runner.py" >/dev/null; then
    log "Plan runner already running"
    return
  fi
  log "Starting plan runner (Redis task consumer)..."
  nohup python3 -u "$PROJECT_DIR/scripts/plan_runner.py" \
    > /tmp/plan_runner.log 2>&1 &
  echo "$! plan-runner" >> "$PIDFILE"
  sleep 1
  if pgrep -f "plan_runner.py" >/dev/null; then
    log "Plan runner started"
  else
    log "WARNING: Plan runner failed to start — check /tmp/plan_runner.log"
  fi
}

stop_plan_runner() {
  pkill -f "plan_runner.py" 2>/dev/null || true
}

# ── Staging workspace ─────────────────────────────────────────────────────────

start_staging() {
  log "Initialising staging workspace at $STAGING_ROOT..."
  mkdir -p "$STAGING_ROOT/dev" "$STAGING_ROOT/tested" "$STAGING_ROOT/approved"
  export JARVIS_STAGING="$STAGING_ROOT"
  log "Staging ready"
}

# ── MPV ───────────────────────────────────────────────────────────────────────

start_mpv() {
  mkdir -p /tmp/jarvis
  log "Starting MPV IPC server..."
  powershell.exe -NoProfile -Command \
    "Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue" \
    >/tmp/jarvis/mpv.log 2>&1 || true
  sleep 1
  powershell.exe -NoProfile -Command \
    "Start-Process -FilePath 'C:\Program Files\MPV Player\mpv.exe' \
     -ArgumentList '--idle=yes','--force-window=no','--input-ipc-server=\\.\pipe\jarvis-mpv' \
     -WindowStyle Hidden"
  sleep 2
  if powershell.exe -NoProfile -Command "Test-Path '\\.\pipe\jarvis-mpv'" | grep -qi True; then
    log "MPV started with IPC pipe"
  else
    log "WARNING: MPV failed to create IPC pipe"
  fi
}

stop_mpv() {
  powershell.exe -NoProfile -Command "Stop-Process -Name mpv -Force" 2>/dev/null || true
}

# ── Model config ──────────────────────────────────────────────────────────────

load_models_from_config() {
  eval "$(
    python3 - "$MODEL_CONFIG" <<'PY'
import json, shlex, sys
from pathlib import Path
cfg = Path(sys.argv[1])
defaults = {
    'fast': 'qwen3:14b', 'tools': 'qwen3:14b', 'reason': 'qwen3:14b',
    'code': 'qwen3.6:27b', 'deep': 'qwen3.6:27b',
}
try:
    data = json.loads(cfg.read_text(encoding='utf-8'))
    models = data.get('models', {}) if isinstance(data, dict) else {}
except Exception:
    models = {}
for key in ['fast', 'tools', 'reason', 'code', 'deep']:
    value = models.get(key, defaults[key])
    print(f"OLLAMA_{key.upper()}={shlex.quote(value)}")
PY
  )"
}

# ── Status helpers ────────────────────────────────────────────────────────────

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

# ── Ollama ────────────────────────────────────────────────────────────────────

ensure_ollama() {
  if curl -sf --max-time 1 "$OLLAMA_HOST/" >/dev/null 2>&1; then
    log "Ollama already responding on $OLLAMA_HOST"
    return 0
  fi
  log "Starting Ollama serve with models at $OLLAMA_MODELS (GPU=${JARVIS_OLLAMA_GPU_UUID:-all})"
  # Sane default keep_alive: warm but evictable. A hidden/legacy -1 ("Forever")
  # pins models and wedges the GPU (agent-loop ollama timeouts, 2026-07-12).
  export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"
  # Pin to the assigned GPU (UUID). Empty CUDA_VISIBLE_DEVICES = CPU-only, so only
  # export it when we actually have a pin; `env` with no assignment is a no-op.
  local cuda_pin=()
  [ -n "${JARVIS_OLLAMA_GPU_UUID:-}" ] && cuda_pin=("CUDA_VISIBLE_DEVICES=${JARVIS_OLLAMA_GPU_UUID}")
  nohup env "${cuda_pin[@]}" ollama serve > /tmp/ollama.log 2>&1 &
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

init_redis_save_qdrant() {
  log "Loading last session snapshot into Qdrant..."
  python3 -c "
import sys, json, pathlib, datetime
sys.path.insert(0, '$PROJECT_DIR')

snapshot_dir = pathlib.Path('$VAULT_DIR/snapshots')
if not snapshot_dir.exists():
    print('[MEMORY] No snapshots dir yet, skipping')
    sys.exit(0)

snapshots = sorted(snapshot_dir.glob('session_*.json'))
if not snapshots:
    print('[MEMORY] No snapshots found, skipping')
    sys.exit(0)

latest = snapshots[-1]
data = json.loads(latest.read_text())
print(f'[MEMORY] Loading snapshot: {latest.name}')

lines = []
if data.get('task'):
    lines.append(f\"Last task: {data['task']}\")
for step in data.get('steps', []):
    lines.append(f\"Step: {step}\")
for item in data.get('working_memory', []):
    lines.append(f\"Memory: {item}\")
if data.get('snapshot_at'):
    lines.append(f\"Session ended: {data['snapshot_at']}\")

if not lines:
    print('[MEMORY] Snapshot empty, skipping')
    sys.exit(0)

text = '\n'.join(lines)
import requests, uuid
embed_resp = requests.post('http://127.0.0.1:11434/api/embeddings', json={
    'model': 'nomic-embed-text', 'prompt': text
}, timeout=30)

if embed_resp.status_code != 200:
    print(f'[MEMORY] Embedding failed: {embed_resp.status_code}, skipping')
    sys.exit(0)

embedding = embed_resp.json()['embedding']

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
q = QdrantClient(host='127.0.0.1', port=6333)
collection = 'jarvis_sessions'
existing = [c.name for c in q.get_collections().collections]
if collection not in existing:
    q.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=len(embedding), distance=Distance.COSINE)
    )
q.upsert(
    collection_name=collection,
    points=[PointStruct(
        id=str(uuid.uuid4()),
        vector=embedding,
        payload={
            'source': latest.name, 'task': data.get('task', ''),
            'steps': data.get('steps', []), 'loop_count': data.get('loop_count', 0),
            'snapshot_at': data.get('snapshot_at', ''), 'text': text
        }
    )]
)
print(f'[MEMORY] Stored in Qdrant collection: {collection}')
print(f'[MEMORY] {len(lines)} memory items embedded')
" 2>/dev/null || log "WARN: Snapshot ingestion failed (non-fatal)"
}

preload_model() {
  local model="$1"
  [ -z "$model" ] && return 0
  log "Preloading model=$model"
  local response
  response=$(curl -sS --max-time 240 "$OLLAMA_HOST/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":\"30m\",\"stream\":false}" \
    2>&1)
  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    log "WARN: preload curl failed for $model (exit=$exit_code)"
    return 1
  fi
  log "Preloaded: $model"
  return 0
}

# ── Telegram watcher ──────────────────────────────────────────────────────────

telegram_watcher() {
  pkill -9 -f telegram_watcher.py 2>/dev/null
  sleep 1
  cd "$PROJECT_DIR" || return 1
  set -a
  [ -f "$PROJECT_DIR/.env" ] && source "$PROJECT_DIR/.env"
  set +a
  nohup python3 -u "$PROJECT_DIR/scripts/telegram_watcher.py" \
    > /tmp/telegram_watcher.log 2>&1 &
  echo "$! telegram-watcher" >> "$PIDFILE"
}

# ── Dictation daemon ──────────────────────────────────────────────────────────

dictation_daemon() {
  cd "$PROJECT_DIR" || return 1
  set -a
  [ -f "$PROJECT_DIR/.env" ] && source "$PROJECT_DIR/.env"
  set +a
  "$PROJECT_DIR/orpheus_env/bin/python" -u \
    "$PROJECT_DIR/services/dictation_daemon.py" \
    --host 127.0.0.1 \
    --port 5110 \
    > /tmp/dictation_daemon.log 2>&1 &
  echo "$! dictation-daemon" >> "$PIDFILE"
}

# ── Shutdown helpers ──────────────────────────────────────────────────────────

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
  log "Stopping named processes..."
  stop_plan_runner
  stop_llama_server
  stop_qdrant
  stop_kokoro
  stop_redis
  VAULT_DIR="$VAULT_DIR" python3 "$PROJECT_DIR/scripts/redis_snapshot.py" 2>/dev/null || true
  pkill -f "watcher.sh" 2>/dev/null || true
  pkill -f "react_server.py" 2>/dev/null || true
  pkill -f "scripts/server.py" 2>/dev/null || true
  pkill -f "voice_capture.py" 2>/dev/null || true
  pkill -f "dictation_daemon.py" 2>/dev/null || true
  pkill -f "plan_runner.py" 2>/dev/null || true
  powershell.exe -Command 'Stop-Process -Name mpv -Force -ErrorAction SilentlyContinue' 2>/dev/null || true
  kill $(cat /tmp/jarvis/loops.pid 2>/dev/null) 2>/dev/null || true
  sudo pkill -f "/usr/local/bin/ollama serve" 2>/dev/null || true
  sudo pkill -f "/usr/local/bin/ollama runner" 2>/dev/null || true
}

# ── Summary ───────────────────────────────────────────────────────────────────

print_summary() {
  local mem_count skill_count tool_count plan_runner_status
  mem_count=$(get_mem_count)
  skill_count=$(get_skill_count)
  tool_count=$(get_tool_count)
  plan_runner_status=$(pgrep -f "plan_runner.py" >/dev/null && echo "running" || echo "offline")

  echo ""
  echo "╔══════════════════════════════════════════════╗"
  echo "║     JARVIS OS ONLINE                         ║"
  echo "║                                              ║"
  echo "║  Browser UI    → http://localhost:4000       ║"
  echo "║  ReAct tools   → http://localhost:7900       ║"
  echo "║  PTY server    → http://localhost:4010       ║"
  printf "║  Fast model    → %-28s ║\n" "$OLLAMA_FAST"
  printf "║  Tool model    → %-28s ║\n" "$OLLAMA_TOOLS"
  printf "║  Reason model  → %-28s ║\n" "$OLLAMA_REASON"
  printf "║  Code model    → %-28s ║\n" "$OLLAMA_CODE"
  printf "║  Deep model    → %-28s ║\n" "$OLLAMA_DEEP"
  printf "║  MemPalace     → %-28s ║\n" "$mem_count drawers"
  printf "║  Skills        → %-28s ║\n" "$skill_count loaded"
  printf "║  Tools         → %-28s ║\n" "$tool_count available"
  printf "║  Plan runner   → %-28s ║\n" "$plan_runner_status"
  printf "║  Staging       → %-28s ║\n" "$STAGING_ROOT"
  echo "║  Audio         → Denon 5.1 (HDMI)           ║"
  echo "╚══════════════════════════════════════════════╝"
  echo ""
}

# ── do_stop ───────────────────────────────────────────────────────────────────

do_stop() {
  echo "╔══════════════════════════════════════╗"
  echo "║     J.A.R.V.I.S OS — SHUTTING DOWN   ║"
  echo "╚══════════════════════════════════════╝"

  log "Snapshotting agent memory..."
  python3 -c "
import sys, json; sys.path.insert(0, '$PROJECT_DIR')
from memory.redis_memory import snapshot, flush
data = snapshot()
import pathlib, datetime
out = pathlib.Path('$VAULT_DIR/snapshots')
out.mkdir(exist_ok=True)
fname = out / f\"session_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json\"
fname.write_text(json.dumps(data, indent=2))
flush()
print(f'[REDIS] Snapshot saved: {fname.name}')
" 2>/dev/null || log "WARN: Redis snapshot failed (non-fatal)"

  stop_pidfile_processes
  stop_named_processes
  reset_bridge_state
  log "Stopping n8n workflow automation"
  n8n_stop   
  log "=== JARVIS OS OFFLINE ==="
  echo ""
  echo "  Systems offline. Goodbye, sir."
  echo ""
}

# ── do_start ──────────────────────────────────────────────────────────────────

do_start() {
  load_models_from_config

  echo "╔══════════════════════════════════════╗"
  # Decide GPU pins from live VRAM BEFORE any inference service starts.
  assign_gpus

  start_redis                        # ← was never called before
  log "Starting n8n workflow automation"
  n8n_start

  log "Starting Ollama"
  ensure_ollama || true

  # ── Memory init (Redis must be up first) ────────────
  init_redis_save_qdrant || true

  # ── Staging workspace ────────────────────────────────
  start_staging                      # ← new

  # ── Preload main model ───────────────────────────────
  preload_model "$OLLAMA_TOOLS"

  # ── Application servers ──────────────────────────────
  log "Starting ReAct tool server on :7900"
  python3 -u "$PROJECT_DIR/scripts/react_server.py" > /tmp/react.log 2>&1 &
  echo "$! react-server" >> "$PIDFILE"
  sleep 2

  # Telegram watcher is started by loop.sh (run_forever auto-restart).
  # Starting it here TOO caused two instances → Telegram HTTP 409 conflicts.

  log "Starting Dictation daemon"
  dictation_daemon

  log "Starting browser bridge on :4000"
  python3 "$PROJECT_DIR/scripts/server.py" > /tmp/jarvis-browser.log 2>&1 &
  echo "$! bridge-server" >> "$PIDFILE"

  log "Starting Qdrant on :6333"
  start_qdrant

  python3 "$PROJECT_DIR/scripts/redis_init.py"

  log "Initialising Redis agent memory"
  python3 -c "
import sys; sys.path.insert(0, '$PROJECT_DIR')
from memory.redis_memory import write_state, write_task, reset_loop
write_state('JARVIS', task='booting', tools={}, confidence='low', notes='startup')
write_task('idle')
reset_loop()
print('[REDIS] Agent memory initialised')
"
  log "Starting llama.cpp vision server"
  start_llama_server
  log "Starting Kokoro TTS"
  start_kokoro

  log "Starting PTY terminal server on :4010"
  python3 "$PROJECT_DIR/scripts/pty_server.py" > /tmp/jarvis-pty.log 2>&1 &
  echo "$! pty-server" >> "$PIDFILE"

  log "Starting plan runner"
  start_plan_runner                  # ← new

  log "Starting loops"
  nohup bash "$PROJECT_DIR/scripts/loop.sh" >> /tmp/jarvis/loops.log 2>&1 &
  echo $! > /tmp/jarvis/loops.pid

  if python3 -c "import sounddevice" 2>/dev/null; then
    log "Starting voice capture (wake word mode)"
    CUDA_VISIBLE_DEVICES="" python3 "$PROJECT_DIR/scripts/voice_capture.py" \
      --wake > /tmp/jarvis-voice.log 2>&1 &
    echo "$! voice-capture" >> "$PIDFILE"
  else
    log "Voice capture skipped (install: pip install sounddevice soundfile numpy openai-whisper)"
  fi

  sleep 2
  print_summary

  log "All systems nominal. Good morning, sir."
}

# ── do_status ─────────────────────────────────────────────────────────────────

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

  if curl -sf --max-time 1 "$BROWSER_HOST/api/state" > /dev/null 2>&1; then
    echo "  ✓ Browser bridge (:4000)"
  else
    echo "  ✗ Browser bridge (:4000)"
  fi
  
  if curl -sf --max-time 1 "$LLAMA_CPP_HOST/health" > /dev/null 2>&1; then
    LLAMA_MODEL_NAME=$(curl -s "$LLAMA_CPP_HOST/props" 2>/dev/null | \
      python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("model_path","unknown").split("/")[-1])' \
      2>/dev/null)
    echo "  ✓ llama.cpp (:8081) [$LLAMA_MODEL_NAME]"
  else
    echo "  ○ llama.cpp server (offline)"
  fi

  if curl -sf --max-time 1 http://localhost:5100/health > /dev/null 2>&1; then
    echo "  ✓ Kokoro TTS (:5100)"
  else
    echo "  ○ Kokoro TTS (offline)"
  fi

  if podman ps --format '{{.Names}}' | grep -q '^jarvis-redis$'; then
    local redis_queue
    redis_queue=$(redis-cli llen jarvis:tasks 2>/dev/null || echo "?")
    echo "  ✓ Redis (:6379)  [queue: $redis_queue tasks]"
  else
    echo "  ✗ Redis (:6379)"
  fi

  if pgrep -f "plan_runner.py" > /dev/null; then
    echo "  ✓ Plan runner"
  else
    echo "  ○ Plan runner (offline)"
  fi

  if pgrep -f "pty_server.py" > /dev/null; then
    echo "  ✓ PTY server (:4010)"
  else
    echo "  ○ PTY server (offline)"
  fi

  echo ""
  echo "  Staging:"
  for stage in dev tested approved; do
    count=$(find "${STAGING_ROOT}/$stage" -type f 2>/dev/null | wc -l)
    echo "    $stage: $count files"
  done

  echo ""
  echo "  GPU:"
  nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw \
    --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r name temp util mem_used mem_total power; do
    echo "    $name | ${temp}°C | GPU ${util}% | VRAM ${mem_used}/${mem_total}MB | ${power}W"
  done

  echo ""
  echo "  State: $(cat "$BRIDGE_DIR/state.txt" 2>/dev/null || echo 'unknown')"
  echo "  Brain: $(cat "$BRIDGE_DIR/brain.txt" 2>/dev/null || echo 'none')"
  echo "  Last:  $(cat "$BRIDGE_DIR/output.txt" 2>/dev/null | head -1 | cut -c1-60)"
  echo ""
}

# ── Entry point ───────────────────────────────────────────────────────────────

case "${1:-}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; sleep 2; do_start ;;
  status)  do_status ;;
  n8n:start)   n8n_start   ;;
  n8n:stop)    n8n_stop    ;;
  n8n:restart) n8n_restart ;;
  n8n:status)  n8n_status  ;;
  n8n:logs)    n8n_logs    ;;
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