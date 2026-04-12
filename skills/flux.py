"""
JARVIS Skill — FLUX image generation (direct, no ComfyUI).

Uses Black Forest Labs FLUX model for text-to-image generation.
Supports Schnell (fast, 4 steps) and Dev (quality, 20 steps).

Workflow:
  1. Optionally enhance prompt via Ollama
  2. Unload Ollama from VRAM
  3. Generate image via FLUX
  4. Save to vault/Daily/images/
  5. Reload Ollama

Requirements:
  pip install flux[all]
  Model downloads on first use (~6-12GB)
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

SKILL_NAME = "flux"
SKILL_DESCRIPTION = "FLUX AI image generation — text to image with prompt enhancement"

VAULT_DIR = Path("/mnt/d/Jarvis_vault") if os.name != "nt" else Path("D:/Jarvis_vault")
IMAGES_DIR = VAULT_DIR / "Daily" / "images"
FLUX_DIR = Path("/mnt/e/coding/flux") if os.name != "nt" else Path("E:/coding/flux")
OLLAMA_HOST = "http://localhost:11434"

# Config
CONFIG_FILE = Path(__file__).parent.parent / "config" / "flux.json"

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

    system = (
        "You are an expert image prompt engineer for FLUX AI image generation. "
        "Rewrite the user's rough description into a detailed, high-quality prompt. "
        "Include: subject, art style, lighting, composition, camera angle, color palette, mood. "
        "Under 150 words. Output ONLY the enhanced prompt, nothing else."
    )

    payload = json.dumps({
        "model": "qwen3:30b-a3b",
        "prompt": user_prompt,
        "system": system,
        "stream": False,
        "options": {"num_predict": 250},
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
        # Strip thinking tags
        if "<think>" in enhanced:
            import re
            enhanced = re.sub(r'<think>.*?</think>', '', enhanced, flags=re.DOTALL).strip()
        return enhanced or user_prompt
    except Exception as e:
        print(f"[FLUX] Prompt enhancement failed: {e}")
        return user_prompt


def _unload_ollama():
    """Unload Ollama models to free VRAM."""
    import urllib.request
    try:
        payload = json.dumps({
            "model": "qwen3:30b-a3b",
            "keep_alive": 0,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        time.sleep(3)
        print("[FLUX] Ollama unloaded from VRAM")
    except Exception:
        pass


def _reload_ollama():
    """Reload Ollama model into VRAM."""
    import urllib.request
    try:
        payload = json.dumps({
            "model": "qwen3:30b-a3b",
            "prompt": "",
            "keep_alive": -1,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=30)
        print("[FLUX] Ollama reloaded")
    except Exception:
        pass


def exec_generate_image(prompt: str, enhance: str = "yes") -> str:
    """Generate an image using FLUX."""
    cfg = _load_config()

    # Step 1: Enhance prompt
    if enhance.lower() in ("yes", "true", "1", ""):
        print(f"[FLUX] Enhancing prompt: {prompt[:50]}...")
        enhanced = _enhance_prompt(prompt)
        print(f"[FLUX] Enhanced: {enhanced[:80]}...")
    else:
        enhanced = prompt

    # Step 2: Unload Ollama
    print("[FLUX] Unloading Ollama for VRAM...")
    _unload_ollama()

    # Step 3: Generate image
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = IMAGES_DIR / f"flux_{ts}.png"

    model = cfg.get("model", "schnell")
    width = cfg.get("width", 1024)
    height = cfg.get("height", 1024)
    steps = cfg.get("steps", 4)
    guidance = cfg.get("guidance", 3.5)

    try:
        # Run FLUX via CLI
        cmd = [
            "python3", "-m", "flux",
            "--name", f"flux-{model}",
            "--width", str(width),
            "--height", str(height),
            "--num_steps", str(steps),
            "--guidance", str(guidance),
            "--output_dir", str(IMAGES_DIR),
            "--prompt", enhanced,
        ]

        print(f"[FLUX] Generating {width}x{height} with {model} ({steps} steps)...")
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=300,
            cwd=str(FLUX_DIR),
        )

        output = (result.stdout + result.stderr).strip()
        print(f"[FLUX] Output: {output[:200]}")

        # Find generated image
        if result.returncode == 0:
            # Look for newest image in output dir
            images = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
            if images:
                img_path = images[0]
                _reload_ollama()
                return (
                    f"Image generated: {img_path.name}\n"
                    f"Path: {img_path}\n"
                    f"Prompt: {enhanced[:100]}..."
                )

        _reload_ollama()
        return f"Generation may have failed. Output:\n{output[:500]}"

    except subprocess.TimeoutExpired:
        _reload_ollama()
        return "Image generation timed out (5 minutes)."
    except Exception as e:
        _reload_ollama()
        return f"FLUX error: {e}"


def exec_flux(action: str, prompt: str = "", enhance: str = "yes") -> str:
    """FLUX image generation dispatcher."""
    action = action.lower().strip()

    if action in ("generate", "create", "make"):
        if not prompt:
            return "Please provide a prompt. Example: generate an image of a sunset over mountains"
        return exec_generate_image(prompt, enhance)

    elif action == "status":
        flux_ok = FLUX_DIR.exists() and (FLUX_DIR / "src").exists()
        return (
            f"FLUX: {'installed' if flux_ok else 'not found'} at {FLUX_DIR}\n"
            f"Output dir: {IMAGES_DIR}\n"
            f"Config: {json.dumps(_load_config(), indent=2)}"
        )

    elif action == "recent":
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        images = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if images:
            lines = [f"  {img.name} ({img.stat().st_size // 1024}KB)" for img in images[:10]]
            return "Recent images:\n" + "\n".join(lines)
        return "No images generated yet."

    else:
        return "Available actions: generate <prompt>, status, recent"


# -- Tool definitions --

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "flux",
            "description": "Generate images using FLUX AI. 'generate' creates an image from a text prompt (auto-enhanced by Qwen3). 'status' checks FLUX installation. 'recent' lists recent images.",
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
            },
        },
    },
]

TOOL_MAP = {
    "flux": exec_flux,
}

KEYWORDS = {
    "flux": [
        "generate image", "create image", "make image", "draw",
        "flux", "picture", "photo", "illustration", "render",
    ],
}
