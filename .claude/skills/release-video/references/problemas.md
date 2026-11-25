# Known problems and fixes

Lessons from hand-made tutorials and from building this skill. Check here before improvising a workaround.

| Symptom | Cause | Fix (already in the scripts unless noted) |
|---|---|---|
| Copying the Firefox session is denied ("Credential Exploration") | auto-mode classifier | Never read browser profiles. The user logs in by hand in `release.py browser start`. |
| `page.screenshot` times out, frames stop | headed window minimised / occluded → Chromium stops painting | Record headless with the session copied in memory (default). The login window also gets no-throttle flags for `--in-login-browser`. |
| A text locator clicks the overlay's own label | overlay text in the DOM | Overlay text is CSS `::after` content. |
| Ring / cursor hidden behind a modal | modal in the top layer | Overlay is a `popover` re-shown on every ring/badge. |
| `waitForURL` hangs on a SPA route change | no `load` event | Use `wait_for` on an element of the new view instead. |
| Video much longer than the voice (36–63 s dead waits) | fixed waits recorded as-is | Loading waits are holds and get cut; each clip is fitted to its narration. |
| Recording died after a save | one long take with writes | One clip per scene; never record writes. Guest mode only touches the sample book, never a real account. |
| Subtitles drift | timed by character count | Word timestamps from the TTS provider; fallback spreads by characters only if counts disagree. |
| Clipping (peak 0 dBFS) | no loudness pass | Two-pass `loudnorm` to −16 LUFS / −1.5 dBTP. |
| Soft zooms | the CDP screencast delivers CSS-pixel frames whatever the device scale | 1440×810 frames upscaled to 1080p; zooms up to ~2.4× stay legible on large UI text (map labels, buttons) but soften small print — check frames. For a crisper UI use `viewport: [1920, 1080]` (smaller UI on screen). |
| Fullscreen pages render at 800×600 / map framed wrong | `chromium-headless-shell` uses an 800×600 screen for the Fullscreen API | Record with new headless (`channel='chromium'`) and `screen` = viewport. |
| Steps fire all at once, ignoring the narration | PyYAML reads the key `on:` as boolean `True` | `load_storyboard` restores `on` keys. |
| `storage_state()` empty after `connect_over_cdp` | Playwright limitation with persistent contexts | `browser.session_state()` reads localStorage from the open tabs, in memory. |
| A locator matches a hidden twin (hidden tabs, off-screen copies) | duplicates in the DOM | Add `:visible` (or a `:not(...)` of the twin's class) to the css. |
| QA flags data hidden off-canvas (notification drawer) | text scan of the whole DOM | Text scan keeps only on-screen, uncovered elements. |
| `libx264` missing in system ffmpeg (Fedora) | ffmpeg-free build | `imageio-ffmpeg` static binary (libx264 + libass) from the venv. |
| Subtitles fall back to another font | brand fonts not installed | Fonts in `assets/fonts` passed as `fontsdir`. |
| `tee` polluted a JSON file | shell plumbing | Scripts write their own files; never pipe JSON through `tee`. |
| Cards: subtitles over the logo | footer at the bottom | Card footer sits at the top; the bottom band belongs to subtitles. |
| `storage_state` session not accepted headless | app keeps auth in sessionStorage / memory | `record --in-login-browser` records inside the visible window (keep it un-minimised). |
| edge-tts fails intermittently | free endpoint, network | Retries ×3; if it keeps failing, `voice.provider: elevenlabs` with a key. |
| Release dir name in card corner | `tag` defaults to product · version | Set `tag:` on every card. |
| Looks like real results / advice | guest sample book shown as the user's | See SKILL.md 'Rules learned': disclose, badge, no named recommendations. |
| Zoom lands on the wrong thing / on the chat drawer | a drawer or panel left open by an earlier take shifts the layout (prefs remember `chat_panel_open`) | Setup closes the drawer (`button.ag-chat-icon.ag-chat-head-wide` when `:root[data-chat=open]`) and collapses the sidebar ("Plegar el menú"); re-measure boxes with a probe screenshot. |
| Chat take leaves an empty "Conversación nueva" / failure toast | a failed or aborted turn in the demo account | Before each AI take overwrite `chat.json` with `{"version": 2, "active": null, "conversations": []}` (no `rm`). |
| AI scene: "El asistente no está disponible… api_error" | local free chain dead: Groq 403s from the dev network, OpenRouter free has a daily cap (resets 00:00 UTC) | Probe first: `llm._free_backends()` and stream "di hola" per backend; record the AI take only when one answers. |
| Hook frame is the whole page, tiny | first zoom eased in late (lead before narration) | Start zoomed on the answer to the hook question (`at: 0`, short `dur`), reveal the whole view on the next phrase. |
| Click on a small control unreadable | clicked at full frame | Zoom to the control (≈2.4×) on the word before, click, then pull back. |
| Disclosure pill covers page title | pill top-centre | Pill burned top-right. |
| `ffmpeg` not on PATH (macOS) | no system ffmpeg | `$PY -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"`; 2 fps sheets: `-vf "fps=2,scale=480:-1,tile=4x3"`. |
