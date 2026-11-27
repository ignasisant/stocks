"""Shared paths, config loading and process helpers for the release video pipeline."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / 'assets'
CACHE = Path(
    os.environ.get('RELEASE_VIDEO_CACHE', Path.home() / '.cache' / 'release-video')
)
USER_CONFIG = Path.home() / '.config' / 'release-video' / 'config.yaml'
FPS = 30

# Output format. `release.py` sets RELEASE_VIDEO_FORMAT from --format before anything imports this,
# so every module sees one layout. 16x9 is the master; 9x16 re-frames the same recording.
FORMAT = os.environ.get('RELEASE_VIDEO_FORMAT', '16x9').replace(':', 'x')
VERTICAL = FORMAT == '9x16'
if FORMAT not in ('16x9', '9x16'):
    sys.exit(f'Unknown format {FORMAT!r} (use 16x9 or 9x16)')
OUT_W, OUT_H = (1080, 1920) if VERTICAL else (1920, 1080)
# Where the recorded UI is drawn on the canvas (x, y, w, h). Vertical: a square stage with a badge row
# above it and a caption band below it; the top and bottom keep clear of the platform's own UI
# (approximate: Reels/TikTok/Shorts differ, so these are constants to tune, not a spec).
STAGE = (0, 270, 1080, 1080) if VERTICAL else (0, 0, 1920, 1080)
BADGE_Y = 196 if VERTICAL else 26          # vertical: centred above the stage; 16:9: top right
CAPTION_BOTTOM = 330 if VERTICAL else 58   # ASS MarginV of the bottom caption style
SUFFIX = '_9x16' if VERTICAL else ''       # deliverables and per-format build folders
CLIPS = 'clips' + SUFFIX                   # composed clips (and, for cards, their frames)


def load_config(path: str | None = None) -> dict:
    """
    Load the skill config: example defaults overlaid with the user's own file.

    :param path: str | None, explicit config path; defaults to ~/.config/release-video/config.yaml
    :return: dict, merged configuration
    """
    cfg = yaml.safe_load((SKILL_DIR / 'config.example.yaml').read_text())
    user = Path(path) if path else USER_CONFIG
    if user.exists():
        _deep_merge(cfg, yaml.safe_load(user.read_text()) or {})
    return cfg


def _deep_merge(base: dict, extra: dict) -> None:
    """
    Merge extra into base in place, recursing into nested dicts.

    :param base: dict, dict that receives the values
    :param extra: dict, values that win over base
    :return: None
    """
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def ffmpeg() -> str:
    """
    Return an ffmpeg binary with libx264 + libass (the imageio-ffmpeg static build).

    :return: str, path to the ffmpeg executable
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return shutil.which('ffmpeg') or 'ffmpeg'


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    """
    Run a command and fail loudly with its stderr tail.

    :param cmd: list[str], argv to execute
    :param quiet: bool, capture output instead of streaming it
    :return: subprocess.CompletedProcess, the finished process
    """
    res = subprocess.run(cmd, capture_output=quiet, text=True)
    if res.returncode != 0:
        tail = (res.stderr or '')[-2500:]
        sys.exit(f'Command failed ({res.returncode}): {" ".join(cmd[:6])} ...\n{tail}')
    return res


def media_duration(path: Path) -> float:
    """
    Read a media file's duration in seconds with ffmpeg.

    :param path: Path, audio or video file
    :return: float, duration in seconds
    """
    res = subprocess.run(
        [ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True, text=True
    )
    for line in res.stderr.splitlines():
        if 'Duration:' in line:
            h, m, s = line.split('Duration:')[1].split(',')[0].strip().split(':')
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f'No duration for {path}')


def read_json(path: Path) -> Any:
    """
    Read a JSON file.

    :param path: Path, file to read
    :return: Any, parsed content
    """
    return json.loads(Path(path).read_text())


def write_json(path: Path, data: Any) -> None:
    """
    Write data as pretty JSON, creating parent directories.

    :param path: Path, destination file
    :param data: Any, JSON-serialisable content
    :return: None
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def load_storyboard(work: Path) -> dict:
    """
    Load escenas.yaml from a release work directory.

    :param work: Path, release work directory
    :return: dict, storyboard with release metadata and scenes
    """
    board = yaml.safe_load((Path(work) / 'escenas.yaml').read_text())
    board['_work'] = str(Path(work).resolve())
    board = _fix_yaml_bools(board)
    for sc in board['scenes']:
        for key in ('setup', 'steps'):
            sc[key] = _flatten(sc.get(key, []))
    ids = [s['id'] for s in board['scenes']]
    if len(ids) != len(set(ids)):
        sys.exit('escenas.yaml: scene ids must be unique')
    return board


def _flatten(steps: list) -> list:
    """
    Flatten nested step lists (YAML anchors reused inside setup/steps).

    :param steps: list, steps possibly containing lists of steps
    :return: list, flat list of step dicts
    """
    out = []
    for st in steps or []:
        out.extend(_flatten(st) if isinstance(st, list) else [st])
    return out


def _fix_yaml_bools(node: Any) -> Any:
    """
    Restore keys YAML 1.1 turns into booleans (`on:` → True), recursively.

    :param node: Any, parsed YAML node
    :return: Any, the node with `on` keys back as strings
    """
    if isinstance(node, dict):
        return {
            ('on' if k is True else 'off' if k is False else k): _fix_yaml_bools(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_fix_yaml_bools(v) for v in node]
    return node
