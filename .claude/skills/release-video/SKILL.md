---
name: release-video
description: Make a short explainer/social video (≤60 s) of a MyBrainStock release or feature — real product footage of the app in guest mode recorded with Playwright, natural Spanish voice-over, burned-in + .srt subtitles, soft music, branded cards — plus post copy for Instagram/TikTok/X/LinkedIn. Use it whenever the user asks for a video of a release, PR or feature, a demo/tutorial/explainer clip, "vídeo de la release", "vídeo de las novedades", "vídeo para redes", or wants to show what a change does, even without saying "skill".
---

# release-video — vídeo de una novedad de MyBrainStock

Pipeline: **gather → guion → aprobación → voz → grabación → montaje → QA → notas**.
Mechanics are in `scripts/release.py`; your job is understanding the change, writing script and
storyboard, driving the app and judging the result. Adapted from Amphora's hermes-release-video.

```bash
R=.claude/skills/release-video/scripts/release.py; PY=~/.cache/release-video/venv/bin/python   # from the repo root; setup: README.md
```

## Inputs
A PR (URL / `owner/repo#n` / number) and/or a feature description — at least one. Optional: focus,
duration (60 s), language (es-ES), environment (`prod-guest` default, `local-guest` for an unmerged
branch), `--auto` (skip script approval). Output is 16:9 1080p30 (landing, YouTube, X, LinkedIn).
Vertical 9:16 (1080×1920, Reels/TikTok/Shorts) is a second export of the same script: after the 16:9
build run `$PY $R record|build|qa --work $W --format 9x16` (`check --format 9x16` first). Videos are
made for social, so 9:16 is the primary deliverable: ship it first. UI scenes are re-recorded in the
phone layout (`video.mobile_ui_viewport`, 540×600, drawn 2× on a stage between badge and captions): the
app's real mobile UI, legible on a phone. A scene overrides its desktop steps with a `mobile:` block
(`setup`/`steps`): no side-menu closers or zooms, tab strips scroll, scroll the subject into view.
Set `mobile_ui_viewport: null` to fall back to cropping the 16:9 take (`focus: [fx, fy]`).
Deliverable: `release_<ver>_9x16.mp4`/`.srt`. Free: ffmpeg only.

**Start from the standard format: read `references/formato.md` first.** It fixes the spine (hook on
real UI → mapa → IA → MCP → branded outro), the landing branding and the demo-account workflow, so a
new video is copy and steps, not a redesign.

## 1. Gather and understand
1. `$PY $R init --version <slug>` → release dir `W` (`~/Movies/mybrainstock-videos`) with
   `escenas.yaml` copied from `assets/templates/escenas.yaml` (the standard format).
2. `$PY $R gather --work $W --pr <refs…>` → `contexto.json` (PR body, commits, files). With no PR,
   read the code / `src/stocks/web/onboarding.py` card and write the context in `W/contexto.json` by hand.
3. Classify changes (visible feature / improvement / fix / internal). Internal stays out. Same bar as
   `CLAUDE.md`: a scene is somewhere new to go; "one more broker" is a line, not a scene.

## 2. Script — `guion.md` + `escenas.yaml`
Read `references/guion.md` and `references/escenas.md`. Write both in `W`; `$PY $R check --work $W`
validates kinds, word budget (≈2.4 words/s) and that every `on:` word is in its narration. The
script rules the duration: cut words, never speed the voice. Unless `--auto`, show narration and
on-screen content and **wait for approval**. No promises of returns, no advice ("compra X"):
it is a tool for tracking and understanding a portfolio.

## 3. Voice
`$PY $R tts --work $W [--scenes a,b]` — edge-tts neural voice (config `voice`), word timestamps
included; ElevenLabs optional (`ELEVENLABS_API_KEY`). Never espeak/pyttsx3/gTTS. Names and acronyms
go in `references/pronunciacion.yaml` (audio only).

## 4. Recording
- Environments are `guest: true`: fresh headless context, `?guest=1` sets the `ts_guest` cookie, the
  app opens its **sample book** (Revolut sample). No login, nothing saved. **Never record a real
  account** — no `browser start`, no session copy.
- Unmerged branch: serve it from a worktree (`env local-guest`, `serve:` command), then `--env local-guest`.
- Explore before scripting steps: `$PY .claude/skills/release-video/scripts/inspect_page.py --env E --url … --shot x.png --text 1500 --code steps.py`; read screenshots for selectors.
  Guest mode locks some AI/import features: those scenes become `card`/`diagram` (**plan B**).
- `$PY $R record --work $W --env E [--scenes …]`; `--setup-only` checks selectors. A failed scene
  leaves `clips/<id>/failure.png`; fix the step or turn it into a card.

## 5. Build and QA (mandatory)
1. `$PY $R build --work $W [--scenes changed]` — clips fitted to narration, zooms, crossfades,
   karaoke subtitles (spoken word in the accent), auto-zoom on clicks when a scene has no manual
   zooms, click/pop/whoosh SFX, music ducked, −16 LUFS, H.264/AAC 1080p30.
