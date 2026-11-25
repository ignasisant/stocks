"""Subtitle cues from word timings: ≤2 lines of ~42 chars, SRT + ASS, moved to the top over bottom highlights."""

from pathlib import Path

from common import OUT_H, OUT_W

SENTENCE_END = ('.', '?', '!', ':', '…')


def split_lines(text: str, limit: int) -> list[str] | None:
    """
    Split a cue into one or two balanced lines within the limit.

    :param text: str, cue text
    :param limit: int, max characters per line
    :return: list[str] | None, lines, or None when two lines cannot hold it
    """
    if len(text) <= limit:
        return [text]
    words = text.split(' ')
    best = None
    for i in range(1, len(words)):
        a, b = ' '.join(words[:i]), ' '.join(words[i:])
        if len(a) <= limit and len(b) <= limit:
            score = abs(len(a) - len(b))
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best[1] if best else None


def build_cues(scenes: list[dict], max_chars: int, max_lines: int) -> list[dict]:
    """
    Group words into cues per scene (never across scenes).

    :param scenes: list[dict], [{'offset': global start of narration, 'words': [...]}]
    :param max_chars: int, characters per line
    :param max_lines: int, lines per cue
    :return: list[dict], [{'start', 'end', 'lines'}]
    """
    cues = []
    for sc in scenes:
        words = [w for w in sc['words'] if w['text'].strip()]
        cur: list[dict] = []

        def flush() -> None:
            if not cur:
                return
            text = ' '.join(w['text'] for w in cur)
            cues.append(
                {
                    'start': sc['offset'] + cur[0]['start'] - 0.05,
                    'end': sc['offset'] + cur[-1]['end'] + 0.25,
                    'lines': split_lines(text, max_chars) or [text],
                }
            )
            cur.clear()

        for w in words:
            candidate = ' '.join(x['text'] for x in [*cur, w])
            fits = len(candidate) <= max_chars * max_lines and (
                max_lines == 1 or split_lines(candidate, max_chars)
            )
            too_long = (
                cur
                and (sc['offset'] + w['end']) - (sc['offset'] + cur[0]['start']) > 6.0
            )
            if cur and (not fits or too_long):
                flush()
            cur.append(w)
            text = ' '.join(x['text'] for x in cur)
            if w['text'].endswith(SENTENCE_END) and len(text) >= 18:
                flush()
            elif w['text'].endswith((',', ';')) and len(text) >= 52:
                flush()
        flush()
    for a, b in zip(cues, cues[1:]):
        a['end'] = min(max(a['end'], a['start'] + 1.0), b['start'] - 0.04)
    if cues:
        cues[-1]['end'] = max(cues[-1]['end'], cues[-1]['start'] + 1.0)
    return cues


def place(cues: list[dict], highlights: list[dict], zone_top: int = 800) -> None:
    """
    Mark cues that must sit at the top because a highlighted element is in the subtitle zone.

    :param cues: list[dict], cues (modified in place with 'top')
    :param highlights: list[dict], global [{'start', 'end', 'box'}] in output px
    :param zone_top: int, y where the bottom subtitle zone starts
    :return: None
    """
    for c in cues:
        c['top'] = any(
            h['start'] < c['end']
            and h['end'] > c['start']
            and h['box'][3] > zone_top
            and h['box'][1] < OUT_H
            for h in highlights
        )


def _srt_ts(t: float) -> str:
    """
    Format seconds as an SRT timestamp.

    :param t: float, seconds
    :return: str, HH:MM:SS,mmm
    """
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _ass_ts(t: float) -> str:
    """
    Format seconds as an ASS timestamp.

    :param t: float, seconds
    :return: str, H:MM:SS.cc
    """
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def write_srt(cues: list[dict], path: Path) -> None:
    """
    Write cues as SRT.

    :param cues: list[dict], cues
    :param path: Path, destination
    :return: None
    """
    blocks = [
        f'{i}\n{_srt_ts(c["start"])} --> {_srt_ts(c["end"])}\n' + '\n'.join(c['lines'])
        for i, c in enumerate(cues, 1)
    ]
    path.write_text('\n\n'.join(blocks) + '\n', encoding='utf-8')


def write_ass(cues: list[dict], path: Path, font: str, size: int) -> None:
    """
    Write cues as ASS with a high-contrast boxed style (bottom by default, top when flagged).

    :param cues: list[dict], cues
    :param path: Path, destination
    :param font: str, font family name available in the fonts dir
    :param size: int, font size in output px
    :return: None
    """
    style = (
        f'{font},{size},&H00FFFFFF,&H00FFFFFF,&H38000000,&H38000000,0,0,0,0,100,100,0.3,0,3,13,0,'
        '{align},120,120,{margin},1'
    )
    head = [
        '[Script Info]',
        'ScriptType: v4.00+',
        f'PlayResX: {OUT_W}',
        f'PlayResY: {OUT_H}',
        'WrapStyle: 2',
        'ScaledBorderAndShadow: yes',
        '',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
        'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, '
        'MarginR, MarginV, Encoding',
        'Style: Bottom,' + style.format(align=2, margin=58),
        'Style: Top,' + style.format(align=8, margin=64),
        '',
        '[Events]',
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    lines = [
        f'Dialogue: 0,{_ass_ts(c["start"])},{_ass_ts(c["end"])},{"Top" if c.get("top") else "Bottom"},,0,0,0,,'
        + r'\N'.join(ln.replace('{', '(').replace('}', ')') for ln in c['lines'])
        for c in cues
    ]
    path.write_text('\n'.join(head + lines) + '\n', encoding='utf-8')
