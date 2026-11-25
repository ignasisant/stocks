"""Explore a page with the login session (copied in memory to headless): screenshot, text, ad-hoc code."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import PORT, session_state  # noqa: E402
from recorder import TEXT_JS  # noqa: E402

from common import load_config  # noqa: E402


async def main(a: argparse.Namespace) -> None:
    """
    Open a URL headless (guest mode, or the login browser's session) and report what is on screen.

    :param a: argparse.Namespace, CLI args (env, url, shot, code, text)
    :return: None
    """
    from playwright.async_api import async_playwright

    cfg = load_config()
    env = cfg['environments'][a.env]
    vw, vh = cfg['video']['viewport']
    async with async_playwright() as pw:
        state = None
        if not env.get('guest') and not env.get('demo_email'):
            login = await pw.chromium.connect_over_cdp(f'http://127.0.0.1:{PORT}')
            state = await session_state(login.contexts[0])
        try:
            b = await pw.chromium.launch(headless=True, channel='chromium')
        except Exception:  # noqa: BLE001 - channel not installed
            b = await pw.chromium.launch(headless=True)
        size = {'width': vw, 'height': vh}
        ctx = await b.new_context(
            storage_state=state,
            viewport=size,
            screen=size,
            device_scale_factor=1,
            locale='es-ES',
            ignore_https_errors=bool(env.get('insecure')),
        )
        if env.get('demo_email'):
            from recorder import demo_cookies
            await ctx.add_cookies(demo_cookies(env))
        elif env.get('guest'):
            boot = await ctx.new_page()  # `?guest=1` sets the ts_guest cookie
            await boot.goto(env['base_url'] + env.get('guest_path', '/?guest=1'))
            await boot.wait_for_load_state('networkidle')
            await boot.close()
        page = await ctx.new_page()
        if a.work:
            from recorder import install_mocks

            from common import load_storyboard

            await install_mocks(page, load_storyboard(Path(a.work)), {})
        url = a.url if a.url.startswith('http') else env['base_url'] + a.url
        await page.goto(url)
        await page.wait_for_load_state('networkidle')
        await page.wait_for_timeout(a.wait * 1000)
        if a.code:
            ns = {'page': page, 'json': json, 'asyncio': asyncio}
            exec(  # nosemgrep: no-exec  # local exploration snippet
                'async def __c():\n'
                + '\n'.join(
                    '    ' + ln for ln in Path(a.code).read_text().splitlines()
                ),
                ns,
            )
            out = await ns['__c']()
            if out is not None:
                print(
                    out
                    if isinstance(out, str)
                    else json.dumps(out, ensure_ascii=False, indent=1)[:20000]
                )
        if a.shot:
            await page.screenshot(path=a.shot)
        if a.text:
            print((await page.evaluate(TEXT_JS))[: a.text])
        print('URL', page.url)
        await b.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env', required=True)
    p.add_argument('--url', required=True)
    p.add_argument('--shot')
    p.add_argument(
        '--code', help='file with async python using `page`; `return` prints'
    )
    p.add_argument(
        '--text', type=int, default=0, help='print the first N chars of visible text'
    )
    p.add_argument('--wait', type=float, default=2)
    p.add_argument('--work', help='release dir: apply its escenas.yaml mock_api')
    asyncio.run(main(p.parse_args()))
