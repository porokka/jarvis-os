#!/bin/bash
# ============================================================
# J.A.R.V.I.S — System Health Check
# Usage: bash check.sh
# ============================================================

G='\033[0;32m'  # Green
R='\033[0;31m'  # Red
Y='\033[0;33m'  # Yellow
C='\033[0;36m'  # Cyan
D='\033[0;90m'  # Dim
N='\033[0m'     # Reset

ok() { echo -e "  ${G}✓${N} $1"; }
fail() { echo -e "  ${R}✗${N} $1"; }
warn() { echo -e "  ${Y}○${N} $1"; }
dim() { echo -e "  ${D}  $1${N}"; }

echo ""
echo -e "${C}╔══════════════════════════════════════╗${N}"
echo -e "${C}║     J.A.R.V.I.S — HEALTH CHECK       ║${N}"
echo -e "${C}╚══════════════════════════════════════╝${N}"
echo ""

# ── Ollama ───────────────────────────────────────────────────
echo -e "${C}OLLAMA${N}"
if pgrep -x ollama > /dev/null 2>&1; then
  ok "Ollama serve running"
  models=$(ollama ps 2>/dev/null | tail -n +2)
  if [ -n "$models" ]; then
    echo "$models" | while read -r line; do
      dim "$line"
    done
  else
    warn "No models loaded (will load on first query)"
  fi
else
  fail "Ollama not running"
fi
echo ""

# ── ReAct Server ─────────────────────────────────────────────
echo -e "${C}REACT SERVER (:7900)${N}"
health=$(curl -sf --max-time 2 http://localhost:7900/api/health 2>/dev/null)
if [ -n "$health" ]; then
  ok "ReAct server online"
  tools=$(echo "$health" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("tools",[])))' 2>/dev/null || echo "?")
  dim "Tools available"
else
  fail "ReAct server down"
  dim "Start: python3 -u scripts/react_server.py &"
fi
echo ""

# ── Watcher ──────────────────────────────────────────────────
echo -e "${C}WATCHER${N}"
wcount=$(pgrep -cf watcher.sh 2>/dev/null || echo 0)
if [ "$wcount" -eq 1 ]; then
  ok "Watcher running"
  state=$(cat /tmp/jarvis/state.txt 2>/dev/null || echo "unknown")
  brain=$(cat /tmp/jarvis/brain.txt 2>/dev/null || echo "none")
  dim "State: $state | Brain: $brain"
elif [ "$wcount" -gt 1 ]; then
  warn "Multiple watchers running ($wcount) — restart recommended"
else
  fail "Watcher not running"
  dim "Start: bash scripts/watcher.sh &"
fi
echo ""

# ── Bridge Server ────────────────────────────────────────────
echo -e "${C}BRIDGE SERVER (:4000)${N}"
bstate=$(curl -sf --max-time 2 http://localhost:4000/api/state 2>/dev/null)
if [ -n "$bstate" ]; then
  ok "Bridge server online"
  last=$(echo "$bstate" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("lastOutput","")[:60])' 2>/dev/null)
  dim "Last: $last"
else
  fail "Bridge server down"
  dim "Start: python3 scripts/server.py &"
fi
echo ""

# ── Next.js HUD ─────────────────────────────────────────────
echo -e "${C}NEXT.JS HUD (:3000)${N}"
hud=$(curl -sf --max-time 2 http://localhost:3000 2>/dev/null | head -1)
if [ -n "$hud" ]; then
  ok "HUD online → http://localhost:3000"
else
  warn "HUD not running"
  dim "Start (Windows): cd app && npm run dev"
fi
echo ""

# ── TTS ──────────────────────────────────────────────────────
echo -e "${C}TTS${N}"
tts=$(curl -sf --max-time 2 http://localhost:5100/health 2>/dev/null)
if [ -n "$tts" ]; then
  voice=$(echo "$tts" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("voice","?"))' 2>/dev/null)
  ok "Orpheus TTS online (voice: $voice)"
else
  warn "Orpheus TTS offline — using PowerShell fallback"
  dim "Start: python3 tts/server.py &"
fi
echo ""

# ── Voice Capture ────────────────────────────────────────────
echo -e "${C}VOICE CAPTURE${N}"
if pgrep -f voice_capture > /dev/null 2>&1; then
  ok "Voice capture running"
else
  warn "Voice capture not running"
  dim "Start: python3 scripts/voice_capture.py --wake"
fi
echo ""

# ── MemPalace ────────────────────────────────────────────────
echo -e "${C}MEMPALACE${N}"
mp=$(python3 -m mempalace status 2>/dev/null | grep "drawers" | head -1)
if [ -n "$mp" ]; then
  ok "$mp"
else
  warn "MemPalace not initialized"
  dim "Run: mempalace init /path/to/vault && mempalace mine /path/to/vault"
fi
echo ""

# ── GPU ──────────────────────────────────────────────────────
echo -e "${C}GPU${N}"
nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r name temp util mem_used mem_total power; do
  name=$(echo "$name" | xargs)
  ok "$name"
  dim "Temp: ${temp}°C | GPU: ${util}% | VRAM: ${mem_used}/${mem_total} MB | Power: ${power}W"
done
if ! command -v nvidia-smi &>/dev/null; then
  fail "nvidia-smi not found"
fi
echo ""

# ── Network (Shields) ────────────────────────────────────────
echo -e "${C}NETWORK DEVICES${N}"
for ip in 192.168.0.18 192.168.0.31; do
  if timeout 1 bash -c "echo > /dev/tcp/$ip/8008" 2>/dev/null; then
    ok "Shield at $ip (Chromecast port open)"
    if timeout 1 bash -c "echo > /dev/tcp/$ip/5555" 2>/dev/null; then
      dim "ADB enabled"
    else
      dim "ADB disabled — enable Network Debugging"
    fi
  else
    warn "Shield at $ip not responding"
  fi
done
echo ""

# ── Summary ──────────────────────────────────────────────────
echo -e "${C}──────────────────────────────────────${N}"
total=0; up=0
for svc in ollama react watcher bridge; do
  total=$((total + 1))
  case $svc in
    ollama)  pgrep -x ollama > /dev/null 2>&1 && up=$((up + 1)) ;;
    react)   curl -sf --max-time 1 http://localhost:7900/api/health > /dev/null 2>&1 && up=$((up + 1)) ;;
    watcher) pgrep -f watcher.sh > /dev/null 2>&1 && up=$((up + 1)) ;;
    bridge)  curl -sf --max-time 1 http://localhost:4000/api/state > /dev/null 2>&1 && up=$((up + 1)) ;;
  esac
done
echo -e "  Core services: ${G}${up}${N}/${total} online"
echo ""
