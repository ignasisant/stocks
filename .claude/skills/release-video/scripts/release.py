#!/usr/bin/env python3
"""release — explainer video of a MyBrainStock release or feature. Run `release.py <command> -h` for each step."""

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The output format must be known before `common` is imported: its size constants are read at import.
for _i, _arg in enumerate(sys.argv):
    if _arg.startswith('--format='):
        os.environ['RELEASE_VIDEO_FORMAT'] = _arg.split('=', 1)[1]
    elif _arg == '--format' and _i + 1 < len(sys.argv):
        os.environ['RELEASE_VIDEO_FORMAT'] = sys.argv[_i + 1]

from common import (  # noqa: E402
    ASSETS,
    CACHE,
    CLIPS,
    VERTICAL,
    load_config,
    load_storyboard,
    read_json,
)

KINDS = {'ui', 'card', 'title', 'outro', 'diagram', 'video'}
CARD_KINDS = {'card', 'title', 'outro', 'diagram'}


def build_dir(work: Path) -> Path:
    """
    Heavy intermediates (frames, audio, clips) live in the cache, not next to the deliverables.

    :param work: Path, release directory
    :return: Path, build directory
    """
    d = CACHE / 'builds' / work.resolve().name
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_init(a: argparse.Namespace, cfg: dict) -> None:
    """
    Create the release directory.

    :param a: argparse.Namespace, CLI args (version)
    :param cfg: dict, config
    :return: None
    """
    slug = re.sub(r'[^\w.-]+', '-', a.version).strip('-')
    work = Path(cfg['output_dir']).expanduser() / f'release_{slug}'
    work.mkdir(parents=True, exist_ok=True)
    # Start from the standard format (references/formato.md), never from a blank file.
    board = work / 'escenas.yaml'
    if not board.exists():
        tpl = ASSETS / 'templates' / 'escenas.yaml'
        board.write_text(tpl.read_text().replace('VERSION', slug, 1))
    print(
        json.dumps({'work': str(work), 'build': str(build_dir(work)), 'version': slug})
    )


def cmd_gather(a: argparse.Namespace, cfg: dict) -> None:
    """
    Read PRs with gh and list linked task codes / PRs into contexto.json.

    :param a: argparse.Namespace, CLI args (pr, jira, repo, owner)
    :param cfg: dict, config
    :return: None
    """
    from gather import gather

    ctx = gather(a.work, a.pr or [], a.jira or [], a.repo, a.owner)
    for pr in ctx['prs']:
        print(
            f'PR {pr["repo"]}#{pr["number"]} [{pr["state"]}] {pr["title"]}  files={len(pr["files"])} jira={pr["jira_keys"]}'
        )
    for key, prs in ctx['prs_by_jira_key'].items():
        print(
            f'JIRA {key}: '
            + ', '.join(f'{p["repo"]}#{p["url"].rsplit("/", 1)[-1]}' for p in prs)
        )
    print(
        f'→ {a.work / "contexto.json"}  (add anything the PRs do not say under "notes")'
    )


