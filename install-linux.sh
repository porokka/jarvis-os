#!/bin/bash
# ============================================================
# J.A.R.V.I.S OS — Native Linux Install Script
# For Ubuntu 22.04+ / Debian 12+ with NVIDIA GPU
# Run: bash install-linux.sh
# ============================================================

set -e
JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="$HOME/jarvis-vault"

echo "╔══════════════════════════════════════════╗"
echo "║     J.A.R.V.I.S — LINUX INSTALLER        ║"
echo "╚══════════════════════════════════════════╝"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# ── 1. System packages ──────────────────────────────────────
log "Installing system packages..."
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-venv python3-full \
  ffmpeg mpv lm-sensors nmap android-tools-adb \
  curl git nodejs npm pulseaudio espeak-ng

# ── 2. NVIDIA drivers + CUDA ────────────────────────────────
if ! command -v nvidia-smi &>/dev/null; then
  log "Installing NVIDIA drivers..."
  sudo apt install -y ubuntu-drivers-common
  sudo ubuntu-drivers autoinstall
  log "REBOOT required after driver install!"
fi

# ── 3. Python packages ──────────────────────────────────────
log "Installing Python packages..."
pip3 install --break-system-packages \
  ddgs mempalace \
  sounddevice soundfile numpy openai-whisper \
  huggingface-hub snac torch

pip3 install --break-system-packages \
  llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 \
  || pip3 install --break-system-packages llama-cpp-python

# ── 4. Ollama ────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

# ── 5. Pull models ──────────────────────────────────────────
log "Pulling Ollama models..."
ollama serve > /dev/null 2>&1 &
sleep 3
ollama pull qwen3:8b
ollama pull qwen3:30b-a3b
ollama pull qwen3-coder:30b

# ── 6. Node.js app ──────────────────────────────────────────
log "Installing Next.js HUD..."
cd "$JARVIS_DIR/app" && npm install
cd "$JARVIS_DIR"

# ── 7. Orpheus TTS ──────────────────────────────────────────
log "Setting up Orpheus TTS..."
python3 "$JARVIS_DIR/tts/setup.py" || log "TTS setup skipped"

# ── 8. Vault setup ──────────────────────────────────────────
mkdir -p "$VAULT/People" "$VAULT/Projects" "$VAULT/References" "$VAULT/Daily"
cp "$JARVIS_DIR/JARVIS.md" "$VAULT/JARVIS.md" 2>/dev/null || true

# ── 9. MemPalace ────────────────────────────────────────────
if [ -d "$VAULT" ]; then
  log "Initializing MemPalace..."
  printf "\n\n\n" | python3 -m mempalace init "$VAULT" || true
  printf "\n\n\n" | python3 -m mempalace mine "$VAULT" || true
fi

# ── 10. Update paths for native Linux ───────────────────────
log "Configuring paths for native Linux..."

# Update watcher paths
sed -i "s|/mnt/d/Jarvis_vault|$VAULT|g" "$JARVIS_DIR/scripts/watcher.sh"
sed -i "s|/mnt/e/coding/jarvis-os|$JARVIS_DIR|g" "$JARVIS_DIR/scripts/watcher.sh"

# Update react server vault path
sed -i "s|/mnt/d/Jarvis_vault|$VAULT|g" "$JARVIS_DIR/scripts/react_server.py"

# Update server.py path
sed -i "s|/mnt/d/Jarvis_vault|$VAULT|g" "$JARVIS_DIR/scripts/server.py"

# Update bridge.ts vault path
sed -i "s|D:/Jarvis_vault|$VAULT|g" "$JARVIS_DIR/app/lib/bridge.ts"

# Bridge directory — use /tmp/jarvis on both
mkdir -p /tmp/jarvis

# ── 11. Create .env.local ───────────────────────────────────
cat > "$JARVIS_DIR/app/.env.local" << EOF
BRIDGE_URL=http://localhost:4000
TTS_URL=http://localhost:5100
EOF

# ── 12. Create jarvis alias ─────────────────────────────────
if ! grep -q "alias jarvis=" "$HOME/.bashrc" 2>/dev/null; then
  echo "alias jarvis='bash $JARVIS_DIR/jarvis.sh'" >> "$HOME/.bashrc"
  log "Added 'jarvis' alias to .bashrc"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     J.A.R.V.I.S INSTALLED (Linux)        ║"
echo "║                                          ║"
echo "║  Start:                                  ║"
echo "║    jarvis start                          ║"
echo "║    OR: bash jarvis.sh start              ║"
echo "║                                          ║"
echo "║  Start HUD:                              ║"
echo "║    cd app && npm run dev                 ║"
echo "║    Open http://localhost:3000            ║"
echo "║                                          ║"
echo "║  Voice:                                  ║"
echo "║    python3 scripts/voice_capture.py      ║"
echo "║    OR: --wake for wake word mode         ║"
echo "║                                          ║"
echo "║  Vault: $VAULT                           ║"
echo "╚══════════════════════════════════════════╝"
