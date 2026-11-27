"""The FIFO calculator: a public tool page beside the public guides.

"Calculadora FIFO acciones" is what people type in April with a list of buys
and one sale in front of them, and the guides explain FIFO but do not do the
sum. This page does it: paste operations, see which lot each sale consumed, the
gain in euros, the losses the two-month rule holds back, and the tax the
savings scale makes of the year's result.

No account and no request: the maths is `calculator.js`, run in the reader's
browser, so a statement never leaves it. The scale is the engine's own
(`portfolio.tax.es.SAVINGS_BRACKETS_BY_YEAR`), handed to the script as data so
the page and the app cannot drift apart. Delivery is the guides' (`web/guides`):
built from constants, cached, the script hashed into the page's own CSP.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from stocks.portfolio.tax.es import SAVINGS_BRACKETS_BY_YEAR
from stocks.web import guides
from stocks.web.markup import esc

SLUGS = guides.CALCULATOR_SLUGS

# Lessons whose reader is one click from doing the sum themselves.
TOOL_LESSONS = ("fifo", "two-month-rule", "revolut-tax-return",
                "trade-republic-tax-return", "ibkr-tax-return")

AS_OF = "2026-11-27"

_JS = (Path(__file__).with_name("calculator.js")).read_text(encoding="utf-8")

_EXAMPLE = (
    "2024-01-10;compra;ASML;10;650;1\n"
    "2024-03-15;compra;ASML;10;720;1\n"
    "2026-12-10;venta;ASML;12;610;1\n"
    "2026-12-20;compra;ASML;5;615;1\n"
)

_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": "Calculadora FIFO de acciones para la renta",
        "desc": "Pega tus compras y ventas y calcula la ganancia por FIFO en euros, "
                "la regla de los dos meses y el IRPF estimado. Sin registro.",
        "h1": "Calculadora FIFO de acciones",
        "lede": "Pega tus operaciones y ve qué compra consume cada venta, la ganancia "
                "en euros y el impuesto estimado. Se calcula en tu navegador: no "
                "enviamos nada.",
        "label": "Tus operaciones, una por línea",
        "format": "Fecha; compra o venta; valor; cantidad; precio por acción; comisión "
                  "(opcional). Todo en euros. Fechas como 2026-12-10 o 10/12/2026.",
        "year": "Año de las ventas",
        "example": "Cargar ejemplo",
        "clear": "Borrar",
        "how_h": "Cómo calcula",
        "how": [
            "**FIFO.** Cada venta consume primero las acciones más antiguas del mismo "
            "valor, como exige el art. 37 de la ley del IRPF. El coste de cada compra "
            "incluye su comisión; el valor de cada venta la descuenta.",
            "**Regla de los dos meses.** Si vendes con pérdidas y compras el mismo valor "
            "en los dos meses anteriores o posteriores, esa pérdida no se puede aplicar "
            "todavía. La calculadora la aparta y te dice cuánto es.",
            "**Impuesto.** El resultado neto del año tributa en la base del ahorro con "
            "la escala de ese año: 19 % hasta 6.000 €, 21 % hasta 50.000 €, 23 % hasta "
            "200.000 €, 27 % hasta 300.000 € y 30 % por encima desde 2025.",
        ],
        "limits_h": "Lo que no hace",
        "limits": [
            "Todo en euros. Si operas en dólares, pasa cada operación a euros con el "
            "cambio de su fecha antes de pegarla.",
            "No cuenta los dividendos, las pérdidas de años anteriores ni el límite del "
            "25 % de compensación con dividendos.",
            "Una compra que desbloquea una pérdida al venderla después no se modela: "
            "la pérdida sigue apartada. Es una estimación para preparar la renta, no "
            "asesoramiento fiscal.",
        ],
        "t": {
            "err_row": "Línea {n}: no entiendo «{text}».",
            "err_oversell": "{ticker}: la venta del {date} supera en {qty} acciones "
                            "lo que tenías. Falta alguna compra.",
            "no_sales": "No hay ventas en {year}.",
            "res_net": "Resultado neto de {year}",
            "res_deferred": "Pérdidas apartadas por la regla de los dos meses",
            "res_tax": "Impuesto estimado",
            "res_rate": "Tipo medio",
            "res_carry": "Pérdida a compensar en los 4 años siguientes",
            "note_deferred": "Esas pérdidas no se restan este año: se aplican cuando "
                             "vendas las acciones que compraste de nuevo.",
            "deferred_row": "Dos meses: {amount} apartados",
            "cols": ["Venta", "Valor", "Cant.", "Compra", "Coste", "Valor venta",
                     "Resultado", ""],
        },
        "cta_note": "¿Tienes decenas de operaciones o varios brókers?",
        "related": "Guías relacionadas",
        "home": "Calculadora FIFO",
    },
    "en": {
        "title": "FIFO share calculator for your Spanish tax return",
        "desc": "Paste your buys and sells to get the FIFO gain in euros, the "
                "two-month rule and the estimated Spanish income tax. No sign-up.",
        "h1": "FIFO share calculator",
        "lede": "Paste your trades and see which purchase each sale uses up, the "
                "gain in euros and the estimated tax. It runs in your browser: we "
                "send nothing.",
        "label": "Your trades, one per line",
        "format": "Date; buy or sell; security; quantity; price per share; fee "
                  "(optional). All in euros. Dates like 2026-12-10 or 10/12/2026.",
        "year": "Year of the sales",
        "example": "Load example",
        "clear": "Clear",
        "how_h": "How it works",
        "how": [
            "**FIFO.** Each sale uses up the oldest shares of the same security "
            "first, as article 37 of the Spanish income tax law requires. Each "
            "purchase's cost includes its fee; each sale's value is net of it.",
            "**Two-month rule.** If you sell at a loss and buy the same security in "
            "the two months before or after, that loss cannot be used yet. The "
            "calculator sets it aside and shows how much.",
            "**Tax.** The year's net result is taxed in the savings base on that "
            "year's scale: 19 % up to €6,000, 21 % up to €50,000, 23 % up to "
            "€200,000, 27 % up to €300,000 and 30 % above from 2025.",
        ],
        "limits_h": "What it does not do",
        "limits": [
            "Everything in euros. If you trade in dollars, convert each trade to "
            "euros at its own date's rate before pasting it.",
            "It leaves out dividends, losses from earlier years and the 25 % cap on "
            "offsetting against dividends.",
            "A loss held back by a later buy is not released when you sell that buy: "
            "it stays set aside. This is an estimate to prepare your return, not "
            "tax advice.",
        ],
        "t": {
            "err_row": "Line {n}: I do not understand “{text}”.",
            "err_oversell": "{ticker}: the sale on {date} is {qty} shares more than "
                            "you held. A purchase is missing.",
            "no_sales": "No sales in {year}.",
            "res_net": "Net result for {year}",
            "res_deferred": "Losses set aside by the two-month rule",
            "res_tax": "Estimated tax",
            "res_rate": "Average rate",
            "res_carry": "Loss to carry forward for the next 4 years",
            "note_deferred": "Those losses are not deducted this year: they apply "
                             "when you sell the shares you bought again.",
            "deferred_row": "Two months: {amount} set aside",
            "cols": ["Sale", "Security", "Qty", "Bought", "Cost", "Sale value",
                     "Result", ""],
        },
        "cta_note": "Dozens of trades or several brokers?",
        "related": "Related guides",
        "home": "FIFO calculator",
    },
    "it": {
        "title": "Calcolatore FIFO per azioni e fisco spagnolo",
        "desc": "Incolla acquisti e vendite: plusvalenza FIFO in euro, regola dei "
                "due mesi e IRPF stimata. Senza registrazione.",
        "h1": "Calcolatore FIFO per azioni",
        "lede": "Incolla le tue operazioni e vedi quale acquisto consuma ogni "
                "vendita, la plusvalenza in euro e l'imposta stimata. Il calcolo "
                "avviene nel tuo browser: non inviamo nulla.",
        "label": "Le tue operazioni, una per riga",
        "format": "Data; acquisto o vendita; titolo; quantità; prezzo per azione; "
                  "commissione (facoltativa). Tutto in euro. Date come 2026-12-10 "
                  "o 10/12/2026.",
        "year": "Anno delle vendite",
        "example": "Carica esempio",
        "clear": "Cancella",
        "how_h": "Come calcola",
        "how": [
            "**FIFO.** Ogni vendita consuma prima le azioni più vecchie dello "
            "stesso titolo, come richiede l'art. 37 della legge IRPF. Il costo di "
            "ogni acquisto include la commissione; il valore di ogni vendita la "
            "detrae.",
            "**Regola dei due mesi.** Se vendi in perdita e riacquisti lo stesso "
            "titolo nei due mesi prima o dopo, quella perdita non è ancora "
            "utilizzabile. Il calcolatore la mette da parte e ti dice quanto è.",
            "**Imposta.** Il risultato netto dell'anno è tassato nella base del "
            "risparmio con la scala di quell'anno: 19 % fino a 6.000 €, 21 % fino a "
            "50.000 €, 23 % fino a 200.000 €, 27 % fino a 300.000 € e 30 % oltre dal "
            "2025.",
        ],
        "limits_h": "Cosa non fa",
        "limits": [
            "Tutto in euro. Se operi in dollari, converti ogni operazione in euro "
            "al cambio della sua data prima di incollarla.",
            "Non conta i dividendi, le perdite degli anni precedenti né il limite "
            "del 25 % di compensazione con i dividendi.",
            "Una perdita trattenuta da un riacquisto non si libera quando vendi "
            "quel riacquisto: resta da parte. È una stima per preparare la "
            "dichiarazione, non consulenza fiscale.",
        ],
        "t": {
            "err_row": "Riga {n}: non capisco «{text}».",
            "err_oversell": "{ticker}: la vendita del {date} supera di {qty} azioni "
                            "quelle che avevi. Manca un acquisto.",
            "no_sales": "Nessuna vendita nel {year}.",
            "res_net": "Risultato netto del {year}",
            "res_deferred": "Perdite messe da parte dalla regola dei due mesi",
            "res_tax": "Imposta stimata",
            "res_rate": "Aliquota media",
            "res_carry": "Perdita da compensare nei 4 anni successivi",
            "note_deferred": "Queste perdite non si sottraggono quest'anno: si "
                             "applicano quando vendi le azioni riacquistate.",
            "deferred_row": "Due mesi: {amount} da parte",
            "cols": ["Vendita", "Titolo", "Quant.", "Acquisto", "Costo",
                     "Valore vendita", "Risultato", ""],
        },
        "cta_note": "Decine di operazioni o più broker?",
        "related": "Guide correlate",
        "home": "Calcolatore FIFO",
    },
}

_CSS = """
.calc { margin: 1.5rem 0; display: grid; gap: 0.75rem; }
.calc label { font-weight: 600; color: #E8E5EF; }
.calc .hint { margin: 0; font-size: 0.85rem; color: #8E88A0; }
.calc textarea { width: 100%; box-sizing: border-box; min-height: 12rem;
  padding: 0.75rem; background: #201E26; color: #E8E5EF;
  border: 1px solid #2C2933; border-radius: 10px; resize: vertical;
  font: 0.9rem/1.5 ui-monospace, "SF Mono", Menlo, monospace; }
.calc select { background: #201E26; color: #E8E5EF; border: 1px solid #2C2933;
  border-radius: 8px; padding: 0.4rem 0.6rem; font: inherit; }
.calc textarea:focus-visible, .calc select:focus-visible, .calc button:focus-visible
  { outline: 2px solid #9AD1FF; outline-offset: 2px; }
.calc .bar { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }
.calc button { background: transparent; color: #9AD1FF; border: 1px solid #2C2933;
  border-radius: 8px; padding: 0.45rem 0.8rem; font: inherit; cursor: pointer; }
.calc-err { color: #FFB4A8; margin: 0; padding-left: 1.2rem; }
.calc-err li { color: #FFB4A8; }
.calc-sum { display: grid; grid-template-columns: 1fr auto; gap: 0.35rem 1rem;
  margin: 1rem 0; padding: 1rem; background: #201E26; border: 1px solid #2C2933;
  border-radius: 12px; }
.calc-sum dt { color: #C9C4D4; }
.calc-sum dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums;
  color: #E8E5EF; }
.calc-sum dd.big { font-weight: 700; font-size: 1.25rem; }
.calc-note { font-size: 0.9rem; color: #8E88A0; }
.calc-scroll { overflow-x: auto; }
.calc-scroll table { border-collapse: collapse; width: 100%; font-size: 0.85rem;
  min-width: 44rem; }
.calc-scroll th, .calc-scroll td { padding: 0.4rem 0.6rem; text-align: left;
  border-bottom: 1px solid #2C2933; color: #C9C4D4; white-space: nowrap; }
.calc-scroll th { color: #8E88A0; font-weight: 600; }
.calc-scroll .n { text-align: right; font-variant-numeric: tabular-nums; }
.calc-scroll .gain { color: #8EE0B0; }
.calc-scroll .loss { color: #FFB4A8; }
"""


def path(lang: str) -> str:
    """The tool's public path in `lang`."""
    return f"{guides.PATHS[guides._lang(lang)]}{SLUGS[guides._lang(lang)]}"


def find(slug: str, lang: str) -> bool:
    """Whether `slug` is the calculator's in `lang`."""
    return SLUGS.get(guides._lang(lang)) == slug


def _alternates() -> dict[str, str]:
    out = {code: path(code) for code in guides.PATHS}
    return {**out, "x-default": out[guides.X_DEFAULT]}


def _scales() -> dict[str, list[list[float | None]]]:
    """The engine's savings scales as JSON: an open top bracket is null."""
    return {
        str(year): [[None if up == float("inf") else up, rate] for up, rate in rows]
        for year, rows in SAVINGS_BRACKETS_BY_YEAR.items()
    }


def _config(lang: str) -> str:
    # `<` escaped so the data block can never close itself early.
    return json.dumps(
        {"lang": lang, "t": _COPY[lang]["t"], "scales": _scales(),
         "example": _EXAMPLE},
        ensure_ascii=False,
    ).replace("<", "\\u003c")


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{guides._inline(i)}</li>" for i in items) + "</ul>"


@lru_cache(maxsize=8)
def page(lang: str, base_url: str) -> str:
    """The calculator's page in `lang`."""
    lang = guides._lang(lang)
    c = _COPY[lang]
    ui = guides._UI[lang]
    crumbs, crumbs_ld = guides._crumbs_for(lang, base_url, (c["home"], path(lang)))
    related = [
        x for i in TOOL_LESSONS
        if (x := guides.learn.lesson(i, lang)) is not None
    ]
    main = (
        f"{crumbs}<h1>{esc(c['h1'])}</h1>"
        f'<p class="meta">{esc(ui["reviewed"])}: '
        f'<time datetime="{AS_OF}">{AS_OF}</time></p>'
        f"<p>{esc(c['lede'])}</p>"
        '<div class="calc">'
        f'<label for="calc-input">{esc(c["label"])}</label>'
        f'<p class="hint">{esc(c["format"])}</p>'
        '<textarea id="calc-input" spellcheck="false" autocomplete="off"></textarea>'
        '<div class="bar">'
        f'<label for="calc-year">{esc(c["year"])}</label>'
        '<select id="calc-year"></select>'
        f'<button type="button" id="calc-example">{esc(c["example"])}</button>'
        f'<button type="button" id="calc-clear">{esc(c["clear"])}</button>'
        "</div>"
        '<div id="calc-out" aria-live="polite"></div>'
        "</div>"
        f"<h2>{esc(c['how_h'])}</h2>{_list(c['how'])}"
        f"<h2>{esc(c['limits_h'])}</h2>{_list(c['limits'])}"
        f"{guides._cta(lang, 'import', 'tool-fifo')}"
        f"<h2>{esc(c['related'])}</h2>"
        '<ul class="list">'
        + "".join(
            f'<li><a href="{esc(guides.href(x.id, lang))}">{esc(x.title)}</a></li>'
            for x in related
        )
        + "</ul>"
    )
    app = {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": c["h1"],
        "description": c["desc"],
        "inLanguage": lang,
        "applicationCategory": "FinanceApplication",
        "operatingSystem": "Any",
        "url": guides._abs(base_url, path(lang)),
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
        "publisher": {"@type": "Organization", "name": "MyBrainStock"},
    }
    scripts = (
        f'<script type="application/json" id="calc-cfg">{_config(lang)}</script>'
        f"<script>{_JS}</script>"
    )
    return guides._document(
        lang, base_url, title=c["title"], desc=c["desc"], main=main,
        alternates=_alternates(), og_type="website", ld=[app, crumbs_ld],
        extra_css=_CSS, scripts=scripts,
    )


def sitemap_pages() -> list[tuple[str, dict[str, str], str]]:
    alts = _alternates()
    return [(alts[lang], alts, AS_OF) for lang in guides.PATHS]
