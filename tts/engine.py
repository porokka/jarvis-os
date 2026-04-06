"""
Orpheus TTS Engine — Local inference via llama.cpp + SNAC decoder

Converts text (with optional emotion tags) to WAV audio.
Supports streaming for low-latency output.

Emotion tags: <laugh>, <chuckle>, <sigh>, <gasp>, <yawn>, <groan>, <cough>, <sniffle>
Voices: tara, leah, jess, leo, dan, mia, zac, zoe
"""

import io
import struct
import wave
from pathlib import Path
from typing import Generator

import numpy as np
import torch

MODELS_DIR = Path(__file__).parent / "models"
GGUF_FILE = "orpheus-3b-0.1-ft-q4_k_m.gguf"

# SNAC special token ranges for decoding
SNAC_TOKEN_START = 10
SNAC_LAYERS = [
    (SNAC_TOKEN_START, SNAC_TOKEN_START + 4096),       # Layer 0: coarse
    (SNAC_TOKEN_START + 4096, SNAC_TOKEN_START + 8192), # Layer 1: mid
    (SNAC_TOKEN_START + 8192, SNAC_TOKEN_START + 12288),# Layer 2: fine
]

# Custom token IDs used by Orpheus
START_TOKEN = 128259
END_TOKENS = {128258, 128260}

SAMPLE_RATE = 24000


class OrpheusEngine:
    def __init__(
        self,
        model_path: str | None = None,
        n_gpu_layers: int = -1,
        voice: str = "tara",
    ):
        from llama_cpp import Llama
        import snac

        self.voice = voice
        self.model_path = model_path or str(MODELS_DIR / GGUF_FILE)

        if not Path(self.model_path).exists():
            raise FileNotFoundError(
                f"Model not found: {self.model_path}\n"
                "Run: python tts/setup.py"
            )

        print(f"[TTS] Loading Orpheus GGUF from {self.model_path}...")
        self.llm = Llama(
            model_path=self.model_path,
            n_ctx=8192,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        print("[TTS] Model loaded")

        print("[TTS] Loading SNAC decoder...")
        self.snac = snac.SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval()
        if torch.cuda.is_available():
            self.snac = self.snac.cuda()
        print("[TTS] SNAC loaded")

    def _format_prompt(self, text: str) -> str:
        """Format text with voice prefix for Orpheus."""
        return f"{self.voice}: {text}"

    def _tokens_to_audio(self, token_ids: list[int]) -> np.ndarray:
        """Decode SNAC tokens back to audio waveform."""
        # Group tokens into SNAC layers (7 tokens per frame: 1 coarse + 2 mid + 4 fine)
        # Pattern: [c, m, f, f, m, f, f, c, m, f, f, m, f, f, ...]
        layer_0 = []  # coarse
        layer_1 = []  # mid
        layer_2 = []  # fine

        i = 0
        while i < len(token_ids):
            if i < len(token_ids):
                layer_0.append(token_ids[i] - SNAC_LAYERS[0][0])
                i += 1
            if i < len(token_ids):
                layer_1.append(token_ids[i] - SNAC_LAYERS[1][0])
                i += 1
            if i < len(token_ids):
                layer_2.append(token_ids[i] - SNAC_LAYERS[2][0])
                i += 1
            if i < len(token_ids):
                layer_2.append(token_ids[i] - SNAC_LAYERS[2][0])
                i += 1
            if i < len(token_ids):
                layer_1.append(token_ids[i] - SNAC_LAYERS[1][0])
                i += 1
            if i < len(token_ids):
                layer_2.append(token_ids[i] - SNAC_LAYERS[2][0])
                i += 1
            if i < len(token_ids):
                layer_2.append(token_ids[i] - SNAC_LAYERS[2][0])
                i += 1

        if not layer_0:
            return np.array([], dtype=np.float32)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        codes = [
            torch.tensor([layer_0], dtype=torch.long, device=device),
            torch.tensor([layer_1], dtype=torch.long, device=device),
            torch.tensor([layer_2], dtype=torch.long, device=device),
        ]

        with torch.no_grad():
            audio = self.snac.decode(codes).squeeze().cpu().numpy()

        return audio.astype(np.float32)

    def synthesize(self, text: str, max_tokens: int = 4096) -> np.ndarray:
        """Generate audio from text. Returns numpy float32 array at 24kHz."""
        prompt = self._format_prompt(text)

        # Tokenize and prepend start token
        input_ids = self.llm.tokenize(prompt.encode("utf-8"), add_bos=True)
        input_ids.append(START_TOKEN)

        output = self.llm.create_completion(
            prompt=self.llm.detokenize(input_ids).decode("utf-8", errors="ignore"),
            max_tokens=max_tokens,
            temperature=0.6,
            top_p=0.95,
            repeat_penalty=1.1,
        )

        # Extract token IDs from completion
        response_text = output["choices"][0]["text"]
        response_ids = self.llm.tokenize(response_text.encode("utf-8"), add_bos=False)

        # Filter to SNAC audio tokens only
        audio_tokens = [
            t for t in response_ids
            if SNAC_LAYERS[0][0] <= t < SNAC_LAYERS[2][1]
        ]

        if not audio_tokens:
            print("[TTS] Warning: No audio tokens generated")
            return np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1s silence

        return self._tokens_to_audio(audio_tokens)

    def synthesize_to_wav(self, text: str, output_path: str) -> str:
        """Generate speech and save as WAV file."""
        audio = self.synthesize(text)

        # Convert float32 [-1, 1] to int16
        audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        return output_path

    def synthesize_to_bytes(self, text: str) -> bytes:
        """Generate speech and return as WAV bytes (for HTTP streaming)."""
        audio = self.synthesize(text)
        audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()


# Quick test
if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Hello, I am Jarvis. How can I help you today?"
    engine = OrpheusEngine()
    out = engine.synthesize_to_wav(text, "tts/test_output.wav")
    print(f"[TTS] Saved: {out}")
