#!/usr/bin/env python3
"""
JARVIS Voice Capture — Always-on mic with wake word detection

Modes:
  1. Always-on: every utterance goes to JARVIS
  2. Wake word: only activates after "hey jarvis" / "ok jarvis"

Requirements:
  pip install sounddevice soundfile numpy openai-whisper --break-system-packages
"""

import os
# Force CPU — keep GPU free for Ollama
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import sounddevice as sd
import soundfile as sf
import numpy as np
import whisper
import torch
import sys
import time
import tempfile

BRIDGE = "/tmp/jarvis"
INPUT_FILE = os.path.join(BRIDGE, "input.txt")
STATE_FILE = os.path.join(BRIDGE, "state.txt")
OUTPUT_FILE = os.path.join(BRIDGE, "output.txt")

VAULT_DIR = "/mnt/d/Jarvis_vault" if os.name != "nt" else "D:/Jarvis_vault"
TRANSCRIPT_LOG = os.path.join(VAULT_DIR, "transcript.log")


def log_transcript(tag: str, text: str):
    """Append timestamped transcript entry to persistent log."""
    try:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(TRANSCRIPT_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{tag}] {text}\n")
    except Exception:
        pass

SAMPLE_RATE = 16000
SILENCE_DURATION = 2.5    # long patience — people pause mid-sentence
MAX_DURATION = 15         # allow long commands

# Silero VAD — proper speech detection
print("Loading Silero VAD...")
vad_model, vad_utils = torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)
(get_speech_timestamps, _, read_audio, _, _) = vad_utils

WAKE_WORDS = [
    "hey jarvis", "ok jarvis", "jarvis",
    "hey charvis", "charwis", "jarvus", "jarvas",
    "hey travis", "hey service", "hey jervis",
    "ok jarves", "okay jarvis", "okay jarves",
]
WAKE_MODE = "--wake" in sys.argv  # pass --wake for wake word mode
FUZZY_MODE = "--fuzzy" in sys.argv  # pass --fuzzy to enable fuzzy matching
AWAKE_TIMEOUT = 30  # seconds before going back to sleep

print("Loading Whisper model...")
model = whisper.load_model("base")  # base is more accurate for wake word detection
print(f"JARVIS voice capture ready. Mode: {'wake word' if WAKE_MODE else 'always-on'} | Fuzzy: {'ON' if FUZZY_MODE else 'OFF'}")


def get_state():
    try:
        with open(STATE_FILE) as f:
            return f.read().strip()
    except:
        return "standby"


def get_last_output() -> str:
    """Read JARVIS's last spoken output for echo detection."""
    try:
        with open(OUTPUT_FILE) as f:
            return f.read().strip().lower()
    except:
        return ""


def is_echo(text: str, threshold: float = 0.5) -> bool:
    """Check if transcribed text is JARVIS echoing itself.

    Compares against last output — if >50% of words overlap, it's echo.
    """
    last = get_last_output()
    if not last or len(last) < 5:
        return False

    heard_words = set(text.lower().split())
    output_words = set(last.split())

    if not heard_words:
        return False

    # What fraction of heard words appear in JARVIS's last output?
    overlap = heard_words & output_words
    ratio = len(overlap) / len(heard_words)

    if ratio >= threshold:
        return True

    # Also check substring match — Whisper might transcribe a fragment
    heard_lower = text.lower().strip()
    if len(heard_lower) > 8 and heard_lower in last:
        return True

    return False


def has_speech_vad(audio_chunk: np.ndarray) -> bool:
    """Use Silero VAD to check if audio contains speech."""
    tensor = torch.from_numpy(audio_chunk).float()
    if tensor.dim() > 1:
        tensor = tensor[:, 0]
    # VAD expects 512 samples at 16kHz
    confidence = vad_model(tensor, SAMPLE_RATE).item()
    return confidence > 0.5


def wait_for_speech(stream):
    """Block until VAD detects real speech. Returns the first chunk."""
    # Read in 512-sample chunks for VAD
    chunk_size = 512
    buffer = []
    while True:
        data, _ = stream.read(chunk_size)
        flat = data.flatten()
        buffer.append(flat)
        vol = np.abs(flat).mean()

        is_speech = has_speech_vad(flat)
        icon = "█" if is_speech else "░"
        print(f"\r  {icon} vol:{vol:.4f}", end="", flush=True)

        if is_speech:
            print(f"\r  █ SPEECH DETECTED (vol:{vol:.4f})")
            # Return last 0.5s of buffer as context
            context = np.concatenate(buffer[-int(0.5 * SAMPLE_RATE / chunk_size):])
            return context


