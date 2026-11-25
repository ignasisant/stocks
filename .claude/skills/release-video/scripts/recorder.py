"""Record one clip per scene: Playwright drives the page in step with the narration, CDP screencasts frames."""

import asyncio
import os
import base64
import json
import re
import time
import unicodedata
from pathlib import Path

from common import ASSETS, SKILL_DIR, write_json

OVERLAY = (SKILL_DIR / 'scripts' / 'overlay.js').read_text()
CARD = SKILL_DIR / 'assets' / 'templates' / 'card.html'
# Collects visible text through shadow roots (design-system components hide theirs).
TEXT_JS = """() => {
  const out = [];
  // On screen = inside the viewport and the top-most element at its centre (not covered, not off-canvas).
  const onScreen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.right <= 0 || r.bottom <= 0 || r.left >= innerWidth || r.top >= innerHeight) return false;
    const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1);
    const y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const root = el.getRootNode();
    const hit = (root.elementFromPoint ? root : document).elementFromPoint(x, y);
    return !!hit && (el === hit || el.contains(hit) || hit.contains(el));
  };
  const walk = (n) => {
    if (n.nodeType === 3) {
      const t = n.textContent.trim();
      if (t && n.parentElement && onScreen(n.parentElement)) out.push(t);
      return;
    }
    if (n.nodeType !== 1 && n.nodeType !== 11) return;
    if (n.id === 'rv-root' || ['SCRIPT','STYLE','NOSCRIPT'].includes(n.tagName)) return;
    if (n.nodeType === 1) {
      const s = getComputedStyle(n);
      if (s.display === 'none' || s.visibility === 'hidden') return;
      if (['INPUT','TEXTAREA'].includes(n.tagName) && n.value && onScreen(n)) out.push(n.value);
    }
    if (n.shadowRoot) walk(n.shadowRoot);
    for (const c of n.childNodes) walk(c);
  };
  walk(document.body);
  return out.join('\\n');
}"""


def _norm(s: str) -> str:
    """
    Lower-case and strip accents and punctuation for word matching.

    :param s: str, word
    :return: str, normalized word
    """
    s = unicodedata.normalize('NFKD', s.lower())
    return re.sub(r'[^\w]', '', ''.join(c for c in s if not unicodedata.combining(c)))


class Clock:
    """Scene clock that excludes loading waits (holds) so the cut clip stays in sync with audio."""

    def __init__(self) -> None:
        """
        Start the clock now.

        :return: None
        """
        self.t0 = time.time()
        self.holds: list[list[float]] = []
        self._hold_start: float | None = None

    def virtual(self) -> float:
        """
        Seconds elapsed in the final clip (real time minus holds).

        :return: float, virtual seconds
        """
        held = sum(b - a for a, b in self.holds)
        if self._hold_start is not None:
            held += time.time() - self._hold_start
        return time.time() - self.t0 - held

    def hold(self) -> None:
        """
        Begin a hold: time that will be cut from the clip.

        :return: None
        """
        self._hold_start = time.time()

    def release(self) -> None:
        """
        End the current hold.

        :return: None
        """
        if self._hold_start is not None:
            self.holds.append([self._hold_start, time.time()])
            self._hold_start = None


