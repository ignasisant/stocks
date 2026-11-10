#!/usr/bin/env python
"""Render the landing's 40-second video, one cut per language. Run when it changes.

    uv run --with imageio-ffmpeg scripts/landing_video.py [--lang es] [--still 20]

Writes `src/stocks/web/assets/topstocks-intro-<lang>.mp4` and its poster
`topstocks-intro-<lang>.jpg`. Both are committed, like the share card: a
container that drew them at boot would need a browser and the fonts.

The film is a web page, not a screen recording. The scenes are the landing's
own mock-ups (sample book, sample statement, sample answer) in the design
tokens, and one `render(t)` function poses the whole page at time `t`.
Playwright steps that clock frame by frame and screenshots each pose, so the
motion is exact at any frame rate and nobody's real book is ever on screen.
ffmpeg (from the `imageio-ffmpeg` wheel) encodes the frames to H.264.

`--still T` writes one frame at T seconds to the scratch directory instead,
for checking a scene without rendering the lot.
"""

# ruff: noqa: E501 — most of this file is the film's own HTML, CSS, JS and SVG
# path data, which read worse broken at 90 columns than left whole.

from __future__ import annotations

import argparse
import base64
import math
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocks.web import landing, seo  # noqa: E402
from stocks.web.ds import ds_vars_css  # noqa: E402

ASSETS = ROOT / "src" / "stocks" / "web" / "assets"
LANGS = ("en", "es", "it")

W, H = 1280, 720
SCALE = 1.5  # frames at 1920x1080
FPS = 30
# The timeline below (SCENES, every data-at) is written in film seconds; the
# cut plays it SPEED times faster. Stills and the poster stay in film seconds.
SECONDS = 54.0
SPEED = 1.4  # 54 film seconds play in 38.6
POSTER_AT = 19.5  # the ledger scene, every number on screen

# Film-only copy. Whatever the landing already says is read from its locale
# files instead (`_strings`), so the two cannot drift apart.
COPY = {
    "en": {
        "step": "Step {n}",
        "s2_title": "Drop your statement.",
        "s2_sub": "Revolut, IBKR, DEGIRO, Trading 212, Saxo. CSV, PDF or XLSX.",
        "drop": "Drop a CSV, PDF or XLSX",
        "file": "revolut-statement.csv",
        "rows": "228 rows",
        "committed": "214 transactions in your ledger",
        "s3_title": "Everything derives.",
        "s3_sub": "Positions, P/L, tax and risk, from one ledger.",
        "book": "Your book",
        "index": "S&P 500 · same money",
        "pos": "Position",
        "pl": "P/L",
        "weight": "Weight",
        "broker": "Your broker app",
        "real": "TopStocks",
        "broker_pct": "+18.2%",
        "real_pct": "+11.4%",
        "chips": (
            "FX at each trade's date",
            "The lots you sold, FIFO",
            "Fees and withholding",
        ),
        "s5_title": "Ask about your own book.",
        "s5_sub": "Answers from your ledger, with the sources.",
        "ask_hint": "Ask about your book…",
        "q": "If I sell 15 MSFT, what do I owe?",
        "status": "Reading your ledger",
        "answer": "Selling 15 MSFT realises **$2,340**, matched to your oldest "
        "lots (2023, long-term). Federal tax at 15%: about **$351**.",
        "sources": ("Your ledger · 2 lots", "Price · 7 Nov 2026"),
        "s6_title": "We never touch your broker login.",
    },
    "es": {
        "step": "Paso {n}",
        "s2_title": "Sube tu extracto.",
        "s2_sub": "Revolut, IBKR, DEGIRO, Trading 212, Saxo. CSV, PDF o XLSX.",
        "drop": "Suelta un CSV, PDF o XLSX",
        "file": "extracto-revolut.csv",
        "rows": "228 filas",
        "committed": "214 movimientos en tu libro",
        "s3_title": "Todo sale de ahí.",
        "s3_sub": "Posiciones, P/L, impuestos y riesgo, de un solo libro.",
        "book": "Tu cartera",
        "index": "S&P 500 · mismo dinero",
        "pos": "Posición",
        "pl": "P/L",
        "weight": "Peso",
        "broker": "La app de tu bróker",
        "real": "TopStocks",
        "broker_pct": "+18,2 %",
        "real_pct": "+11,4 %",
        "chips": (
            "Divisa a fecha de cada operación",
            "Los lotes vendidos, FIFO",
            "Comisiones y retenciones",
        ),
        "s5_title": "Pregunta por tu propia cartera.",
        "s5_sub": "Respuestas desde tu libro, con las fuentes.",
        "ask_hint": "Pregunta por tu cartera…",
        "q": "Si vendo 15 MSFT, ¿cuánto pago?",
        "status": "Leyendo tu libro",
        "answer": "Vender 15 MSFT realiza una ganancia de **2.340 €**, contra tus "
        "lotes más antiguos (FIFO). IRPF del ahorro al 19 %: unos **445 €**.",
        "sources": ("Tu libro · 2 lotes", "Cambio BCE · 7 nov 2026"),
        "s6_title": "Nunca tocamos tu bróker.",
    },
    "it": {
        "step": "Passo {n}",
        "s2_title": "Carica il tuo estratto.",
        "s2_sub": "Revolut, IBKR, DEGIRO, Trading 212, Saxo. CSV, PDF o XLSX.",
        "drop": "Trascina un CSV, PDF o XLSX",
        "file": "estratto-revolut.csv",
        "rows": "228 righe",
        "committed": "214 movimenti nel tuo registro",
        "s3_title": "Tutto deriva da lì.",
        "s3_sub": "Posizioni, P/L, tasse e rischio, da un solo registro.",
        "book": "Il tuo portafoglio",
        "index": "S&P 500 · stessi soldi",
        "pos": "Posizione",
        "pl": "P/L",
        "weight": "Peso",
        "broker": "L'app del tuo broker",
        "real": "TopStocks",
        "broker_pct": "+18,2%",
        "real_pct": "+11,4%",
        "chips": (
            "Cambio alla data di ogni operazione",
            "I lotti venduti, LIFO",
            "Commissioni e ritenute",
        ),
        "s5_title": "Chiedi del tuo portafoglio.",
        "s5_sub": "Risposte dal tuo registro, con le fonti.",
        "ask_hint": "Chiedi del tuo portafoglio…",
        "q": "Se vendo 15 MSFT, quanto pago?",
        "status": "Leggo il tuo registro",
        "answer": "Vendere 15 MSFT realizza una plusvalenza di **2.340 €**, sui lotti "
        "più recenti (LIFO). Imposta sostitutiva al 26%: circa **608 €**.",
        "sources": ("Il tuo registro · 2 lotti", "Cambio BCE · 7 nov 2026"),
        "s6_title": "Non tocchiamo mai il tuo broker.",
    },
}

