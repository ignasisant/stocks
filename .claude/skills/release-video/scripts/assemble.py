"""Final cut: crossfaded scene clips + burned subtitles, narration over a ducked music bed, −16 LUFS, MP4."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from subtitles import build_cues, place, write_ass, write_srt

from common import CLIPS, SKILL_DIR, SUFFIX, VERTICAL, ffmpeg, read_json, run, write_json


def _filter_path(p: Path) -> str:
    """
    Escape a path for use inside an ffmpeg filter argument.

    :param p: Path, file or directory
    :return: str, escaped path
    """
    return str(p).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")


def layout(board: dict, build: Path, xf: float) -> list[dict]:
    """
    Compute each scene's start on the final timeline (clips overlap by the crossfade).

    :param board: dict, storyboard
    :param build: Path, build directory with clips/ and audio/
    :param xf: float, crossfade seconds
    :return: list[dict], [{'id', 'start', 'duration', 'clip', 'meta', 'wav'}]
    """
    out, t = [], 0.0
    for i, sc in enumerate(board['scenes']):
        d = build / CLIPS / sc['id']
        meta = read_json(d / 'clip.json')
        wav = build / 'audio' / f'{sc["id"]}.wav'
        out.append(
            {
                'id': sc['id'],
                'start': t,
                'duration': meta['duration'],
                'clip': d / 'clip.mp4',
                'meta': meta,
                'wav': (
                    wav if wav.exists() and sc.get('narration', '').strip() else None
                ),
            }
        )
        t += meta['duration'] - (xf if i < len(board['scenes']) - 1 else 0)
    return out


def subtitles(
    parts: list[dict], timings: dict, cfg: dict, build: Path, srt_out: Path
) -> Path:
    """
    Build global cues from word timings, write the SRT deliverable and the ASS used for burning.

    :param parts: list[dict], scene layout
    :param timings: dict, narration timings keyed by scene id
    :param cfg: dict, full skill config
    :param build: Path, build directory
    :param srt_out: Path, SRT deliverable path
    :return: Path, ASS file
    """
    scenes, hl = [], []
    for p in parts:
        if p['wav'] is None:
            continue
        off = p['start'] + p['meta']['narration_offset']
        scenes.append({'offset': off, 'words': timings[p['id']]['words']})
        hl += [
            {**h, 'start': h['start'] + p['start'], 'end': h['end'] + p['start']}
            for h in p['meta']['highlights']
        ]
    sub = {**cfg['subtitles'], **(cfg['subtitles'].get('vertical', {}) if VERTICAL else {})}
    cues = build_cues(scenes, sub['max_chars'], sub['max_lines'])
    place(cues, hl)
    write_json(build / f'cues{SUFFIX}.json', cues)
    write_srt(cues, srt_out)
    ass = build / f'subs{SUFFIX}.ass'
    accent = cfg.get('brand', {}).get('accent', '#A98EF7') if sub.get('karaoke', True) else None
    write_ass(cues, ass, sub['font'], sub['size'], accent)
    return ass


def sound_cues(parts: list[dict], cfg: dict) -> list[tuple[float, Path, float]]:
    """
    Global sound effects: each clip's click / pop cues plus a whoosh on every scene change.

    :param parts: list[dict], scene layout
    :param cfg: dict, full skill config (`sfx`: enabled, volume_db, per-kind gain)
    :return: list[tuple[float, Path, float]], (seconds, wav, gain dB)
    """
    sfx = cfg.get('sfx', {})
    if not sfx.get('enabled', True):
        return []
    files = {k: SKILL_DIR / 'assets' / 'sfx' / f'{k}.wav' for k in ('click', 'pop', 'whoosh')}
    gain = {'click': 0.0, 'pop': -2.0, 'whoosh': -4.0, **sfx.get('gain', {})}
    base = sfx.get('volume_db', -12)
    out = []
    for i, p in enumerate(parts):
        if i:
            # The whoosh peaks mid-crossfade (its wav rises for ~0.25 s).
            out.append((p['start'] - 0.1, 'whoosh'))
        out += [(p['start'] + c['t'], c['kind']) for c in p['meta'].get('sfx', [])]
    return [(t, files[k], base + gain[k]) for t, k in out if files[k].exists()]


def mix_audio(parts: list[dict], total: float, cfg: dict, build: Path) -> Path:
    """
    Place narration, duck the music bed under it and loudness-normalise (two-pass loudnorm).

    :param parts: list[dict], scene layout
    :param total: float, video length in seconds
    :param cfg: dict, full skill config
    :param build: Path, build directory
    :return: Path, final wav
    """
    ff = ffmpeg()
    inputs, chains, labels = [], [], []
    for p in parts:
        if p['wav'] is None:
            continue
        ms = int((p['start'] + p['meta']['narration_offset']) * 1000)
        inputs += ['-i', str(p['wav'])]
        n = len(labels)
        chains.append(
            f'[{n}:a]aresample=48000,aformat=channel_layouts=mono,adelay={ms}:all=1[n{n}]'
        )
        labels.append(f'[n{n}]')
    graph = ';'.join(chains)
    graph += f';{"".join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f}[voice]'
    music = cfg['music']
    mfile = (
        SKILL_DIR / music['file']
        if not Path(music['file']).is_absolute()
        else Path(music['file'])
    )
    if music.get('enabled') and mfile.exists():
        k = len(labels)
        inputs += ['-stream_loop', '-1', '-i', str(mfile)]
        graph += (
            f';[voice]asplit=2[v1][key];[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},'
            f'volume={music["volume_db"]}dB,afade=t=in:d=1.2,afade=t=out:st={max(total - 2.5, 0):.2f}:d=2.5[bed];'
            f'[key]aformat=channel_layouts=stereo[k2];'
            f'[bed][k2]sidechaincompress=threshold=0.02:ratio={music["duck_ratio"]}:attack=25:release=450:makeup=1[duck];'
            f'[v1]aformat=channel_layouts=stereo[vs];[vs][duck]amix=inputs=2:normalize=0[mix0]'
        )
    else:
        graph += ';[voice]aformat=channel_layouts=stereo[mix0]'
    # Effects go in after the duck: keyed by the voice only, so a click never pumps the music.
    cues = sound_cues(parts, cfg)
    if cues:
        base = inputs.count('-i')
        fx = []
        for j, (t, wav, db) in enumerate(cues):
            inputs += ['-i', str(wav)]
            ms = max(int(t * 1000), 0)
            graph += (
                f';[{base + j}:a]aresample=48000,aformat=channel_layouts=stereo,'
                f'volume={db}dB,adelay={ms}:all=1[fx{j}]'
            )
            fx.append(f'[fx{j}]')
        graph += (
            f';[mix0]{"".join(fx)}amix=inputs={len(fx) + 1}:normalize=0:dropout_transition=0,'
            f'atrim=0:{total:.3f}[mix]'
        )
    else:
        graph += ';[mix0]anull[mix]'
    raw = build / 'mix_raw.wav'
    run(
        [
            ff,
            '-y',
            '-v',
            'error',
            *inputs,
            '-filter_complex',
            graph,
            '-map',
            '[mix]',
            '-t',
            f'{total:.3f}',
            '-ar',
            '48000',
            str(raw),
        ]
    )
    a = cfg['audio']
    target = f'I={a["lufs"]}:TP={a["true_peak"]}:LRA=11'
    res = subprocess.run(
        [
            ff,
            '-hide_banner',
            '-i',
            str(raw),
            '-af',
            f'loudnorm={target}:print_format=json',
            '-f',
            'null',
            '-',
        ],
        capture_output=True,
        text=True,
    )
    m = json.loads(re.findall(r'\{[^{}]+\}', res.stderr)[-1])
    final = build / 'mix.wav'
    run(
        [
            ff,
            '-y',
            '-v',
            'error',
            '-i',
            str(raw),
            '-af',
            f'loudnorm={target}:measured_I={m["input_i"]}:measured_TP={m["input_tp"]}:measured_LRA={m["input_lra"]}'
            f':measured_thresh={m["input_thresh"]}:offset={m["target_offset"]}:linear=true,aresample=48000',
            str(final),
        ]
    )
    return final


def assemble(work: Path, build: Path, board: dict, cfg: dict, timings: dict) -> Path:
    """
    Produce release_<version>.mp4 and .srt in the work directory.

    :param work: Path, user-facing release directory
    :param build: Path, build directory
    :param board: dict, storyboard
    :param cfg: dict, full skill config
    :param timings: dict, narration timings
    :return: Path, the MP4
    """
    xf = cfg['video']['crossfade']
    version = board['release']['version']
    parts = layout(board, build, xf)
    total = parts[-1]['start'] + parts[-1]['duration']
    srt = work / f'release_{version}{SUFFIX}.srt'
    ass = subtitles(parts, timings, cfg, build, srt)
    ff = ffmpeg()
    inputs, graph, last = [], [], '[0:v]'
    for p in parts:
        inputs += ['-i', str(p['clip'])]
    for i, p in enumerate(parts[1:], 1):
        lab = f'[x{i}]'
        graph.append(
            f'{last}[{i}:v]xfade=transition=fade:duration={xf}:offset={p["start"]:.3f}{lab}'
        )
        last = lab
    fonts = SKILL_DIR / 'assets' / 'fonts'
    graph.append(
        f"{last}ass=filename='{_filter_path(ass)}':fontsdir='{_filter_path(fonts)}',format=yuv420p[v]"
    )
    video = build / f'video{SUFFIX}.mp4'
    run(
        [
            ff,
            '-y',
            '-v',
            'error',
            *inputs,
            '-filter_complex',
            ';'.join(graph),
            '-map',
            '[v]',
            '-r',
            '30',
            '-c:v',
            'libx264',
            '-preset',
            'slow',
            '-crf',
            '18',
            '-profile:v',
            'high',
            '-pix_fmt',
            'yuv420p',
            str(video),
        ]
    )
    audio = mix_audio(parts, total, cfg, build)
    out = work / f'release_{version}{SUFFIX}.mp4'
    run(
        [
            ff,
            '-y',
            '-v',
            'error',
            '-i',
            str(video),
            '-i',
            str(audio),
            '-map',
            '0:v',
            '-map',
            '1:a',
            '-c:v',
            'copy',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            '-ar',
            '48000',
            '-shortest',
            '-movflags',
            '+faststart',
            str(out),
        ]
    )
    write_json(
        build / f'layout{SUFFIX}.json',
        [
            {
                k: (str(v) if isinstance(v, Path) else v)
                for k, v in p.items()
                if k != 'meta'
            }
            for p in parts
        ],
    )
    print(f'OUT {out} {total:.1f}s')
    shutil.copy(srt, build / srt.name)
    return out
