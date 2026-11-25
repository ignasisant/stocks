"""Quality gate before delivery: duration, format, loudness, silences, sync, PII and a contact sheet to review."""

import json
import re
import subprocess
from pathlib import Path

from common import ffmpeg, read_json, run, write_json

PII = {
    'email': re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),
    'phone': re.compile(
        r'(?<![\w.])(?:\+?\d{2,3}[\s-]?)?[6789]\d{2}[\s-]?\d{3}[\s-]?\d{3}(?![\w.])'
    ),
    'iban': re.compile(r'\b[A-Z]{2}\d{2}(?:\s?\d{4}){4,7}\b'),
    'dni_nie': re.compile(r'\b[XYZ]?\d{7,8}[A-HJ-NP-TV-Z]\b'),
    'jwt': re.compile(r'\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}'),
    'secret': re.compile(r'\b(?:sk|pk|xox[abp]|ghp|gho|AKIA)[_-]?[A-Za-z0-9]{16,}\b'),
    'card': re.compile(r'\b(?:\d{4}[\s-]?){3}\d{4}\b'),
}
ERROR_HINTS = re.compile(
    r'(Something went wrong|Ha ocurrido un error|Error \d{3}|\b404\b|\b500\b|Not Found|Unauthorized|'
    r'No se ha podido|Sesión caducada|Session expired|Cargando\.\.\.|Loading\.\.\.)',
    re.I,
)