# The landing hero's sample book, so the video and the page show one portfolio.
KPIS = (
    ("landing.kpi_cost", 48230, False),
    ("landing.kpi_value", 61484, False),
    ("landing.kpi_unrealised", 13254, True),
    ("landing.kpi_realised", 2141, True),
)
POSITIONS = (
    ("MSFT", 6120, 30.8),
    ("ASML", 3485, 20.0),
    ("ITX.MC", 2410, 16.1),
    ("NVDA", 1239, 9.7),
)
IMPORT_ROWS = (
    ("landing.imp_clean", 214, "up"),
    ("landing.imp_warn", 3, "warn"),
    ("landing.imp_reject", 1, "down"),
    ("landing.imp_skip", 6, "skip"),
)

# Scene windows in seconds: (id, in, out). Each fades in from its start and
# out over the last 0.6 s; neighbours overlap a little so the cut is a dissolve.
SCENES = (
    ("s1", 0.0, 5.0),
    ("s2", 4.7, 13.6),
    ("s3", 13.3, 23.0),
    ("s4", 22.7, 30.0),
    ("s5", 29.7, 41.0),
    ("s6", 40.7, 47.0),
    ("s7", 46.7, 99.0),
)


def _grad_tail(text: str) -> str:
    """Escape `text`, the part after its first comma or full stop in gradient."""
    m = re.search(r"([,.]\s)", text)
    if not m:
        return escape(text)
    cut = m.end()
    return f'{escape(text[:cut])}<span class="grad">{escape(text[cut:])}</span>'


def _grad_emphasis(text: str) -> str:
    return re.sub(r"\*([^*]+)\*", r'<span class="grad">\1</span>', escape(text))


def _series(end: float, wobble: float, phase: float, n: int = 48) -> list[float]:
    """A deterministic return path from 0 to `end` (fractions), gently noisy."""
    out = []
    for i in range(n):
        x = i / (n - 1)
        noise = wobble * (
            math.sin(9 * x + phase) * 0.6 + math.sin(23 * x + 2 * phase) * 0.4
        )
        out.append(end * x**0.9 + noise * math.sin(math.pi * x))
    return out


def _chart_paths() -> tuple[str, str, str]:
    """SVG paths for the book line, its area and the index line (640x200)."""
    book, index = _series(0.275, 0.035, 0.4), _series(0.19, 0.025, 1.7)
    lo, hi = min(book + index) - 0.02, max(book + index) + 0.02

    def pts(series: list[float]) -> list[tuple[float, float]]:
        return [
            (640 * i / (len(series) - 1), 200 - 200 * (v - lo) / (hi - lo))
            for i, v in enumerate(series)
        ]

    def line(series: list[float]) -> str:
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts(series))

    area = line(book) + " L640,200 L0,200 Z"
    return line(book), area, line(index)


def _answer_html(text: str) -> str:
    """The answer as one span per word, bold runs kept, for the word stream.

    Split on spaces before the `**` markers, so punctuation after a bold run
    stays on its word instead of streaming in as a word of its own.
    """
    out, bold = [], False
    for i, word in enumerate(text.split()):
        html = ""
        for j, part in enumerate(word.split("**")):
            bold ^= j > 0
            if part:
                html += (
                    f'<span class="num">{escape(part)}</span>' if bold else escape(part)
                )
        out.append(f'<span data-w="{i}">{html} </span>')
    return "".join(out)


def _strings(lang: str) -> dict:
    """Everything one cut says, in its language and its jurisdiction's money."""
    c = COPY[lang]
    with landing.render_language(lang):
        tr = landing.tr
        return {
            "c": c,
            "tagline": _grad_tail(tr("landing.footer_tagline")),
            "gap_title": escape(tr("landing.gap_title")),
            "kpis": [
                (tr(k, year=landing._FISCAL_YEAR), v, signed) for k, v, signed in KPIS
            ],
            "imports": [(tr(k), n, kind) for k, n, kind in IMPORT_ROWS],
            "flow": {
                k: tr(f"landing.flow_{k}")
                for k in ("broker", "file", "ledger", "no_login", "account", "caption")
            },
            "final_eyebrow": tr("landing.final_eyebrow"),
            "final_title": _grad_tail(tr("landing.final_title")),
            "final_sub": tr("landing.final_sub"),
            "sign_in": tr("common.sign_in_google"),
            "money": _money_format(landing._money(1000)),
        }


def _money_format(sample: str) -> dict:
    """How the landing writes 1000 here: symbol, side and grouping mark."""
    digits = re.search(r"1[.,  ]?000", sample).group(0)
    sep = digits[1] if len(digits) == 5 else ""
    sym = sample.replace(digits, "").strip()
    return {"sym": sym, "after": sample.strip().startswith("1"), "sep": sep}


def _money_text(amount: int, fmt: dict, signed: bool = False) -> str:
    body = f"{amount:,}".replace(",", fmt["sep"])
    sign = "+" if signed else ""
    return f"{sign}{body} {fmt['sym']}" if fmt["after"] else f"{sign}{fmt['sym']}{body}"


_ICONS = {
    "upload": '<path d="M12 16V4m0 0-5 5m5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "doc": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "bank": '<path d="M3 10 12 4l9 6M5 10v8m4-8v8m6-8v8m4-8v8M3 20h18"/>',
    "book": '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    "x": '<path d="m7 7 10 10M17 7 7 17"/>',
    "send": '<path d="M5 12h13m-5-6 6 6-6 6"/>',
}


