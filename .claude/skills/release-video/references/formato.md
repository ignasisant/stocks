# Formato estándar MyBrainStock (≈35–45 s, 16:9; export 9:16 con `--format 9x16`)

Every video starts from `assets/templates/escenas.yaml` (`init` copies it). Change the copy and the
steps; keep the shape. It is the shape the 2026-11 "mapa + IA" video reached after many takes, so
departing from it needs a reason.

## The spine

| # | Scene | kind | Length | What is on screen |
|---|---|---|---|---|
| 1 | gancho + mapa | `ui` | 15–18 s | Real UI from frame 0 already zoomed (`at: 0`) on the answer to the hook question. Then the explanation with zooms that land on each narrated thing, and one click that changes the view. |
| 2 | ia | `ui` | 8–10 s | Chat drawer on the same page: type the question (input zoomed), answer arrives in a cut, zoom on its first paragraph, ring on the line with the figures. |
| 3 | mcp | `video` (or `card` until the clip exists) | 6–8 s | Claude Desktop/claude.ai reading the demo book through the connector. The user records it; see "MCP clip". |
| 4 | cierre | `outro` | 5–6 s | Landing look: eyebrow pill, gradient title, CTA `mybrainstock.com`, a real shot of scene 1 on the right. |

One differentiator per scene. Basics (value, TWR, FIFO) never get a scene of their own.

## Non-negotiables
- **Never a bare title.** Every card has `card.shot` (a ui scene id, `{scene: id, at: 0–1}`, or a PNG in
  the release dir); `check` fails without it. The shot sits in the landing's bordered card with a slow
  Ken Burns; aim it with `shot_focus: [x%, y%]` and `shot_zoom: [from, to]`.
- **Landing branding, not Ánfora.** Colours, fonts and glows come from `brand:` in config
  (= `src/stocks/web/landing_css.py`, dark). Titles mark the gradient words with `*asterisks*`:
  `'Tu cartera, *dentro de Claude*'`. Kicker = mono eyebrow pill. Outro carries `cta:`.
- **Hook in ≤2 s on real UI**: a question with stakes, already zoomed on where the answer is.
- **Sample data disclosed**: `release.badge` set, narration says "cartera de ejemplo" early, `tag:` on cards.
- **Short copy**: ≈2.4 words/s; cards ≤2 items; subtitles ≤42 chars × 2 lines.

## Polish (on by default)
- **Karaoke subtitles**: the word being said turns `brand.accent`. Off: `subtitles.karaoke: false`.
- **Auto-zoom** on clicks/hovers/fills in scenes without manual zooms (see escenas.md, `auto_zoom`).
- **SFX**: soft click on each click, pop on each highlight/card item, whoosh on each scene change,
  mixed under the voice before loudnorm (`sfx.volume_db` −12, per-effect `sfx.gain`, `sfx.enabled`).
  The wavs in `assets/sfx/` are synthesized by `scripts/make_sfx.py` (original, license-free); rerun it
  to regenerate.

## Card fields (landing template)
`kicker` (eyebrow pill) · `title` (`*grad*`) · `subtitle` · `items` (≤2, `{title, text, on}`) ·
`cta` (outro button) · `tag` (top-right) · `shot` · `shot_focus` · `shot_zoom`.

## AI scene: the demo account
Guest mode locks the chat, so AI footage runs on `video-demo@example.com` (`env local-demo`) on a
local server. Never the owner, never a real user.

1. Server with the demo book: `uv run stocks dashboard --port 8502` (any port; set `base_url`).
2. Key once: `uv run python .claude/skills/release-video/scripts/demo_gemini.py video-demo@example.com`
   — the user pastes a Gemini key (getpass, BYOK on the demo account only). Model `gemini-flash-lite-latest`
   (8–25 s per answer). The free chain (Groq/OpenRouter) is too often rate-limited to record on.
3. Before a take: `uv run python .claude/skills/release-video/scripts/demo_reset.py video-demo@example.com --probe`
   — real empty thread, drawer closed, one probe answer (fails if error or >40 s). `record` runs the
   reset itself for any env with `demo_email`.
4. **Never show chat Settings** (masked key on screen). Never put `mcp__topstocks__*` output on screen.

Recipe that reads well (copy from the template):
- setup: open `/review`, close drawer, fold the menu, set `chatPanelWidth` 640px, click the fab.
- steps: `zoom` input 1.7× `at: 0` → `fill` (`delay: 25`; the cursor hides while typing) → `press Enter`
  → `wait_for` `.ag-chat-assistant .ag-chat-meta-btn` (a hold: the wait is cut) → `python` scroll with
  `held: true` (lands in the same cut, no visible jump) → `zoom` 2.3× on `.ag-chat-bubble > :first-child`
  → `highlight` on the `li` with the figures, `on:` the word "cifras".

## MCP clip
Playwright cannot record Claude's client. The user records it (screen recording of Claude Desktop or
claude.ai with the connector on an account holding only the sample book — never the real one; the
prod connector of the owner reads the real book), drops the file in
the release dir and the scene becomes `kind: video, src: mcp.mov, start: <s>, speed: 1.0–1.25`.
Review every frame of `src` before building. Until it exists, the mcp scene is a `card` with a shot.

## Review before delivering
- `qa` passes, then 2 fps contact sheets of the **whole** video:
  `$FF -i release_*.mp4 -vf "fps=2,scale=480:-1,tile=4x5" sheet%02d.png`
  (`FF=$($PY -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")`).
- Check: hook frame, each zoom on its word, auto-zooms landing on the clicked thing, nothing cut under the badge or subtitles, no cursor
  artefacts, cards with a visible shot, CTA readable. Not something you would post yourself = not delivered.
- You cannot hear: SFX/whoosh levels are the user's call. Name them when delivering.

## Lessons this format already absorbs
- Overlay CSS is an adopted stylesheet: a `<style>` could end up unparsed after the drawer opened and
  the overlay root fell back to the UA popover box (framed square mid-screen).
- `held: true` on any step runs it inside a hold: used for scrolls that must not show as a jump.
- Zoom then zoom_out then zoom pumps; chain zooms directly.
- Empty `chat.json` invents a new thread id per read (POST /chat/runs 404): `demo_reset` seeds a real thread.

## Comparison videos (X vs MyBrainStock)
- Scenes about the other platform: own logo, colours and imagery (`card.brand`), real clips from a sample-book-only account when the user provides them (`kind: video`); mock pages only as a flagged placeholder.
- Neutral example values, no named buy/sell, no signals matrix.

