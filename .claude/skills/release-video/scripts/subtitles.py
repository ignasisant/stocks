"""Subtitle cues from word timings: ≤2 lines of ~42 chars, SRT + ASS, moved to the top over bottom highlights."""

from pathlib import Path

from common import CAPTION_BOTTOM, OUT_H, OUT_W, VERTICAL

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
    :return: list[dict], [{'start', 'end', 'lines', 'words': [{'start', 'text'}]}] (global seconds)
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
                    'words': [
                        {'start': sc['offset'] + w['start'], 'text': w['text']} for w in cur
                    ],
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
        # Vertical captions live in their own band under the stage: nothing to dodge.
        c['top'] = not VERTICAL and any(
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


def _ass_color(hex_color: str) -> str:
    """
    Convert #RRGGBB to an ASS colour override value.

    :param hex_color: str, e.g. '#A98EF7'
    :return: str, e.g. '&H00F78EA9&'
    """
    h = hex_color.lstrip('#')
    return f'&H00{h[4:6]}{h[2:4]}{h[0:2]}&'.upper()


def _esc(text: str) -> str:
    """
    Keep ASS override braces out of spoken text.

    :param text: str, raw text
    :return: str, safe text
    """
    return text.replace('{', '(').replace('}', ')')


def karaoke_events(cue: dict, accent: str) -> list[tuple[float, float, str]]:
    """
    One event per spoken word: the cue's lines with that word in the accent colour.

    The box and the line breaks are identical in every event, so only the colour moves.

    :param cue: dict, cue with 'lines' and 'words'
    :param accent: str, ASS colour value of the current word
    :return: list[tuple[float, float, str]], (start, end, text)
    """
    words = cue.get('words') or []
    tokens = [t for ln in cue['lines'] for t in ln.split(' ')]
    owner = [i for i, w in enumerate(words) for _ in w['text'].split(' ')]
    if not words or len(owner) != len(tokens):
        return [(cue['start'], cue['end'], r'\N'.join(_esc(ln) for ln in cue['lines']))]
    per_line = [len(ln.split(' ')) for ln in cue['lines']]
    out = []
    for i, w in enumerate(words):
        start = cue['start'] if i == 0 else w['start']
        end = words[i + 1]['start'] if i + 1 < len(words) else cue['end']
        if end <= start:
            continue
        parts, k = [], 0
        for n in per_line:
            line = []
            for _ in range(n):
                tok = _esc(tokens[k])
                line.append(f'{{\\c{accent}}}{tok}{{\\r}}' if owner[k] == i else tok)
                k += 1
            parts.append(' '.join(line))
        out.append((start, end, r'\N'.join(parts)))
    return out


def write_ass(
    cues: list[dict], path: Path, font: str, size: int, accent: str | None = None
) -> None:
    """
    Write cues as ASS with a high-contrast boxed style (bottom by default, top when flagged).

    :param cues: list[dict], cues
    :param path: Path, destination
    :param font: str, font family name available in the fonts dir
    :param size: int, font size in output px
    :param accent: str | None, #RRGGBB of the spoken word (karaoke); None keeps plain white cues
    :return: None
    """
    style = (
        f'{font},{size},&H00FFFFFF,&H00FFFFFF,&H00181818,&H00181818,0,0,0,0,100,100,0.3,0,3,13,0,'
        '{align},' + ('60,60' if VERTICAL else '120,120') + ',{margin},1'
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
        'Style: Bottom,' + style.format(align=2, margin=CAPTION_BOTTOM),
        'Style: Top,' + style.format(align=8, margin=64),
        '',
        '[Events]',
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    lines = []
    for c in cues:
        where = 'Top' if c.get('top') else 'Bottom'
        events = (
            karaoke_events(c, _ass_color(accent))
            if accent
            else [(c['start'], c['end'], r'\N'.join(_esc(ln) for ln in c['lines']))]
        )
        lines += [
            f'Dialogue: 0,{_ass_ts(a)},{_ass_ts(b)},{where},,0,0,0,,{text}' for a, b, text in events
        ]
    path.write_text('\n'.join(head + lines) + '\n', encoding='utf-8')
