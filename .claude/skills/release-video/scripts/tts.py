"""Narration per scene: neural TTS → wav + word timings mapped back to the written script."""

import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from common import SKILL_DIR, ffmpeg, media_duration, run, write_json

TOKEN = re.compile(r'\S+')
WORD = re.compile(r"[\wÀ-ÿ'’]+")


def load_lexicon() -> dict:
    """
    Load the pronunciation dictionary (written form → spoken form).

    :return: dict, replacements keyed by the written token
    """
    path = SKILL_DIR / 'references' / 'pronunciacion.yaml'
    return yaml.safe_load(path.read_text()) or {}


def to_spoken(text: str, lexicon: dict) -> tuple[str, list[tuple[str, int]]]:
    """
    Apply the lexicon token by token, remembering how many spoken words each token became.

    :param text: str, narration as written (and as subtitled)
    :param lexicon: dict, written → spoken replacements
    :return: tuple[str, list[tuple[str, int]]], spoken text and (display token, spoken word count)
    """
    spoken, mapping = [], []
    for tok in TOKEN.findall(text):
        m = re.match(r'^([«“"(¿¡]*)(.*?)([»”").,;:!?…]*)$', tok)
        lead, core, trail = m.groups()
        rep = (
            lexicon.get(core) or lexicon.get(core.upper()) or lexicon.get(core.lower())
        )
        said = f'{lead}{rep}{trail}' if rep else tok
        spoken.append(said)
        mapping.append((tok, len(WORD.findall(rep or core))))
    return ' '.join(spoken), mapping


def align(
    mapping: list[tuple[str, int]], words: list[dict], total: float
) -> list[dict]:
    """
    Give every display token a start/end from the provider's spoken-word timings.

    :param mapping: list[tuple[str, int]], display token and its spoken word count
    :param words: list[dict], provider timings [{'start', 'end'}] in spoken order
    :param total: float, audio duration (fallback span)
    :return: list[dict], [{'text', 'start', 'end'}] per display token
    """
    out = []
    if sum(n for _, n in mapping) == len(words) and words:
        i = 0
        last_end = words[0]['start']
        for tok, n in mapping:
            if n == 0:
                out.append({'text': tok, 'start': last_end, 'end': last_end})
                continue
            chunk = words[i : i + n]
            i += n
            last_end = chunk[-1]['end']
            out.append(
                {'text': tok, 'start': chunk[0]['start'], 'end': chunk[-1]['end']}
            )
        return out
    # Counts disagree (numbers, symbols): spread the spoken span by character weight.
    start = words[0]['start'] if words else 0.05
    end = words[-1]['end'] if words else total - 0.05
    weights = [max(len(tok), 1) + 1 for tok, _ in mapping]
    acc = start
    for (tok, _), w in zip(mapping, weights):
        d = (end - start) * w / sum(weights)
        out.append({'text': tok, 'start': acc, 'end': acc + d * 0.92})
        acc += d
    return out


async def _edge(text: str, cfg: dict, mp3: Path) -> list[dict]:
    """
    Synthesize with edge-tts (free Microsoft neural voices) and collect word boundaries.

    :param text: str, spoken text
    :param cfg: dict, voice.edge config
    :param mp3: Path, output mp3
    :return: list[dict], spoken word timings
    """
    import edge_tts

    com = edge_tts.Communicate(
        text,
        cfg['voice'],
        rate=cfg.get('rate', '+0%'),
        pitch=cfg.get('pitch', '+0Hz'),
        boundary='WordBoundary',
    )
    words = []
    with open(mp3, 'wb') as f:
        async for chunk in com.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                s = chunk['offset'] / 1e7
                words.append(
                    {
                        'spoken': chunk['text'],
                        'start': s,
                        'end': s + chunk['duration'] / 1e7,
                    }
                )
    return [w for w in words if WORD.search(w['spoken'])]


