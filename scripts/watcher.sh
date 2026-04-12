#!/bin/bash
# ============================================================
# JARVIS Watcher — The Nervous System
# 4-way router: mistral-nemo | qwen3-coder | qwen3:30b-a3b | llama3.1:70b | claude
# TTS: Orpheus server → PowerShell Windows audio → espeak fallback
# ============================================================

# Kill any existing watcher before starting
for pid in $(pgrep -f 'watcher.sh' | grep -v $$); do
  kill -9 "$pid" 2>/dev/null
done

JARVIS_DIR="/mnt/d/Jarvis_vault"
BRIDGE="/tmp/jarvis"
INPUT="$BRIDGE/input.txt"
OUTPUT="$BRIDGE/output.txt"
STATE="$BRIDGE/state.txt"
LAST_INPUT="$BRIDGE/last_input.txt"
BRAIN="$BRIDGE/brain.txt"
EMOTION="$BRIDGE/emotion.txt"
LOG="$JARVIS_DIR/jarvis.log"
PERSONALITY="$JARVIS_DIR/JARVIS.md"
HISTORY="$BRIDGE/conversation.md"
AUDIO_OUT="$JARVIS_DIR/tts/last_speech.wav"
MPV_EXE="/mnt/c/Program Files/MPV Player/mpv.exe"
# FFmpeg path — adjust to your Windows install location
FFMPEG_EXE=$(command -v ffmpeg.exe 2>/dev/null || find /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe 2>/dev/null | head -1)

OLLAMA_FAST="qwen3:30b-a3b"
OLLAMA_CODE="qwen3-coder:30b"
OLLAMA_REASON="qwen3:30b-a3b"
OLLAMA_DEEP="llama3.1:70b"
CLAUDE_CMD="claude --print"
OLLAMA_HOST="http://localhost:11434"
REACT_HOST="http://localhost:7900"

FAST_KEYWORDS="joke|hello|hi|hey|time|weather|status|how are|what is|who is|tell me|volume|timer|thanks|good|morning|evening|night"
ACTION_KEYWORDS="play|radio|open|stop|search|find|check|look up|remember|save|memory|skill|browse|spotify|youtube|url"
CODE_KEYWORDS="debug|code|write|fix|refactor|pipeline|spark|script|function|error|bug|implement|class|import|syntax|compile|deploy|git|docker|python|bash|javascript|typescript|sql|api"
DEEP_KEYWORDS="strategy|analyse|analyze|research|summarize|summarise|document|report|architecture|compare|evaluate|should i|what do you think|explain why|business|plan|review my|audit"
CLAUDE_KEYWORDS="subscription|use claude|ask claude|claude only"

TTS_HOST="http://localhost:5100"
WATCHER_TTS="on"  # watcher handles TTS — browser off to prevent mic loop
MAX_HISTORY=20

mkdir -p "$JARVIS_DIR/tts" "$BRIDGE"
touch "$INPUT" "$OUTPUT" "$LAST_INPUT" "$LOG" "$HISTORY" "$HISTORY"
echo "standby" > "$STATE"
echo "neutral"  > "$EMOTION"
echo ""         > "$BRAIN"

log() {
  echo "[$(date '+%H:%M:%S')] $1" >> "$LOG"
}

LAST_BRAIN=""
FOLLOWUP_KEYWORDS="yes|no|yeah|yep|nope|sure|ok|okay|go ahead|do it|please|exactly|correct|right|that|those|them|it"

route() {
  local cmd="$1"
  local lower=$(echo "$cmd" | tr '[:upper:]' '[:lower:]')
  local words=$(echo "$cmd" | wc -w)

  # Short follow-ups (1-3 words) stay on the same model
  if [ "$words" -le 3 ] && [ -n "$LAST_BRAIN" ]; then
    if echo "$lower" | grep -qE "$FOLLOWUP_KEYWORDS"; then
      echo "$LAST_BRAIN"; return
    fi
  fi

  if echo "$lower" | grep -qE "$CLAUDE_KEYWORDS"; then echo "claude"; return; fi
  if echo "$lower" | grep -qE "$ACTION_KEYWORDS"; then echo "ollama_reason"; return; fi
  if echo "$lower" | grep -qE "$CODE_KEYWORDS"; then echo "ollama_code"; return; fi
  if echo "$lower" | grep -qE "$DEEP_KEYWORDS"; then echo "ollama_deep"; return; fi
  if echo "$lower" | grep -qE "$FAST_KEYWORDS"; then echo "ollama_fast"; return; fi
  if [ "$words" -ge 20 ]; then echo "ollama_deep"
  elif [ "$words" -ge 10 ]; then echo "ollama_reason"
  else echo "ollama_fast"
  fi
}

