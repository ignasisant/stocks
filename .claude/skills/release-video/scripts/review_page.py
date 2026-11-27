#!/usr/bin/env python3
"""review_page — one HTML page to react to options (card styles, captions, music...) with keep / maybe / drop.

Usage: review_page.py OPTIONS_DIR [--title T] [--open]
OPTIONS_DIR holds one file per option (.png/.jpg/.webp/.mp4/.mp3/.wav); the filename is its label.
Writes OPTIONS_DIR/review.html. "Copy verdicts" puts `label: keep|maybe|drop` lines on the clipboard
to paste back in chat; the verdicts then go to references/ as (picked) rules.
Look at every option yourself before sending the page: it must match what its label says.
"""

import argparse
import html
import webbrowser
from pathlib import Path

IMG = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
VID = {'.mp4', '.mov', '.webm'}
AUD = {'.mp3', '.wav', '.m4a'}


def media(f: Path) -> str:
    """
    HTML element that shows one option.

    :param f: Path, option file
    :return: str, img/video/audio tag with a relative src
    """
    src = html.escape(f.name)
    if f.suffix.lower() in IMG:
        return f'<img src="{src}" loading="lazy">'
    if f.suffix.lower() in VID:
        return f'<video src="{src}" controls loop muted playsinline></video>'
    return f'<audio src="{src}" controls></audio>'


def build(folder: Path, title: str) -> str:
    """
    Render the review page for every media file in a folder.

    :param folder: Path, options directory
    :param title: str, page heading
    :return: str, full HTML document
    """
    files = sorted(f for f in folder.iterdir() if f.suffix.lower() in IMG | VID | AUD)
    cards = ''.join(
        f'<section data-label="{html.escape(f.stem)}"><h2>{html.escape(f.stem)}</h2>{media(f)}'
        '<div class="v"><button data-v="keep">Keep</button><button data-v="maybe">Maybe</button>'
        '<button data-v="drop">Drop</button></div></section>'
        for f in files
    )
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font:16px system-ui;margin:0 auto;padding:16px;max-width:1100px;background:#fff;color:#111}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}}
section{{border:2px solid #ddd;border-radius:10px;padding:10px}}
section h2{{font-size:14px;margin:0 0 8px}} img,video{{width:100%;border-radius:6px}} audio{{width:100%}}
.v{{display:flex;gap:6px;margin-top:8px}} button{{flex:1;padding:10px;border:1px solid #bbb;border-radius:6px;background:#fff;font:inherit;cursor:pointer}}
section[data-v=keep]{{border-color:#1a9a4a}} section[data-v=maybe]{{border-color:#d9a400}} section[data-v=drop]{{border-color:#c33;opacity:.55}}
button.on{{background:#111;color:#fff}} #copy{{position:sticky;bottom:12px;width:100%;margin-top:16px;background:#111;color:#fff}}
@media(prefers-color-scheme:dark){{body{{background:#111;color:#eee}}button{{background:#222;color:#eee;border-color:#444}}button.on,#copy{{background:#eee;color:#111}}section{{border-color:#333}}}}
</style>
<h1>{html.escape(title)}</h1><div class="grid">{cards}</div>
<button id="copy">Copy verdicts</button>
<script>
document.querySelectorAll('section').forEach(s=>s.querySelectorAll('button').forEach(b=>b.onclick=()=>{{
  s.dataset.v=b.dataset.v;s.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));}}));
document.getElementById('copy').onclick=async e=>{{
  const t=[...document.querySelectorAll('section')].map(s=>s.dataset.label+': '+(s.dataset.v||'unrated')).join('\\n');
  try{{await navigator.clipboard.writeText(t);e.target.textContent='Copied';}}catch(_){{prompt('Copy:',t);}}}};
</script>"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--title', default='Review options')
    p.add_argument('--open', action='store_true')
    a = p.parse_args()
    out = a.folder / 'review.html'
    out.write_text(build(a.folder, a.title))
    print(out)
    if a.open:
        webbrowser.open(out.as_uri())


if __name__ == '__main__':
    main()