class SceneRecorder:
    """Runs one scene's steps against a page while capturing a screencast."""

    def __init__(
        self, page, scene: dict, timing: dict, env: dict, cfg: dict, out: Path
    ) -> None:
        """
        Prepare a recorder for one scene.

        :param page: playwright Page, page to drive
        :param scene: dict, storyboard scene
        :param timing: dict, narration timing for the scene (duration, words)
        :param env: dict, environment config (base_url)
        :param cfg: dict, full skill config
        :param out: Path, scene output directory
        :return: None
        """
        self.page, self.scene, self.timing, self.env, self.cfg, self.out = (
            page,
            scene,
            timing,
            env,
            cfg,
            out,
        )
        self.lead = cfg['video']['scene_lead']
        self.events: list[dict] = []
        self.frames: list[dict] = []
        self.mouse = [cfg['video']['viewport'][0] / 2, cfg['video']['viewport'][1] / 2]
        self.word_cursor = 0
        self.texts: list[str] = []

    # ---------- screencast ----------
    async def start(self) -> None:
        """
        Start the CDP screencast and the scene clock.

        :return: None
        """
        (self.out / 'frames').mkdir(parents=True, exist_ok=True)
        self.cdp = await self.page.context.new_cdp_session(self.page)
        vw, vh = self.cfg['video']['viewport']
        scale = self.cfg['video']['scale']

        def on_frame(ev: dict) -> None:
            path = self.out / 'frames' / f'{len(self.frames):06d}.jpg'
            path.write_bytes(base64.b64decode(ev['data']))
            self.frames.append({'file': path.name, 'ts': ev['metadata']['timestamp']})
            asyncio.ensure_future(
                self.cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
            )

        self.cdp.on('Page.screencastFrame', on_frame)
        await self.cdp.send(
            'Page.startScreencast',
            {
                'format': 'jpeg',
                'quality': 90,
                'maxWidth': vw * scale,
                'maxHeight': vh * scale,
                'everyNthFrame': 1,
            },
        )
        await self.page.wait_for_timeout(150)
        self.clock = Clock()

    async def stop(self) -> None:
        """
        Stop the screencast and write timeline.json.

        :return: None
        """
        end = time.time()
        await self.cdp.send('Page.stopScreencast')
        await self.page.wait_for_timeout(200)
        write_json(
            self.out / 'timeline.json',
            {
                't0': self.clock.t0,
                'end': end,
                'holds': self.clock.holds,
                'frames': self.frames,
                'events': self.events,
                'viewport': self.cfg['video']['viewport'],
                'scale': self.cfg['video']['scale'],
            },
        )
        (self.out / 'text.txt').write_text('\n'.join(self.texts))

    # ---------- timing ----------
    def word_time(self, word: str) -> float:
        """
        Virtual time at which the narration says `word` (searching forward from the last match).

        :param word: str, word or word prefix from the narration
        :return: float, seconds since scene start
        """
        words = self.timing.get('words', [])
        target = _norm(word)
        for i in range(self.word_cursor, len(words)):
            if _norm(words[i]['text']).startswith(target):
                self.word_cursor = i + 1
                return self.lead + words[i]['start']
        raise ValueError(
            f'Scene {self.scene["id"]}: word {word!r} not found in narration (after #{self.word_cursor})'
        )

    async def until(self, t: float) -> None:
        """
        Wait until the scene clock reaches t.

        :param t: float, virtual seconds
        :return: None
        """
        while (left := t - self.clock.virtual()) > 0:
            await self.page.wait_for_timeout(min(left * 1000, 250))

    def mark(self, kind: str, **data: object) -> None:
        """
        Log an event at the current virtual time.

        :param kind: str, event type (zoom, zoom_out, highlight, clear, step)
        :param data: object, event payload
        :return: None
        """
        self.events.append({'t': round(self.clock.virtual(), 3), 'type': kind, **data})

    # ---------- targets ----------
    def locator(self, spec: dict | str):
        """
        Build a Playwright locator from a target spec (role/name, text, label, testid, css).

        :param spec: dict | str, target description; a str is a css selector
        :return: playwright Locator, the resolved locator
        """
        if isinstance(spec, str):
            spec = {'css': spec}
        base = self.locator(spec['within']) if 'within' in spec else self.page
        if 'role' in spec:
            loc = base.get_by_role(
                spec['role'], name=spec.get('name'), exact=spec.get('exact', False)
            )
        elif 'text' in spec:
            loc = base.get_by_text(spec['text'], exact=spec.get('exact', False))
        elif 'label' in spec:
            loc = base.get_by_label(spec['label'], exact=spec.get('exact', False))
        elif 'placeholder' in spec:
            loc = base.get_by_placeholder(spec['placeholder'])
        elif 'testid' in spec:
            loc = base.get_by_test_id(spec['testid'])
        else:
            loc = base.locator(spec['css'])
        if 'has_text' in spec:
            loc = loc.filter(has_text=spec['has_text'])
        return loc.nth(spec['nth']) if 'nth' in spec else loc.first

    async def box(self, spec: dict | str) -> dict:
        """
        Bounding box of a target in CSS px, waiting for it to be visible.

        :param spec: dict | str, target description
        :return: dict, {x, y, width, height}
        """
        loc = self.locator(spec)
        await loc.wait_for(state='visible', timeout=20000)
        bb = await loc.bounding_box()
        if not bb:
            raise RuntimeError(f'No box for {spec}')
        return bb

    async def move(self, x: float, y: float, ms: int = 650) -> None:
        """
        Glide the mouse to (x, y) with ease-in-out so the overlay cursor travels naturally.

        :param x: float, target x in CSS px
        :param y: float, target y in CSS px
        :param ms: int, travel time
        :return: None
        """
        sx, sy = self.mouse
        steps = max(8, ms // 16)
        for i in range(1, steps + 1):
            k = i / steps
            e = 2 * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 2 / 2
            await self.page.mouse.move(sx + (x - sx) * e, sy + (y - sy) * e)
            await self.page.wait_for_timeout(ms / steps)
        self.mouse = [x, y]

    async def overlay(self) -> None:
        """
        Inject (or re-inject after navigation) the recording overlay.

        :return: None
        """
        brand = self.cfg['brand']
        await self.page.evaluate(
            f'window.__RV_ACCENT={json.dumps(brand["accent"])};window.__RV_BG={json.dumps(brand["background"])};'
        )
        await self.page.evaluate(OVERLAY)
        await self.page.mouse.move(*self.mouse)

    async def snapshot_text(self) -> None:
        """
        Store the page's visible text for the PII scan.

        :return: None
        """
        try:
            self.texts.append(await self.page.evaluate(TEXT_JS))
        except Exception:  # noqa: BLE001 - page mid-navigation
            pass

    async def apply_masks(self) -> None:
        """
        Blur every element listed in the scene's `mask`.

        :return: None
        """
        rects = []
        for spec in self.scene.get('mask', []):
            loc = (
                self.locator(spec)
                if not isinstance(spec, str)
                else self.page.locator(spec)
            )
            for i in range(await loc.count() if isinstance(spec, str) else 1):
                item = loc.nth(i) if isinstance(spec, str) else loc
                if await item.is_visible():
                    bb = await item.bounding_box()
                    if bb:
                        rects.append(bb)
        if self.scene.get('mask'):
            await self.page.evaluate('r => window.__rv && window.__rv.blur(r)', rects)

    # ---------- steps ----------
    async def step(self, st: dict) -> None:
        """
        Execute one storyboard step.

        :param st: dict, step with `do` and its arguments (see references/escenas.md)
        :return: None
        """
        do = st['do']
        url = st.get('url')
        if do == 'goto':
            self.clock.hold()
            await self.page.goto(
                url if url.startswith('http') else self.env['base_url'] + url
            )
            await self.page.wait_for_load_state(st.get('until', 'networkidle'))
            await self.overlay()
            self.clock.release()
        elif do == 'wait_for':
            self.clock.hold()
            await self.locator(st['target']).wait_for(
                state=st.get('state', 'visible'), timeout=st.get('timeout', 45000)
            )
            self.clock.release()
        elif do == 'wait':
            self.clock.hold()
            await self.page.wait_for_timeout(st.get('s', 1) * 1000)
            self.clock.release()
        elif do == 'pause':
            await self.page.wait_for_timeout(st.get('s', 1) * 1000)
        elif do in ('click', 'hover', 'move'):
            bb = await self.box(st['target'])
            x, y = bb['x'] + bb['width'] * st.get('fx', 0.5), bb['y'] + bb[
                'height'
            ] * st.get('fy', 0.5)
            await self.move(x, y, st.get('ms', 650))
            if st.get('ring', do == 'click'):
                await self.page.evaluate('r => window.__rv.ring(r, 6)', bb)
                self.mark('highlight', box=bb, dur=1.2)
                await self.page.wait_for_timeout(st.get('ring_ms', 450))
            if do == 'click':
                await self.page.mouse.down()
                await self.page.wait_for_timeout(90)
                await self.page.mouse.up()
                await self.page.wait_for_timeout(250)
                await self.page.evaluate('window.__rv && window.__rv.clearRing()')
        elif do == 'fill':
            bb = await self.box(st['target'])
            await self.move(bb['x'] + 24, bb['y'] + bb['height'] / 2)
            await self.page.mouse.click(bb['x'] + 24, bb['y'] + bb['height'] / 2)
            await self.page.keyboard.press('Control+A')
            await self.page.keyboard.type(str(st['text']), delay=st.get('delay', 55))
        elif do == 'press':
            await self.page.keyboard.press(st['key'])
        elif do == 'scroll':
            if 'target' in st:
                await self.locator(st['target']).scroll_into_view_if_needed()
            else:
                for _ in range(10):
                    await self.page.mouse.wheel(0, st.get('dy', 400) / 10)
                    await self.page.wait_for_timeout(35)
        elif do == 'highlight':
            bb = await self.box(st['target'])
            fn = 'spotlight' if st.get('style') == 'spotlight' else 'ring'
            await self.page.evaluate(
                f'r => window.__rv.{fn}(r, {st.get("pad", 8)})', bb
            )
            self.mark('highlight', box=bb)
        elif do == 'clear':
            await self.page.evaluate(
                'window.__rv.clearRing(); window.__rv.clearSpotlight()'
            )
            self.mark('clear')
        elif do == 'zoom':
            bb = await self.box(st['target']) if 'target' in st else st['box']
            self.mark(
                'zoom', box=bb, scale=st.get('scale', 1.3), dur=st.get('dur', 0.9)
            )
        elif do == 'zoom_out':
            self.mark('zoom_out', dur=st.get('dur', 0.8))
        elif do == 'badge':
            await self.page.evaluate(
                '([n, t]) => window.__rv.badge(n, t)', [st.get('n'), st['text']]
            )
        elif do == 'hide_badge':
            await self.page.evaluate('window.__rv.hideBadge()')
        elif do == 'eval':
            await self.page.evaluate(st['js'])
        elif do == 'python':
            ns = {'page': self.page, 'rec': self, 'asyncio': asyncio}
            exec(  # nosemgrep: no-exec  # CH-4329: storyboard author's own step code
                'async def __s():\n'
                + '\n'.join('    ' + ln for ln in st['code'].splitlines()),
                ns,
            )
            await ns['__s']()
        else:
            raise ValueError(f'Unknown step {do!r}')

    async def run(self, setup_only: bool = False) -> None:
        """
        Run setup (unrecorded), then the recorded steps synced to narration, then the tail.

        :param setup_only: bool, stop after setup (to check selectors)
        :return: None
        """
        is_ui = self.scene.get('kind') == 'ui'
        for st in self.scene.get('setup', []):
            await self._unrecorded(st)
        if is_ui:
            await self.overlay()
            await self.apply_masks()
        if setup_only:
            return
        await self.start()
        steps = list(self.scene.get('steps', []))
        if not is_ui:
            await self.page.evaluate('window.__cardPlay()')
            # Card items appear when the narration reaches their `on` word.
            items = self.scene.get('card', {}).get('items', [])
            steps += [
                {
                    'do': 'eval',
                    'js': f'window.__cardStep({i})',
                    'on': it['on'],
                    'early': 0.15,
                }
                for i, it in enumerate(items)
                if isinstance(it, dict) and it.get('on')
            ]
        for st in steps:
            if 'on' in st:
                await self.until(self.word_time(st['on']) - st.get('early', 0.35))
            elif 'at' in st:
                await self.until(self.lead + st['at'])
            await self.step(st)
            await self.apply_masks()
            await self.snapshot_text()
        end = (
            self.lead
            + self.timing.get('duration', self.scene.get('hold', 2.5))
            + self.cfg['video']['scene_tail']
        )
        await self.until(end)
        await self.snapshot_text()
        await self.stop()

    async def _unrecorded(self, st: dict) -> None:
        """
        Run a setup step before the screencast starts (no clock yet).

        :param st: dict, step
        :return: None
        """
        self.clock = Clock()
        await self.step(st)


async def install_mocks(page, board: dict, scene: dict) -> None:
    """
    Answer API calls whose path ends with a configured suffix with a local JSON file (synthetic demo data).

    :param page: playwright Page, page about to be driven
    :param board: dict, storyboard (release.mock_api, _work)
    :param scene: dict, scene (its own mock_api wins)
    :return: None
    """
    mocks = {
        **board.get('release', {}).get('mock_api', {}),
        **scene.get('mock_api', {}),
    }
    if not mocks:
        return
    base = Path(board.get('_work', '.'))
    payloads = {k: json.loads((base / v).read_text()) for k, v in mocks.items()}

    async def handle(route) -> None:
        path = route.request.url.split('?')[0]
        hit = max((k for k in payloads if path.endswith(k)), key=len, default=None)
        if hit is None:
            await route.continue_()
        elif isinstance(payloads[hit], dict) and '__status' in payloads[hit]:
            # Error demo: {"__status": 409, "__body": {...}}
            await route.fulfill(
                status=payloads[hit]['__status'], json=payloads[hit].get('__body', {})
            )
        else:
            await route.fulfill(json=payloads[hit])

    await page.route(
        lambda url: any(url.split('?')[0].endswith(k) for k in payloads), handle
    )


def card_url(scene: dict, cfg: dict, board: dict) -> str:
    """
    Build the file:// URL of the card template for a card/diagram scene.

    :param scene: dict, storyboard scene with a `card` block
    :param cfg: dict, full skill config
    :param board: dict, storyboard (release metadata)
    :return: str, URL whose hash carries the card data
    """
    data = {
        **scene.get('card', {}),
        'kind': scene.get('card', {}).get('kind', scene['kind']),
        'release': board.get('release', {}),
        'brand': cfg['brand'],
        'assets': ASSETS.as_uri(),
    }
    return (
        CARD.as_uri()
        + '#'
        + base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    )


DEMO_GUARD = '@example.com'


def demo_cookies(envc: dict) -> list[dict]:
    """
    Session cookies for a throwaway local demo account, minted by the app itself.

    Only `@example.com` addresses on a local base_url: never the owner, never prod.

    :param envc: dict, environment config with `demo_email`, `base_url`, `repo`
    :return: list[dict], Playwright cookies (ts_session, ts_app)
    """
    import subprocess
    from urllib.parse import urlparse

    email = envc['demo_email']
    host = urlparse(envc['base_url']).hostname
    if not email.endswith(DEMO_GUARD) or host not in ('127.0.0.1', 'localhost'):
        raise SystemExit(f'demo_email must be *{DEMO_GUARD} on a local base_url')
    code = (
        'from stocks import session;'
        f'print(session.mint({{"email": {email!r}, "email_verified": True}}))'
    )
    tok = subprocess.run(
        ['uv', 'run', 'python', '-c', code],
        cwd=os.path.expanduser(envc.get('repo', '.')),
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]
    return [
        {'name': 'ts_session', 'value': tok, 'domain': host, 'path': '/'},
        {'name': 'ts_app', 'value': '1', 'domain': host, 'path': '/'},
    ]


async def record(
    work: Path,
    board: dict,
    cfg: dict,
    timings: dict,
    env_name: str | None,
    only: list[str] | None,
    in_login_browser: bool,
    setup_only: bool,
) -> list[str]:
    """
    Record every scene (or a subset); UI scenes reuse the login browser's session in a headless context.

    :param work: Path, release work directory
    :param board: dict, storyboard
    :param cfg: dict, full skill config
    :param timings: dict, narration timings keyed by scene id
    :param env_name: str | None, environment key for UI scenes
    :param only: list[str] | None, scene ids to record
    :param in_login_browser: bool, record inside the visible login window instead of headless
    :param setup_only: bool, only run setup steps (selector check)
    :return: list[str], ids of scenes that failed
    """
    from browser import PORT, session_state
    from playwright.async_api import async_playwright

    vw, vh = cfg['video']['viewport']
    scale = cfg['video']['scale']
    failed = []
    async with async_playwright() as pw:
        # New headless Chromium: headless_shell shrinks fullscreen pages to an 800×600 screen.
        try:
            headless = await pw.chromium.launch(headless=True, channel='chromium')
        except Exception:  # noqa: BLE001 - channel not installed
            headless = await pw.chromium.launch(headless=True)
        size = {'width': vw, 'height': vh}
        card_ctx = await headless.new_context(
            viewport=size, screen=size, device_scale_factor=scale
        )
        ui_ctx, login = None, None
        # External clips (kind: video) are cut in at build time, never recorded.
        scenes = [
            s
            for s in board['scenes']
            if (not only or s['id'] in only) and s['kind'] != 'video'
        ]
        if any(s['kind'] == 'ui' for s in scenes):
            if not env_name:
                raise SystemExit('UI scenes need --env')
            envc = cfg['environments'][env_name]
            if envc.get('guest') or envc.get('demo_email'):
                # Guest mode or a throwaway demo account: no login, fresh context, nothing to copy.
                ui_ctx = await headless.new_context(
                    viewport=size,
                    screen=size,
                    device_scale_factor=scale,
                    locale='es-ES',
                    timezone_id='Europe/Madrid',
                    ignore_https_errors=bool(envc.get('insecure')),
                )
                in_login_browser = False
                if envc.get('demo_email'):
                    await ui_ctx.add_cookies(demo_cookies(envc))
                else:
                    boot = await ui_ctx.new_page()  # `?guest=1` sets the ts_guest cookie
                    await boot.goto(envc['base_url'] + envc.get('guest_path', '/?guest=1'))
                    await boot.wait_for_load_state('networkidle')
                    await boot.close()
            else:
                login = await pw.chromium.connect_over_cdp(f'http://127.0.0.1:{PORT}')
            if login and not in_login_browser:
                src = login.contexts[0]
                state = await session_state(src)  # in memory only, never written
                ui_ctx = await headless.new_context(
                    storage_state=state,
                    viewport=size,
                    screen=size,
                    device_scale_factor=scale,
                    locale='es-ES',
                    timezone_id='Europe/Madrid',
                    ignore_https_errors=bool(
                        cfg['environments'][env_name].get('insecure')
                    ),
                )
        for scene in scenes:
            out = work / 'clips' / scene['id']
            if out.exists():
                import shutil

                shutil.rmtree(out)
            out.mkdir(parents=True)
            timing = timings.get(scene['id'], {})
            try:
                if scene['kind'] == 'ui':
                    if in_login_browser:
                        page = await login.contexts[0].new_page()
                        cdp = await login.contexts[0].new_cdp_session(page)
                        await cdp.send(
                            'Emulation.setDeviceMetricsOverride',
                            {
                                'width': vw,
                                'height': vh,
                                'deviceScaleFactor': scale,
                                'mobile': False,
                            },
                        )
                    else:
                        page = await ui_ctx.new_page()
                    await install_mocks(page, board, scene)
                    rec = SceneRecorder(
                        page, scene, timing, cfg['environments'][env_name], cfg, out
                    )
                else:
                    page = await card_ctx.new_page()
                    await page.goto(card_url(scene, cfg, board))
                    await page.wait_for_function(
                        'window.__cardReady === true', timeout=15000
                    )
                    rec = SceneRecorder(
                        page,
                        {**scene, 'steps': scene.get('steps', [])},
                        timing,
                        {'base_url': ''},
                        cfg,
                        out,
                    )
                await rec.run(setup_only=setup_only)
                await page.close()
                print(f'REC {scene["id"]:<14} frames={len(rec.frames)}', flush=True)
            except (
                Exception
            ) as e:  # noqa: BLE001 - one broken scene must not lose the others
                failed.append(scene['id'])
                print(
                    f'FAIL {scene["id"]}: {type(e).__name__}: {str(e)[:400]}',
                    flush=True,
                )
                try:
                    await page.screenshot(path=str(out / 'failure.png'))
                except Exception:  # noqa: BLE001
                    pass
        await headless.close()
    return failed
