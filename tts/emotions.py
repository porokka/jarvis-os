"""
Emotion Mapper — Bridges Orpheus TTS tags to MetaHuman face expressions

Maps Claude's [EMOTION:xxx] output to:
  1. Orpheus inline tags for expressive speech
  2. MetaHuman emotion file (emotion.txt) for face animation

Usage:
  from emotions import prepare_for_tts, EMOTION_MAP

  tts_text, ue_emotion = prepare_for_tts(claude_response)
"""

# Mapping from Jarvis emotion → Orpheus TTS tag to inject
ORPHEUS_TAGS = {
    "happy": "<chuckle>",
    "serious": "",
    "thinking": "<sigh>",
    "confused": "",
    "neutral": "",
    "laughing": "<laugh>",
    "sad": "<sigh>",
    "surprised": "<gasp>",
    "tired": "<yawn>",
    "annoyed": "<groan>",
}

# Mapping from Jarvis emotion → MetaHuman morph target values
METAHUMAN_MORPHS = {
    "neutral": {
        "brow_inner_up": 0.0,
        "mouth_smile_L": 0.0,
        "mouth_smile_R": 0.0,
    },
    "thinking": {
        "brow_inner_up": 0.3,
        "eye_look_up_L": 0.2,
        "eye_look_up_R": 0.2,
    },
    "happy": {
        "mouth_smile_L": 0.6,
        "mouth_smile_R": 0.6,
        "cheek_squint_L": 0.3,
        "cheek_squint_R": 0.3,
    },
    "serious": {
        "brow_down_L": 0.3,
        "brow_down_R": 0.3,
        "mouth_press_L": 0.2,
        "mouth_press_R": 0.2,
    },
    "confused": {
        "brow_inner_up": 0.4,
        "brow_outer_up_L": 0.3,
        "mouth_pucker": 0.2,
    },
    "surprised": {
        "brow_inner_up": 0.5,
        "brow_outer_up_L": 0.4,
        "brow_outer_up_R": 0.4,
        "jaw_open": 0.3,
    },
}


def prepare_for_tts(claude_response: str) -> tuple[str, str]:
    """
    Parse Claude's response for emotion prefix and prepare for TTS.

    Input:  "[EMOTION:happy]\nGlad to help with that."
    Output: ("<chuckle> Glad to help with that.", "happy")

    Returns (tts_text, emotion_name)
    """
    lines = claude_response.strip().split("\n")
    emotion = "neutral"
    text_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[EMOTION:") and stripped.endswith("]"):
            emotion = stripped[9:-1].lower()
        else:
            text_lines.append(line)

    text = "\n".join(text_lines).strip()

    # Inject Orpheus emotion tag at start if available
    tag = ORPHEUS_TAGS.get(emotion, "")
    if tag:
        text = f"{tag} {text}"

    return text, emotion


def get_morphs(emotion: str) -> dict[str, float]:
    """Get MetaHuman morph target values for an emotion."""
    return METAHUMAN_MORPHS.get(emotion, METAHUMAN_MORPHS["neutral"])
