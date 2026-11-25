#!/usr/bin/env bash
# Install the release-video skill's runtime: venv with pinned deps, Playwright Chromium, music asset.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${RELEASE_VIDEO_CACHE:-$HOME/.cache/release-video}/venv"
PY="${PYTHON:-python3}"

[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$HERE/requirements.txt"
"$VENV/bin/python" -m playwright install chromium
[ -f "$HERE/../assets/music/explainer_soft.m4a" ] || {
  "$VENV/bin/python" "$HERE/make_music.py" "$HERE/../assets/music/explainer_soft_raw.wav"
  "$("$VENV/bin/python" -c 'import imageio_ffmpeg as i; print(i.get_ffmpeg_exe())')" -v error -y \
    -i "$HERE/../assets/music/explainer_soft_raw.wav" -c:a aac -b:a 192k "$HERE/../assets/music/explainer_soft.m4a"
  rm -f "$HERE/../assets/music/explainer_soft_raw.wav"
}
mkdir -p "$HOME/.config/release-video"
echo "OK → $VENV/bin/python $HERE/release.py --help"
