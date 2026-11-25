# release-video — explainer/social video of a MyBrainStock release

Turns a PR or a feature description into a ≤60 s 16:9 video (real app footage in guest mode + Spanish neural voice +
subtitles + soft music), an `.srt`, a script (`guion.md`) and post copy per network (`notas_release.md`).
Claude drives it through `SKILL.md`. Adapted from Amphora's hermes-release-video.

## Install
```bash
.claude/skills/release-video/scripts/setup.sh    # venv in ~/.cache/release-video/venv, Chromium, music
```
Needs `python3` ≥ 3.11, `gh` logged in. FFmpeg comes from `imageio-ffmpeg`. Overrides: `~/.config/release-video/config.yaml`.

| Variable | When |
|---|---|
| `ELEVENLABS_API_KEY` | `voice.provider: elevenlabs` (paid); default edge-tts is free |
| `RELEASE_VIDEO_CACHE` | Move the build cache |

No login anywhere: environments are `guest: true` and the app shows its sample book. Never point it at a real account.

## Example
```bash
PY=~/.cache/release-video/venv/bin/python; R=.claude/skills/release-video/scripts/release.py
$PY $R init --version 2026-11-mi-release               # → ~/Movies/mybrainstock-videos/release_2026-11-mi-release
W=~/Movies/mybrainstock-videos/release_2026-11-mi-release
$PY $R gather --work $W --pr 269
# write $W/escenas.yaml + guion.md (references/)
$PY $R check --work $W && $PY $R tts --work $W
$PY $R record --work $W --env prod-guest
$PY $R build --work $W && $PY $R qa --work $W
```

## Layout
```
SKILL.md · config.example.yaml (environments, voice, brand, music, subtitles)
scripts/     release.py · gather · tts · recorder + overlay.js · inspect_page · compose · subtitles · assemble · qa · make_music · setup.sh
references/  guion.md · escenas.md · pronunciacion.yaml · problemas.md
assets/      fonts (Instrument Sans, Epilogue — OFL) · logo · templates/card.html · music (synthesized by setup.sh, git-ignored)
```
