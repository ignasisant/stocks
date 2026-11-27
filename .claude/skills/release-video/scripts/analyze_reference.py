#!/usr/bin/env python3
"""analyze_reference — measure a reference video (cuts/min, shot length, loudness) to set pace targets.

Usage: analyze_reference.py VIDEO [--out DIR] [--threshold 0.3]
Works on a local file only; downloading third-party videos is the user's call and they stay private.
Writes DIR/report.json and prints a one-line summary to compare against references/formato.md.
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ffmpeg  # noqa: E402
from qa import loudness, probe  # noqa: E402


def cut_times(path: Path, threshold: float) -> list[float]:
    """
    Timestamps of scene changes (hard cuts and fast dissolves) found by ffmpeg's scene score.

    :param path: Path, media file
    :param threshold: float, scene score above which a frame counts as a cut (0.3 is a good default)
    :return: list[float], seconds of each cut
    """
    res = subprocess.run(
        [
            ffmpeg(),
            '-hide_banner',
            '-i',
            str(path),
            '-vf',
            f"select='gt(scene,{threshold})',showinfo",
            '-an',
            '-f',
            'null',
            '-',
        ],
        capture_output=True,
        text=True,
    ).stderr
    return [float(t) for t in re.findall(r'pts_time:([\d.]+)', res)]


def analyze(path: Path, threshold: float) -> dict:
    """
    Pace and loudness numbers for one video.

    :param path: Path, media file
    :param threshold: float, scene-change score
    :return: dict, duration, cuts, cuts_per_min, shot length stats, LUFS and true peak
    """
    duration = probe(path)['duration']
    cuts = cut_times(path, threshold)
    edges = [0.0, *cuts, duration]
    shots = [b - a for a, b in zip(edges, edges[1:], strict=False) if b > a]
    return {
        'file': path.name,
        'duration_s': round(duration, 1),
        'cuts': len(cuts),
        'cuts_per_min': round(len(cuts) / duration * 60, 1),
        'shot_median_s': round(statistics.median(shots), 2),
        'shot_longest_s': round(max(shots), 2),
        'first_cut_s': round(cuts[0], 2) if cuts else None,
        **loudness(path),
        'threshold': threshold,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video', type=Path)
    p.add_argument('--out', type=Path, default=Path('.'))
    p.add_argument('--threshold', type=float, default=0.3)
    a = p.parse_args()
    report = analyze(a.video, a.threshold)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(report, indent=2))
    print(
        f"{report['file']}: {report['duration_s']}s, {report['cuts_per_min']} cuts/min, "
        f"median shot {report['shot_median_s']}s, first cut {report['first_cut_s'] if report['first_cut_s'] is not None else '-'} s, "
        f"{report['lufs']} LUFS"
    )


if __name__ == '__main__':
    main()
