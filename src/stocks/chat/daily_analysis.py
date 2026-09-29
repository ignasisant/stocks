"""The analysis behind one line of the daily card.

The card is a summary: one line per thing to look at today. Its "see more"
used to be one call that rewrote every line at paragraph length, and a longer
paragraph of the same facts can only restate them — at best it ends on "it may
be worth comparing its outlook with its sector's", which is the work the reader
opened it for. This module is the replacement. Each line opens on its own, and
opening it runs the comparison the line invites:

* `api/evidence.py` fetches the other side of it — peers, the sector ETF, the
  index, business figures and consensus, the tax arithmetic, the attribution
  of a month behind the index — with every difference already computed;
* the model is told to *do* the analysis on that evidence: a verdict, then a
  few points, each one a comparison with the names and the figures in it;
* the same number audit as the card (`daily.audit`) gates every point: the
  pool is the card's facts plus the evidence, so a point that quotes a figure
  nobody fetched is dropped, and a reply left with too few points is a miss;
* the tables under it are computed, never written: the reader checks the
  prose against them, so they cannot come from the prose's author.

Pure: no network and no files. `api/briefing.analysis` fetches, calls and
stores.
"""

from __future__ import annotations

import json
import re
from datetime import date

from stocks import obs
from stocks.chat import daily, engine, signals

VERDICT_CHARS = 320
TITLE_CHARS = 48
POINT_CHARS = 620
POINTS_MIN = 2
POINTS_MAX = 4
# The model's share of the wait; the evidence fetch has its own (`evidence.
# WAIT_S`). The reader is watching a wait line for both.
TIMEOUT_S = 30.0

_SOURCE_LLM = "llm"
_SOURCE_COMPUTED = "computed"
# A gap to the peers (or the sector) this wide is the company's own move.
OWN_MOVE_PP = 5.0

_TASK = (
    "The user opened the analysis behind ONE line of today's action card in "
    "TopStocks, a personal stock tracker. Do the analysis — never tell the "
    "user what they could analyse or compare. Where the line invites a "
    "comparison (against peers, the sector, the index, alternatives that move "
    "differently, the tax arithmetic of a sale), make it here, with the names "
    "and the figures in `evidence`, and say what it shows."
)

_EVIDENCE = (
    "`line` is what the card said and `action` the trigger behind it. "
    "`evidence` is what the app fetched for this analysis:\n"
    "- subject: the company. `perf` is its price performance (m1/m3/y1 = 1, 3 "
    "and 12 months, from_high = distance from its 12-month high, vol_1y = "
    "annualised volatility, max_dd_1y = worst fall in the year), `business` "
    "its figures (pe_fwd / pe_ttm = forward / trailing P/E, ev_sales, margins, "
    "revenue_cagr, fcf_yield, net_debt_ebitda), `consensus` the analysts' "
    "estimates (target_upside = mean target against the price, growth next "
    "fiscal year) and `position` the user's own holding.\n"
    "- peers: comparable companies, with the same blocks. sector: the sector's "
    "ETF. index: the S&P 500 (SPY).\n"
    "- compare: the differences, already computed — `…_pp` are percentage "
    "points (vs_peers_m3_pp = the subject's 3-month return minus the peers' "
    "median), `peers_median` the peers' median of each figure.\n"
    "- tax: selling today — the offset, the tax it saves on the savings scale "
    "(`saving`), and `clear_if_sold_today`, the first day a repurchase would "
    "no longer defer the loss.\n"
    "- history: the last earnings prints — EPS against the estimate, the "
    "surprise, and `move_pct`, the stock's move from the close before the "
    "report to the close after it. outlook: the consensus for the quarter "
    "being reported (analysts', not company guidance). print: the reported "
    "quarter and the company's own press release.\n"
    "- holdings: the user's positions in the sector or currency concerned. "
    "sectors: every sector ETF, with `corr_1y`, the one-year correlation of "
    "its daily returns to the tilted sector's (low = it moves differently). "
    "attribution: each position's weight × its month move (`contribution_pp`), "
    "in its own currency at today's weights — an attribution, not an exact "
    "reconciliation. fx: the EUR/USD move. open: the largest open losses and "
    "gains. rates: the bank's recent rate path.\n"
    "Any block can be missing or hold nulls: then that figure is not "
    "available — say so, never fill it in."
)