def _icon(name: str, cls: str = "ico") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{_ICONS[name]}</svg>'
    )


_GOOGLE_G = (
    '<svg class="g" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" '
    'd="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 '
    "3-4.3 3-7.3zM12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6"
    "-4.1H3.1v2.6A10 10 0 0 0 12 22zM6.4 14c-.2-.6-.3-1.3-.3-2s.1-1.4.3-2V7.4H3.1a10 "
    "10 0 0 0 0 9.2zM12 6c1.5 0 2.8.5 3.8 1.5l2.9-2.9A10 10 0 0 0 3.1 7.4L6.4 10C7.2 "
    '7.7 9.4 6 12 6z"/></svg>'
)


def film_html(lang: str) -> str:
    s = _strings(lang)
    c, fmt = s["c"], s["money"]
    logo = (
        "data:image/svg+xml;base64,"
        + base64.b64encode((ASSETS / "topstocks-icon.svg").read_bytes()).decode()
    )
    book, area, index = _chart_paths()

    kpis = "".join(
        f'<div class="kpi" data-at="{14.2 + i * 0.15:.2f}"><span>{escape(label)}</span>'
        f'<b class="{"up" if signed else ""}" data-count="{value}" data-from="{14.4 + i * 0.15:.2f}" '
        f'data-sign="{int(signed)}">{escape(_money_text(value, fmt, signed))}</b></div>'
        for i, (label, value, signed) in enumerate(s["kpis"])
    )
    positions = "".join(
        f'<div class="pos" data-at="{16.4 + i * 0.22:.2f}" data-dy="0" data-dx="18">'
        f'<span class="tk"><i>{t[0]}</i>{t}</span>'
        f'<span class="up">{escape(_money_text(pl, fmt, True))}</span>'
        f'<span class="wt">{str(w).replace(".", "," if lang != "en" else ".")}%'
        f'<em><u data-bar="{w / 32:.3f}" data-from="{16.6 + i * 0.22:.2f}"></u></em></span></div>'
        for i, (t, pl, w) in enumerate(POSITIONS)
    )
    imports = "".join(
        f'<div class="row {kind}" data-at="{7.0 + i * 0.28:.2f}">'
        f'<span>{escape(label)}</span><b data-count="{n}" data-from="{7.1 + i * 0.28:.2f}" '
        f'data-plain="1">{n}</b></div>'
        for i, (label, n, kind) in enumerate(s["imports"])
    )
    chips = "".join(
        f'<span class="chip" data-at="{26.6 + i * 0.3:.2f}">{_icon("check")}{escape(t)}</span>'
        for i, t in enumerate(c["chips"])
    )
    sources = "".join(
        f'<span class="src" data-at="{38.4 + i * 0.3:.2f}">{escape(t)}</span>'
        for i, t in enumerate(c["sources"])
    )
    flow = s["flow"]
    scenes = ",".join(f'["{i}",{a},{b}]' for i, a, b in SCENES)
    step = lambda n: escape(c["step"].format(n=n))  # noqa: E731

    return Template(_TEMPLATE).substitute(
        lang=lang,
        tokens=ds_vars_css(),
        fonts=escape(seo.FONTS_HREF, quote=True),
        logo=logo,
        scenes=scenes,
        w=W,
        h=H,
        tagline=s["tagline"],
        step1=step(1),
        step2=step(2),
        step3=step(3),
        s2_title=escape(c["s2_title"]),
        s2_sub=escape(c["s2_sub"]),
        drop=escape(c["drop"]),
        file=escape(c["file"]),
        rows=escape(c["rows"]),
        imports=imports,
        committed=escape(c["committed"]),
        s3_title=escape(c["s3_title"]),
        s3_sub=escape(c["s3_sub"]),
        kpis=kpis,
        book_label=escape(c["book"]),
        index_label=escape(c["index"]),
        book=book,
        area=area,
        index=index,
        pos=escape(c["pos"]),
        pl=escape(c["pl"]),
        weight=escape(c["weight"]),
        positions=positions,
        gap_title=s["gap_title"],
        broker=escape(c["broker"]),
        real=escape(c["real"]),
        broker_pct=escape(c["broker_pct"]),
        real_pct=escape(c["real_pct"]),
        chips=chips,
        s5_title=escape(c["s5_title"]),
        s5_sub=escape(c["s5_sub"]),
        ask_hint=escape(c["ask_hint"]),
        q=escape(c["q"]),
        status=escape(c["status"]),
        answer=_answer_html(c["answer"]),
        sources=sources,
        s6_title=escape(c["s6_title"]),
        f_broker=escape(flow["broker"]),
        f_file=escape(flow["file"]),
        f_ledger=escape(flow["ledger"]),
        f_no_login=escape(flow["no_login"]),
        f_account=escape(flow["account"]),
        f_caption=escape(flow["caption"]),
        final_eyebrow=escape(s["final_eyebrow"]),
        final_title=s["final_title"],
        final_sub=escape(s["final_sub"]),
        sign_in=escape(s["sign_in"]),
        sep=fmt["sep"],
        sym=escape(fmt["sym"]),
        after=int(fmt["after"]),
        i_upload=_icon("upload", "ico up-ico"),
        i_doc=_icon("doc"),
        i_check=_icon("check"),
        i_bank=_icon("bank"),
        i_book=_icon("book"),
        i_x=_icon("x"),
        i_send=_icon("send"),
        g=_GOOGLE_G,
    )


