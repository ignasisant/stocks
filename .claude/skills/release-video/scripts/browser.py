"""Visible login browser: the user logs in by hand each run; its profile lives in RAM and is wiped on stop."""

import json
import os
import re
import shutil
import signal
import sys
import time
import urllib.request
from pathlib import Path

RAM = Path('/dev/shm') if Path('/dev/shm').is_dir() else Path('/tmp')
STATE_DIR = RAM / f'release-video-{os.getuid()}'
STATE = STATE_DIR / 'browser.json'
PORT = 9333
# Keeps the hidden/minimised login window painting if a scene must record inside it.
NO_THROTTLE = [
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
]


def start(login_url: str) -> None:
    """
    Launch a headed Chromium on the login page and keep it alive until stopped.

    :param login_url: str, page where the user logs in
    :return: None
    """
    from playwright.sync_api import sync_playwright

    if STATE.exists():
        sys.exit(
            f'Login browser already running ({STATE}); run `release.py browser stop` first'
        )
    profile = STATE_DIR / 'profile'
    profile.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)

    def _cleanup(*_: object) -> None:
        shutil.rmtree(STATE_DIR, ignore_errors=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            no_viewport=True,
            locale='es-ES',
            ignore_https_errors=True,
            args=[
                f'--remote-debugging-port={PORT}',
                '--window-size=1500,950',
                *NO_THROTTLE,
            ],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(login_url)
        STATE.write_text(
            json.dumps({'pid': os.getpid(), 'port': PORT, 'login_url': login_url})
        )
        print('READY', flush=True)
        while True:
            try:
                page.wait_for_timeout(1000) if not page.is_closed() else time.sleep(1)
            except Exception:  # noqa: BLE001 - window closed by the user
                if not ctx.pages:
                    _cleanup()
                time.sleep(1)


def tabs() -> list[str]:
    """
    List the URLs open in the login browser.

    :return: list[str], page URLs
    """
    with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list', timeout=5) as res:
        return [t['url'] for t in json.loads(res.read()) if t.get('type') == 'page']


def wait_login(pattern: str, timeout: int = 900) -> str:
    """
    Block until any tab reaches a URL matching the logged-in pattern.

    :param pattern: str, regex of a post-login URL
    :param timeout: int, seconds to wait
    :return: str, the matching URL
    """
    rx = re.compile(pattern)
    end = time.time() + timeout
    while time.time() < end:
        try:
            for url in tabs():
                if rx.search(url):
                    print('LOGGED_IN', url, flush=True)
                    return url
        except OSError:
            pass
        time.sleep(2)
    sys.exit('Timed out waiting for login')


async def session_state(ctx) -> dict:
    """
    Copy the login session in memory: cookies plus localStorage of every open tab's origin.

    connect_over_cdp's storage_state() comes back empty for persistent contexts, so localStorage is read
    from the pages themselves. The result is passed straight to new_context and never written to disk.

    :param ctx: playwright BrowserContext, the login browser's context
    :return: dict, a Playwright storage_state
    """
    origins = {}
    for page in ctx.pages:
        try:
            origin = await page.evaluate('location.origin')
            if origin.startswith('http') and origin not in origins:
                items = await page.evaluate('Object.entries(localStorage)')
                origins[origin] = [{'name': k, 'value': v} for k, v in items]
        except Exception:  # noqa: BLE001 - tab mid-navigation or closed
            continue
    return {
        'cookies': await ctx.cookies(),
        'origins': [{'origin': o, 'localStorage': ls} for o, ls in origins.items()],
    }


def stop() -> None:
    """
    Close the login browser and wipe its RAM profile.

    :return: None
    """
    if STATE.exists():
        pid = json.loads(STATE.read_text())['pid']
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(1.5)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    print('STOPPED')
