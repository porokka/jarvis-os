#!/bin/bash
# ============================================================
# JARVIS Watcher — The Nervous System
#
# Polls input.txt for new commands. When found:
#   1. Copies to last_input.txt
#   2. Sets state → thinking
#   3. Pipes through Claude Code with JARVIS.md personality
#   4. Writes response to output.txt
#   5. Sets state → speaking
#   6. Sends to Orpheus TTS server (or falls back to system TTS)
#   7. Plays audio
#   8. Sets state → standby
#
# Usage: bash scripts/watcher.sh
# ============================================================

JARVIS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INPUT="$JARVIS_DIR/input.txt"
OUTPUT="$JARVIS_DIR/output.txt"
STATE="$JARVIS_DIR/state.txt"
LAST_INPUT="$JARVIS_DIR/last_input.txt"
EMOTION="$JARVIS_DIR/emotion.txt"
LOG="$JARVIS_DIR/jarvis.log"
PERSONALITY="$JARVIS_DIR/JARVIS.md"
AUDIO_OUT="$JARVIS_DIR/tts/last_speech.wav"

# Orpheus TTS server
TTS_HOST="http://localhost:5100"

# Initialize files
touch "$INPUT" "$OUTPUT" "$LAST_INPUT" "$LOG"
echo "standby" > "$STATE"
echo "neutral" > "$EMOTION"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
  echo "$1"
}

# --- Check if Orpheus TTS server is running ---
orpheus_available() {
  curl -sf "$TTS_HOST/health" > /dev/null 2>&1
}

# --- Speak via Orpheus TTS server ---
speak_orpheus() {
  local text="$1"
  local emotion="$2"

  # Use Python emotion mapper to inject Orpheus tags
  local tts_text
  tts_text=$(python -c "
import sys
sys.path.insert(0, '$JARVIS_DIR/tts')
from emotions import prepare_for_tts
text, _ = prepare_for_tts('[EMOTION:$emotion]\n$text')
print(text)
" 2>/dev/null)

  if [ -z "$tts_text" ]; then
    tts_text="$text"
  fi

  log "TTS [Orpheus]: $tts_text"

  # Send to TTS server, save WAV
  curl -sf "$TTS_HOST/speak" \
    -H "Content-Type: application/json" \
    -d "{\"text\": $(echo "$tts_text" | python -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')}" \
    -o "$AUDIO_OUT" 2>/dev/null

  if [ -f "$AUDIO_OUT" ] && [ -s "$AUDIO_OUT" ]; then
    play_audio "$AUDIO_OUT"
  else
    log "WARN: Orpheus returned no audio, falling back"
    speak_fallback "$text"
  fi
}

# --- Play audio file cross-platform ---
play_audio() {
  local file="$1"
  if command -v powershell.exe &>/dev/null; then
    # Windows via WSL/Git Bash
    powershell.exe -Command "(New-Object Media.SoundPlayer '$(cygpath -w "$file" 2>/dev/null || echo "$file")').PlaySync()" &
  elif command -v powershell &>/dev/null; then
    # Windows native Git Bash
    local winpath="${file//\//\\}"
    powershell -Command "(New-Object Media.SoundPlayer '$winpath').PlaySync()" &
  elif command -v aplay &>/dev/null; then
    aplay "$file" &
  elif command -v afplay &>/dev/null; then
    afplay "$file" &
  elif command -v ffplay &>/dev/null; then
    ffplay -nodisp -autoexit "$file" &
  else
    log "WARN: No audio player found"
  fi
  wait
}

# --- Fallback TTS (system voices) ---
speak_fallback() {
  local text="$1"
  if command -v say &>/dev/null; then
    say -v Daniel "$text"
  elif command -v piper &>/dev/null; then
    echo "$text" | piper --model en_US-lessac-medium --output-raw | aplay -r 22050 -f S16_LE -c 1
  elif command -v espeak &>/dev/null; then
    espeak "$text"
  elif command -v powershell.exe &>/dev/null; then
    powershell.exe -Command "Add-Type -AssemblyName System.Speech; \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; \$s.Speak('$text')"
  elif command -v powershell &>/dev/null; then
    powershell -Command "Add-Type -AssemblyName System.Speech; \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; \$s.Speak('$text')"
  else
    log "WARN: No TTS engine found at all"
  fi
}

# --- Main speak dispatcher ---
speak() {
  local text="$1"
  local emotion="$2"

  if orpheus_available; then
    speak_orpheus "$text" "$emotion"
  else
    log "TTS [fallback]: system voice"
    speak_fallback "$text"
  fi
}

# --- Startup ---
log "=== JARVIS WATCHER ONLINE ==="
log "Watching: $INPUT"

if orpheus_available; then
  log "TTS: Orpheus server at $TTS_HOST"
else
  log "TTS: Orpheus not running, using system fallback"
  log "     Start Orpheus: python tts/server.py"
fi

# --- Main loop ---
while true; do
  if [ -s "$INPUT" ]; then
    COMMAND=$(cat "$INPUT")
    log "HEARD: $COMMAND"

    # Save and clear input
    echo "$COMMAND" > "$LAST_INPUT"
    > "$INPUT"

    # Thinking state
    echo "thinking" > "$STATE"
    echo "thinking" > "$EMOTION"

    # Build prompt with personality context
    PROMPT="$(cat "$PERSONALITY")

---
User said: $COMMAND

Respond as JARVIS. Plain text only, no markdown. Under 3 sentences."

    # Call Claude Code
    log "Calling Claude..."
    RESPONSE=$(echo "$PROMPT" | claude --print 2>/dev/null)

    if [ -z "$RESPONSE" ]; then
      RESPONSE="I didn't catch that. Could you try again?"
      log "WARN: Empty Claude response"
    fi

    # Parse emotion from response
    DETECTED_EMOTION="neutral"
    CLEAN_RESPONSE="$RESPONSE"
    if echo "$RESPONSE" | head -1 | grep -q '^\[EMOTION:'; then
      DETECTED_EMOTION=$(echo "$RESPONSE" | head -1 | sed 's/\[EMOTION:\(.*\)\]/\1/')
      CLEAN_RESPONSE=$(echo "$RESPONSE" | tail -n +2)
    fi

    # Write output + emotion
    echo "$CLEAN_RESPONSE" > "$OUTPUT"
    echo "$DETECTED_EMOTION" > "$EMOTION"
    echo "speaking" > "$STATE"
    log "SAID [$DETECTED_EMOTION]: $CLEAN_RESPONSE"

    # Speak it
    speak "$CLEAN_RESPONSE" "$DETECTED_EMOTION"

    # Back to idle
    echo "standby" > "$STATE"
    echo "neutral" > "$EMOTION"
  fi

  sleep 0.5
done