_SHAPE = (
    "Answer with a single JSON object and nothing else — no prose around it, "
    "no code fence:\n"
    '{"verdict": "...", "points": [{"title": "...", "text": "..."}]}\n'
    f"- verdict: 1 or 2 sentences, at most {VERDICT_CHARS} characters: what the "
    "evidence points to, and how clearly — e.g. 'The fall is the company's "
    "own: its peers and its sector are flat over the same three months.'\n"
    f"- points: 3 to {POINTS_MAX}, in this order as far as the evidence goes: "
    "what happened; how it compares (named tickers with their figures); what "
    "the business figures, the consensus or the tax arithmetic say; what "
    "would settle the question (a date, a level, a figure to watch).\n"
    f"- title: at most 4 words. text: 2 to 4 sentences, at most {POINT_CHARS} "
    "characters, plain prose — no lists, no markdown."
)

_GUARDRAILS = (
    "Quote only figures that appear in `action` or `evidence`, exactly as "
    "given. Every difference you could want is already in `compare`: never "
    "subtract, average, round into a new figure or estimate one. A figure "
    "about one company goes with that company's name. Weigh the evidence and "
    "conclude — which way it points and how strongly — but you are not a "
    "licensed financial advisor: never tell the user to buy, sell or hold, "
    "never predict a price, and present consensus figures as analysts' "
    "estimates, not facts."
)


# ------------------------------------------------------------------- prompt


def _item(card: daily.DailyAction, key: str) -> dict | None:
    return next((i for i in card.entries if i["key"] == key), None)


def prompt(
    card: daily.DailyAction, key: str, evidence: dict, profile: dict, lang: str
) -> tuple[str, list[dict]]:
    """(system, messages) for the analysis of line `key`. Pure."""
    facts = card.facts or {}
    item = _item(card, key) or {}
    payload = {
        "date": facts.get("date") or card.day,
        "currency": facts.get("currency"),
        "line": item.get("line") or "",
        "action": daily.keyed_actions(facts).get(key) or {},
        "evidence": evidence,
        "book": {
            k: facts[k]
            for k in ("total_value", "unrealised_pl_pct", "top_weights", "month")
            if k in facts
        },
    }
    system = (
        f"{_TASK} {engine.persona(profile or {})}"
        f"Write in {daily._LANG_NAME.get(lang, 'English')}.\n\n"
        f"{daily._KINDS}\n\n{_EVIDENCE}\n\n{_GUARDRAILS}\n\n{_SHAPE}"
        f"{daily._HOUSE_RULES}"
    )
    return system, [{"role": "user", "content": json.dumps(payload)}]


# A difference in points ("16.0 pp", "11 puntos") is a claim like any
# percentage — the analysis is mostly made of them — so it is audited as one.
_POINTS_RE = re.compile(
    rf"({daily._NUM})\s*(?:p\.\s?p\.|pp\b|pts?\b\.?|puntos\b|points\b)", re.IGNORECASE
)


def _audit(parts: list[str], pool: dict) -> str | None:
    """`daily.audit`, with point differences read as the percentages they are."""
    return daily.audit([_POINTS_RE.sub(r"\1%", part) for part in parts], pool)


def _pool(card: daily.DailyAction, evidence: dict) -> dict:
    """What the analysis's figures are audited against."""
    return {"facts": card.facts or {}, "evidence": evidence}


def _text(value, limit: int) -> str:
    return daily._clip(" ".join(str(value or "").split()), limit)


def parse(raw: str, card: daily.DailyAction, evidence: dict, lang: str) -> dict | None:
    """{"verdict", "points"} from a completion, or None when it is unusable.

    The verdict must pass the audit — it is the sentence a reader keeps — and
    so must at least POINTS_MIN points; a point that fails is dropped alone.
    """
    data = daily._json_object(raw)
    if not data:
        return None
    pool = _pool(card, evidence)
    verdict = _text(data.get("verdict"), VERDICT_CHARS)
    if not verdict:
        return None
    bogus = _audit([verdict], pool)
    if bogus:
        obs.warn(
            "daily.analysis_figure_rejected", figure=bogus, lang=lang, part="verdict"
        )
        return None
    points: list[dict] = []
    for entry in data.get("points") or []:
        if not isinstance(entry, dict):
            continue
        title = _text(entry.get("title"), TITLE_CHARS)
        text = _text(entry.get("text"), POINT_CHARS)
        if not title or not text:
            continue
        bogus = _audit([title, text], pool)
        if bogus:
            obs.warn(
                "daily.analysis_figure_rejected", figure=bogus, lang=lang, part="point"
            )
            continue
        points.append({"title": title, "text": text})
        if len(points) == POINTS_MAX:
            break
    if len(points) < POINTS_MIN:
        return None
    return {"verdict": verdict, "points": points}


