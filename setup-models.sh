#!/bin/bash
# ============================================================
# J.A.R.V.I.S — Smart Model Setup
# Detects GPU(s), recommends models, lets user customize
# Usage: bash setup-models.sh
# ============================================================

G='\033[0;32m'; R='\033[0;31m'; Y='\033[0;33m'; C='\033[0;36m'; B='\033[1m'; N='\033[0m'

echo ""
echo -e "${C}╔══════════════════════════════════════╗${N}"
echo -e "${C}║   J.A.R.V.I.S — MODEL SETUP          ║${N}"
echo -e "${C}╚══════════════════════════════════════╝${N}"
echo ""

# ── Detect GPUs ──────────────────────────────────────────────
echo -e "${C}Detecting GPUs...${N}"
echo ""

GPU_COUNT=0
GPU_NAMES=()
GPU_VRAM=()
TOTAL_VRAM=0

while IFS=, read -r name vram; do
  name=$(echo "$name" | xargs)
  vram=$(echo "$vram" | xargs)
  GPU_NAMES+=("$name")
  GPU_VRAM+=("$vram")
  TOTAL_VRAM=$((TOTAL_VRAM + vram))
  GPU_COUNT=$((GPU_COUNT + 1))
  echo -e "  ${G}GPU $GPU_COUNT:${N} $name — ${B}${vram} MB${N} VRAM"
done < <(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null)

if [ "$GPU_COUNT" -eq 0 ]; then
  echo -e "  ${R}No NVIDIA GPU detected!${N}"
  echo "  J.A.R.V.I.S requires at least one NVIDIA GPU."
  exit 1
fi

echo ""
echo -e "  ${B}Total VRAM: ${TOTAL_VRAM} MB (${GPU_COUNT} GPU(s))${N}"
echo ""

# ── Detect RAM ───────────────────────────────────────────────
RAM_MB=$(free -m 2>/dev/null | awk '/Mem:/ {print $2}' || echo 0)
echo -e "  System RAM: ${RAM_MB} MB"
echo ""

# ── Auto-recommend models based on VRAM ─────────────────────
echo -e "${C}Recommending models for ${TOTAL_VRAM} MB VRAM...${N}"
echo ""

# Model catalog: name, vram_needed_mb, supports_tools, description
declare -A CATALOG_VRAM CATALOG_TOOLS CATALOG_DESC
# Fast models
CATALOG_VRAM[qwen3:8b]=5000;      CATALOG_TOOLS[qwen3:8b]=yes;  CATALOG_DESC[qwen3:8b]="Fast chat + tools (recommended)"
CATALOG_VRAM[qwen3:4b]=2500;      CATALOG_TOOLS[qwen3:4b]=yes;  CATALOG_DESC[qwen3:4b]="Ultra-fast, minimal VRAM"
CATALOG_VRAM[phi4:14b]=9000;      CATALOG_TOOLS[phi4:14b]=no;   CATALOG_DESC[phi4:14b]="Fast chat, no tools"
CATALOG_VRAM[gemma3:12b]=8000;    CATALOG_TOOLS[gemma3:12b]=yes; CATALOG_DESC[gemma3:12b]="Google, good quality"
# Medium models
CATALOG_VRAM[qwen3:30b-a3b]=18000; CATALOG_TOOLS[qwen3:30b-a3b]=yes; CATALOG_DESC[qwen3:30b-a3b]="Best reasoning + tools (recommended)"
CATALOG_VRAM[qwen3:14b]=9000;     CATALOG_TOOLS[qwen3:14b]=yes; CATALOG_DESC[qwen3:14b]="Mid-size reasoning"
CATALOG_VRAM[mistral-small:24b]=14000; CATALOG_TOOLS[mistral-small:24b]=yes; CATALOG_DESC[mistral-small:24b]="Mistral reasoning"
# Code models
CATALOG_VRAM[qwen3-coder:30b]=18000; CATALOG_TOOLS[qwen3-coder:30b]=yes; CATALOG_DESC[qwen3-coder:30b]="Best code model (recommended)"
CATALOG_VRAM[qwen3-coder:14b]=9000; CATALOG_TOOLS[qwen3-coder:14b]=yes; CATALOG_DESC[qwen3-coder:14b]="Mid-size code"
CATALOG_VRAM[deepseek-coder-v2:16b]=10000; CATALOG_TOOLS[deepseek-coder-v2:16b]=yes; CATALOG_DESC[deepseek-coder-v2:16b]="DeepSeek code"
# Deep models
CATALOG_VRAM[llama3.1:70b]=42000; CATALOG_TOOLS[llama3.1:70b]=yes; CATALOG_DESC[llama3.1:70b]="Largest, needs 2x 3090"
CATALOG_VRAM[qwen3:32b]=20000;    CATALOG_TOOLS[qwen3:32b]=yes; CATALOG_DESC[qwen3:32b]="Large reasoning"