def cmd_check(a: argparse.Namespace, cfg: dict) -> None:
    """
    Validate escenas.yaml: kinds, word budget, `on` words present, ui scenes have steps.

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    from recorder import IMAGE_EXT, _norm

    board = load_storyboard(a.work)
    rel = board.get('release', {})
    errs, total = [], 0
    for key in ('version', 'title'):
        if not rel.get(key):
            errs.append(f'release.{key} missing')
    for sc in board['scenes']:
        if sc.get('kind') not in KINDS:
            errs.append(f'{sc["id"]}: kind must be one of {sorted(KINDS)}')
        words = [_norm(w) for w in sc.get('narration', '').split()]
        total += len(words)
        ons = [st['on'] for st in sc.get('steps', []) if 'on' in st]
        ons += [
            it['on']
            for it in sc.get('card', {}).get('items', [])
            if isinstance(it, dict) and it.get('on')
        ]
        pos = 0
        for on in ons:
            hit = next(
                (i for i in range(pos, len(words)) if words[i].startswith(_norm(on))),
                None,
            )
            if hit is None:
                errs.append(
                    f'{sc["id"]}: `on: {on}` not found in narration after word #{pos}'
                )
            else:
                pos = hit + 1 if sc['kind'] == 'ui' else pos
        if sc['kind'] == 'video' and not Path(str(sc.get('src', ''))).expanduser().exists():
            errs.append(f'{sc["id"]}: video scene needs an existing `src:` file')
        if sc['kind'] == 'ui' and not sc.get('steps'):
            errs.append(f'{sc["id"]}: ui scene without steps')
        if sc['kind'] in CARD_KINDS:
            shot = sc.get('card', {}).get('shot')
            ids = {s['id']: s['kind'] for s in board['scenes']}
            ref = shot.get('scene') if isinstance(shot, dict) else shot
            if not shot:
                errs.append(
                    f'{sc["id"]}: a card needs real product behind it: `card.shot:` '
                    'a ui scene id or an image (see references/formato.md)'
                )
            elif isinstance(ref, str) and ref.lower().endswith(IMAGE_EXT):
                if not (a.work / ref).exists():
                    errs.append(f'{sc["id"]}: shot image {ref} not found')
            elif ids.get(ref) != 'ui':
                errs.append(f'{sc["id"]}: shot {ref!r} is not a ui scene')
    if VERTICAL:
        for sc in board['scenes']:
            if sc.get('kind') == 'ui' and not sc.get('focus'):
                acts = [
                    st for st in sc.get('steps', []) if st.get('do') in ('zoom', 'click', 'fill', 'hover')
                ]
                if not acts:
                    print(f'WARN {sc["id"]}: no zoom/click/hover to follow; 9:16 shows the page centre (add `focus: [x, y]`, fractions 0-1)')
            if sc.get('kind') == 'video':
                print(f'WARN {sc["id"]}: external video is letterboxed into the 9:16 stage (it keeps its own 16:9)')
    limit = rel.get('max_duration', cfg['max_duration'])
    budget = int(limit * cfg['words_per_second'] * 0.92)
    print(f'narration words {total} / budget {budget} for {limit}s')
    if total > budget:
        errs.append(f'narration has {total} words; {limit}s allows about {budget}')
    print('\n'.join(f'ERROR {e}' for e in errs) or 'OK')
    sys.exit(1 if errs else 0)


def cmd_tts(a: argparse.Namespace, cfg: dict) -> None:
    """
    Narrate scenes (all, or --scenes) into the build directory.

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    from tts import synth_all

    board = load_storyboard(a.work)
    scenes = [s for s in board['scenes'] if s.get('narration', '').strip()]
    synth_all(build_dir(a.work), {**board, 'scenes': scenes}, cfg, a.scenes)


def cmd_browser(a: argparse.Namespace, cfg: dict) -> None:
    """
    Login browser: start (blocks; run in background), wait (until logged in), stop (wipe).

    :param a: argparse.Namespace, CLI args (action, env, url)
    :param cfg: dict, config
    :return: None
    """
    import browser

    env = cfg['environments'].get(a.env or '', {})
    if a.action == 'start':
        browser.start(a.url or env['login_url'])
    elif a.action == 'wait':
        browser.wait_login(a.pattern or env['logged_in'], a.timeout)
    elif a.action == 'tabs':
        print('\n'.join(browser.tabs()))
    else:
        browser.stop()


def cmd_record(a: argparse.Namespace, cfg: dict) -> None:
    """
    Record scene clips; failed UI scenes are reported so they can be fixed or turned into cards.

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    from recorder import record

    board = {**load_storyboard(a.work), '_dir': str(a.work)}
    build = build_dir(a.work)
    tpath = build / 'audio' / 'timings.json'
    timings = read_json(tpath) if tpath.exists() else {}
    missing = [
        s['id']
        for s in board['scenes']
        if s.get('narration', '').strip() and s['id'] not in timings
    ]
    if missing:
        sys.exit(f'Run tts first; no narration for {missing}')
    if VERTICAL:
        # UI footage is shared with the 16:9 take: only the cards are re-recorded, at portrait size.
        print('9:16: recording cards only (UI scenes are re-framed from the 16:9 recording)')
        board = {
            **board,
            'scenes': [s for s in board['scenes'] if s['kind'] in CARD_KINDS],
        }
        cfg = {**cfg, 'video': {**cfg['video'], 'viewport': [1080, 1920]}}
    failed = asyncio.run(
        record(
            build,
            board,
            cfg,
            timings,
            a.env,
            a.scenes,
            a.in_login_browser,
            a.setup_only,
        )
    )
    if failed:
        print(
            'FAILED '
            + ','.join(failed)
            + '  (see clips/<id>/failure.png; fix steps or switch the scene to kind: card)'
        )
        sys.exit(2)


def cmd_build(a: argparse.Namespace, cfg: dict) -> None:
    """
    Compose every clip and assemble the final MP4 + SRT.

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    from assemble import assemble
    from compose import compose_scene, compose_video

    board = load_storyboard(a.work)
    build = build_dir(a.work)
    timings = read_json(build / 'audio' / 'timings.json')
    for sc in board['scenes']:
        if (
            a.scenes
            and sc['id'] not in a.scenes
            and (build / CLIPS / sc['id'] / 'clip.mp4').exists()
        ):
            continue
        # 9:16 re-frames the 16:9 recording of UI scenes; cards have their own portrait frames.
        src = build / CLIPS / sc['id']
        if not (src / 'timeline.json').exists():
            src = build / 'clips' / sc['id']
        focus = tuple(sc.get('focus', (0.5, 0.5)))
        badge = sc.get(
            'badge',
            board['release'].get('badge') if sc.get('kind') in ('ui', 'video') else None,
        )
        if sc.get('kind') == 'video':
            meta = compose_video(
                build / CLIPS / sc['id'],
                timings.get(sc['id'], {}),
                cfg,
                sc['src'],
                sc.get('start', 0.0),
                sc.get('speed', 1.0),
                badge,
            )
            print(f'CLIP {sc["id"]:<14} {meta["duration"]:5.1f}s  video {sc["src"]}')
            continue
        meta = compose_scene(
            build / CLIPS / sc['id'],
            timings.get(sc['id'], {}),
            cfg,
            sc.get('hold'),
            badge,
            sc.get('auto_zoom', True),
            focus,
            src,
        )
        print(
            f'CLIP {sc["id"]:<14} {meta["duration"]:5.1f}s  cut_holds={meta["cut_holds"]}s overrun={meta["overrun"]}s'
        )
    assemble(a.work, build, board, cfg, timings)