def generate(
    prefs: dict,
    profile: dict,
    card: daily.DailyAction,
    key: str,
    evidence: dict,
    lang: str,
    *,
    timeout_s: float = TIMEOUT_S,
    spend_free=None,
) -> dict | None:
    """The model's analysis of line `key`, or None. Never raises."""
    try:
        system, messages = prompt(card, key, evidence, profile, lang)
    except Exception:  # noqa: BLE001
        return None
    return engine.complete_attempts(
        prefs,
        system,
        messages,
        timeout_s,
        spend_free=spend_free or engine.spend_free_quota,
        accept=lambda raw: parse(raw, card, evidence, lang),
    )


# ------------------------------------------------------------------ figures

_ES = str.maketrans({",": ".", ".": ","})
_NA = "—"


def _n(value, lang: str, digits: int = 1, sign: bool = False) -> str:
    text = format(float(value), f"{'+' if sign else ''},.{digits}f")
    return text.translate(_ES) if lang == "es" else text


def _p(value, lang: str, sign: bool = True, digits: int = 1) -> str:
    return _NA if value is None else _n(value, lang, digits, sign) + "%"


def _pts(value, lang: str) -> str:
    return _NA if value is None else _n(value, lang, 1, True)


def _x(value, lang: str) -> str:
    return _NA if value is None else _n(value, lang, 1) + "x"


def _money(value, ccy: str, lang: str) -> str:
    from stocks.config import currency_symbol

    if value is None:
        return _NA
    amount = float(value)
    sign = "-" if amount < 0 else ""
    body = _n(abs(amount), lang, 0)
    symbol = currency_symbol(ccy)
    return f"{sign}{body} {symbol}" if lang == "es" else f"{sign}{symbol}{body}"


# A figure as the card's own templates print it (`daily._money`, "-31.2%"):
# English separators, the currency symbol in front.
_EN_FIGURE = re.compile(
    r"(?<![\w.,])([€$£¥])?([-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)(?![\w])"
)


def _localize(text: str, lang: str) -> str:
    """The card's template text with its figures written the way the rest of
    the analysis writes them. The "what happened" paragraph comes from the
    card's own templates, which print every figure the English way; beside
    tables in Spanish it would read as two different apps."""
    if lang != "es":
        return text

    def swap(match: re.Match) -> str:
        symbol, body = match.group(1), match.group(2).translate(_ES)
        return f"{body} {symbol}" if symbol else body

    return _EN_FIGURE.sub(swap, text)


def _day(iso) -> str:
    try:
        return date.fromisoformat(str(iso)).strftime("%d/%m/%y")
    except ValueError:
        return str(iso or "")


def _sector_name(name: str, lang: str) -> str:
    from stocks.web.i18n import has, translate

    slug = f"sentiment.sector_{str(name or '').lower().replace(' ', '_')}"
    return translate(slug, lang) if has(slug) else str(name or "")


def _t(key: str, lang: str, **kw) -> str:
    from stocks.web.i18n import translate

    return translate(f"home.daily_an_{key}", lang, **kw)


def _join(parts: list[str]) -> str:
    return " ".join(p for p in parts if p)


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


# ----------------------------------------------------------------- computed


def _compare_ref(evidence: dict, lang: str) -> tuple[float | None, str]:
    """The gap the verdict is read on, and what it is a gap to."""
    cmp = evidence.get("compare") or {}
    if cmp.get("vs_peers_m3_pp") is not None:
        return cmp["vs_peers_m3_pp"], _t("ref_peers", lang)
    if cmp.get("vs_sector_m3_pp") is not None:
        etf = (evidence.get("sector") or {}).get("etf") or ""
        return cmp["vs_sector_m3_pp"], _t("ref_sector", lang, etf=etf)
    return None, ""


