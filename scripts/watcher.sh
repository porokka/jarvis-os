#!/bin/bash
# ============================================================
# JARVIS Watcher — The Nervous System
# Route-aware watcher using shared model-config.json
# Runtime-mode-aware TTS via runtime_mode.json
# ============================================================

set -u

# Kill any existing watcher before starting
for pid in $(pgrep -f 'watcher.sh' | grep -v $$); do
  kill -9 "$pid" 2>/dev/null
done

PROJECT_DIR="/mnt/e/coding/jarvis-os"
VAULT_DIR="/mnt/d/Jarvis_vault"
BRIDGE_DIR="/tmp/jarvis"

INPUT="$BRIDGE_DIR/input.txt"
OUTPUT="$BRIDGE_DIR/output.txt"
STATE="$BRIDGE_DIR/state.txt"
LAST_INPUT="$BRIDGE_DIR/last_input.txt"
BRAIN="$BRIDGE_DIR/brain.txt"
EMOTION="$BRIDGE_DIR/emotion.txt"
HISTORY="$BRIDGE_DIR/conversation.md"
RUNTIME_MODE="$BRIDGE_DIR/runtime_mode.json"

LOG="$VAULT_DIR/jarvis.log"
PERSONALITY="$VAULT_DIR/JARVIS.md"
AUDIO_OUT="$VAULT_DIR/tts/last_speech.wav"

SETTINGS_JSON="$VAULT_DIR/.jarvis/settings.json"
ACTIVE_PROFILE_JSON="$VAULT_DIR/.jarvis/active_profile.json"
PROFILES_DIR="$VAULT_DIR/.jarvis/profiles"

MODEL_CONFIG="$PROJECT_DIR/config/models-config.json"
REACT_HOST="http://127.0.0.1:7900"
OLLAMA_API="http://127.0.0.1:11434"
CLAUDE_CMD="claude --print"

MPV_EXE="/mnt/c/Program Files/MPV Player/mpv.exe"
FFMPEG_EXE=$(command -v ffmpeg.exe 2>/dev/null || find /mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe 2>/dev/null | head -1)

TTS_HOST="http://localhost:5100"
WATCHER_TTS="on"
MAX_HISTORY=20
HISTORY_TIMEOUT=300

FAST_KEYWORDS="joke|hello|hi|hey|time|weather|status|how are|what is|who is|tell me|volume|timer|thanks|good|morning|evening|night"
ACTION_KEYWORDS="play|radio|open|stop|search|find|check|look up|remember|save|memory|skill|browse|spotify|youtube|url"
CODE_KEYWORDS="debug|code|write|fix|refactor|pipeline|spark|script|function|error|bug|implement|class|import|syntax|compile|deploy|git|docker|python|bash|javascript|typescript|sql|api"
DEEP_KEYWORDS="strategy|analyse|analyze|research|summarize|summarise|document|report|architecture|compare|evaluate|should i|what do you think|explain why|business|plan|review my|audit"
CLAUDE_KEYWORDS="subscription|use claude|ask claude|claude only"
FOLLOWUP_KEYWORDS="yes|no|yeah|yep|nope|sure|ok|okay|go ahead|do it|please|exactly|correct|right|that|those|them|it"
WAKE_WORDS="hey jarvis|ok jarvis|jarvis wake|jarvis listen"

LAST_BRAIN=""
LAST_HISTORY_TIME=0
AWAKE=false
AWAKE_TIMEOUT=30
LAST_ACTIVE=0

mkdir -p "$VAULT_DIR/tts" "$BRIDGE_DIR"
touch "$INPUT" "$OUTPUT" "$LAST_INPUT" "$LOG" "$HISTORY"
echo "standby" > "$STATE"
echo "neutral" > "$EMOTION"
echo "" > "$BRAIN"

log() {
  echo "[$(date '+%H:%M:%S')] [WATCHER] $1" >> "$LOG"
}

