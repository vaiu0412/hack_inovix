"""Generate assets/alert.wav – the partner app's "new urgent order" alarm – with numpy (no audio libraries).

The file is exactly 15 s long: two bursts of loud two-tone beeps, then silence. The app plays it with loop=True,
so the alarm repeats every 15 s until the order is accepted. WAV (not MP3) because writing MP3 needs an encoder;
every browser plays WAV.

Run:  python scripts/make_alert_sound.py
"""
import wave
from pathlib import Path

import numpy as np

RATE = 8000          # samples per second – plenty for beeps, keeps the file small
LOOP_SEC = 15.0      # one alarm cycle
OUT = Path(__file__).resolve().parent.parent / "assets" / "alert.wav"


def beep(freq, seconds, volume=0.85):
    """One tone with 5 ms fades so it doesn't click."""
    t = np.arange(int(RATE * seconds)) / RATE
    tone = np.sign(np.sin(2 * np.pi * freq * t)) * 0.35 + np.sin(2 * np.pi * freq * t) * 0.65  # bright, cuts through
    fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.005)
    return tone * fade * volume


def silence(seconds):
    return np.zeros(int(RATE * seconds))


def alarm():
    burst = np.concatenate([part for _ in range(3) for part in (beep(880, 0.16), silence(0.05),
                                                                 beep(1320, 0.16), silence(0.08))])
    sound = np.concatenate([burst, silence(0.35), burst])
    return np.concatenate([sound, silence(LOOP_SEC - len(sound) / RATE)])


def main():
    samples = (np.clip(alarm(), -1, 1) * 32767).astype("<i2")
    with wave.open(str(OUT), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    print(f"wrote {OUT} ({len(samples) / RATE:.1f} s, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