def _verdict_company(evidence: dict, ticker: str, lang: str) -> str:
    gap, ref = _compare_ref(evidence, lang)
    if gap is None:
        return ""
    cmp = evidence.get("compare") or {}
    year = cmp.get("vs_peers_y1_pp", cmp.get("vs_sector_y1_pp"))
    if year is not None and abs(gap) >= OWN_MOVE_PP and abs(year) >= OWN_MOVE_PP:
        if (gap < 0) != (year < 0):
            # Three months and twelve disagree: say both, conclude neither.
            return _t(
                "v_mixed",
                lang,
                ticker=ticker,
                ref=ref,
                m3=_n(gap, lang, sign=True),
                y1=_n(year, lang, sign=True),
            )
    if gap <= -OWN_MOVE_PP:
        return _t("v_behind", lang, ticker=ticker, gap=_n(abs(gap), lang), ref=ref)
    if gap >= OWN_MOVE_PP:
        return _t("v_ahead", lang, ticker=ticker, gap=_n(gap, lang), ref=ref)
    return _t("v_with", lang, ticker=ticker, gap=_n(abs(gap), lang), ref=ref)


def _compare_text(evidence: dict, ticker: str, lang: str) -> str:
    own = (evidence.get("subject") or {}).get("perf") or {}
    if own.get("m3_pct") is None:
        return ""
    parts = [
        _t(
            "c_self",
            lang,
            ticker=ticker,
            m1=_p(own.get("m1_pct"), lang),
            m3=_p(own.get("m3_pct"), lang),
            y1=_p(own.get("y1_pct"), lang),
        )
    ]
    sector = evidence.get("sector") or {}
    sec = sector.get("perf") or {}
    if sec.get("m3_pct") is not None:
        parts.append(
            _t(
                "c_sector",
                lang,
                etf=sector.get("etf") or "",
                m3=_p(sec.get("m3_pct"), lang),
                y1=_p(sec.get("y1_pct"), lang),
            )
        )
    cmp = evidence.get("compare") or {}
    median = cmp.get("peers_median") or {}
    peers = [p.get("ticker") for p in evidence.get("peers") or [] if p.get("ticker")]
    if peers and median.get("m3_pct") is not None:
        parts.append(
            _t(
                "c_peers",
                lang,
                names=", ".join(peers),
                m3=_p(median.get("m3_pct"), lang),
                y1=_p(median.get("y1_pct"), lang),
            )
        )
    idx = (evidence.get("index") or {}).get("perf") or {}
    if idx.get("m3_pct") is not None:
        parts.append(
            _t(
                "c_index",
                lang,
                m3=_p(idx.get("m3_pct"), lang),
                y1=_p(idx.get("y1_pct"), lang),
            )
        )
    if own.get("vol_1y_pct") is not None:
        refs = []
        if median.get("vol_1y_pct") is not None:
            refs.append(
                _t("peers_label", lang, value=_p(median["vol_1y_pct"], lang, False))
            )
        if idx.get("vol_1y_pct") is not None:
            refs.append(f"S&P 500 {_p(idx['vol_1y_pct'], lang, False)}")
        parts.append(
            _t(
                "c_vol",
                lang,
                vol=_p(own["vol_1y_pct"], lang, False),
                ref=f" ({', '.join(refs)})" if refs else "",
            )
        )
    return _join(parts)


_BUSINESS = (
    # (clause key, block, field, format)
    ("b_pe", "business", "pe_fwd", "x"),
    ("b_growth", "consensus", "rev_growth_next_fy_pct", "p"),
    ("b_margin", "business", "op_margin_pct", "p0"),
    ("b_fcf", "business", "fcf_yield_pct", "p0"),
    ("b_upside", "consensus", "target_upside_pct", "p"),
)


def _fmt(value, how: str, lang: str) -> str:
    if how == "x":
        return _x(value, lang)
    return _p(value, lang, sign=how == "p")


def _business_text(evidence: dict, ticker: str, lang: str) -> str:
    subject = evidence.get("subject") or {}
    median = (evidence.get("compare") or {}).get("peers_median") or {}
    clauses = []
    for clause, block, field, how in _BUSINESS:
        value = (subject.get(block) or {}).get(field)
        if value is None:
            continue
        text = _t(clause, lang, ticker=ticker, value=_fmt(value, how, lang))
        if median.get(field) is not None:
            text += " " + _t("b_peers", lang, value=_fmt(median[field], how, lang))
        clauses.append(text)
    return _first_up("; ".join(clauses)) + "." if clauses else ""