def probe(path: Path) -> dict:
    """
    Read stream facts with ffmpeg's banner (no ffprobe needed).

    :param path: Path, media file
    :return: dict, {'video': str, 'audio': str, 'duration': float}
    """
    res = subprocess.run(
        [ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True, text=True
    ).stderr
    video = next((ln.strip() for ln in res.splitlines() if 'Video:' in ln), '')
    audio = next((ln.strip() for ln in res.splitlines() if 'Audio:' in ln), '')
    h, m, s = re.search(r'Duration: (\d+):(\d+):([\d.]+)', res).groups()
    return {
        'video': video,
        'audio': audio,
        'duration': int(h) * 3600 + int(m) * 60 + float(s),
    }


def loudness(path: Path) -> dict:
    """
    Integrated loudness and true peak (EBU R128).

    :param path: Path, media file
    :return: dict, {'lufs': float, 'true_peak': float}
    """
    res = subprocess.run(
        [
            ffmpeg(),
            '-hide_banner',
            '-i',
            str(path),
            '-vn',
            '-af',
            'ebur128=peak=true',
            '-f',
            'null',
            '-',
        ],
        capture_output=True,
        text=True,
    ).stderr
    summary = res[res.rfind('Summary:') :]
    lufs = float(re.search(r'I:\s+(-?[\d.]+) LUFS', summary).group(1))
    peak = float(re.search(r'Peak:\s+(-?[\d.]+) dBFS', summary).group(1))
    return {'lufs': lufs, 'true_peak': peak}


def inner_silences(wav: Path, limit: float = 1.4) -> list[float]:
    """
    Pauses longer than `limit` inside one narration file.

    :param wav: Path, narration wav
    :param limit: float, seconds
    :return: list[float], durations of long pauses
    """
    res = subprocess.run(
        [
            ffmpeg(),
            '-hide_banner',
            '-i',
            str(wav),
            '-af',
            f'silencedetect=n=-38dB:d={limit}',
            '-f',
            'null',
            '-',
        ],
        capture_output=True,
        text=True,
    ).stderr
    return [float(x) for x in re.findall(r'silence_duration: ([\d.]+)', res)]


def scan_pii(text: str, cfg: dict) -> list[dict]:
    """
    Find PII-looking strings in captured page text.

    :param text: str, visible text of a scene
    :param cfg: dict, full skill config (pii allowlists)
    :return: list[dict], [{'kind', 'value'}] partially masked
    """
    allow = [
        re.compile(p)
        for p in cfg['pii'].get('allow_patterns', [])
        + cfg['pii'].get('release_allow', [])
    ]
    allow_emails = {e.lower() for e in cfg['pii'].get('allow_emails', [])}
    hits = set()
    for kind, rx in PII.items():
        for m in rx.findall(text):
            v = m if isinstance(m, str) else m[0]
            if kind == 'email' and v.lower() in allow_emails:
                continue
            if any(a.search(v) for a in allow):
                continue
            hits.add((kind, v[:3] + '…' + v[-2:] if len(v) > 6 else v))
    return [{'kind': k, 'value': v} for k, v in sorted(hits)]


def contact_sheet(
    video: Path, layout: list[dict], qa_dir: Path, n: int = 6
) -> list[str]:
    """
    Extract n frames (mid-scene, away from crossfades) and tile them 3×2 for visual review.

    :param video: Path, final MP4
    :param layout: list[dict], scene layout
    :param qa_dir: Path, QA output directory
    :param n: int, frames to extract
    :return: list[str], frame files (plus the grid as the last item)
    """
    ff = ffmpeg()
    total = layout[-1]['start'] + layout[-1]['duration']
    if len(layout) >= n:
        idx = [round(i * (len(layout) - 1) / (n - 1)) for i in range(n)]
        times = [layout[i]['start'] + layout[i]['duration'] * 0.6 for i in idx]
    else:
        times = [total * (i + 0.5) / n for i in range(n)]
    files = []
    for i, t in enumerate(times):
        f = qa_dir / f'frame_{i + 1}_{t:05.1f}s.png'
        run(
            [
                ff,
                '-y',
                '-v',
                'error',
                '-ss',
                f'{t:.2f}',
                '-i',
                str(video),
                '-frames:v',
                '1',
                str(f),
            ]
        )
        files.append(str(f))
    grid = qa_dir / 'contact_sheet.jpg'
    ins = sum([['-i', f] for f in files], [])
    tiles = ''.join(
        f'[{i}:v]scale=960:540,drawtext=text=\'{float(Path(f).stem.split("_")[-1][:-1]):.1f}s\':'
        f'x=14:y=14:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6[t{i}];'
        for i, f in enumerate(files)
    )
    run(
        [
            ffmpeg(),
            '-y',
            '-v',
            'error',
            *ins,
            '-filter_complex',
            tiles
            + ''.join(f'[t{i}]' for i in range(len(files)))
            + f'xstack=inputs={len(files)}:layout='
            '0_0|w0_0|w0+w1_0|0_h0|w0_h0|w0+w1_h0',
            '-q:v',
            '3',
            str(grid),
        ]
    )
    return files + [str(grid)]


def qa(work: Path, build: Path, board: dict, cfg: dict, timings: dict) -> dict:
    """
    Run every check, write qa/report.json and return it; `ok` is False on any hard failure.

    :param work: Path, release directory
    :param build: Path, build directory
    :param board: dict, storyboard
    :param cfg: dict, full skill config
    :param timings: dict, narration timings
    :return: dict, report
    """
    version = board['release']['version']
    video = work / f'release_{version}.mp4'
    qa_dir = build / 'qa'
    qa_dir.mkdir(exist_ok=True)
    layout = read_json(build / 'layout.json')
    cues = read_json(build / 'cues.json')
    max_d = board['release'].get('max_duration', cfg['max_duration'])
    info, loud = probe(video), loudness(video)
    fails, warns = [], []
    if info['duration'] > max_d + 0.5:
        fails.append(f'duration {info["duration"]:.1f}s > {max_d}s')
    for need in ('h264', '1920x1080', '30 fps'):
        if need not in info['video']:
            fails.append(f'video stream lacks {need}: {info["video"]}')
    if 'aac' not in info['audio']:
        fails.append(f'audio is not AAC: {info["audio"]}')
    if abs(loud['lufs'] - cfg['audio']['lufs']) > 1.0:
        fails.append(f'loudness {loud["lufs"]} LUFS (target {cfg["audio"]["lufs"]})')
    if loud['true_peak'] > cfg['audio']['true_peak'] + 0.6:
        warns.append(f'true peak {loud["true_peak"]} dBFS')
    # Silence between narrations (music keeps playing, but the voice must not vanish).
    spans = [
        (p['start'] + 0.35, p['start'] + 0.35 + timings[p['id']]['duration'])
        for p in layout
        if p.get('wav')
    ]
    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
        if b0 - a1 > 2.6:
            warns.append(f'{b0 - a1:.1f}s without narration at {a1:.1f}s')
    for p in layout:
        if p.get('wav'):
            for s in inner_silences(Path(p['wav'])):
                warns.append(f'{p["id"]}: {s:.1f}s pause inside narration')
    # Sync: every cue sits inside a narration span.
    for c in cues:
        if not any(a - 0.3 <= c['start'] and c['end'] <= b + 0.8 for a, b in spans):
            fails.append(
                f'cue out of narration: {c["start"]:.1f}s {c["lines"][0][:30]}'
            )
    for c in cues:
        if (
            any(len(ln) > cfg['subtitles']['max_chars'] for ln in c['lines'])
            or len(c['lines']) > cfg['subtitles']['max_lines']
        ):
            warns.append(f'long cue at {c["start"]:.1f}s: {" / ".join(c["lines"])}')
    cfg = {
        **cfg,
        'pii': {**cfg['pii'], 'release_allow': board['release'].get('pii_allow', [])},
    }
    pii, errors = {}, {}
    for p in layout:
        txt = build / 'clips' / p['id'] / 'text.txt'
        if txt.exists():
            text = txt.read_text()
            if hits := scan_pii(text, cfg):
                pii[p['id']] = hits
            if errs := sorted(set(ERROR_HINTS.findall(text))):
                errors[p['id']] = errs
        meta = read_json(build / 'clips' / p['id'] / 'clip.json')
        if meta.get('overrun', 0) > 1.0:
            warns.append(f'{p["id"]}: actions overran narration by {meta["overrun"]}s')
    if pii:
        fails.append('possible PII on screen: ' + json.dumps(pii, ensure_ascii=False))
    if errors:
        warns.append(
            'error/loading text on screen: ' + json.dumps(errors, ensure_ascii=False)
        )
    sheet = contact_sheet(video, layout, qa_dir)
    report = {
        'ok': not fails,
        'fails': fails,
        'warnings': warns,
        'duration': info['duration'],
        'loudness': loud,
        'video': info['video'],
        'audio': info['audio'],
        'cues': len(cues),
        'frames': sheet,
    }
    write_json(qa_dir / 'report.json', report)
    return report
