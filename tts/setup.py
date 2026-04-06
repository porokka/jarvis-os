"""
Orpheus TTS Setup — Downloads GGUF model + SNAC decoder

Run once: python tts/setup.py

Requirements:
  pip install huggingface-hub torch snac soundfile numpy

Downloads:
  - Orpheus 3B Q4_K_M GGUF (~2.5GB) for llama.cpp
  - SNAC audio decoder model
"""

import os
import sys
from pathlib import Path

TTS_DIR = Path(__file__).parent
MODELS_DIR = TTS_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

GGUF_REPO = "isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF"
GGUF_FILE = "orpheus-3b-0.1-ft-q4_k_m.gguf"


def download_gguf():
    """Download Orpheus GGUF model from HuggingFace."""
    from huggingface_hub import hf_hub_download

    target = MODELS_DIR / GGUF_FILE
    if target.exists():
        print(f"[OK] GGUF model already exists: {target}")
        return

    print(f"[DOWNLOAD] Orpheus 3B Q4_K_M GGUF from {GGUF_REPO}...")
    path = hf_hub_download(
        repo_id=GGUF_REPO,
        filename=GGUF_FILE,
        local_dir=str(MODELS_DIR),
    )
    print(f"[OK] Downloaded to: {path}")


def check_snac():
    """Verify SNAC decoder can be loaded."""
    try:
        import snac
        print("[OK] SNAC decoder available")
    except ImportError:
        print("[INSTALL] pip install snac")
        sys.exit(1)


def check_llama_cpp():
    """Check if llama-cpp-python is installed with CUDA."""
    try:
        from llama_cpp import Llama
        print("[OK] llama-cpp-python available")
    except ImportError:
        print("[INSTALL] Install llama-cpp-python with CUDA support:")
        print("  pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 50)
    print("Orpheus TTS Setup for Operation Jarvis")
    print("=" * 50)
    print()

    # Check dependencies
    check_snac()
    check_llama_cpp()

    # Download model
    download_gguf()

    print()
    print("=" * 50)
    print("[READY] Run the TTS server: python tts/server.py")
    print("=" * 50)
