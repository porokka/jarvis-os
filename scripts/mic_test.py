#!/usr/bin/env python3
"""Quick mic level test — speak normally and note the numbers."""
import sounddevice as sd
import numpy as np

SAMPLE_RATE = 16000
print("Monitoring mic levels for 20 seconds...")
print("Be SILENT for 5s, then SPEAK NORMALLY, then WHISPER.")
print("─" * 50)

with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', blocksize=1024) as stream:
    peaks = []
    for i in range(int(20 * SAMPLE_RATE / 1024)):
        data, _ = stream.read(1024)
        vol = np.abs(data).mean()
        peak = np.abs(data).max()
        peaks.append(vol)

        if i % int(SAMPLE_RATE / 1024) == 0:
            secs = i * 1024 // SAMPLE_RATE
            bar_len = min(int(vol * 2000), 40)
            bar = "█" * bar_len + "░" * (40 - bar_len)
            print(f"  [{secs:2d}s] {bar} avg:{vol:.5f} peak:{peak:.4f}")

    print("─" * 50)
    arr = np.array(peaks)
    print(f"  Min (silence): {arr.min():.5f}")
    print(f"  Max (speech):  {arr.max():.5f}")
    print(f"  Suggested VOICE_THRESHOLD: {arr.min() * 3:.5f}")
