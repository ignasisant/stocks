"""Synthesize the default background track: light, upbeat explainer bed (original, license-free)."""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 104
BEAT = 60 / BPM
# C – G – Am – F, one bar each; MIDI notes of each chord.
CHORDS = [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]]
ROOTS = [36, 43, 45, 41]


def hz(note: float) -> float:
    """
    Convert a MIDI note to frequency.

    :param note: float, MIDI note number
    :return: float, frequency in Hz
    """
    return 440.0 * 2 ** ((note - 69) / 12)


def env(n: int, attack: float, decay: float) -> np.ndarray:
    """
    Attack + exponential decay envelope.

    :param n: int, length in samples
    :param attack: float, attack seconds
    :param decay: float, decay time constant in seconds
    :return: np.ndarray, envelope
    """
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / decay)


def add(buf: np.ndarray, start: float, sig: np.ndarray, pan: float = 0.0) -> None:
    """
    Mix a mono signal into the stereo buffer at a time offset with equal-power pan.

    :param buf: np.ndarray, stereo buffer (n, 2)
    :param start: float, offset in seconds
    :param sig: np.ndarray, mono signal
    :param pan: float, -1 (left) .. 1 (right)
    :return: None
    """
    i = int(start * SR)
    j = min(len(buf), i + len(sig))
    if i >= len(buf):
        return
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:j, 0] += sig[: j - i] * l
    buf[i:j, 1] += sig[: j - i] * r


def marimba(note: float, dur: float = 0.6) -> np.ndarray:
    """
    Soft mallet pluck: fundamental plus a quickly decaying 4th partial.

    :param note: float, MIDI note
    :param dur: float, length in seconds
    :return: np.ndarray, mono signal
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = hz(note)
    sig = np.sin(2 * np.pi * f * t) * env(n, 0.003, 0.28)
    sig += 0.25 * np.sin(2 * np.pi * f * 3.98 * t) * env(n, 0.002, 0.05)
    return sig


def pad(notes: list[int], dur: float) -> np.ndarray:
    """
    Warm sustained chord with slow swell and slight detune.

    :param notes: list[int], MIDI notes of the chord
    :param dur: float, length in seconds
    :return: np.ndarray, mono signal
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for note in notes:
        for det in (-0.06, 0.06):
            sig += np.sin(2 * np.pi * hz(note + det) * t) + 0.18 * np.sin(
                2 * np.pi * hz(note + 12 + det) * t
            )
    shape = np.minimum(1, t / 0.6) * np.minimum(1, (dur - t) / 0.5).clip(0, 1)
    return sig * shape / (len(notes) * 2)


def bass(note: float, dur: float) -> np.ndarray:
    """
    Round sine bass note.

    :param note: float, MIDI note
    :param dur: float, length in seconds
    :return: np.ndarray, mono signal
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    return (
        np.sin(2 * np.pi * hz(note) * t) + 0.2 * np.sin(4 * np.pi * hz(note) * t)
    ) * env(n, 0.01, 0.35)


def noise_hit(
    dur: float, decay: float, rng: np.random.Generator, bright: bool = True
) -> np.ndarray:
    """
    Filtered noise burst for shaker / clap.

    :param dur: float, length in seconds
    :param decay: float, decay constant in seconds
    :param rng: np.random.Generator, noise source
    :param bright: bool, high-pass (shaker) instead of band (clap)
    :return: np.ndarray, mono signal
    """
    n = int(dur * SR)
    x = rng.standard_normal(n)
    x = (
        np.diff(x, prepend=0)
        if bright
        else np.convolve(x, np.ones(6) / 6, mode='same')
        - np.convolve(x, np.ones(40) / 40, mode='same')
    )
    return x * env(n, 0.001, decay)


def kick(dur: float = 0.35) -> np.ndarray:
    """
    Soft kick: sine sweep from 110 Hz down to 48 Hz.

    :param dur: float, length in seconds
    :return: np.ndarray, mono signal
    """
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 48 + 62 * np.exp(-t / 0.04)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.12)


def render(bars: int = 32) -> np.ndarray:
    """
    Arrange the track: 4-bar intro (pad + mallets), then the full groove with a lift every 8 bars.

    :param bars: int, number of 4/4 bars
    :return: np.ndarray, stereo float signal
    """
    rng = np.random.default_rng(7)
    bar = 4 * BEAT
    buf = np.zeros((int((bars * bar + 2) * SR), 2))
    arp = [0, 1, 2, 1, 2, 0, 1, 2]
    for b in range(bars):
        t0 = b * bar
        chord = CHORDS[b % 4]
        add(buf, t0, pad(chord, bar + 0.4) * 0.16)
        octave = 12 if (b // 8) % 2 else 0
        for k, idx in enumerate(arp):
            add(
                buf,
                t0 + k * BEAT / 2,
                marimba(chord[idx] + octave) * 0.23,
                pan=-0.35 if k % 2 else 0.35,
            )
        if b < 4:
            continue
        for beat in range(4):
            if beat in (0, 2):
                add(buf, t0 + beat * BEAT, kick() * 0.34)
                add(buf, t0 + beat * BEAT, bass(ROOTS[b % 4], BEAT * 1.4) * 0.30)
            else:
                add(
                    buf,
                    t0 + beat * BEAT,
                    noise_hit(0.2, 0.06, rng, bright=False) * 0.07,
                )
            add(
                buf,
                t0 + beat * BEAT + BEAT / 2,
                bass(ROOTS[b % 4] + 12, BEAT * 0.5) * 0.10,
            )
        for k in range(8):
            add(
                buf,
                t0 + k * BEAT / 2,
                noise_hit(0.08, 0.018, rng) * (0.035 if k % 2 else 0.022),
                pan=0.5,
            )
    fade = int(2 * SR)
    buf[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return buf / np.max(np.abs(buf)) * 0.7


def main(out: str) -> None:
    """
    Render the track to a 16-bit stereo wav.

    :param out: str, output path
    :return: None
    """
    sig = (render() * 32767).astype(np.int16)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(out, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(sig.tobytes())
    print(out, f'{len(sig) / SR:.1f}s')


if __name__ == '__main__':
    main(
        sys.argv[1]
        if len(sys.argv) > 1
        else str(
            Path(__file__).resolve().parent.parent
            / 'assets'
            / 'music'
            / 'explainer_soft_raw.wav'
        )
    )