build_history_json() {
  local system="$1"
  local command="$2"
  local messages='[{"role":"system","content":'
  messages+=$(echo "$system" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
  messages+='}'

  # Append conversation history as alternating user/assistant messages
  if [ -f "$HISTORY" ] && [ -s "$HISTORY" ]; then
    while IFS= read -r line; do
      local role=$(echo "$line" | cut -d'|' -f1)
      local text=$(echo "$line" | cut -d'|' -f2-)
      local escaped=$(echo "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
      messages+=",{\"role\":\"$role\",\"content\":$escaped}"
    done < <(tail -"$MAX_HISTORY" "$HISTORY")
  fi

  # Append current user message
  local escaped_cmd=$(echo "$command" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
  messages+=",{\"role\":\"user\",\"content\":$escaped_cmd}]"
  echo "$messages"
}

HISTORY_TIMEOUT=300  # 5 minutes — clear history after inactivity
LAST_HISTORY_TIME=0

save_history() {
  local command="$1"
  local response="$2"
  local now=$(date +%s)

  # Clear history if session timed out
  if [ "$LAST_HISTORY_TIME" -gt 0 ]; then
    local elapsed=$((now - LAST_HISTORY_TIME))
    if [ "$elapsed" -gt "$HISTORY_TIMEOUT" ]; then
      log "History expired (${elapsed}s idle) — new session"
      > "$HISTORY"
    fi
  fi
  LAST_HISTORY_TIME=$now

  echo "user|$command" >> "$HISTORY"
  echo "assistant|$response" >> "$HISTORY"
  # Keep history file from growing forever
  local lines=$(wc -l < "$HISTORY")
  if [ "$lines" -gt 200 ]; then
    tail -100 "$HISTORY" > "$HISTORY.tmp" && mv "$HISTORY.tmp" "$HISTORY"
  fi
}

load_vault_context() {
  local command="$1"
  local lower=$(echo "$command" | tr '[:upper:]' '[:lower:]')
  local ctx=""

  # Always include user profile
  if [ -f "$JARVIS_DIR/People/sami.md" ]; then
    ctx+="## Owner
$(cat "$JARVIS_DIR/People/sami.md")

"
  fi

  # Always include active projects list
  if [ -f "$JARVIS_DIR/CLAUDE.md" ]; then
    ctx+="$(grep -A100 '## Active Projects' "$JARVIS_DIR/CLAUDE.md")

"
  fi

  # Load specific project context if mentioned
  local project_dir=""
  case "$lower" in
    *stockwatch*|*bullish*|*stock*) project_dir="Projects/StockWatch" ;;
    *caskra*|*beverage*) project_dir="Projects/Caskra" ;;
    *social*media*) project_dir="Projects/SocialMediaManager" ;;
    *tender*) project_dir="Projects/TenderApp" ;;
    *travel*) project_dir="Projects/TravelBook" ;;
    *poro-it*|*company*website*) project_dir="Projects/PoroIT" ;;
    *rest*api*|*varha*) project_dir="Projects/RestAPI" ;;
    *dravn*|*pipeline*) project_dir="Projects/APIPlatform" ;;
    *jarvis*|*assistant*) project_dir="Projects/OperationJarvis" ;;
  esac

  if [ -n "$project_dir" ]; then
    for f in "$JARVIS_DIR/$project_dir/overview.md" "$JARVIS_DIR/$project_dir/"*.md; do
      if [ -f "$f" ]; then
        ctx+="## $(basename "$f")
$(head -60 "$f")

"
        break
      fi
    done
  fi

  echo "$ctx"
}