def cmd_qa(a: argparse.Namespace, cfg: dict) -> None:
    """
    Run the QA gate and print the report (exit 1 on hard failures).

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    from qa import qa

    board = load_storyboard(a.work)
    build = build_dir(a.work)
    rep = qa(a.work, build, board, cfg, read_json(build / 'audio' / 'timings.json'))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    sys.exit(0 if rep['ok'] else 1)


def cmd_clean(a: argparse.Namespace, cfg: dict) -> None:
    """
    Delete the build directory (frames, clips, audio) once the video is accepted.

    :param a: argparse.Namespace, CLI args
    :param cfg: dict, config
    :return: None
    """
    d = CACHE / 'builds' / a.work.resolve().name
    shutil.rmtree(d, ignore_errors=True)
    print(f'removed {d}')


def main() -> None:
    """
    Parse the CLI and dispatch.

    :return: None
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        '--config', help='config file (default ~/.config/release-video/config.yaml)'
    )
    sub = p.add_subparsers(dest='cmd', required=True)
    work = argparse.ArgumentParser(add_help=False)
    work.add_argument(
        '--work', type=Path, required=True, help='release directory (from init)'
    )
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument(
        '--format',
        choices=['16x9', '9x16'],
        default='16x9',
        help='output format: 16x9 master (default) or 9x16 re-framed from the same recording',
    )
    scenes = argparse.ArgumentParser(add_help=False)
    scenes.add_argument(
        '--scenes', type=lambda s: s.split(','), help='comma-separated scene ids'
    )

    s = sub.add_parser('init')
    s.add_argument('--version', required=True)
    s = sub.add_parser('gather', parents=[work])
    s.add_argument('--pr', nargs='*')
    s.add_argument('--issue', '--jira', dest='jira', nargs='*')
    s.add_argument(
        '--repo', default='ignasisant/stocks', help='repo for bare PR numbers'
    )
    s.add_argument('--owner', default='ignasisant')
    sub.add_parser('check', parents=[work, fmt])
    sub.add_parser('tts', parents=[work, scenes])
    s = sub.add_parser('browser')
    s.add_argument('action', choices=['start', 'wait', 'tabs', 'stop'])
    s.add_argument('--env')
    s.add_argument('--url', help='override login URL')
    s.add_argument('--pattern', help='override logged-in URL regex')
    s.add_argument('--timeout', type=int, default=900)
    s = sub.add_parser('record', parents=[work, scenes, fmt])
    s.add_argument('--env')
    s.add_argument(
        '--in-login-browser',
        action='store_true',
        help='record inside the visible window',
    )
    s.add_argument(
        '--setup-only',
        action='store_true',
        help='run setup steps only (selector check)',
    )
    sub.add_parser('build', parents=[work, scenes, fmt])
    sub.add_parser('qa', parents=[work, fmt])
    sub.add_parser('clean', parents=[work])
    a = p.parse_args()
    cfg = load_config(a.config)
    {
        'init': cmd_init,
        'gather': cmd_gather,
        'check': cmd_check,
        'tts': cmd_tts,
        'browser': cmd_browser,
        'record': cmd_record,
        'build': cmd_build,
        'qa': cmd_qa,
        'clean': cmd_clean,
    }[a.cmd](a, cfg)


if __name__ == '__main__':
    main()