# `$name` placeholders (string.Template); a literal dollar would be `$$`, and
# the script below concatenates strings rather than use template literals.
_TEMPLATE = r"""<!doctype html>
<html lang="$lang"><head><meta charset="utf-8">
<link rel="stylesheet" href="$fonts">
$tokens
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: ${w}px; height: ${h}px; overflow: hidden; background: var(--ag-surface-page); }
body { color: var(--ag-text-primary); font-family: 'Instrument Sans', sans-serif;
  -webkit-font-smoothing: antialiased; }
#stage { position: relative; width: ${w}px; height: ${h}px; overflow: hidden; isolation: isolate; }
.glow { position: absolute; width: 760px; height: 760px; border-radius: 50%; z-index: -1; }
.g1 { background: radial-gradient(circle, color-mix(in srgb, var(--ag-brand-cta) 42%, transparent), transparent 64%); }
.g2 { background: radial-gradient(circle, color-mix(in srgb, var(--ag-landing-info) 26%, transparent), transparent 64%); }
.g3 { background: radial-gradient(circle, color-mix(in srgb, var(--ag-brand-accent) 24%, transparent), transparent 64%); }
.grad { background: linear-gradient(100deg, var(--ag-landing-info), var(--ag-brand-accent) 50%, var(--ag-purple-300));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.s { position: absolute; inset: 0; visibility: hidden; }
[data-at] { opacity: 0; }
h1, h2 { font-family: 'Epilogue', sans-serif; font-weight: 800; letter-spacing: -0.025em; line-height: 1.08; }
h2 { font-size: 50px; }
.sub { font-size: 20px; line-height: 1.5; color: var(--ag-text-secondary); }
.eyebrow { display: inline-flex; align-items: center; gap: 8px; font-family: 'Martian Mono', monospace;
  font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--ag-purple-300);
  border: 1px solid var(--ag-border-brand-band); border-radius: 999px; padding: 6px 13px;
  background: color-mix(in srgb, var(--ag-brand-cta) 14%, transparent); }
.eyebrow::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--ag-landing-up); }
.card { background: color-mix(in srgb, var(--ag-surface-card) 86%, transparent);
  border: 1px solid var(--ag-border); border-radius: 22px;
  box-shadow: 0 40px 90px -40px color-mix(in srgb, var(--ag-brand-cta) 55%, transparent); }
.ico { width: 22px; height: 22px; flex: none; }
.mono { font-family: 'Martian Mono', monospace; }
.up { color: var(--ag-landing-up); }
.col { position: absolute; left: 80px; top: 50%; transform: translateY(-50%); width: 440px;
  display: flex; flex-direction: column; gap: 20px; align-items: flex-start; }

#brand { position: absolute; top: 30px; left: 40px; display: flex; gap: 10px; align-items: center;
  font-family: 'Epilogue'; font-weight: 800; font-size: 19px; opacity: 0; z-index: 5; }
#brand img { width: 30px; height: 30px; }

/* 1 · title */
#s1 .in { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 18px; text-align: center; }
#s1 img { width: 136px; height: 136px; }
#s1 h1 { font-size: 92px; }
#s1 p { font-size: 32px; font-weight: 600; color: var(--ag-text-secondary); }

/* 2 · import */
.zone { position: absolute; left: 600px; top: 120px; width: 600px; height: 480px; padding: 30px;
  border-radius: 24px; border: 2px dashed color-mix(in srgb, var(--ag-text-muted) 55%, transparent);
  background: color-mix(in srgb, var(--ag-surface-card) 60%, transparent);
  display: flex; flex-direction: column; gap: 12px; }
.zone .lit { position: absolute; inset: -2px; border-radius: 24px; border: 2px solid var(--ag-brand-accent);
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--ag-brand-cta) 18%, transparent),
    0 30px 90px -30px var(--ag-brand-cta); opacity: 0; pointer-events: none; }
.hint { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 14px; color: var(--ag-text-muted); font-size: 19px; }
.up-ico { width: 46px; height: 46px; color: var(--ag-brand-accent); }
.file { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border-radius: 16px;
  background: var(--ag-surface-raised); border: 1px solid var(--ag-border); opacity: 0;
  box-shadow: 0 20px 50px -24px rgb(0 0 0 / .7); margin-bottom: 8px; }
.file .tile { width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  color: var(--ag-on-brand); background: linear-gradient(135deg, var(--ag-brand-cta), var(--ag-landing-info)); }
.file b { font-size: 17px; font-weight: 600; }
.file small { margin-left: auto; font-family: 'Martian Mono'; font-size: 13px; color: var(--ag-text-muted); }
.row { display: flex; justify-content: space-between; align-items: center; padding: 13px 16px;
  border-radius: 12px; font-size: 16px; font-weight: 600; border: 1px solid; }
.row b { font-family: 'Martian Mono'; font-weight: 500; font-size: 15px; }
.row.up { color: var(--ag-landing-up); border-color: color-mix(in srgb, var(--ag-landing-up) 35%, transparent);
  background: color-mix(in srgb, var(--ag-landing-up) 10%, transparent); }
.row.warn { color: var(--ag-warn); border-color: color-mix(in srgb, var(--ag-warn) 35%, transparent);
  background: color-mix(in srgb, var(--ag-warn) 9%, transparent); }
.row.down { color: var(--ag-landing-down); border-color: color-mix(in srgb, var(--ag-landing-down) 35%, transparent);
  background: color-mix(in srgb, var(--ag-landing-down) 9%, transparent); }
.row.skip { color: var(--ag-text-secondary); border-color: var(--ag-border); background: var(--ag-surface-sunken); }
.done { display: flex; align-items: center; gap: 10px; margin-top: 10px; font-size: 18px; font-weight: 600; }
.done .ico { width: 30px; height: 30px; padding: 6px; border-radius: 50%; color: var(--ag-surface-page);
  background: var(--ag-landing-up); }

/* 3 · ledger */
#s3 .top { position: absolute; left: 80px; right: 80px; top: 80px; display: flex; align-items: flex-end;
  justify-content: space-between; gap: 40px; }
#s3 .top > div { display: flex; flex-direction: column; gap: 16px; align-items: flex-start; }
#s3 .top .sub { max-width: 400px; text-align: right; }
.ledger { position: absolute; left: 80px; right: 80px; top: 250px; height: 420px; padding: 26px;
  display: grid; grid-template-rows: auto 1fr; gap: 22px; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.kpi { padding: 14px 16px; border-radius: 14px; background: var(--ag-surface-sunken); border: 1px solid var(--ag-border);
  display: flex; flex-direction: column; gap: 6px; }
.kpi span { font-family: 'Martian Mono'; font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--ag-text-muted); }
.kpi b { font-family: 'Epilogue'; font-weight: 700; font-size: 28px; letter-spacing: -0.02em; }
.split { display: grid; grid-template-columns: 1fr 380px; gap: 28px; min-height: 0; }
.chart { display: flex; flex-direction: column; gap: 10px; }
.legend { display: flex; gap: 20px; font-size: 13px; color: var(--ag-text-secondary); }
.legend i { display: inline-block; width: 18px; height: 3px; border-radius: 2px; margin-right: 8px; vertical-align: middle; }
.legend .lb { background: linear-gradient(90deg, var(--ag-brand-cta), var(--ag-brand-accent)); }
.legend .li { background: var(--ag-landing-info); }
.chart svg { width: 100%; height: 200px; overflow: visible; }
.years { display: flex; justify-content: space-between; font-family: 'Martian Mono'; font-size: 11px; color: var(--ag-text-muted); }
.ptable { display: flex; flex-direction: column; border: 1px solid var(--ag-border); border-radius: 14px; overflow: hidden; }
.pos, .phead { display: grid; grid-template-columns: 1.3fr 1fr 1fr; align-items: center; padding: 11px 16px; font-size: 15px; }
.phead { font-family: 'Martian Mono'; font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--ag-text-muted); background: var(--ag-surface-sunken); }
.pos { border-top: 1px solid var(--ag-border); font-variant-numeric: tabular-nums; }
.pos .tk { display: flex; align-items: center; gap: 10px; font-weight: 600; }
.pos .tk i { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; font-style: normal;
  font-size: 12px; font-weight: 700; color: var(--ag-on-brand);
  background: linear-gradient(135deg, var(--ag-brand-cta), var(--ag-landing-info)); }
.pos > span:not(.tk), .phead .r { text-align: right; }
.wt { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
.wt em { width: 64px; height: 4px; border-radius: 2px; background: var(--ag-surface-sunken); overflow: hidden; }
.wt u { display: block; height: 100%; width: 100%; transform-origin: left; transform: scaleX(0);
  background: linear-gradient(90deg, var(--ag-brand-cta), var(--ag-brand-accent)); }

/* 4 · the gap */
#s4 .in { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 44px; text-align: center; }
#s4 h2 { max-width: 900px; }
.vs { display: flex; gap: 28px; }
.vs .card { width: 400px; padding: 30px 34px; display: flex; flex-direction: column; gap: 10px; align-items: center; position: relative; }
.vs span { font-size: 17px; color: var(--ag-text-secondary); font-weight: 600; }
.vs b { font-family: 'Epilogue'; font-weight: 800; font-size: 86px; letter-spacing: -0.03em; line-height: 1; position: relative; }
.vs .broker b { color: var(--ag-text-muted); }
.vs .broker b::after { content: ""; position: absolute; left: -6%; right: -6%; top: 52%; height: 5px; border-radius: 3px;
  background: var(--ag-landing-down); transform-origin: left; transform: scaleX(var(--strike, 0)); }
.vs .real { border-color: color-mix(in srgb, var(--ag-brand-accent) 55%, transparent); }
.chips { display: flex; gap: 14px; }
.chip { display: inline-flex; align-items: center; gap: 9px; padding: 11px 18px; border-radius: 999px; font-size: 16px;
  font-weight: 600; background: var(--ag-surface-raised); border: 1px solid var(--ag-border); }
.chip .ico { width: 18px; height: 18px; color: var(--ag-landing-up); }

/* 5 · ask */
.chat { position: absolute; left: 600px; top: 100px; width: 600px; height: 520px; display: flex; flex-direction: column; overflow: hidden; }
.chat header { display: flex; align-items: center; gap: 10px; padding: 16px 20px; border-bottom: 1px solid var(--ag-border);
  font-weight: 700; font-size: 16px; }
.chat header img { width: 24px; height: 24px; }
.thread { flex: 1; padding: 22px 20px; display: flex; flex-direction: column; gap: 16px; }
.bubble { max-width: 82%; padding: 13px 16px; border-radius: 18px; font-size: 17px; line-height: 1.5; }
.mine { align-self: flex-end; color: var(--ag-on-brand); border-bottom-right-radius: 6px;
  background: linear-gradient(110deg, var(--ag-brand-cta), color-mix(in srgb, var(--ag-brand-cta) 55%, var(--ag-landing-info))); }
.caret { display: inline-block; width: 2px; height: 1.05em; margin-left: 2px; vertical-align: -0.15em; background: currentColor; }
.status { display: flex; align-items: center; gap: 10px; font-size: 15px; color: var(--ag-text-secondary); }
.status .star { color: var(--ag-brand-accent); font-size: 20px; display: inline-block; }
.theirs { align-self: flex-start; background: var(--ag-surface-raised); border: 1px solid var(--ag-border); border-bottom-left-radius: 6px; }
.theirs [data-w] { opacity: 0; }
.theirs .num { font-weight: 700; color: var(--ag-purple-300); }
.srcs { display: flex; gap: 8px; }
.src { font-family: 'Martian Mono'; font-size: 11.5px; padding: 6px 10px; border-radius: 8px; color: var(--ag-text-secondary);
  background: var(--ag-surface-sunken); border: 1px solid var(--ag-border); }
.askbar { margin: 0 16px 16px; display: flex; align-items: center; gap: 10px; padding: 12px 14px 12px 18px; border-radius: 14px;
  background: var(--ag-surface-sunken); border: 1px solid var(--ag-border); color: var(--ag-text-muted); font-size: 15px; }
.askbar .ico { margin-left: auto; width: 34px; height: 34px; padding: 7px; border-radius: 10px; color: var(--ag-on-brand);
  background: var(--ag-brand-cta); }

/* 6 · privacy */
#s6 .in { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 56px; text-align: center; }
.flow { display: flex; align-items: center; }
.node { width: 230px; padding: 24px 18px; display: flex; flex-direction: column; align-items: center; gap: 12px;
  font-size: 18px; font-weight: 700; }
.node .ico { width: 40px; height: 40px; padding: 8px; border-radius: 12px; }
.node.muted .ico { color: var(--ag-text-muted); background: var(--ag-surface-sunken); }
.node.file .ico { color: var(--ag-on-brand); background: linear-gradient(135deg, var(--ag-brand-cta), var(--ag-landing-info)); }
.node.brand { border-color: color-mix(in srgb, var(--ag-brand-accent) 55%, transparent);
  background: color-mix(in srgb, var(--ag-brand-cta) 16%, var(--ag-surface-card)); }
.node.brand .ico { color: var(--ag-on-brand); background: var(--ag-brand-cta); }
.link { width: 170px; position: relative; height: 60px; }
.link .ln { position: absolute; left: 10px; right: 10px; top: 29px; height: 3px; transform-origin: left; transform: scaleX(0); }
.link.cut .ln { background: repeating-linear-gradient(90deg, var(--ag-landing-down) 0 9px, transparent 9px 16px); }
.link.live .ln { background: linear-gradient(90deg, var(--ag-brand-cta), var(--ag-landing-info)); border-radius: 2px; }
.link small { position: absolute; left: 0; right: 0; top: 0; font-family: 'Martian Mono'; font-size: 11.5px;
  color: var(--ag-text-secondary); opacity: 0; }
.link.cut small { color: var(--ag-landing-down); }
.link .xx { position: absolute; left: 70px; top: 15px; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
  color: var(--ag-surface-page); background: var(--ag-landing-down); transform: scale(0); }
.link .xx .ico { width: 18px; height: 18px; }
.link .dot { position: absolute; top: 24px; left: 10px; width: 13px; height: 13px; border-radius: 50%; opacity: 0;
  background: var(--ag-purple-300); box-shadow: 0 0 14px var(--ag-brand-accent); }
#s6 .sub { max-width: 640px; }

/* 7 · close */
.final { position: absolute; left: 190px; right: 190px; top: 110px; bottom: 110px; border-radius: 30px; overflow: hidden;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 22px; text-align: center; padding: 40px;
  border: 1px solid var(--ag-border-brand-band);
  background: linear-gradient(160deg, color-mix(in srgb, var(--ag-brand-cta) 22%, var(--ag-surface-card)), var(--ag-surface-card) 70%); }
.final img { width: 64px; height: 64px; }
.final h2 { font-size: 52px; max-width: 760px; }
.final .sub { max-width: 600px; font-size: 19px; }
.cta { display: inline-flex; align-items: center; gap: 12px; padding: 16px 30px; border-radius: 999px; font-size: 19px;
  font-weight: 700; color: var(--ag-on-brand); position: relative; overflow: hidden;
  background: linear-gradient(100deg, var(--ag-brand-cta), color-mix(in srgb, var(--ag-brand-cta) 55%, var(--ag-landing-info)));
  box-shadow: 0 18px 40px -14px var(--ag-cta-halo); }
.cta .g { width: 20px; height: 20px; }
.cta::after { content: ""; position: absolute; top: 0; bottom: 0; width: 60px; left: var(--shine, -80px);
  background: linear-gradient(100deg, transparent, rgb(255 255 255 / .35), transparent); }
</style></head>
<body><div id="stage">
<div class="glow g1"></div><div class="glow g2"></div><div class="glow g3"></div>
<div id="brand"><img src="$logo" alt="">TopStocks</div>

<section class="s" id="s1"><div class="in">
  <img src="$logo" alt="" data-at="0.3" data-dy="0" data-zoom="1">
  <h1 data-at="0.9">TopStocks</h1>
  <p data-at="1.6">$tagline</p>
</div></section>

<section class="s" id="s2">
  <div class="col">
    <span class="eyebrow" data-at="5.1">$step1</span>
    <h2 data-at="5.3">$s2_title</h2>
    <p class="sub" data-at="5.6">$s2_sub</p>
  </div>
  <div class="zone" data-at="5.4">
    <div class="lit"></div>
    <div class="hint">$i_upload<span>$drop</span></div>
    <div class="file"><span class="tile">$i_doc</span><b>$file</b><small>$rows</small></div>
    $imports
    <div class="done" data-at="9.6">$i_check<span>$committed</span></div>
  </div>
</section>

<section class="s" id="s3">
  <div class="top">
    <div><span class="eyebrow" data-at="13.6">$step2</span><h2 data-at="13.8">$s3_title</h2></div>
    <p class="sub" data-at="14.1">$s3_sub</p>
  </div>
  <div class="ledger card" data-at="14.0">
    <div class="kpis">$kpis</div>
    <div class="split">
      <div class="chart">
        <div class="legend"><span><i class="lb"></i>$book_label</span><span><i class="li"></i>$index_label</span></div>
        <svg viewBox="0 0 640 200" preserveAspectRatio="none">
          <defs>
            <linearGradient id="lg" x1="0" x2="1"><stop offset="0" stop-color="var(--ag-brand-cta)"/><stop offset="1" stop-color="var(--ag-brand-accent)"/></linearGradient>
            <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--ag-brand-cta)" stop-opacity=".35"/><stop offset="1" stop-color="var(--ag-brand-cta)" stop-opacity="0"/></linearGradient>
          </defs>
          <g stroke="var(--ag-border)" stroke-width="1"><path d="M0,50H640M0,100H640M0,150H640"/></g>
          <path id="area" d="$area" fill="url(#fill)" opacity="0"/>
          <path d="$index" fill="none" stroke="var(--ag-landing-info)" stroke-width="2" stroke-opacity=".8" data-draw="14.9" data-dur="2.6"/>
          <path d="$book" fill="none" stroke="url(#lg)" stroke-width="3.2" stroke-linejoin="round" data-draw="14.9" data-dur="2.6"/>
        </svg>
        <div class="years"><span>2023</span><span>2024</span><span>2025</span><span>2026</span></div>
      </div>
      <div class="ptable">
        <div class="phead" data-at="16.2"><span>$pos</span><span class="r">$pl</span><span class="r">$weight</span></div>
        $positions
      </div>
    </div>
  </div>
</section>

<section class="s" id="s4"><div class="in">
  <h2 data-at="23.0">$gap_title</h2>
  <div class="vs">
    <div class="card broker" data-at="23.6"><span>$broker</span><b id="strike">$broker_pct</b></div>
    <div class="card real" data-at="24.0"><span>$real</span><b class="grad">$real_pct</b></div>
  </div>
  <div class="chips">$chips</div>
</div></section>

<section class="s" id="s5">
  <div class="col">
    <span class="eyebrow" data-at="30.0">$step3</span>
    <h2 data-at="30.2">$s5_title</h2>
    <p class="sub" data-at="30.5">$s5_sub</p>
  </div>
  <div class="chat card" data-at="30.3">
    <header><img src="$logo" alt="">TopStocks</header>
    <div class="thread">
      <div class="bubble mine" data-at="31.0" data-dy="12"><span data-type="$q" data-from="31.1" data-cps="20"></span></div>
      <div class="status" id="status" data-at="33.2" data-dy="8"><span class="star">✻</span><span>$status</span><span id="dots"></span></div>
      <div class="bubble theirs" data-at="34.8" data-dy="10"><span data-stream="35.0" data-wps="7.5">$answer</span></div>
      <div class="srcs">$sources</div>
    </div>
    <div class="askbar">$ask_hint$i_send</div>
  </div>
</section>

<section class="s" id="s6"><div class="in">
  <h2 data-at="41.0">$s6_title</h2>
  <div class="flow">
    <div class="node card muted" data-at="41.5">$i_bank$f_broker</div>
    <div class="link cut"><small data-at="42.3" data-dy="6">$f_no_login</small><span class="ln" data-grow="42.1"></span><span class="xx" data-pop="42.6">$i_x</span></div>
    <div class="node card file" data-at="41.75">$i_doc$f_file</div>
    <div class="link live"><small data-at="43.2" data-dy="6">$f_account</small><span class="ln" data-grow="43.0"></span><span class="dot" data-travel="43.5"></span></div>
    <div class="node card brand" data-at="42.0">$i_book$f_ledger</div>
  </div>
  <p class="sub" data-at="43.8">$f_caption</p>
</div></section>

<section class="s" id="s7">
  <div class="final" data-at="47.0" data-dy="30">
    <img src="$logo" alt="" data-at="47.4" data-dy="10">
    <span class="eyebrow" data-at="47.6">$final_eyebrow</span>
    <h2 data-at="47.8">$final_title</h2>
    <p class="sub" data-at="48.1">$final_sub</p>
    <span class="cta" id="cta" data-at="48.4">$g$sign_in</span>
  </div>
</section>
</div>
<script>
var SCENES = [$scenes];
var SEP = "$sep", SYM = "$sym", AFTER = $after;
function clamp(x) { return Math.min(1, Math.max(0, x)); }
function prog(t, a, d) { return clamp((t - a) / d); }
function out3(x) { return 1 - Math.pow(1 - x, 3); }
function inOut(x) { return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
function back(x) { var c = 1.7; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); }
function group(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, SEP); }
function money(n, signed) {
  var body = group(n), sign = signed ? "+" : "";
  return AFTER ? sign + body + " " + SYM : sign + SYM + body;
}
function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

var lens = new Map();
function render(t) {
  var g = all(".glow");
  g[0].style.transform = "translate(" + (-160 + 120 * Math.sin(t * .23)) + "px," + (-300 + 80 * Math.cos(t * .19)) + "px)";
  g[1].style.transform = "translate(" + (760 + 110 * Math.cos(t * .17)) + "px," + (-120 + 90 * Math.sin(t * .21)) + "px)";
  g[2].style.transform = "translate(" + (300 + 140 * Math.sin(t * .13 + 1)) + "px," + (260 + 70 * Math.cos(t * .27)) + "px)";

  SCENES.forEach(function (sc) {
    var el = document.getElementById(sc[0]), a = sc[1], b = sc[2];
    var i = out3(prog(t, a, .6)), o = inOut(prog(t, b - .6, .6));
    el.style.visibility = t >= a && t <= b ? "visible" : "hidden";
    el.style.opacity = i * (1 - o);
    el.style.transform = "scale(" + (1 + .03 * o) + ")";
    el.style.filter = o > 0 ? "blur(" + (o * 8) + "px)" : "none";
  });
  var bi = out3(prog(t, 5.0, .6)) * (1 - inOut(prog(t, 46.4, .6)));
  document.getElementById("brand").style.opacity = bi;

  all("[data-at]").forEach(function (el) {
    var at = +el.dataset.at, e = out3(prog(t, at, .75));
    var dy = el.dataset.dy !== undefined ? +el.dataset.dy : 24, dx = +(el.dataset.dx || 0);
    el.style.opacity = e;
    var tr = "translate(" + ((1 - e) * dx) + "px," + ((1 - e) * dy) + "px)";
    if (el.dataset.zoom) tr += " scale(" + (.6 + .4 * back(prog(t, at, .9))) + ")";
    el.style.transform = tr;
  });
  all("[data-count]").forEach(function (el) {
    var to = +el.dataset.count, v = Math.round(to * out3(prog(t, +el.dataset.from, 1.2)));
    el.textContent = el.dataset.plain ? String(v) : money(v, el.dataset.sign === "1");
  });
  all("[data-bar]").forEach(function (el) {
    el.style.transform = "scaleX(" + (+el.dataset.bar * out3(prog(t, +el.dataset.from, .9))) + ")";
  });
  all("[data-draw]").forEach(function (el) {
    if (!lens.has(el)) lens.set(el, el.getTotalLength());
    var L = lens.get(el), p = inOut(prog(t, +el.dataset.draw, +el.dataset.dur));
    el.style.strokeDasharray = L;
    el.style.strokeDashoffset = L * (1 - p);
  });
  document.getElementById("area").style.opacity = out3(prog(t, 16.5, 1.2));

  // the statement drops into the zone, the zone lights, the hint gives way
  var file = document.querySelector(".file"), d = inOut(prog(t, 5.9, 1.0));
  file.style.opacity = prog(t, 5.9, .3);
  file.style.transform = "translate(" + (380 * (1 - d)) + "px," + (-340 * (1 - d)) + "px) rotate(" + (12 * (1 - d)) + "deg) scale(" + (1 + .08 * (1 - d)) + ")";
  var lit = prog(t, 6.3, .5) * (1 - prog(t, 7.4, .8));
  document.querySelector(".zone .lit").style.opacity = lit;
  document.querySelector(".hint").style.opacity = 1 - prog(t, 6.4, .4);

  all("[data-type]").forEach(function (el) {
    var text = el.dataset.type, n = Math.floor((t - +el.dataset.from) * +el.dataset.cps);
    n = Math.max(0, Math.min(text.length, n));
    var typing = n < text.length || t < +el.dataset.from + text.length / +el.dataset.cps + .5;
    el.innerHTML = "";
    el.appendChild(document.createTextNode(text.slice(0, n)));
    if (typing && Math.floor(t * 2.2) % 2 === 0) {
      var c = document.createElement("span"); c.className = "caret"; el.appendChild(c);
    }
  });
  var st = document.getElementById("status");
  st.querySelector(".star").style.transform = "rotate(" + (t * 300) + "deg)";
  document.getElementById("dots").textContent = ".".repeat(1 + Math.floor(t * 3) % 3);
  if (t > 34.8) st.style.opacity = 1 - prog(t, 34.8, .3);
  st.style.height = t > 35.1 ? "0px" : "";
  st.style.overflow = "hidden";

  all("[data-stream]").forEach(function (el) {
    var shown = (t - +el.dataset.stream) * +el.dataset.wps;
    all("#s5 [data-w]").forEach(function (w) { w.style.opacity = clamp(shown - +w.dataset.w); });
  });

  all("[data-grow]").forEach(function (el) {
    el.style.transform = "scaleX(" + inOut(prog(t, +el.dataset.grow, .7)) + ")";
  });
  all("[data-pop]").forEach(function (el) {
    el.style.transform = "scale(" + back(prog(t, +el.dataset.pop, .5)) + ")";
  });
  all("[data-travel]").forEach(function (el) {
    var a = +el.dataset.travel;
    if (t < a) { el.style.opacity = 0; return; }
    var ph = ((t - a) % 1.6) / 1.6;
    el.style.opacity = Math.min(1, Math.sin(Math.PI * ph) * 2);
    el.style.left = (10 + 137 * inOut(ph)) + "px";
  });
  document.getElementById("strike").style.setProperty("--strike", inOut(prog(t, 25.6, .6)));
  var sh = prog(t, 50.0, 1.1);
  document.getElementById("cta").style.setProperty("--shine", (-80 + 420 * inOut(sh)) + "px");
}
window.render = render;
</script></body></html>
"""


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        sys.exit("needs ffmpeg: uv run --with imageio-ffmpeg scripts/landing_video.py")
    return imageio_ffmpeg.get_ffmpeg_exe()