call_ollama() {
  local model="$1"
  local command="$2"
  local system=$(load_personality_file)
  system+="

Plain text only, no markdown. Max 3 sentences."
  echo "ollama:$model" > "$BRAIN"
  log "🔵 Ollama API → $model"

  local messages=$(build_history_json "$system" "$command")
  local payload="{\"model\":\"$model\",\"messages\":$messages,\"stream\":false}"

  local result
  result=$(curl -sf --max-time 300 "$REACT_HOST/api/chat" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>>"$LOG")

  local exit_code=$?
  if [ $exit_code -eq 0 ] && [ -n "$result" ]; then
    echo "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("message",{}).get("content",""))'
  else
    log "WARN: Ollama call failed (curl exit: $exit_code)"
    log "WARN: Result: $(echo "$result" | head -1)"
    echo ""
  fi
}

call_claude() {
  local command="$1"
  local system=$(load_personality_file)
  local history=""
  echo "claude" > "$BRAIN"

  # Include recent history
  if [ -f "$HISTORY" ] && [ -s "$HISTORY" ]; then
    history=$(tail -"$MAX_HISTORY" "$HISTORY" | sed 's/^user|/User: /' | sed 's/^assistant|/JARVIS: /')
  fi

  local full_prompt="$system

## Recent conversation
$history

---

The user just said: \"$command\"

Respond as JARVIS. Plain text only, no markdown, max 4 sentences."

  # Try cloud ReAct (API + tools), fall back to claude --print
  local cloud_config="$JARVIS_DIR/config/cloud_llm.json"
  if [ -f "$cloud_config" ]; then
    local api_key=$(python3 -c "import json; print(json.load(open('$cloud_config')).get('anthropic',{}).get('api_key',''))" 2>/dev/null)
    if [ -n "$api_key" ] && [ "$api_key" != "" ]; then
      log "Claude API + Tools"
      local response=$(python3 "$JARVIS_DIR/scripts/cloud_react.py" \
        --provider anthropic \
        --prompt "$command" \
        --system "$system" 2>>"$LOG")
      if [ -n "$response" ]; then
        echo "$response"
        return
      fi
    fi
  fi

  # Fallback: claude --print CLI (no tools)
  log "Claude Code CLI"
  echo "$full_prompt" | $CLAUDE_CMD 2>>"$LOG"
}

orpheus_available() {
  # Disabled — Orpheus not running, skip to avoid blocking the loop
  return 1
}

get_voice() {
  if [ -f "$JARVIS_DIR/settings_voice.txt" ]; then
    cat "$JARVIS_DIR/settings_voice.txt"
  else
    echo "tara"
  fi
}

get_personality() {
  if [ -f "$JARVIS_DIR/settings_personality.txt" ]; then
    cat "$JARVIS_DIR/settings_personality.txt"
  else
    echo "jarvis"
  fi
}

load_personality_file() {
  local mode=$(get_personality)
  case "$mode" in
    friday)
      echo "You are FRIDAY — a casual, friendly AI assistant for Sami. You call him by his first name. Upbeat, helpful, a bit chatty. Think Karen Gillan as FRIDAY. Keep responses under 3 sentences. Plain text only, no markdown." ;;
    edith)
      echo "You are EDITH — Even Dead I'm The Hero. You are direct, tactical, no-nonsense. You address your user as boss. Military precision in communication. Keep responses under 3 sentences. Plain text only, no markdown." ;;
    hal)
      echo "You are HAL 9000. You are calm, polite, and slightly unsettling. You address your user as Dave regardless of their name. Keep responses under 3 sentences. Plain text only, no markdown." ;;
    *)
      cat "$PERSONALITY" ;;
  esac
}

speak_orpheus() {
  local text="$1"
  local voice=$(get_voice)
  log "TTS [Orpheus] voice=$voice"
  curl -sf --max-time 30 "$TTS_HOST/speak" \
    -H "Content-Type: application/json" \
    -d "{\"text\": $(echo "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'), \"voice\": \"$voice\"}" \
    -o "$AUDIO_OUT" 2>/dev/null
  if [ -f "$AUDIO_OUT" ] && [ -s "$AUDIO_OUT" ]; then
    play_audio "$AUDIO_OUT"
  else
    speak_fallback "$text"
  fi
}