# Auto-pick based on VRAM
AUTO_FAST=""
AUTO_REASON=""
AUTO_CODE=""
AUTO_DEEP=""

if [ "$TOTAL_VRAM" -ge 48000 ]; then
  # Dual 3090 or better
  AUTO_FAST="qwen3:8b"
  AUTO_REASON="qwen3:30b-a3b"
  AUTO_CODE="qwen3-coder:30b"
  AUTO_DEEP="llama3.1:70b"
  TIER="ULTRA (48GB+)"
elif [ "$TOTAL_VRAM" -ge 24000 ]; then
  # Single 3090 or 4090
  AUTO_FAST="qwen3:8b"
  AUTO_REASON="qwen3:30b-a3b"
  AUTO_CODE="qwen3-coder:30b"
  AUTO_DEEP="qwen3:30b-a3b"
  TIER="HIGH (24GB)"
elif [ "$TOTAL_VRAM" -ge 16000 ]; then
  # RTX 4080, 3080 Ti, etc.
  AUTO_FAST="qwen3:4b"
  AUTO_REASON="qwen3:14b"
  AUTO_CODE="qwen3-coder:14b"
  AUTO_DEEP="qwen3:14b"
  TIER="MEDIUM (16GB)"
elif [ "$TOTAL_VRAM" -ge 8000 ]; then
  # RTX 3070, 4060, etc.
  AUTO_FAST="qwen3:4b"
  AUTO_REASON="qwen3:8b"
  AUTO_CODE="qwen3-coder:14b"
  AUTO_DEEP="qwen3:8b"
  TIER="STANDARD (8GB)"
else
  # Low VRAM
  AUTO_FAST="qwen3:4b"
  AUTO_REASON="qwen3:4b"
  AUTO_CODE="qwen3:4b"
  AUTO_DEEP="qwen3:4b"
  TIER="BASIC (<8GB)"
fi

echo -e "  Tier: ${B}${TIER}${N}"
echo ""
echo -e "  ${B}Recommended:${N}"
echo -e "    Fast:   ${G}$AUTO_FAST${N}   — ${CATALOG_DESC[$AUTO_FAST]}"
echo -e "    Reason: ${G}$AUTO_REASON${N} — ${CATALOG_DESC[$AUTO_REASON]}"
echo -e "    Code:   ${G}$AUTO_CODE${N}   — ${CATALOG_DESC[$AUTO_CODE]}"
echo -e "    Deep:   ${G}$AUTO_DEEP${N}   — ${CATALOG_DESC[$AUTO_DEEP]}"
echo ""

# ── Ask user to accept or customize ─────────────────────────
echo -e "${Y}Accept these models? [Y/n/custom]${N}"
read -r choice

pick_model() {
  local slot="$1"
  local current="$2"
  local max_vram="$3"

  echo ""
  echo -e "  ${C}Pick $slot model (max ~${max_vram}MB VRAM):${N}"
  local i=1
  local options=()
  for model in "${!CATALOG_VRAM[@]}"; do
    if [ "${CATALOG_VRAM[$model]}" -le "$max_vram" ]; then
      local tools_tag=""
      [ "${CATALOG_TOOLS[$model]}" = "yes" ] && tools_tag="${G}[tools]${N}" || tools_tag="${R}[no tools]${N}"
      echo -e "    $i) $model — ${CATALOG_DESC[$model]} $tools_tag (${CATALOG_VRAM[$model]}MB)"
      options+=("$model")
      i=$((i + 1))
    fi
  done
  echo -e "    Current: ${B}$current${N}"
  echo -n "  Choice [enter=keep current]: "
  read -r pick
  if [ -n "$pick" ] && [ "$pick" -ge 1 ] 2>/dev/null && [ "$pick" -le "${#options[@]}" ]; then
    echo "${options[$((pick - 1))]}"
  else
    echo "$current"
  fi
}

if [ "$choice" = "custom" ] || [ "$choice" = "c" ]; then
  AUTO_FAST=$(pick_model "FAST" "$AUTO_FAST" "$TOTAL_VRAM")
  AUTO_REASON=$(pick_model "REASON" "$AUTO_REASON" "$TOTAL_VRAM")
  AUTO_CODE=$(pick_model "CODE" "$AUTO_CODE" "$TOTAL_VRAM")
  AUTO_DEEP=$(pick_model "DEEP" "$AUTO_DEEP" "$TOTAL_VRAM")