def _open(play, html: Path):
    browser = play.chromium.launch()
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
    page.goto(html.as_uri())
    page.evaluate("""() => Promise.all([
        document.fonts.load("800 40px Epilogue"), document.fonts.load("700 40px Epilogue"),
        document.fonts.load("400 16px 'Instrument Sans'"), document.fonts.load("600 16px 'Instrument Sans'"),
        document.fonts.load("700 16px 'Instrument Sans'"), document.fonts.load("400 12px 'Martian Mono'"),
        document.fonts.load("500 12px 'Martian Mono'")]).then(() => document.fonts.ready)""")
    return browser, page


def render_cut(lang: str, work: Path, still: float | None = None) -> None:
    from playwright.sync_api import sync_playwright

    html = work / f"film-{lang}.html"
    html.write_text(film_html(lang), encoding="utf-8")
    with sync_playwright() as play:
        browser, page = _open(play, html)
        if still is not None:
            page.evaluate("t => render(t)", still)
            out = work / f"still-{lang}-{still:g}.png"
            page.screenshot(path=str(out))
            print(out)
            browser.close()
            return
        frames = work / f"frames-{lang}"
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir()
        total = int(SECONDS / SPEED * FPS)
        for i in range(total):
            page.evaluate("t => render(t)", i / FPS * SPEED)
            page.screenshot(path=str(frames / f"{i:05d}.jpg"), type="jpeg", quality=95)
            if i % (FPS * 5) == 0:
                print(f"{lang} {i / FPS:4.0f}s / {SECONDS / SPEED:.0f}s", flush=True)
        page.evaluate("t => render(t)", POSTER_AT)
        poster = work / f"poster-{lang}.png"
        page.screenshot(path=str(poster))
        browser.close()

    video = ASSETS / landing.VIDEO_FILE.format(lang=lang)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(frames / "%05d.jpg"),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-tune",
            "animation",
            "-crf",
            "24",
            # JPEG frames are full-range; browsers expect limited-range BT.709,
            # and an untagged full-range stream crushes the dark purples.
            "-vf",
            "scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            # moov atom first, so the player starts before the whole file lands
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
    )

    from PIL import Image

    # The poster is fetched with the page (the video is not), so it is small.
    Image.open(poster).convert("RGB").resize((W, H), Image.LANCZOS).save(
        ASSETS / landing.VIDEO_POSTER.format(lang=lang),
        quality=80,
        optimize=True,
        progressive=True,
    )
    shutil.rmtree(frames)
    print(f"{video.name}: {video.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--lang", choices=LANGS, action="append", help="one cut (repeatable); default all"
    )
    ap.add_argument("--still", type=float, help="write one frame at this second instead")
    ap.add_argument("--work", type=Path, help="scratch directory (default: a temp dir)")
    args = ap.parse_args()
    work = args.work or Path(tempfile.mkdtemp(prefix="landing-video-"))
    work.mkdir(parents=True, exist_ok=True)
    for lang in args.lang or LANGS:
        render_cut(lang, work, args.still)


if __name__ == "__main__":
    main()