load_models_from_config() {
  if [ ! -f "$MODEL_CONFIG" ]; then
    OLLAMA_FAST="qwen3:8b"
    OLLAMA_REASON="qwen3:14b"
    OLLAMA_CODE="gemma4:31b"
    OLLAMA_DEEP="qwen3:30b-a3b"
    log "model-config.json missing -> using defaults"
    return
  fi

  mapfile -t _models < <(
    python3 - "$MODEL_CONFIG" <<'PY'
import json, sys
from pathlib import Path

cfg = Path(sys.argv[1])
defaults = {
    "fast": "qwen3:8b",
    "reason": "qwen3:14b",
    "code": "gemma4:31b",
    "deep": "qwen3:30b-a3b",
}

try:
    data = json.loads(cfg.read_text(encoding="utf-8"))
    models = data.get("models", {}) if isinstance(data, dict) else {}
except Exception:
    models = {}

print(models.get("fast", defaults["fast"]))
print(models.get("reason", defaults["reason"]))
print(models.get("code", defaults["code"]))
print(models.get("deep", defaults["deep"]))
PY
  )

  OLLAMA_FAST="${_models[0]}"
  OLLAMA_REASON="${_models[1]}"
  OLLAMA_CODE="${_models[2]}"
  OLLAMA_DEEP="${_models[3]}"

  log "Loaded models from $MODEL_CONFIG"
  log "Models -> fast=$OLLAMA_FAST reason=$OLLAMA_REASON code=$OLLAMA_CODE deep=$OLLAMA_DEEP"
}

load_models_from_config

route() {
  local cmd="$1"
  local lower
  lower=$(echo "$cmd" | tr '[:upper:]' '[:lower:]')
  local words
  words=$(echo "$cmd" | wc -w)

  if [ "$words" -le 3 ] && [ -n "$LAST_BRAIN" ]; then
    if echo "$lower" | grep -qE "$FOLLOWUP_KEYWORDS"; then
      echo "$LAST_BRAIN"
      return
    fi
  fi

  if echo "$lower" | grep -qE "$CLAUDE_KEYWORDS"; then
    echo "claude"
    return
  fi

  if echo "$lower" | grep -qE "$CODE_KEYWORDS"; then
    echo "ollama_code"
    return
  fi

  if echo "$lower" | grep -qE "$ACTION_KEYWORDS"; then
    echo "ollama_reason"
    return
  fi

  if echo "$lower" | grep -qE "$DEEP_KEYWORDS" && [ "$words" -ge 20 ]; then
    echo "ollama_deep"
    return
  fi

  if echo "$lower" | grep -qE "$FAST_KEYWORDS"; then
    echo "ollama_fast"
    return
  fi

  if [ "$words" -ge 30 ]; then
    echo "ollama_deep"
  elif [ "$words" -ge 12 ]; then
    echo "ollama_reason"
  else
    echo "ollama_fast"
  fi
}

brain_to_route() {
  case "$1" in
    ollama_fast) echo "fast" ;;
    ollama_reason) echo "reason" ;;
    ollama_code) echo "code" ;;
    ollama_deep) echo "deep" ;;
    *) echo "reason" ;;
  esac
}