def _elevenlabs(text: str, cfg: dict, mp3: Path) -> list[dict]:
    """
    Synthesize with ElevenLabs /with-timestamps and rebuild word timings from characters.

    :param text: str, spoken text
    :param cfg: dict, voice.elevenlabs config
    :param mp3: Path, output mp3
    :return: list[dict], spoken word timings
    """
    key = os.environ.get('ELEVENLABS_API_KEY')
    if not key or not cfg.get('voice_id'):
        sys.exit('ElevenLabs needs ELEVENLABS_API_KEY and voice.elevenlabs.voice_id')
    body = {
        'text': text,
        'model_id': cfg['model_id'],
        'voice_settings': {
            k: cfg[k] for k in ('stability', 'similarity_boost', 'style')
        },
    }
    req = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{cfg["voice_id"]}/with-timestamps',
        data=json.dumps(body).encode(),
        headers={'xi-api-key': key, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        data = json.loads(res.read())
    mp3.write_bytes(base64.b64decode(data['audio_base64']))
    al = data['alignment']
    words, cur = [], None
    for ch, s, e in zip(
        al['characters'],
        al['character_start_times_seconds'],
        al['character_end_times_seconds'],
    ):
        if WORD.match(ch):
            cur = cur or {'spoken': '', 'start': s}
            cur['spoken'] += ch
            cur['end'] = e
        elif cur:
            words.append(cur)
            cur = None
    if cur:
        words.append(cur)
    return words


def synth_scene(scene: dict, cfg: dict, lexicon: dict, out_dir: Path) -> dict:
    """
    Produce <id>.wav and the word timings for one scene, retrying flaky providers.

    :param scene: dict, storyboard scene with `id` and `narration`
    :param cfg: dict, full skill config
    :param lexicon: dict, pronunciation replacements
    :param out_dir: Path, audio directory of the release
    :return: dict, {'id', 'duration', 'words'}
    """
    spoken, mapping = to_spoken(scene['narration'].strip(), lexicon)
    provider = cfg['voice']['provider']
    mp3, wav = out_dir / f'{scene["id"]}.mp3', out_dir / f'{scene["id"]}.wav'
    for attempt in range(3):
        try:
            if provider == 'edge':
                words = asyncio.run(_edge(spoken, cfg['voice']['edge'], mp3))
            elif provider == 'elevenlabs':
                words = _elevenlabs(spoken, cfg['voice']['elevenlabs'], mp3)
            else:
                sys.exit(f'Unknown voice provider {provider!r} (edge | elevenlabs)')
            break
        except Exception as e:  # noqa: BLE001 - network providers fail in many ways
            if attempt == 2:
                raise
            print(f'TTS retry {scene["id"]}: {e}', file=sys.stderr)
            time.sleep(2 + attempt * 3)
    run(
        [
            ffmpeg(),
            '-y',
            '-v',
            'error',
            '-i',
            str(mp3),
            '-ar',
            '48000',
            '-ac',
            '1',
            str(wav),
        ]
    )
    mp3.unlink(missing_ok=True)
    dur = media_duration(wav)
    return {
        'id': scene['id'],
        'duration': dur,
        'spoken': spoken,
        'words': align(mapping, words, dur),
    }


def synth_all(
    work: Path, board: dict, cfg: dict, only: list[str] | None = None
) -> dict:
    """
    Narrate every scene (or a subset) and write audio/timings.json.

    :param work: Path, release work directory
    :param board: dict, storyboard
    :param cfg: dict, full skill config
    :param only: list[str] | None, scene ids to regenerate
    :return: dict, timings keyed by scene id
    """
    out_dir = work / 'audio'
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / 'timings.json'
    timings = json.loads(path.read_text()) if path.exists() else {}
    lexicon = load_lexicon()
    for scene in board['scenes']:
        if only and scene['id'] not in only:
            continue
        timings[scene['id']] = synth_scene(scene, cfg, lexicon, out_dir)
        print(
            f'{scene["id"]:<14} {timings[scene["id"]]["duration"]:5.1f}s  {len(scene["narration"].split())} words'
        )
    timings = {s['id']: timings[s['id']] for s in board['scenes'] if s['id'] in timings}
    write_json(path, timings)
    total = sum(t['duration'] for t in timings.values())
    print(f'narration total {total:.1f}s')
    return timings
