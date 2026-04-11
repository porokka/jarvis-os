#!/bin/bash
# ============================================================
# JARVIS OS — start.sh
# Boots the entire system in correct order
# ============================================================

JARVIS_DIR="$(dirname "$0")"
LOG="$JARVIS_DIR/jarvis.log"

echo "╔══════════════════════════════════════╗"
echo "║     J.A.R.V.I.S OS — BOOTING        ║"
echo "╚══════════════════════════════════════╝"

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

# ── 1. Ollama models on RTX 3090 ─────────────────────────────
log "Starting Ollama — Mistral-Nemo on RTX 3090..."
ollama run mistral-nemo --keepalive 24h &
MISTRAL_PID=$!

log "Starting Ollama — Qwen3-Coder on RTX 3090..."
ollama run qwen3-coder:30b --keepalive 24h &
QWEN_PID=$!

sleep 3

# ── 2. ReAct tool server ────────────────────────────────────
log "Starting ReAct tool server on :7900..."
python3 "$JARVIS_DIR/scripts/react_server.py" &
REACT_PID=$!
sleep 2

# ── 3. JARVIS file bridge watcher ────────────────────────────
log "Starting JARVIS watcher..."
bash "$JARVIS_DIR/scripts/watcher.sh" &
WATCHER_PID=$!

# ── 4. Bridge server for browser/Next.js ─────────────────────
log "Starting bridge server on :4000..."
python3 "$JARVIS_DIR/scripts/server.py" &
SERVER_PID=$!

# ── 4. Next.js UI ────────────────────────────────────────────
if [ -d "$JARVIS_DIR/ui" ]; then
  log "Starting Next.js UI on :3000..."
  cd "$JARVIS_DIR/ui" && npm run dev &
  UI_PID=$!
  cd "$JARVIS_DIR"
fi

# ── 5. Claude Code agent teams (optional) ────────────────────
if [ "$1" == "--agents" ]; then
  log "Enabling Claude Code Agent Teams..."
  export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true
  cd "$JARVIS_DIR/vault"
  log "Launch 'claude' in this directory to start agent sessions."
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════╗"
echo "║     JARVIS OS ONLINE                 ║"
echo "║                                      ║"
echo "║  Voice bridge  → https://:7799       ║"
echo "║  Web UI        → https://:3000       ║"
echo "║  Mistral-Nemo  → RTX 2080            ║"
echo "║  Qwen3-Coder   → RTX 3090            ║"
echo "║  Unreal        → launch manually     ║"
echo "╚══════════════════════════════════════╝"
echo ""
log "All systems nominal. Good morning, sir."

# ── Trap shutdown ─────────────────────────────────────────────
cleanup() {
  log "Shutting down JARVIS OS..."
  kill $MISTRAL_PID $QWEN_PID $REACT_PID $WATCHER_PID $SERVER_PID $UI_PID 2>/dev/null
  log "Systems offline."
  exit 0
}
trap cleanup SIGINT SIGTERM

# Keep alive
wait
