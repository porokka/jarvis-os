#!/bin/bash
# ============================================================
# J.A.R.V.I.S OS — install.sh
# Run from WSL: bash /mnt/e/coding/jarvis-os/install.sh
# ============================================================

set -e
JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════╗"
echo "║     J.A.R.V.I.S — INSTALLER              ║"
echo "╚══════════════════════════════════════════╝"

log() { echo "[$(date '+%H:%M:%S')] $1"; }

# ── 1. System packages ──────────────────────────────────────
log "Installing system packages..."
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-full \
  ffmpeg lm-sensors nmap android-tools-adb \
  curl git

# ── 2. Python packages ──────────────────────────────────────
log "Installing Python packages..."
pip3 install --break-system-packages \
  ddgs mempalace \
  sounddevice soundfile numpy openai-whisper \
  huggingface-hub snac torch

# llama-cpp-python with CUDA (for Orpheus TTS)
pip3 install --break-system-packages \
  llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 \
  || pip3 install --break-system-packages llama-cpp-python

# ── 3. Ollama ────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
  log "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

# ── 4. Pull models ──────────────────────────────────────────
log "Pulling Ollama models (this takes a while)..."
ollama serve > /dev/null 2>&1 &
sleep 3
ollama pull qwen3:8b
ollama pull qwen3:30b-a3b
ollama pull qwen3-coder:30b

# ── 5. Orpheus TTS model ────────────────────────────────────
log "Setting up Orpheus TTS..."
python3 "$JARVIS_DIR/tts/setup.py" || log "TTS setup skipped (optional)"

# ── 6. MemPalace ────────────────────────────────────────────
VAULT="/mnt/d/Jarvis_vault"
if [ -d "$VAULT" ]; then
  log "Initializing MemPalace on vault..."
  printf "\n\n\n" | python3 -m mempalace init "$VAULT" || true
  printf "\n\n\n" | python3 -m mempalace mine "$VAULT" || true
else
  log "Vault not found at $VAULT — skipping MemPalace"
fi

# ── 7. Copy personality to vault ─────────────────────────────
if [ -d "$VAULT" ]; then
  cp "$JARVIS_DIR/JARVIS.md" "$VAULT/JARVIS.md"
  log "Personality copied to vault"
fi

# ── 8. Create bridge directory ───────────────────────────────
mkdir -p /tmp/jarvis

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     J.A.R.V.I.S INSTALLED                ║"
echo "║                                          ║"
echo "║  Next steps:                             ║"
echo "║                                          ║"
echo "║  1. Windows: install mpv + ffmpeg        ║"
echo "║     winget install shinchiro.mpv         ║"
echo "║     winget install ffmpeg                ║"
echo "║                                          ║"
echo "║  2. Windows: install Next.js app         ║"
echo "║     cd E:\coding\jarvis-os\app           ║"
echo "║     npm install                          ║"
echo "║                                          ║"
echo "║  3. Start J.A.R.V.I.S:                  ║"
echo "║     bash jarvis.sh start                 ║"
echo "║                                          ║"
echo "║  4. Start HUD (Windows PowerShell):      ║"
echo "║     cd app && npm run dev                ║"
echo "║     Open http://localhost:3000           ║"
echo "╚══════════════════════════════════════════╝"