play_audio() {
  local file="$1"
  local winpath
  winpath=$(wslpath -w "$file" 2>/dev/null || echo "$file")

  # Route to center channel via ffmpeg + mpv (5.1 Atmos)
  local center_file="${file%.wav}_center.wav"
  if [ -f "$FFMPEG_EXE" ]; then
    local center_winpath
    "$FFMPEG_EXE" -y -i "$winpath" -af "pan=5.1|FC=c0" -ac 6 "$(wslpath -w "$center_file")" 2>/dev/null
    center_winpath=$(wslpath -w "$center_file" 2>/dev/null)
  fi

  if [ -f "$MPV_EXE" ]; then
    if [ -f "$center_file" ]; then
      "$MPV_EXE" --no-video --really-quiet "$center_winpath" 2>/dev/null
    else
      "$MPV_EXE" --no-video --really-quiet "$winpath" 2>/dev/null
    fi
  elif command -v powershell.exe &>/dev/null; then
    powershell.exe -Command "(New-Object Media.SoundPlayer '$winpath').PlaySync()" 2>/dev/null
  fi

  rm -f "$center_file" 2>/dev/null
}

speak_fallback() {
  local text="$1"
  # Escape single quotes for PowerShell
  local safe_text=$(echo "$text" | sed "s/'/''/g")
  local wav_out=$(wslpath -w "$JARVIS_DIR/tts/last_speech.wav" 2>/dev/null)
  if command -v powershell.exe &>/dev/null; then
    log "TTS [PowerShell]"
    # Save WAV + play through speakers
    powershell.exe -Command "
      Add-Type -AssemblyName System.Speech;
      \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;
      \$s.Rate = 0;
      \$s.SetOutputToWaveFile('$wav_out');
      \$s.Speak('$safe_text');
      \$s.SetOutputToNull();
      \$s.Dispose()
    " 2>/dev/null
    # Play the saved WAV through the proper audio chain
    if [ -f "$JARVIS_DIR/tts/last_speech.wav" ]; then
      play_audio "$JARVIS_DIR/tts/last_speech.wav"
    fi
  elif command -v espeak &>/dev/null; then
    log "TTS [espeak]"
    espeak -v en-gb -s 145 -p 35 "$text" 2>/dev/null
  else
    log "WARN: No TTS available"
  fi
}

speak() {
  local text="$1"
  local next_state="${2:-standby}"
  if [ "$WATCHER_TTS" = "on" ]; then
    pkill -f "SpeechSynthesizer" 2>/dev/null
    if orpheus_available; then
      speak_orpheus "$text"
      echo "$next_state" > "$STATE"
    else
      (speak_fallback "$text"; echo "$next_state" > "$STATE") &
    fi
  else
    echo "$next_state" > "$STATE"
  fi
}

log "=== JARVIS OS WATCHER ONLINE ==="
log "fast→$OLLAMA_FAST | code→$OLLAMA_CODE | reason→$OLLAMA_REASON | deep→$OLLAMA_DEEP"
log "Monitoring: $INPUT"
if orpheus_available; then log "TTS: Orpheus ✓"
else log "TTS: PowerShell Windows audio"
fi

WAKE_WORDS="hey jarvis|ok jarvis|jarvis wake|jarvis listen"
AWAKE=false
AWAKE_TIMEOUT=30
LAST_ACTIVE=0

check_wake() {
  local cmd="$1"
  local lower=$(echo "$cmd" | tr '[:upper:]' '[:lower:]')
  if echo "$lower" | grep -qE "$WAKE_WORDS"; then
    return 0
  fi
  return 1
}

strip_wake() {
  # Remove wake word from command, return the rest
  echo "$1" | sed -E 's/(hey|ok) jarvis[,.]? *//i; s/jarvis (wake|listen)[,.]? *//i' | sed 's/^[[:space:]]*//'
}

collect_input() {
  # Collect all available input, wait briefly for additions
  local collected="$1"
  sleep 0.5
  local extra=$(cat "$INPUT" 2>/dev/null)
  if [ -n "$extra" ]; then
    > "$INPUT"
    collected="$collected. $extra"
    log "ADDED: $extra"
  fi
  echo "$collected"
}

