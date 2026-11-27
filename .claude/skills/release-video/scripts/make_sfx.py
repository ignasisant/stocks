"""Synthesize the UI sound effects (click, pop, whoosh): soft, short, original and license-free."""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
RNG = np.random.default_rng(7)


def t_axis(secs: float) -> np.ndarray:
    """
    Time axis of a given length.

    :param secs: float, seconds
    :return: np.ndarray, seconds per sample
    """
    return np.arange(int(secs * SR)) / SR


def lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """
    One-pole low-pass with an optionally time-varying cutoff.

    :param x: np.ndarray, mono signal
    :param cutoff: np.ndarray | float, cutoff Hz (per sample or constant)
    :return: np.ndarray, filtered signal
    """
    fc = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    y, acc = np.empty_like(x), 0.0
    for i, v in enumerate(x):
        acc += a[i] * (v - acc)
        y[i] = acc
    return y


def click() -> np.ndarray:
    """
    Soft trackpad tick: a damped 2.4 kHz blip over a 4 ms noise transient.

    :return: np.ndarray, stereo (n, 2)
    """
    t = t_axis(0.07)
    tone = np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.012)
    tone += 0.5 * np.sin(2 * np.pi * 1200 * t) * np.exp(-t / 0.02)
    noise = lowpass(RNG.standard_normal(len(t)), 5000) * np.exp(-t / 0.004)
    sig = 0.6 * tone + 0.8 * noise
    return np.stack([sig, sig], axis=1)


def pop() -> np.ndarray:
    """
    Bubble-like pop: a sine gliding 1.1 kHz → 520 Hz with a fast decay.

    :return: np.ndarray, stereo (n, 2)
    """
    t = t_axis(0.22)
    f = 520 + 580 * np.exp(-t / 0.025)
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.clip(t / 0.003, 0, 1) * np.exp(-t / 0.06)
    sig = np.sin(phase) * env + 0.25 * np.sin(2 * phase) * env * np.exp(-t / 0.02)
    return np.stack([sig, sig], axis=1)


def whoosh() -> np.ndarray:
    """
    Air sweep for scene changes: filtered noise opening then closing, panned left to right.

    :return: np.ndarray, stereo (n, 2)
    """
    secs = 0.6
    t = t_axis(secs)
    k = t / secs
    shape = np.sin(np.pi * np.clip(k / 0.42, 0, 1) / 2) ** 2 * np.exp(-np.clip(k - 0.42, 0, None) / 0.18)
    cutoff = 300 + 3200 * shape
    noise = RNG.standard_normal(len(t))
    band = lowpass(noise, cutoff) - lowpass(noise, cutoff * 0.25)
    sig = band * shape
    pan = -0.7 + 1.4 * k
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    return np.stack([sig * left, sig * right], axis=1)


def write(path: Path, sig: np.ndarray, peak: float) -> None:
    """
    Normalise to a peak and write 16-bit stereo wav with 3 ms fades at both ends.

    :param path: Path, destination
    :param sig: np.ndarray, stereo signal
    :param peak: float, peak level 0..1
    :return: None
    """
    fade = int(0.003 * SR)
    sig = sig.copy()
    sig[:fade] *= np.linspace(0, 1, fade)[:, None]
    sig[-fade:] *= np.linspace(1, 0, fade)[:, None]
    sig = sig / np.max(np.abs(sig)) * peak
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((sig * 32767).astype(np.int16).tobytes())
    print(path, f'{len(sig) / SR:.2f}s')


def main(out: str) -> None:
    """
    Render the three effects into a directory.

    :param out: str, output directory
    :return: None
    """
    d = Path(out)
    write(d / 'click.wav', click(), 0.7)
    write(d / 'pop.wav', pop(), 0.6)
    write(d / 'whoosh.wav', whoosh(), 0.5)


if __name__ == '__main__':
    main(
        sys.argv[1]
        if len(sys.argv) > 1
        else str(Path(__file__).resolve().parent.parent / 'assets' / 'sfx')
    )