def _tax_text(evidence: dict, ccy: str, lang: str) -> str:
    tax = evidence.get("tax") or {}
    if tax.get("offset") is None:
        return ""
    parts = [
        _t(
            "tax",
            lang,
            loss=_money(tax.get("loss"), ccy, lang),
            gain=_money(tax.get("gain_ytd"), ccy, lang),
            offset=_money(tax.get("offset"), ccy, lang),
        )
    ]
    if tax.get("saving") is not None:
        parts.append(
            _t(
                "tax_saving",
                lang,
                saving=_money(tax["saving"], ccy, lang),
                share=_p(tax.get("saving_pct_of_offset"), lang, False),
            )
        )
    if tax.get("clear_if_sold_today"):
        parts.append(_t("tax_clear", lang, date=_day(tax["clear_if_sold_today"])))
    return _join(parts)


def _history_text(evidence: dict, ticker: str, lang: str) -> str:
    past = evidence.get("history") or {}
    parts = []
    if past.get("counted"):
        parts.append(
            _t(
                "hist",
                lang,
                ticker=ticker,
                n=past["counted"],
                beats=past.get("beats", 0),
                surprise=_p(past.get("avg_surprise_pct"), lang),
                move=_p(past.get("avg_abs_move_pct"), lang, False),
            )
        )
    ahead = evidence.get("outlook") or {}
    if ahead.get("eps_avg") is not None:
        parts.append(
            _t(
                "outlook",
                lang,
                eps=_n(ahead["eps_avg"], lang, 2),
                growth=_p(ahead.get("eps_growth_pct"), lang),
            )
        )
    return _join(parts)


def _list(rows: list[dict], lang: str, field: str, fmt) -> str:
    return ", ".join(f"{r['ticker']} {fmt(r.get(field), lang)}" for r in rows) or _t(
        "none", lang
    )


def _tilt_points(evidence: dict, action: dict, lang: str) -> list[dict]:
    out = []
    held = evidence.get("holdings") or []
    sector = _sector_name(str(action.get("sector") or ""), lang)
    if held:
        out.append(
            _point(
                "holdings",
                lang,
                _t(
                    "tilt_holdings",
                    lang,
                    sector=sector,
                    names=_list(held, lang, "weight_pct", lambda v, lg: _p(v, lg, False)),
                ),
            )
        )
    others = [r for r in evidence.get("sectors") or [] if r.get("corr_1y") is not None]
    if others:
        least = sorted(others, key=lambda r: r["corr_1y"])[:3]
        out.append(
            _point(
                "sectors",
                lang,
                _t(
                    "tilt_alt",
                    lang,
                    list="; ".join(
                        _t(
                            "tilt_alt_row",
                            lang,
                            sector=_sector_name(r["sector"], lang),
                            etf=r["etf"],
                            corr=_n(r["corr_1y"], lang, 2),
                            y1=_p(r.get("y1_pct"), lang),
                        )
                        for r in least
                    ),
                ),
            )
        )
    return out


def _tilt_verdict(evidence: dict, action: dict, lang: str) -> str:
    cmp = evidence.get("compare") or {}
    gap = cmp.get("sector_vs_index_y1_pp")
    if gap is None:
        return ""
    key = "v_tilt_paid" if gap >= 0 else "v_tilt_cost"
    return _t(
        key,
        lang,
        sector=_sector_name(str(action.get("sector") or ""), lang),
        own=_p(action.get("own_pct"), lang, False),
        gap=_n(abs(gap), lang),
    )


def _attr_parts(evidence: dict, action: dict, lang: str) -> tuple[str, str]:
    rows = evidence.get("attribution") or []
    if not rows:
        return "", ""
    down = [r for r in rows if r["contribution_pp"] < 0][:3]
    up = [r for r in reversed(rows) if r["contribution_pp"] > 0][:3]
    text = _t(
        "attr",
        lang,
        down=_list(down, lang, "contribution_pp", _pts),
        up=_list(up, lang, "contribution_pp", _pts),
    )
    fx = evidence.get("fx") or {}
    if fx.get("m1_pct") is not None:
        text += " " + _t("fx_pair", lang, m1=_p(fx["m1_pct"], lang))
    verdict = ""
    gap = abs(float(action.get("gap_pp") or 0.0))
    if down and gap:
        worst = down[0]
        key = (
            "v_attr_one" if abs(worst["contribution_pp"]) >= gap / 2 else "v_attr_spread"
        )
        verdict = _t(
            key, lang, ticker=worst["ticker"], pp=_n(abs(worst["contribution_pp"]), lang)
        )
    return text, verdict