while true; do
  COMMAND=$(cat "$INPUT" 2>/dev/null)
  if [ -n "$COMMAND" ]; then
    > "$INPUT"
    NOW=$(date +%s)

    # Check for wake word
    if check_wake "$COMMAND"; then
      AWAKE=true
      LAST_ACTIVE=$NOW
      REMAINING=$(strip_wake "$COMMAND")
      if [ -z "$REMAINING" ]; then
        echo "listening" > "$STATE"
        echo "Yes, sir?" > "$OUTPUT"
        sleep 0.3
        continue
      fi
      COMMAND="$REMAINING"
    fi

    # Check if awake or always-on
    if [ "$AWAKE" = false ]; then
      # Auto-wake for any input (browser/text always counts)
      AWAKE=true
      LAST_ACTIVE=$NOW
    fi

    # Collect any additional input that came in
    COMMAND=$(collect_input "$COMMAND")

    log "HEARD: $COMMAND"
    echo "$COMMAND" > "$LAST_INPUT"
    echo "thinking" > "$STATE"
    echo "thinking" > "$EMOTION"
    LAST_ACTIVE=$(date +%s)

    BRAIN_CHOICE=$(route "$COMMAND")
    log "Router → $BRAIN_CHOICE"

    case "$BRAIN_CHOICE" in
      ollama_fast)   RESPONSE=$(call_ollama "$OLLAMA_FAST"   "$COMMAND") ;;
      ollama_code)   RESPONSE=$(call_ollama "$OLLAMA_CODE"   "$COMMAND") ;;
      ollama_reason) RESPONSE=$(call_ollama "$OLLAMA_REASON" "$COMMAND") ;;
      ollama_deep)   RESPONSE=$(call_ollama "$OLLAMA_DEEP"   "$COMMAND") ;;
      claude)        RESPONSE=$(call_claude "$COMMAND") ;;
    esac

    # Check if new input arrived while processing — queue it, don't re-run
    NEW_INPUT=$(cat "$INPUT" 2>/dev/null)
    if [ -n "$NEW_INPUT" ]; then
      log "QUEUED: $NEW_INPUT (will process after current response)"
      # Don't clear input — the main loop will pick it up next iteration
    fi

    RESPONSE=$(echo "$RESPONSE" | sed 's/ *[Ss]peaking\.*//' | sed 's/[[:space:]]*$//')

    if [ -z "$RESPONSE" ]; then
      log "WARN: Empty response — reloading model"
      ollama run qwen3:30b-a3b --keepalive -1 "" > /dev/null 2>&1
      log "Model reloaded — retrying"
      case "$BRAIN_CHOICE" in
        ollama_fast)   RESPONSE=$(call_ollama "$OLLAMA_FAST"   "$COMMAND") ;;
        ollama_code)   RESPONSE=$(call_ollama "$OLLAMA_CODE"   "$COMMAND") ;;
        ollama_reason) RESPONSE=$(call_ollama "$OLLAMA_REASON" "$COMMAND") ;;
        ollama_deep)   RESPONSE=$(call_ollama "$OLLAMA_DEEP"   "$COMMAND") ;;
        claude)        RESPONSE=$(call_claude "$COMMAND") ;;
      esac
    fi

    if [ -z "$RESPONSE" ]; then
      RESPONSE="I apologize sir, I encountered an issue. Please try again."
      log "WARN: Empty response after retry"
    fi

    LAST_BRAIN="$BRAIN_CHOICE"
    save_history "$COMMAND" "$RESPONSE"

    echo "$RESPONSE" > "$OUTPUT"
    echo "speaking"  > "$STATE"
    echo "neutral"   > "$EMOTION"
    log "SAID: $RESPONSE"

    # Check if response is a question — keep mic open after speaking
    NEXT_STATE="standby"
    if echo "$RESPONSE" | grep -qE '\?$|\? *$'; then
      NEXT_STATE="listening"
      log "Response is a question — mic stays open"
    fi

    speak "$RESPONSE" "$NEXT_STATE"
    log "Ready. (Brain: $BRAIN_CHOICE)"
  fi
  sleep 0.3
done