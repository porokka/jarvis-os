"""
JARVIS Unreal Engine Bridge

Polls output.txt and state.txt, drives MetaHuman face animations.
Run this inside Unreal Engine's Python console:
    import jarvis_bridge

Setup:
  1. Enable Python Editor Script Plugin in UE
  2. Set JARVIS_DIR to your operation-jarvis folder
  3. Set METAHUMAN_ACTOR_NAME to your MetaHuman actor
  4. Set animation paths to your idle/thinking/speaking anims
"""

import unreal
import os
import time

# ============================================================
# CONFIG — Edit these for your project
# ============================================================
JARVIS_DIR = "D:/coding/operation-jarvis"
METAHUMAN_ACTOR_NAME = "BP_MetaHuman_Jarvis"

# Animation asset paths (set these to your actual animation assets)
ANIMS = {
    "idle": "/Game/Jarvis/Animations/Idle_Breathing",
    "thinking": "/Game/Jarvis/Animations/Thinking_HeadTilt",
    "speaking": "/Game/Jarvis/Animations/Speaking_Generic",
}

# Poll interval in seconds
POLL_INTERVAL = 0.3

# ============================================================
# FILE I/O
# ============================================================
def read_file(name):
    """Read a bridge file, return empty string if missing."""
    path = os.path.join(JARVIS_DIR, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def write_file(name, content):
    """Write to a bridge file."""
    path = os.path.join(JARVIS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ============================================================
# UNREAL HELPERS
# ============================================================
def get_metahuman():
    """Find the MetaHuman actor in the current level."""
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for actor in actors:
        if actor.get_name() == METAHUMAN_ACTOR_NAME:
            return actor
    unreal.log_warning(f"[JARVIS] MetaHuman '{METAHUMAN_ACTOR_NAME}' not found in level")
    return None


def play_animation(actor, anim_key):
    """Play an animation on the MetaHuman skeletal mesh."""
    if not actor or anim_key not in ANIMS:
        return

    anim_path = ANIMS[anim_key]
    anim_asset = unreal.load_asset(anim_path)
    if not anim_asset:
        unreal.log_warning(f"[JARVIS] Animation not found: {anim_path}")
        return

    # Get skeletal mesh component
    mesh_comp = actor.get_component_by_class(unreal.SkeletalMeshComponent)
    if mesh_comp:
        mesh_comp.play_animation(anim_asset, True)
        unreal.log(f"[JARVIS] Playing: {anim_key}")


def set_face_expression(actor, emotion):
    """
    Drive MetaHuman face blend shapes based on emotion.
    This uses morph targets — adjust names to match your MetaHuman rig.
    """
    if not actor:
        return

    face_comp = None
    components = actor.get_components_by_class(unreal.SkeletalMeshComponent)
    for comp in components:
        if "face" in comp.get_name().lower():
            face_comp = comp
            break

    if not face_comp:
        return

    # Reset all expression morphs
    expressions = {
        "neutral": {"brow_inner_up": 0.0, "mouth_smile_L": 0.0, "mouth_smile_R": 0.0},
        "thinking": {"brow_inner_up": 0.3, "eye_look_up_L": 0.2, "eye_look_up_R": 0.2},
        "happy": {"mouth_smile_L": 0.6, "mouth_smile_R": 0.6, "cheek_squint_L": 0.3},
        "serious": {"brow_down_L": 0.3, "brow_down_R": 0.3, "mouth_press_L": 0.2},
        "confused": {"brow_inner_up": 0.4, "brow_outer_up_L": 0.3, "mouth_pucker": 0.2},
    }

    morphs = expressions.get(emotion, expressions["neutral"])
    for morph_name, value in morphs.items():
        face_comp.set_morph_target(morph_name, value)


# ============================================================
# MAIN POLL LOOP
# ============================================================
class JarvisBridge:
    def __init__(self):
        self.last_state = ""
        self.last_output = ""
        self.last_emotion = ""
        self.metahuman = get_metahuman()
        self.running = True

        if self.metahuman:
            unreal.log(f"[JARVIS] Found MetaHuman: {METAHUMAN_ACTOR_NAME}")
        else:
            unreal.log_warning("[JARVIS] No MetaHuman found — running in headless mode")

        unreal.log("[JARVIS] Bridge online. Polling bridge files...")

    def tick(self, delta_time):
        """Called each tick by Unreal's timer."""
        state = read_file("state.txt")
        emotion = read_file("emotion.txt")
        output_text = read_file("output.txt")

        # State changed → switch animation
        if state != self.last_state:
            self.last_state = state
            unreal.log(f"[JARVIS] State → {state}")

            if state == "thinking":
                play_animation(self.metahuman, "thinking")
            elif state == "speaking":
                play_animation(self.metahuman, "speaking")
            else:
                play_animation(self.metahuman, "idle")

        # Emotion changed → update face
        if emotion != self.last_emotion:
            self.last_emotion = emotion
            set_face_expression(self.metahuman, emotion)

        # New output → log it (TTS is handled by watcher.sh)
        if output_text != self.last_output:
            self.last_output = output_text
            if output_text:
                unreal.log(f"[JARVIS] Says: {output_text[:80]}...")

    def stop(self):
        self.running = False
        unreal.log("[JARVIS] Bridge stopped")


# ============================================================
# START
# ============================================================
bridge = JarvisBridge()

# Register tick function with Unreal's slate ticker
tick_handle = unreal.register_slate_post_tick_callback(bridge.tick)

unreal.log("=" * 50)
unreal.log("[JARVIS] Unreal bridge active")
unreal.log(f"[JARVIS] Watching: {JARVIS_DIR}")
unreal.log("=" * 50)

# To stop: unreal.unregister_slate_post_tick_callback(tick_handle)