def _market_text(evidence: dict, lang: str) -> str:
    rows = [r for r in evidence.get("sectors") or [] if r.get("m3_pct") is not None]
    if len(rows) < 4:
        return ""
    ranked = sorted(rows, key=lambda r: r["m3_pct"], reverse=True)

    def names(group):
        return ", ".join(
            f"{_sector_name(r['sector'], lang)} {_p(r['m3_pct'], lang)}" for r in group
        )

    return _t("market_sectors", lang, up=names(ranked[:3]), down=names(ranked[-3:][::-1]))


def _open_text(evidence: dict, ccy: str, lang: str) -> str:
    book = evidence.get("open") or {}
    if not (book.get("losses") or book.get("gains")):
        return ""

    def money(v, lg):
        return _money(v, ccy, lg)

    return _t(
        "open_book",
        lang,
        losses=_list(book.get("losses") or [], lang, "pnl", money),
        gains=_list(book.get("gains") or [], lang, "pnl", money),
    )


def _point(title: str, lang: str, text: str) -> dict:
    return {"title": _t(f"t_{title}", lang), "text": text}


def computed(card: daily.DailyAction, key: str, evidence: dict, lang: str) -> dict:
    """{"verdict", "points"} without a model: the same evidence, stated in
    templates. Never empty for a line with a trigger behind it."""
    facts = card.facts or {}
    action = daily.keyed_actions(facts).get(key)
    item = _item(card, key) or {}
    if action is None:
        return {"verdict": item.get("line") or "", "points": []}
    ccy = str(facts.get("currency") or "EUR")
    kind = str(action.get("kind") or "")
    ticker = str(action.get("ticker") or "")
    source = evidence.get("print") or evidence.get("rates") or {}
    points: list[dict] = []
    verdict = ""

    what = _localize(daily._detail_line(action, source, lang, ccy), lang)
    if what:
        points.append(_point("what", lang, what))
    if kind == signals.HARVEST:
        tax = _tax_text(evidence, ccy, lang)
        if tax:
            points.append(_point("tax", lang, tax))
        saving = (evidence.get("tax") or {}).get("saving")
        if saving is not None:
            verdict = _t(
                "v_harvest", lang, ticker=ticker, saving=_money(saving, ccy, lang)
            )
    if ticker and "subject" in evidence:
        verdict = verdict or _verdict_company(evidence, ticker, lang)
        compared = _compare_text(evidence, ticker, lang)
        if compared:
            points.append(_point("compare", lang, compared))
        firm = _business_text(evidence, ticker, lang)
        if firm:
            points.append(_point("business", lang, firm))
        past = _history_text(evidence, ticker, lang)
        if past:
            points.append(_point("history", lang, past))
    if kind == signals.SECTOR_TILT:
        verdict = _tilt_verdict(evidence, action, lang)
        points.extend(_tilt_points(evidence, action, lang))
    elif kind == signals.VS_BENCH:
        text, verdict = _attr_parts(evidence, action, lang)
        if text:
            points.append(_point("attribution", lang, text))
    elif kind == signals.MARKET:
        text = _market_text(evidence, lang)
        if text:
            points.append(_point("sectors", lang, text))
    elif kind == signals.FX:
        held = evidence.get("holdings") or []
        if held:
            text = _t(
                "fx_holdings",
                lang,
                currency=action.get("currency") or "",
                names=_list(held, lang, "weight_pct", lambda v, lg: _p(v, lg, False)),
            )
            fx = evidence.get("fx") or {}
            if fx.get("m1_pct") is not None:
                text += " " + _t("fx_pair", lang, m1=_p(fx["m1_pct"], lang))
            points.append(_point("holdings", lang, text))
    elif kind in (signals.TAX_YEAR_END, signals.TAX_BRACKET):
        text = _open_text(evidence, ccy, lang)
        if text:
            points.append(_point("open", lang, text))
    if not verdict:
        verdict = _localize(daily._action_line(action, lang, ccy), lang) or (
            item.get("line") or ""
        )
    return {"verdict": verdict, "points": points[:POINTS_MAX]}