def record_until_silence(stream, first_chunk):
    """Record until VAD says speech stopped."""
    frames = [first_chunk]
    no_speech_count = 0
    silence_limit = int(SILENCE_DURATION * SAMPLE_RATE / 512)
    chunk_size = 512

    for i in range(int(MAX_DURATION * SAMPLE_RATE / chunk_size)):
        data, _ = stream.read(chunk_size)
        flat = data.flatten()
        frames.append(flat)

        is_speech = has_speech_vad(flat)

        if i % int(SAMPLE_RATE / chunk_size) == 0:
            secs = i * chunk_size // SAMPLE_RATE
            vol = np.abs(flat).mean()
            icon = "█" if is_speech else "░"
            print(f"\r  [{secs}s] {icon} vol:{vol:.4f}", end="", flush=True)

        if is_speech:
            no_speech_count = 0
        else:
            no_speech_count += 1
            if no_speech_count > silence_limit:
                break

    print()
    return np.concatenate(frames)


def transcribe(audio):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, audio, SAMPLE_RATE)
        result = model.transcribe(
            f.name, language="en", fp16=False,
            initial_prompt="Hey JARVIS, OK JARVIS, play radio, stop radio, check my projects, scan network, set timer",
        )
        os.unlink(f.name)
        return result["text"].strip()


# Voice corrections — load from vault
TRANSLATIONS = {}
TRANSLATIONS_FILE = "/mnt/d/Jarvis_vault/References/voice-translations.md"

def load_translations():
    """Parse translations from the vault markdown table."""
    global TRANSLATIONS
    try:
        with open(TRANSLATIONS_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("|") and "|" in line[1:] and "Heard" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) == 2:
                        TRANSLATIONS[parts[0].lower()] = parts[1]
    except:
        pass

load_translations()
print(f"Loaded {len(TRANSLATIONS)} voice translations")


COMMON_WORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "am",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "do", "did", "does", "have", "has", "had", "will", "would", "can", "could",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up", "as",
    "and", "or", "but", "not", "no", "so", "if", "how", "what", "who", "that",
    "this", "then", "than", "just", "like", "get", "got", "go", "come", "say",
    "said", "know", "see", "make", "take", "want", "give", "use", "find", "tell",
    "today", "now", "here", "there", "all", "some", "any", "very", "too", "also"}

def fuzzy_match(word: str, target: str, threshold: float = 0.6) -> bool:
    """Check if two strings are similar enough."""
    from difflib import SequenceMatcher
    # Never fuzzy-correct common English words
    if word.lower().rstrip(".,?!") in COMMON_WORDS:
        return False
    if len(word) <= 2 and len(target) > 3:
        return False
    return SequenceMatcher(None, word.lower(), target.lower()).ratio() >= threshold


def correct_text(text: str) -> str:
    """Apply voice translation corrections — exact first, then fuzzy only on short commands."""
    lower = text.lower()

    # Exact match always
    for wrong, right in TRANSLATIONS.items():
        if wrong in lower:
            idx = lower.find(wrong)
            text = text[:idx] + right + text[idx + len(wrong):]
            lower = text.lower()

    if not FUZZY_MODE:
        return text

    # Fuzzy match only on short text (max 6 words)
    words = text.split()
    if len(words) > 6:
        return text

    changed = False
    for i in range(len(words)):
        for wrong, right in TRANSLATIONS.items():
            if fuzzy_match(words[i], wrong):
                print(f"  [FUZZY] '{words[i]}' ≈ '{wrong}' → '{right}'")
                words[i] = right
                changed = True
                break
        if i < len(words) - 1:
            combo = f"{words[i]} {words[i+1]}"
            for wrong, right in TRANSLATIONS.items():
                if fuzzy_match(combo, wrong):
                    print(f"  [FUZZY] '{combo}' ≈ '{wrong}' → '{right}'")
                    words[i] = right
                    words[i+1] = ""
                    changed = True
                    break

    if changed:
        return " ".join(w for w in words if w)
    return text


def has_wake_word(text):
    lower = text.lower()
    for wake in WAKE_WORDS:
        if wake in lower:
            return True
    return False


def strip_wake_word(text):
    lower = text.lower()
    for wake in WAKE_WORDS:
        idx = lower.find(wake)
        # Only strip if wake word is near the beginning (first 20 chars)
        if idx != -1 and idx < 20:
            result = text[idx + len(wake):].strip().lstrip(",").lstrip(".").strip()
            return result
    return text