build_history_json() {
  local system="$1"
  local command="$2"
  local messages='[{"role":"system","content":'
  messages+=$(echo "$system" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
  messages+='}'

  if [ -f "$HISTORY" ] && [ -s "$HISTORY" ]; then
    while IFS= read -r line; do
      local role
      role=$(echo "$line" | cut -d'|' -f1)
      local text
      text=$(echo "$line" | cut -d'|' -f2-)
      local escaped
      escaped=$(echo "$text" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
      messages+=",{\"role\":\"$role\",\"content\":$escaped}"
    done < <(tail -"$MAX_HISTORY" "$HISTORY")
  fi

  local escaped_cmd
  escaped_cmd=$(echo "$command" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
  messages+=",{\"role\":\"user\",\"content\":$escaped_cmd}]"
  echo "$messages"
}

save_history() {
  local command="$1"
  local response="$2"
  local now
  now=$(date +%s)

  if [ "$LAST_HISTORY_TIME" -gt 0 ]; then
    local elapsed=$((now - LAST_HISTORY_TIME))
    if [ "$elapsed" -gt "$HISTORY_TIMEOUT" ]; then
      log "History expired (${elapsed}s idle) -> new session"
      > "$HISTORY"
    fi
  fi

  LAST_HISTORY_TIME=$now

  echo "user|$command" >> "$HISTORY"
  echo "assistant|$response" >> "$HISTORY"

  local lines
  lines=$(wc -l < "$HISTORY")
  if [ "$lines" -gt 200 ]; then
    tail -100 "$HISTORY" > "$HISTORY.tmp" && mv "$HISTORY.tmp" "$HISTORY"
  fi
}

get_runtime_field() {
  local field="$1"
  if [ -f "$RUNTIME_MODE" ]; then
    python3 - "$RUNTIME_MODE" "$field" <<'PY'
import json, sys
from pathlib import Path

p = Path(sys.argv[1])
field = sys.argv[2]
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    value = data.get(field, "")
    if isinstance(value, bool):
        print("true" if value else "false")
    else:
        print(value if value is not None else "")
except Exception:
    print("")
PY
  else
    echo ""
  fi
}

get_runtime_persona() {
  get_runtime_field "persona"
}

get_runtime_tts_engine() {
  local value
  value=$(get_runtime_field "tts_engine")
  if [ -n "$value" ]; then
    echo "$value"
  else
    echo "orpheus"
  fi
}

get_runtime_tts_enabled() {
  local value
  value=$(get_runtime_field "tts_enabled")
  if [ "$value" = "false" ]; then
    echo "false"
  else
    echo "true"
  fi
}

get_profile_voice_from_id() {
  local profile_id="$1"
  if [ -z "$profile_id" ]; then
    echo ""
    return
  fi
  local profile_file="$PROFILES_DIR/$profile_id.json"
  if [ -f "$profile_file" ]; then
    python3 - "$profile_file" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    voice = ((data.get("voice") or {}).get("preferred") or "").strip()
    print(voice)
except Exception:
    print("")
PY
  else
    echo ""
  fi
}

get_voice() {
  if [ -f "$VAULT_DIR/settings_voice.txt" ]; then
    local explicit_voice
    explicit_voice=$(tr -d '\r\n' < "$VAULT_DIR/settings_voice.txt" 2>/dev/null)
    if [ -n "$explicit_voice" ]; then
      echo "$explicit_voice"
      return
    fi
  fi

  local runtime_persona
  runtime_persona=$(get_runtime_persona)
  if [ -n "$runtime_persona" ]; then
    local runtime_voice
    runtime_voice=$(get_profile_voice_from_id "$runtime_persona")
    if [ -n "$runtime_voice" ]; then
      echo "$runtime_voice"
      return
    fi
  fi

  if [ -f "$ACTIVE_PROFILE_JSON" ]; then
    local profile_voice
    profile_voice=$(python3 - "$ACTIVE_PROFILE_JSON" <<'PY'
import json, sys
from pathlib import Path

p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("active"):
        print("")
    else:
        voice = ((data.get("voice") or {}).get("preferred") or "").strip()
        print(voice)
except Exception:
    print("")
PY
)
    if [ -n "$profile_voice" ]; then
      echo "$profile_voice"
      return
    fi
  fi

  echo "tara"
}

get_personality() {
  if [ -f "$VAULT_DIR/settings_personality.txt" ]; then
    tr -d '\r\n' < "$VAULT_DIR/settings_personality.txt"
  else
    echo "jarvis"
  fi
}

load_personality_file() {
  local runtime_persona
  runtime_persona=$(get_runtime_persona)

  if [ -n "$runtime_persona" ]; then
    local runtime_profile="$PROFILES_DIR/$runtime_persona.json"
    if [ -f "$runtime_profile" ]; then
      local prompt
      prompt=$(python3 - "$runtime_profile" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = json.loads(p.read_text(encoding="utf-8"))
    print((data.get("systemPrompt") or "").strip())
except Exception:
    print("")
PY
)
      if [ -n "$prompt" ]; then
        log "Loaded personality from runtime persona=$runtime_persona"
        echo "$prompt"
        return
      fi
    fi
  fi

  if [ -f "$ACTIVE_PROFILE_JSON" ]; then
    local prompt
    prompt=$(python3 - "$ACTIVE_PROFILE_JSON" "$PROFILES_DIR" <<'PY'
import json, sys
from pathlib import Path

active = Path(sys.argv[1])
profiles_dir = Path(sys.argv[2])

try:
    data = json.loads(active.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("active"):
        pf = profiles_dir / f"{data['active']}.json"
        if pf.exists():
            pdata = json.loads(pf.read_text(encoding="utf-8"))
            print((pdata.get("systemPrompt") or "").strip())
        else:
            print("")
    else:
        print((data.get("systemPrompt") or "").strip())
except Exception:
    print("")
PY
)
    if [ -n "$prompt" ]; then
      log "Loaded personality from active profile"
      echo "$prompt"
      return
    fi
  fi

  local mode
  mode=$(get_personality)
  case "$mode" in
    friday)
      log "Fallback personality mode=friday"
      echo "You are FRIDAY — a casual, friendly AI assistant for Sami. You call him by his first name. Upbeat, helpful, a bit chatty. Keep responses under 3 sentences. Plain text only, no markdown."
      return
      ;;
    edith)
      log "Fallback personality mode=edith"
      echo "You are EDITH — Even Dead I'm The Hero. You are direct, tactical, no-nonsense. Keep responses under 3 sentences. Plain text only, no markdown."
      return
      ;;
    hal)
      log "Fallback personality mode=hal"
      echo "You are HAL 9000. You are calm, polite, and slightly unsettling. Keep responses under 3 sentences. Plain text only, no markdown."
      return
      ;;
  esac

  if [ -f "$PERSONALITY" ]; then
    log "Fallback personality from JARVIS.md"
    cat "$PERSONALITY"
  else
    log "Fallback personality default inline"
    echo "You are JARVIS, a capable AI assistant. Be clear, helpful, and concise."
  fi
}

call_ollama() {
  local model="$1"
  local route="$2"
  local command="$3"

  echo "ollama:$model" > "$BRAIN"
  log "OLLAMA route=$route model=$model"

  local payload
  payload=$(python3 - "$model" "$route" "$command" <<'PY'
import json, sys
model = sys.argv[1]
route = sys.argv[2]
command = sys.argv[3]
print(json.dumps({
    "model": model,
    "route": route,
    "messages": [{"role": "user", "content": command}],
    "stream": False
}, ensure_ascii=False))
PY
)

  local result
  result=$(curl -sf --max-time 300 "$REACT_HOST/api/chat" \
    -H "Content-Type: application/json" \
    -d "$payload" 2>>"$LOG")

  local exit_code=$?
  if [ $exit_code -eq 0 ] && [ -n "$result" ]; then
    echo "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("message",{}).get("content",""))'
  else
    log "WARN: ReAct call failed route=$route model=$model curl_exit=$exit_code"
    log "WARN: Result: $(echo "$result" | head -1)"
    echo ""
  fi
}

call_claude() {
  local command="$1"
  local system
  system=$(load_personality_file)
  local history=""
  echo "claude" > "$BRAIN"

  if [ -f "$HISTORY" ] && [ -s "$HISTORY" ]; then
    history=$(tail -"$MAX_HISTORY" "$HISTORY" | sed 's/^user|/User: /' | sed 's/^assistant|/Jarvis: /')
  fi

  local full_prompt="$system

## Recent conversation
$history

---

The user just said: \"$command\"

Respond in plain text only, no markdown, max 4 sentences."

  local cloud_config="$VAULT_DIR/config/cloud_llm.json"
  if [ -f "$cloud_config" ]; then
    local api_key
    api_key=$(python3 -c "import json; print(json.load(open('$cloud_config')).get('anthropic',{}).get('api_key',''))" 2>/dev/null)
    if [ -n "$api_key" ] && [ "$api_key" != "" ]; then
      log "Claude API + Tools"
      local response
      response=$(python3 "$VAULT_DIR/scripts/cloud_react.py" \
        --provider anthropic \
        --prompt "$command" \
        --system "$system" 2>>"$LOG")
      if [ -n "$response" ]; then
        echo "$response"
        return
      fi
    fi
  fi

  log "Claude Code CLI"
  echo "$full_prompt" | $CLAUDE_CMD 2>>"$LOG"
}

orpheus_available() {
  local tts_engine
  tts_engine=$(get_runtime_tts_engine)

  if [ "$tts_engine" != "orpheus" ]; then
    return 1
  fi

  curl -sf --max-time 2 "$TTS_HOST/health" >/dev/null 2>&1
}

normalize_tts_text() {
  local text="$1"
  text=$(echo "$text" | sed \
    -e 's/\bJARVIS\b/Jarvis/g' \
    -e 's/\bFRIDAY\b/Friday/g' \
    -e 's/\bEDITH\b/Edith/g' \
    -e 's/\bHAL\b/Hal/g')
  echo "$text"
}

speak_orpheus() {
  local text="$1"
  local voice
  voice=$(get_voice)
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
  text=$(normalize_tts_text "$text")

  local safe_text
  safe_text=$(echo "$text" | sed "s/'/''/g")

  local wav_file="$VAULT_DIR/tts/last_speech.wav"
  local padded_wav="$VAULT_DIR/tts/last_speech_padded.wav"
  local wav_out
  wav_out=$(wslpath -w "$wav_file" 2>/dev/null)
  local padded_out
  padded_out=$(wslpath -w "$padded_wav" 2>/dev/null)

  if command -v powershell.exe &>/dev/null; then
    log "TTS [PowerShell]"

    powershell.exe -Command "
      Add-Type -AssemblyName System.Speech;
      \$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;
      \$s.Rate = 0;
      \$null = \$s.GetInstalledVoices();
      \$s.SetOutputToWaveFile('$wav_out');
      \$s.Speak('$safe_text');
      \$s.SetOutputToNull();
      \$s.Dispose()
    " 2>/dev/null

    if [ -f "$wav_file" ]; then
      if [ -n "${FFMPEG_EXE:-}" ] && [ -f "$FFMPEG_EXE" ]; then
        "$FFMPEG_EXE" -y \
          -f lavfi -i anullsrc=r=22050:cl=mono \
          -i "$wav_out" \
          -filter_complex "[0:a]atrim=0:0.30[s0];[s0][1:a]concat=n=2:v=0:a=1[a]" \
          -map "[a]" \
          "$padded_out" 2>/dev/null

        if [ -f "$padded_wav" ]; then
          play_audio "$padded_wav"
          rm -f "$padded_wav" 2>/dev/null
        else
          play_audio "$wav_file"
        fi
      else
        play_audio "$wav_file"
      fi
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

  local tts_enabled
  tts_enabled=$(get_runtime_tts_enabled)

  if [ "$WATCHER_TTS" != "on" ] || [ "$tts_enabled" = "false" ]; then
    echo "$next_state" > "$STATE"
    return
  fi

  pkill -f "SpeechSynthesizer" 2>/dev/null

  if orpheus_available; then
    speak_orpheus "$text"
    echo "$next_state" > "$STATE"
  else
    (speak_fallback "$text"; echo "$next_state" > "$STATE") &
  fi
}

check_wake() {
  local cmd="$1"
  local lower
  lower=$(echo "$cmd" | tr '[:upper:]' '[:lower:]')
  echo "$lower" | grep -qE "$WAKE_WORDS"
}

strip_wake() {
  echo "$1" | sed -E 's/(hey|ok) jarvis[,.]? *//i; s/jarvis (wake|listen)[,.]? *//i' | sed 's/^[[:space:]]*//'
}

collect_input() {
  local collected="$1"
  sleep 0.5
  local extra
  extra=$(cat "$INPUT" 2>/dev/null)
  if [ -n "$extra" ]; then
    > "$INPUT"
    collected="$collected. $extra"
    log "ADDED: $extra"
  fi
  echo "$collected"
}

reload_route_model() {
  local route="$1"
  local model="$2"

  log "Reloading route=$route model=$model"
  curl -sf --max-time 30 "$OLLAMA_API/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"prompt\":\"\",\"keep_alive\":-1}" \
    > /dev/null 2>&1 || log "WARN: reload failed route=$route model=$model"
}

log "=== JARVIS WATCHER ONLINE ==="
log "Monitoring input: $INPUT"
log "Monitoring runtime mode: $RUNTIME_MODE"
log "Models -> fast=$OLLAMA_FAST reason=$OLLAMA_REASON code=$OLLAMA_CODE deep=$OLLAMA_DEEP"

if [ -f "$ACTIVE_PROFILE_JSON" ]; then
  log "Profile source: $ACTIVE_PROFILE_JSON"
else
  log "Profile source: legacy fallback mode"
fi

while true; do
  COMMAND=$(cat "$INPUT" 2>/dev/null)
  if [ -n "$COMMAND" ]; then
    > "$INPUT"
    NOW=$(date +%s)

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

    if [ "$AWAKE" = false ]; then
      AWAKE=true
      LAST_ACTIVE=$NOW
    fi

    COMMAND=$(collect_input "$COMMAND")

    log "HEARD: $COMMAND"
    echo "$COMMAND" > "$LAST_INPUT"
    echo "thinking" > "$STATE"
    echo "thinking" > "$EMOTION"
    LAST_ACTIVE=$(date +%s)

    BRAIN_CHOICE=$(route "$COMMAND")
    ROUTE_NAME=$(brain_to_route "$BRAIN_CHOICE")
    log "ROUTE -> brain=$BRAIN_CHOICE route=$ROUTE_NAME"

    case "$BRAIN_CHOICE" in
      ollama_fast)
        RESPONSE=$(call_ollama "$OLLAMA_FAST" "fast" "$COMMAND")
        ;;
      ollama_code)
        RESPONSE=$(call_ollama "$OLLAMA_CODE" "code" "$COMMAND")
        ;;
      ollama_reason)
        RESPONSE=$(call_ollama "$OLLAMA_REASON" "reason" "$COMMAND")
        ;;
      ollama_deep)
        RESPONSE=$(call_ollama "$OLLAMA_DEEP" "deep" "$COMMAND")
        ;;
      claude)
        RESPONSE=$(call_claude "$COMMAND")
        ;;
      *)
        RESPONSE=$(call_ollama "$OLLAMA_REASON" "reason" "$COMMAND")
        ;;
    esac

    NEW_INPUT=$(cat "$INPUT" 2>/dev/null)
    if [ -n "$NEW_INPUT" ]; then
      log "QUEUED: $NEW_INPUT"
    fi

    RESPONSE=$(echo "$RESPONSE" | sed 's/ *[Ss]peaking\.*//' | sed 's/[[:space:]]*$//')

    if [ -z "$RESPONSE" ]; then
      log "WARN: Empty response -> reloading route model"
      case "$BRAIN_CHOICE" in
        ollama_fast)
          reload_route_model "fast" "$OLLAMA_FAST"
          RESPONSE=$(call_ollama "$OLLAMA_FAST" "fast" "$COMMAND")
          ;;
        ollama_code)
          reload_route_model "code" "$OLLAMA_CODE"
          RESPONSE=$(call_ollama "$OLLAMA_CODE" "code" "$COMMAND")
          ;;
        ollama_reason)
          reload_route_model "reason" "$OLLAMA_REASON"
          RESPONSE=$(call_ollama "$OLLAMA_REASON" "reason" "$COMMAND")
          ;;
        ollama_deep)
          reload_route_model "deep" "$OLLAMA_DEEP"
          RESPONSE=$(call_ollama "$OLLAMA_DEEP" "deep" "$COMMAND")
          ;;
        claude)
          RESPONSE=$(call_claude "$COMMAND")
          ;;
      esac
    fi

    if [ -z "$RESPONSE" ]; then
      RESPONSE="I apologize sir, I encountered an issue. Please try again."
      log "WARN: Empty response after retry"
    fi

    LAST_BRAIN="$BRAIN_CHOICE"
    save_history "$COMMAND" "$RESPONSE"

    echo "$RESPONSE" > "$OUTPUT"
    echo "speaking" > "$STATE"
    echo "neutral" > "$EMOTION"
    log "SAID: $RESPONSE"

    NEXT_STATE="standby"
    if echo "$RESPONSE" | grep -qE '\?$|\? *$'; then
      NEXT_STATE="listening"
      log "Response is a question -> mic stays open"
    fi

    speak "$RESPONSE" "$NEXT_STATE"
    log "Ready (brain=$BRAIN_CHOICE tts_engine=$(get_runtime_tts_engine) persona=$(get_runtime_persona))"
  fi

  sleep 0.3
done