# ------------------------------------------------------------------- tables


def _row(
    label: str, cells: list[str], ticker: str | None = None, highlight=False
) -> dict:
    return {
        "ticker": ticker,
        "label": label,
        "cells": cells,
        "highlight": bool(highlight),
    }


def _table(
    title: str, columns: list[str], rows: list[dict], lang: str, note: str = ""
) -> dict:
    return {
        "title": _t(f"tbl_{title}", lang),
        "columns": [_t(f"col_{c}", lang) for c in columns],
        "rows": rows,
        "note": _t(f"note_{note}", lang) if note else "",
    }


def _price_cells(p: dict, lang: str) -> list[str]:
    return [
        _p(p.get("m1_pct"), lang),
        _p(p.get("m3_pct"), lang),
        _p(p.get("y1_pct"), lang),
        _p(p.get("from_high_pct"), lang),
        _p(p.get("vol_1y_pct"), lang, False),
    ]


def _name(company: dict) -> str:
    """A company row's label: its name beside the symbol — a peer the reader
    has never heard of is a bare ticker otherwise."""
    return str(company.get("name") or "")


def _company_tables(evidence: dict, lang: str) -> list[dict]:
    subject = evidence.get("subject") or {}
    ticker = subject.get("ticker")
    peers = evidence.get("peers") or []
    out = []
    rows = []
    if subject.get("perf"):
        rows.append(
            _row(_name(subject), _price_cells(subject["perf"], lang), ticker, True)
        )
    rows += [
        _row(_name(p), _price_cells(p["perf"], lang), p["ticker"])
        for p in peers
        if p.get("perf")
    ]
    sector = evidence.get("sector") or {}
    if sector.get("perf"):
        rows.append(
            _row(
                _sector_name(sector.get("sector") or "", lang),
                _price_cells(sector["perf"], lang),
                sector.get("etf"),
            )
        )
    index = evidence.get("index") or {}
    if index.get("perf"):
        rows.append(_row("S&P 500", _price_cells(index["perf"], lang), index.get("etf")))
    if rows and subject.get("perf"):
        out.append(
            _table(
                "price", ["name", "m1", "m3", "y1", "high", "vol"], rows, lang, "price"
            )
        )

    def firm(block: dict) -> list[str]:
        return [
            _fmt((block.get(b) or {}).get(f), how, lang) for _c, b, f, how in _BUSINESS
        ]

    median = (evidence.get("compare") or {}).get("peers_median") or {}
    rows = [_row(_name(subject), firm(subject), ticker, True)] + [
        _row(_name(p), firm(p), p["ticker"]) for p in peers
    ]
    if median:
        rows.append(
            _row(
                _t("row_median", lang),
                [_fmt(median.get(f), how, lang) for _c, _b, f, how in _BUSINESS],
            )
        )
    if any(cell != _NA for cell in rows[0]["cells"]):
        out.append(
            _table(
                "business",
                ["name", "pe", "growth", "margin", "fcf", "upside"],
                rows,
                lang,
                "business",
            )
        )
    return out