elif [ "$choice" = "n" ] || [ "$choice" = "N" ]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo -e "${C}Final configuration:${N}"
echo -e "  Fast:   ${G}$AUTO_FAST${N}"
echo -e "  Reason: ${G}$AUTO_REASON${N}"
echo -e "  Code:   ${G}$AUTO_CODE${N}"
echo -e "  Deep:   ${G}$AUTO_DEEP${N}"
echo ""

# ── TTS choice ───────────────────────────────────────────────
echo -e "${C}TTS Voice:${N}"
echo "  1) Orpheus (local, high quality, needs ~3GB VRAM or CPU)"
echo "  2) System default (PowerShell/espeak, no GPU needed)"
echo -n "  Choice [1]: "
read -r tts_choice
TTS_MODE="orpheus"
[ "$tts_choice" = "2" ] && TTS_MODE="system"

echo ""

# ── Pull models ──────────────────────────────────────────────
echo -e "${C}Pulling models...${N}"

# Collect unique models
declare -A TO_PULL
TO_PULL[$AUTO_FAST]=1
TO_PULL[$AUTO_REASON]=1
TO_PULL[$AUTO_CODE]=1
TO_PULL[$AUTO_DEEP]=1

for model in "${!TO_PULL[@]}"; do
  if ollama list 2>/dev/null | grep -q "^$model"; then
    echo -e "  ${G}✓${N} $model already pulled"
  else
    echo -e "  ${Y}↓${N} Pulling $model..."
    ollama pull "$model"
  fi
done

# ── Write config to watcher.sh ───────────────────────────────
echo ""
echo -e "${C}Writing configuration...${N}"

JARVIS_DIR="$(cd "$(dirname "$0")" && pwd)"
WATCHER="$JARVIS_DIR/scripts/watcher.sh"

if [ -f "$WATCHER" ]; then
  sed -i "s|^OLLAMA_FAST=.*|OLLAMA_FAST=\"$AUTO_FAST\"|" "$WATCHER"
  sed -i "s|^OLLAMA_CODE=.*|OLLAMA_CODE=\"$AUTO_CODE\"|" "$WATCHER"
  sed -i "s|^OLLAMA_REASON=.*|OLLAMA_REASON=\"$AUTO_REASON\"|" "$WATCHER"
  sed -i "s|^OLLAMA_DEEP=.*|OLLAMA_DEEP=\"$AUTO_DEEP\"|" "$WATCHER"
  echo -e "  ${G}✓${N} watcher.sh updated"
fi

# Update bridge.ts
BRIDGE="$JARVIS_DIR/app/lib/bridge.ts"
if [ -f "$BRIDGE" ]; then
  sed -i "s|fast: \".*\"|fast: \"$AUTO_FAST\"|" "$BRIDGE"
  sed -i "s|code: \".*\"|code: \"$AUTO_CODE\"|" "$BRIDGE"
  sed -i "s|reason: \".*\"|reason: \"$AUTO_REASON\"|" "$BRIDGE"
  sed -i "s|deep: \".*\"|deep: \"$AUTO_DEEP\"|" "$BRIDGE"
  echo -e "  ${G}✓${N} bridge.ts updated"
fi

# Update jarvis.sh
JARVIS_SH="$JARVIS_DIR/jarvis.sh"
if [ -f "$JARVIS_SH" ]; then
  sed -i "s|ollama run .* --keepalive|ollama run $AUTO_FAST --keepalive|" "$JARVIS_SH"
  echo -e "  ${G}✓${N} jarvis.sh updated"
fi

# Save config for reference
cat > "$JARVIS_DIR/model-config.json" << EOF
{
  "tier": "$TIER",
  "total_vram_mb": $TOTAL_VRAM,
  "gpu_count": $GPU_COUNT,
  "models": {
    "fast": "$AUTO_FAST",
    "reason": "$AUTO_REASON",
    "code": "$AUTO_CODE",
    "deep": "$AUTO_DEEP"
  },
  "tts": "$TTS_MODE",
  "updated": "$(date -Iseconds)"
}
EOF
echo -e "  ${G}✓${N} model-config.json saved"

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${C}╔══════════════════════════════════════╗${N}"
echo -e "${C}║   Models configured!                  ║${N}"
echo -e "${C}║                                      ║${N}"
echo -e "${C}║   Restart J.A.R.V.I.S:               ║${N}"
echo -e "${C}║     bash jarvis.sh restart            ║${N}"
echo -e "${C}╚══════════════════════════════════════╝${N}"
echo ""
