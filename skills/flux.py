"""
JARVIS Skill — FLUX image generation via ComfyUI.

Uses FLUX model through ComfyUI for text-to-image generation.
Supports prompt enhancement, Ollama VRAM swap, and image export
to the vault Daily/images directory.
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
import threading

SKILL_NAME = "flux"
SKILL_DESCRIPTION = "FLUX AI image generation via ComfyUI — text to image with prompt enhancement"

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
IMAGES_DIR = VAULT_DIR / "Daily" / "images"
FLUX_DIR = Path("/mnt/e/coding/flux") if os.name != "nt" else Path("E:/coding/flux")
OLLAMA_HOST = "http://localhost:11434"

CONFIG_FILE = Path(__file__).parent.parent / "config" / "flux.json"
MODEL_CONFIG_FILE = Path(__file__).parent.parent / "config" / "models-config.json"


def _load_model_config() -> dict:
    try:
        return json.loads(MODEL_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_small_runtime_model() -> str:
    cfg = _load_model_config()
    models = cfg.get("models", {}) if isinstance(cfg, dict) else {}

    return (
        models.get("live")
        or models.get("fast")
        or "gemma4:e4b"
    )

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "model": "schnell",
            "width": 1024,
            "height": 1024,
            "steps": 4,
            "guidance": 3.5,
            "enhance_prompts": True,
        }


def _enhance_prompt(user_prompt: str) -> str:
    """Use Ollama to enhance a rough prompt into a detailed image generation prompt."""
    import urllib.request
    import re

    system = (
        "You are an expert image prompt engineer for FLUX AI image generation. "
        "Rewrite the user's rough description into a detailed, high-quality prompt. "
        "Include: subject, art style, lighting, composition, camera angle, color palette, mood. "
        "Under 150 words. Output ONLY the enhanced prompt, nothing else."
    )

    payload = json.dumps({
        "model": "qwen3.6:27b",
        "prompt": user_prompt,
        "system": system,
        "stream": False,
        "options": {"num_predict": 500},
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        enhanced = data.get("response", "").strip()

        if "<think>" in enhanced:
            enhanced = re.sub(r"<think>.*?</think>", "", enhanced, flags=re.DOTALL).strip()

        return enhanced or user_prompt
    except Exception as e:
        print(f"[FLUX] Prompt enhancement failed: {e}")
        return user_prompt


def _ollama_model(model: str, keep_alive: int = -1):
    """Load or unload an Ollama model."""
    import urllib.request
    try:
        payload = json.dumps({
            "model": model,
            "prompt": "",
            "keep_alive": keep_alive,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass


def _swap_to_mini():
    """Unload big models and keep the configured fast/live model available during FLUX."""
    small_model = _get_small_runtime_model()

    print("[FLUX] Swapping to small runtime model...")

    for model in [
        "qwen3.6:27b",
        "qwen3:14b",
    ]:
        if model != small_model:
            _ollama_model(model, keep_alive=0)

    time.sleep(2)

    _ollama_model(small_model, keep_alive=-1)

    print(f"[FLUX] Small runtime model loaded: {small_model}")


def _restore_big():
    """Kill ComfyUI + restore big Ollama model."""
    print("[FLUX] Stopping ComfyUI...")
    subprocess.run(["pkill", "-f", "python3 main.py"], capture_output=True, timeout=5)
    time.sleep(3)
    print("[FLUX] Flux killed")

def _start_comfyui_if_needed():
    """Start ComfyUI in background. Returns True if ready or already running."""
    import urllib.request as _ur
    try:
        _ur.urlopen("http://localhost:8188/system_stats", timeout=2)
        print("[FLUX] ComfyUI already running")
        return True
    except Exception:
        print("[FLUX] Starting ComfyUI in background...")
        _swap_to_mini()
        subprocess.Popen(
            ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"],
            cwd="/mnt/e/coding/ComfyUI",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return False


def _wait_for_comfyui(timeout_secs: int = 60) -> bool:
    """Wait for ComfyUI to be ready."""
    import urllib.request as _ur
    for _ in range(timeout_secs // 2):
        try:
            _ur.urlopen("http://localhost:8188/system_stats", timeout=2)
            print("[FLUX] ComfyUI ready")
            return True
        except Exception:
            time.sleep(2)
    return False


def exec_generate_image(prompt: str, enhance: str = "yes") -> str:
    """Generate an image using FLUX through ComfyUI."""
    cfg = _load_config()
    import urllib.request as _ur
    import random
    import shutil

    comfyui_was_running = _start_comfyui_if_needed()

    if enhance.lower() in ("yes", "true", "1", ""):
        print("[FLUX] Enhancing prompt (ComfyUI loading in parallel)...")
        enhanced = _enhance_prompt(prompt)
        print(f"[FLUX] Enhanced: {enhanced[:80]}...")
    else:
        enhanced = prompt

    if not comfyui_was_running:
        _swap_to_mini()

    if not _wait_for_comfyui(60):
        _restore_big()
        return "ComfyUI failed to start."

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    model = cfg.get("model", "dev")
    width = cfg.get("width", 1024)
    height = cfg.get("height", 1024)
    steps = cfg.get("steps", 20)
    guidance = cfg.get("guidance", 3.5)

    try:
        print("[FLUX] Generating via ComfyUI")
        seed = random.randint(0, 2**32)

        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": "flux1-dev-fp8.safetensors"
                }
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": enhanced,
                    "clip": ["1", 1]
                }
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": "",
                    "clip": ["1", 1]
                }
            },
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                }
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": 1.0,
                    "sampler_name": "euler",
                    "scheduler": "simple",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0]
                }
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["1", 2]
                }
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": f"jarvis_flux_{ts}",
                    "images": ["6", 0]
                }
            },
        }

        payload = json.dumps({"prompt": workflow}).encode("utf-8")
        req = _ur.Request(
            "http://localhost:8188/prompt",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp_data = json.loads(_ur.urlopen(req, timeout=10).read())
        prompt_id = resp_data.get("prompt_id")

        for _ in range(90):
            time.sleep(3)
            hist = json.loads(_ur.urlopen(f"http://localhost:8188/history/{prompt_id}", timeout=5).read())
            entry = hist.get(prompt_id, {})

            if entry.get("status", {}).get("status_str") == "error":
                _restore_big()
                return "ComfyUI generation failed."

            outputs = entry.get("outputs", {})
            for nid in outputs:
                images = outputs[nid].get("images", [])
                if images:
                    img = images[0]
                    src = Path(f"/mnt/e/coding/ComfyUI/output/{img['filename']}")
                    dst = IMAGES_DIR / img["filename"]
                    if src.exists():
                        shutil.copy2(str(src), str(dst))
                    _restore_big()
                    return f"Image generated: {img['filename']}\nPath: {dst}\nPrompt: {enhanced[:100]}..."

        _restore_big()
        return "Generation timed out."

    except Exception as e:
        _restore_big()
        return f"FLUX error: {e}"

def exec_flux(action: str, prompt: str = "", enhance: str = "yes", async_mode: str = "no") -> str:
    action = action.lower().strip()

    if action in ("generate", "create", "make"):
        if not prompt:
            return "Please provide a prompt."

        if async_mode.lower() in ("yes", "true", "1"):
            def worker():
                exec_generate_image(prompt, enhance)

            threading.Thread(target=worker, daemon=True).start()

            return json.dumps({
                "status": "started",
                "message": "Image generation started.",
                "prompt": prompt,
            }, ensure_ascii=False)

        return exec_generate_image(prompt, enhance)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "flux",
            "description": "Generate images using FLUX AI via ComfyUI. 'generate' creates an image from a text prompt (optionally enhanced by Ollama). 'status' checks FLUX installation. 'recent' lists recent images.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: generate, status, recent",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Image description for generation",
                    },
                    "enhance": {
                        "type": "string",
                        "description": "Enhance prompt with AI? 'yes' (default) or 'no'",
                    },
                },
                "required": ["action"],
                "async_mode": {
                            "type": "string",
                            "description": "Run generation in background? yes or no",
}
            },
        },
    },
]

TOOL_MAP = {
    "flux": exec_flux,
}

KEYWORDS = {
    "flux": [
        "generate image",
        "create image",
        "make image",
        "draw",
        "flux",
        "picture",
        "photo",
        "illustration",
        "render",
    ],
}

SKILL_META = {
    "intent_aliases": [
        "image generation",
        "generate image",
        "create image",
        "make image",
        "draw image",
        "flux",
        "picture",
        "illustration",
        "render",
    ],
    "keywords": [
        "generate image",
        "create image",
        "make image",
        "draw",
        "draw image",
        "flux",
        "picture",
        "photo",
        "illustration",
        "render",
        "image generator",
        "text to image",
    ],
    "route": "reason",
    "tools": {
        "flux": {
            "intent_aliases": [
                "generate image",
                "create image",
                "make image",
                "draw image",
                "flux",
            ],
            "keywords": [
                "generate image",
                "create image",
                "make image",
                "draw",
                "draw image",
                "flux",
                "picture",
                "photo",
                "illustration",
                "render",
                "text to image",
            ],
            "direct_match": [
                "generate image",
                "create image",
                "make image",
                "draw image",
                "text to image",
            ],
            "route": "reason",
        }
    },
}