def tables(card: daily.DailyAction, key: str, evidence: dict, lang: str) -> list[dict]:
    """The computed tables under the analysis, headers in `lang`."""
    facts = card.facts or {}
    action = daily.keyed_actions(facts).get(key) or {}
    ccy = str(facts.get("currency") or "EUR")
    kind = str(action.get("kind") or "")
    out: list[dict] = []

    tax = evidence.get("tax") or {}
    if tax.get("offset") is not None:
        rows = [
            _row(_t("row_loss", lang), [_money(tax.get("loss"), ccy, lang)]),
            _row(_t("row_gain", lang), [_money(tax.get("gain_ytd"), ccy, lang)]),
            _row(_t("row_offset", lang), [_money(tax.get("offset"), ccy, lang)]),
        ]
        if tax.get("saving") is not None:
            rows.append(
                _row(
                    _t("row_saving", lang),
                    [_money(tax["saving"], ccy, lang)],
                    highlight=True,
                )
            )
        if tax.get("clear_if_sold_today"):
            rows.append(_row(_t("row_clear", lang), [_day(tax["clear_if_sold_today"])]))
        note = "tax" if tax.get("saving") is not None else ""
        out.append(_table("tax", ["concept", "amount"], rows, lang, note))

    out += _company_tables(evidence, lang)

    past = (evidence.get("history") or {}).get("prints") or []
    if past:
        out.append(
            _table(
                "history",
                ["date", "eps_est", "eps", "surprise", "move"],
                [
                    _row(
                        _day(r["date"]),
                        [
                            _NA
                            if r.get("eps_estimate") is None
                            else _n(r["eps_estimate"], lang, 2),
                            _NA
                            if r.get("reported_eps") is None
                            else _n(r["reported_eps"], lang, 2),
                            _p(r.get("surprise_pct"), lang),
                            _p(r.get("move_pct"), lang),
                        ],
                    )
                    for r in past
                ],
                lang,
                "history",
            )
        )

    held = evidence.get("holdings") or []
    if held:
        out.append(
            _table(
                "holdings",
                ["name", "weight", "pnl_pct", "m1", "y1"],
                [
                    _row(
                        "",
                        [
                            _p(r.get("weight_pct"), lang, False),
                            _p(r.get("pnl_pct"), lang),
                            _p(r.get("m1_pct"), lang),
                            _p(r.get("y1_pct"), lang),
                        ],
                        r["ticker"],
                    )
                    for r in held
                ],
                lang,
            )
        )

    rows = evidence.get("sectors") or []
    if rows:
        tilted = signals.SECTOR_TILT == kind and str(action.get("sector") or "")
        corr = any(r.get("corr_1y") is not None for r in rows)
        out.append(
            _table(
                "sectors",
                ["name", "m1", "m3", "y1", "vol"] + (["corr"] if corr else []),
                [
                    _row(
                        _sector_name(r["sector"], lang),
                        [
                            _p(r.get("m1_pct"), lang),
                            _p(r.get("m3_pct"), lang),
                            _p(r.get("y1_pct"), lang),
                            _p(r.get("vol_1y_pct"), lang, False),
                        ]
                        + (
                            [
                                _NA
                                if r.get("corr_1y") is None
                                else _n(r["corr_1y"], lang, 2)
                            ]
                            if corr
                            else []
                        ),
                        r["etf"],
                        highlight=r["sector"] == tilted,
                    )
                    for r in rows
                ],
                lang,
                "corr" if corr else "",
            )
        )

    attr = evidence.get("attribution") or []
    if attr:
        out.append(
            _table(
                "attribution",
                ["name", "weight", "m1", "contrib"],
                [
                    _row(
                        "",
                        [
                            _p(r.get("weight_pct"), lang, False),
                            _p(r.get("m1_pct"), lang),
                            _pts(r.get("contribution_pp"), lang),
                        ],
                        r["ticker"],
                    )
                    for r in attr
                ],
                lang,
                "attribution",
            )
        )

    book = evidence.get("open") or {}
    opened = (book.get("losses") or []) + (book.get("gains") or [])
    if opened:
        out.append(
            _table(
                "open",
                ["name", "pnl", "pnl_pct"],
                [
                    _row(
                        "",
                        [_money(r.get("pnl"), ccy, lang), _p(r.get("pnl_pct"), lang)],
                        r["ticker"],
                    )
                    for r in opened
                ],
                lang,
            )
        )

    path = (evidence.get("rates") or {}).get("history") or []
    if path:
        out.append(
            _table(
                "rates",
                ["date", "rate"],
                [
                    _row(_day(r.get("date")), [_p(r.get("rate"), lang, False, 2)])
                    for r in path
                ],
                lang,
            )
        )
    return out


def record(
    card: daily.DailyAction, key: str, evidence: dict, written: dict | None, lang: str
) -> dict:
    """What is stored under the card's `analysis[key]` and served: the
    model's verdict and points (or the computed ones) and the tables."""
    body = written or computed(card, key, evidence, lang)
    return {
        "source": _SOURCE_LLM if written else _SOURCE_COMPUTED,
        "verdict": body.get("verdict") or "",
        "points": list(body.get("points") or []),
        "tables": tables(card, key, evidence, lang),
        "as_of": str((card.facts or {}).get("date") or card.day),
    }