def send_to_jarvis(text):
    os.makedirs(BRIDGE, exist_ok=True)
    with open(INPUT_FILE, "w") as f:
        f.write(text)
    log_transcript("SENT", text)
    print(f"  → SENT: {text}")


awake = not WAKE_MODE  # always-on if no --wake flag
awake_until = 0
last_speaking_end = 0  # timestamp when JARVIS stopped speaking
SPEAKING_COOLDOWN = 2.5  # seconds to ignore audio after JARVIS speaks

print("Listening for voice... (speak loudly to trigger)")

with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', blocksize=1024) as mic:
  while True:
    state = get_state()

    if state in ("thinking", "speaking"):
        last_speaking_end = time.time()
        # Command is being processed — reset awake state
        if awake:
            awake = False
            awake_until = 0
            print("  [SLEEP] Command processing — wake word required for next command")
        time.sleep(0.5)
        continue

    # Cooldown after JARVIS stops speaking — ignore its own echo
    if time.time() - last_speaking_end < SPEAKING_COOLDOWN:
        time.sleep(0.3)
        continue

    try:
        # Stage 1: VAD waits for real speech (not noise/traffic)
        first_chunk = wait_for_speech(mic)

        # Re-check state — JARVIS may have started speaking while VAD was waiting
        state = get_state()
        if state in ("thinking", "speaking"):
            time.sleep(1.0)
            continue

        # Stage 2: record until VAD says speech stopped
        audio = record_until_silence(mic, first_chunk)

        if len(audio) == 0:
            continue

        text = transcribe(audio)

        if not text or len(text) < 3:
            continue

        # Echo detection — skip if JARVIS is hearing itself
        if is_echo(text):
            print(f"  [ECHO] '{text}' — matches last output, skipped")
            log_transcript("ECHO", text)
            continue

        # Filter out noise/hallucinations
        noise_patterns = [
            "thank you", "thanks for watching", "subscribe", "like and subscribe",
            "you", "the", "i", "a", "so", "um", "uh", "hmm",
            "ideas", "expected", "cycles", "silence", "music",
            "applause", "laughter", "foreign", "inaudible",
        ]
        lower = text.lower().strip().rstrip(".")
        words = text.split()

        # Single word noise
        if lower in noise_patterns or len(words) < 2:
            print(f"  [NOISE] '{text}' — skipped")
            log_transcript("NOISE", text)
            continue

        # Whisper hallucination: transcribes the initial_prompt on silence
        if "suomipop" in lower and "radio nova" in lower and "stockwatch" in lower:
            print(f"  [HALLUCINATION] '{text[:50]}' — initial_prompt leak, skipped")
            log_transcript("HALLUCINATION", text)
            continue

        # Long sentences = TV/background audio, not a voice command
        # Apply even when awake — real commands are short
        if len(words) > 15 and not has_wake_word(text):
            print(f"  [TV/BG] '{text[:50]}...' — too long for command, skipped")
            log_transcript("TV/BG", text)
            continue

        # Fuzzy correction disabled — exact matches only
        corrected = correct_text(text)
        if corrected != text:
            print(f"[HEARD]: {text} → [CORRECTED]: {corrected}")
            log_transcript("HEARD", text)
            log_transcript("CORRECTED", corrected)
            text = corrected
        else:
            print(f"[HEARD]: {text}")
            log_transcript("HEARD", text)

        now = time.time()

        if WAKE_MODE:
            if has_wake_word(text):
                awake = True
                awake_until = now + AWAKE_TIMEOUT
                command = strip_wake_word(text)
                if command:
                    send_to_jarvis(command)
                    awake_until = now + AWAKE_TIMEOUT  # reset timer on each command
                else:
                    send_to_jarvis("hey jarvis")
                    print(f"  [awake for {AWAKE_TIMEOUT}s — listening...]")
            elif awake and now < awake_until:
                send_to_jarvis(text)
                awake_until = now + AWAKE_TIMEOUT  # reset timer on each command
            elif awake:
                awake = False
                print("  [timed out — sleeping. Say 'hey jarvis' to wake]")
            else:
                pass  # sleeping, ignore
        else:
            # Always-on mode — send everything
            send_to_jarvis(text)

    except KeyboardInterrupt:
        print("\nVoice capture stopped.")
        break
    except Exception as e:
        print(f"[ERROR]: {e}")
        time.sleep(1)