2. `$PY $R qa --work $W` — duration, format, loudness, sync, PII + error/loading text, plus
   `qa/contact_sheet.jpg`. **Look at the contact sheet and frames of every UI scene**: readable
   subtitles, right thing on screen, no sample-book weirdness, no error/empty screens. Traps: `references/problemas.md`.

## Optional: measure and choose
- **Pace targets from references**: `$PY scripts/analyze_reference.py <local.mp4> --out DIR` → cuts/min, median shot,
  first cut, LUFS. Run on 2–3 product videos you like (the user supplies the files; never download or reuse
  third-party footage) and compare with ours (`qa` output). Record the numbers in `references/formato.md`.
- **Taste round**: when a style is open (card look, caption style, music), render 3–5 options on one short
  scene into a folder, check each against its label, then `$PY scripts/review_page.py DIR --open`. The user
  marks keep/maybe/drop and pastes the verdicts; write the winners as rules in `formato.md` / `problemas.md`.

## Rules learned (video review 2026-11)
- **Sample data is always disclosed.** Guest footage = invented operations. Narration says so in the
  first 5 s ("cuenta de ejemplo", never "tu cartera" / "tus datos" as if real); every `ui` scene keeps a
  `badge` "Cuenta de ejemplo · operaciones inventadas" (set `release.badge` once: burned at build, survives every zoom); the post copy says it too. Never show a
  named sell/buy recommendation (e.g. "Recortar AAPL") as if advice: prefer ticker, calendar, sectors.
- **No internal labels on cards.** The card footer shows `release.version` by default: set
  `tag:` on every card (e.g. `tag: Cuenta de ejemplo`) so the release dir name never leaks.
- **Subtitles must not cover UI.** In qa frames check the bottom cards/numbers; keep copy short or
  move the zoom/scroll so the figure being narrated is not under the caption.
- **Voice matches screen.** Do not narrate what is not shown (Importar is locked in guest); the page
  title on screen must match the word used (Asignación vs cartera).
- **Hook = a number or a question with stakes in the first 3 s**, not a static title; zooms ≥1.6×
  and thicker highlights so they read on a phone; no silent gaps >2 s.
- **Differentiators first.** For MyBrainStock: the Quality×Price map on `/review` (with the 1A/2A trail),
  the AI assistant answering about the book, and the MCP connector (Claude reading your book).
  Value/TWR/FIFO/sell lists are copyable basics: supporting shots only, never the spine of a video.
- **AI footage**: guest locks the chat. Use the throwaway `video-demo@example.com` account (`env local-demo`):
  seeded from `data/users/_guest/*` with its 'demo…' `note` rows relabelled (else `demo.has_real` walls
  /review); `record` mints its session and runs `scripts/demo_reset.py`. Gemini BYOK via
  `scripts/demo_gemini.py`, model flash-lite. Never the owner's account. Full workflow: `references/formato.md`.
- **Branding = the web landing**, never a generic dark card: every card has a real `shot`, `*gradient*`
  title words, the outro a `cta`. `check` enforces the shot.
- **MCP lives in Claude's client**, not the app: Playwright cannot record it, and the connected
  `mcp__topstocks__*` tools read the owner's real book — never put that output on screen.
- **Review frames densely** (≈2 fps per UI clip), not 6 stills: zooms must land on the narrated element
  (`zoom target:`, not guessed `box:` pixels). You cannot hear audio: voice is the user's call — give
  2–3 short samples before building. No draft goes to the user that you would not post yourself.
- 9:16 re-records UI in the phone layout: give each UI scene a `mobile:` block; a transient yfinance banner ("la fuente de precios no responde") can show in a recording, hide it in setup. `kind: video` scenes are letterboxed.
- **Two platforms = two looks.** When a scene is about another product (Claude…), its card, logo, colours and
  imagery are that product's, never MyBrainStock's, or the viewer cannot tell them apart. `card.brand:`
  overrides the global brand per card (`name, logo, plain: true, accent, cta, info, soft, up, background,
  text, muted, border`); Claude theme: `assets/logo/claude.svg`, terracotta `#D97757` on cream `#F5F4ED`.
  Until a real capture exists, a mock page of the other product is a placeholder: say so to the user.
- **A shot shows ONE thing, whole.** A zoom-baked frame cover-cropped in the shot box cuts the page and the
  viewer does not know what to look at. For a card, screenshot exactly the element at 2× (`clip=`) into a PNG
  in the release dir, hide floating bits (chat FAB, banners), and size the frame to it with
  `shot_size: [w, h]` (+ `shot_zoom: [1, 1.03]` for a gentle drift).
- **Playwright `get_by_role(name=…)` matches substrings**: "Plegar el menú" also hits "Desplegar el menú" and
  toggles the persisted fold. Always `exact=True`; wait for the button before clicking.

## 6. Deliver
- `W/release_<version>.mp4`, `.srt`, `guion.md`, `notas_release.md` (template in `references/guion.md`).
- `notas_release.md` carries post copy per network (IG/TikTok caption + hashtags, X, LinkedIn), in Spanish, ≤40 words each, link `mybrainstock.com`.
- Offer `$PY $R clean --work $W` (frames ≈1 GB). Report: paths, QA numbers, what was synthetic or a card. Do not publish anything; the user posts.
