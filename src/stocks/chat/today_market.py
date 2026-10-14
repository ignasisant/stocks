"""The Today page's market read — the part of the day every account shares.

Macro, rates, the central banks, sector rotation, the risk-appetite regime and
crypto sentiment are the same for every reader, so they are written once a
morning rather than once per account: a GitHub Actions cron
(`stocks today-market`, `.github/workflows/today.yml`) reads the figures off
the same loaders the Pulse page uses, asks the free chain for a headline and a
few lines per language, audits every figure in them against the facts, and
stores one file (`data/today_market.json`, mirrored to the bucket like the
sector and crypto scans). The API reads that file; when it is missing or a
session behind, it rebuilds it once on a background thread
(`api.briefing.market_day`), so the page never waits on it.

The file is stamped with the US session its figures close on, not with
`daily.action_day`: that rolls over at 09:00 local and reads "yesterday" when
the cron runs, while the figures are already the latest close.

Failure policy: a block that did not answer keeps the previous file's block
(the sector scan's rule), a language whose model did not answer gets the
computed lines, and a save that cannot reach the bucket is logged and
swallowed — the local file still serves this process.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, date, datetime
from typing import Any

from stocks import atomic, obs, storage
from stocks.config import DATA_DIR
from stocks.formatting import finite, fmt_num

FILE = DATA_DIR / "today_market.json"

TOPICS = ("trend", "sector", "rates", "macro", "crypto")
MIN_LINES = 2
MAX_LINES = 5
HEADLINE_CHARS = 90
LINE_CHARS = 160
# A line past this is dropped rather than cut: card text is never truncated.
LINE_MAX = 240
TIMEOUT_S = 30.0
# A read older than this is stale whatever its session says: the cron missed.
STALE_AFTER_S = 30 * 3600.0
# A failed rebuild is not retried before this: a session that will not advance
# (a holiday, a throttled download) must not cost a unit per page view.
MIN_REBUILD_S = 2 * 3600.0
MONTH, WEEK = 21, 5
# sentiment.TREND_SLOW, the sector ETFs' breadth window (stated in the prompt).
TREND_WINDOW_SECTORS = 100
# The rates the card quotes, by FRED id: (key, scale to basis points).
RATES = (("DGS10", "us10y"), ("T10Y2Y", "curve_2s10s"), ("BAMLH0A0HYM2", "hy_spread"))
# The policy series each bank's line quotes (the Fed's upper bound).
BANK_SERIES = {"fed": "DFEDTARU", "ecb": "ECBDFR"}
INFLATION_AREAS = ("US", "EA")
# Index names whose digits are part of the name, not a figure.
INDEX_NAMES = (
    "S&P 500", "Nasdaq 100", "Euro Stoxx 50", "Russell 2000", "FTSE 100",
    "IBEX 35", "CAC 40", "DAX 40", "Nikkei 225", "10-year", "10 años", "2 años",
    "2-year", "10y", "2s10s",
)
# What the model reads first, the same every morning: how the app reads the
# regime, rotation and rates (web/knowledge). Fixed, so the cron builds no index.
KNOWLEDGE = (
    ("pulse-risk-appetite", "The risk appetite score"),
    ("pulse-risk-appetite", "Rates regime"),
    ("pulse-risk-appetite", "Rotation, factor"),
)

_LANG_NAME = {"en": "English", "es": "Spanish"}


# ------------------------------------------------------------------- facts


def _series_last(series) -> tuple[float | None, Any]:
    clean = series.dropna() if series is not None else None
    if clean is None or clean.empty:
        return None, None
    return finite(clean.iloc[-1]), clean.index[-1]


def _change_bp(series, sessions: int = MONTH) -> float | None:
    """The move over `sessions` observations, in basis points (FRED's
    percent-quoted series: one point is 100 bp)."""
    clean = series.dropna() if series is not None else None
    if clean is None or len(clean) <= sessions:
        return None
    move = finite(clean.iloc[-1] - clean.iloc[-sessions - 1])
    return None if move is None else round(move * 100, 0)


def _last_move(series) -> tuple[float | None, str | None]:
    """(the policy rate's last change in bp, the day it took effect)."""
    clean = series.dropna() if series is not None else None
    if clean is None or len(clean) < 2:
        return None, None
    diff = clean.diff()
    moved = diff[diff.abs() > 1e-9]
    if moved.empty:
        return 0.0, None
    return round(float(moved.iloc[-1]) * 100, 0), str(moved.index[-1].date())


def _pct(series, sessions: int) -> float | None:
    from stocks.analysis import sentiment as sm

    if series is None:
        return None
    out = finite(sm.pct_over(series, sessions))
    return None if out is None else round(out * 100, 2)


def _regime(pulse) -> dict:
    from stocks.analysis import sentiment as sm

    score = finite(pulse.score)
    if score is None:
        raise ValueError("no score")
    history = pulse.history.dropna()
    month = finite(history.iloc[-MONTH - 1]) if len(history) > MONTH else None
    return {
        "score": round(score, 1),
        "key": sm.regime_key(score),
        "run": int(sm.regime_run(history)),
        "score_month": None if month is None else round(month, 1),
    }


def _breadth(closes) -> dict:
    from stocks.analysis import sentiment as sm

    ih, it = sm.above_ma_share(closes, [i.ticker for i in sm.INDICES], 200)
    sh, st = sm.above_ma_share(closes, list(sm.SECTOR_ETFS.values()), sm.TREND_SLOW)
    if not (it or st):
        raise ValueError("no breadth")
    return {"indices_hits": ih, "indices_total": it,
            "sectors_hits": sh, "sectors_total": st}


def _sectors(closes) -> list[dict]:
    """Sector ETFs against SPY, best month first — `routes.pulse._rotation`'s
    excess return over the week and the month."""
    from stocks.analysis import sentiment as sm

    bench = closes.get("SPY")
    if bench is None or bench.dropna().empty:
        raise ValueError("no SPY")
    rows = []
    for name, ticker in sm.SECTOR_ETFS.items():
        series = closes.get(ticker)
        if series is None or series.dropna().empty:
            continue
        excess = {}
        for label, days in (("week", WEEK), ("month", MONTH)):
            own, base = _pct(series, days), _pct(bench, days)
            excess[label] = None if own is None or base is None else round(own - base, 2)
        rows.append({"ticker": ticker, "name": name, **excess})
    if not rows:
        raise ValueError("no sectors")
    return sorted(rows, key=lambda r: -(r["month"] if r["month"] is not None else -1e9))


def _index(closes) -> dict:
    spy = closes.get("SPY")
    if spy is None or spy.dropna().empty:
        raise ValueError("no SPY")
    return {"name": "S&P 500", "day": _pct(spy, 1), "week": _pct(spy, WEEK),
            "month": _pct(spy, MONTH)}


def _rates(series: dict) -> list[dict]:
    out = []
    for sid, key in RATES:
        value, _ = _series_last(series.get(sid))
        if value is None:
            continue
        out.append({"key": key, "value": round(value, 2),
                    "change_bp": _change_bp(series.get(sid))})
    if not out:
        raise ValueError("no rates")
    return out


def _banks(series: dict, day: date) -> list[dict]:
    from stocks.data import macro_calendar as cal

    out = []
    for bank, sid in BANK_SERIES.items():
        rate, _ = _series_last(series.get(sid))
        move, moved_on = _last_move(series.get(sid))
        nxt = cal.next_decision(bank, day)
        last = cal.last_decision(bank, day)
        out.append({
            "bank": bank,
            "rate": None if rate is None else round(rate, 2),
            "last_move_bp": move,
            "last_date": last.isoformat() if last else None,
            # When the rate last changed, which is not always the last meeting:
            # "held at the last decision" needs both.
            "moved_on": moved_on,
            "next_date": nxt.isoformat() if nxt else None,
            "days": (nxt - day).days if nxt else None,
        })
    return out


def _inflation(frame) -> list[dict]:
    out = []
    if frame is None or getattr(frame, "empty", True):
        raise ValueError("no inflation")
    for _, row in frame.iterrows():
        if row.get("area") not in INFLATION_AREAS:
            continue
        head = finite(row.get("headline"))
        if head is None:
            continue
        core, mom = finite(row.get("core")), finite(row.get("momentum"))
        out.append({
            "area": str(row["area"]), "period": str(row.get("period") or ""),
            "headline": round(head, 1),
            "core": None if core is None else round(core, 1),
            "momentum": None if mom is None else round(mom, 1),
        })
    if not out:
        raise ValueError("no inflation rows")
    return sorted(out, key=lambda r: INFLATION_AREAS.index(r["area"]))


def _crypto(scan: dict) -> dict:
    greed = [row for row in scan.get("fear_greed") or []
             if isinstance(row, (list, tuple)) and len(row) == 2]
    dom = finite((scan.get("global") or {}).get("btc_dominance"))
    if not greed and dom is None:
        raise ValueError("no crypto scan")
    now = finite(greed[-1][1]) if greed else None
    week = finite(greed[-8][1]) if len(greed) >= 8 else None
    return {"fear_greed": now, "fear_greed_week": week,
            "btc_dominance": None if dom is None else round(dom, 1)}


def facts(day: date) -> dict:
    """Every figure the read is written from, each block on its own: a block
    whose source failed is named under `missing` and left out."""
    from stocks.api import loaders

    out: dict[str, Any] = {"day": day.isoformat(), "missing": []}

    def block(name: str, build) -> None:
        try:
            out[name] = build()
        except Exception as exc:  # noqa: BLE001 — one source, one block
            out["missing"].append(name)
            obs.warn("today.market_block_failed", block=name,
                     error_type=type(exc).__name__, error=str(exc)[:200])

    closes: dict = {}
    try:
        closes = loaders.pulse_closes()
    except Exception as exc:  # noqa: BLE001
        obs.warn("today.market_closes_failed", error_type=type(exc).__name__)
    block("regime", lambda: _regime(loaders.market_pulse()))
    block("breadth", lambda: _breadth(closes))
    block("sectors", lambda: _sectors(closes))
    block("index", lambda: _index(closes))
    rates: dict = {}
    try:
        rates = loaders.pulse_rate_rows()
    except Exception as exc:  # noqa: BLE001
        obs.warn("today.market_rates_failed", error_type=type(exc).__name__)
    block("rates", lambda: _rates(rates))
    block("banks", lambda: _banks(rates, day))
    block("inflation", lambda: _inflation(loaders.inflation()))
    block("crypto", lambda: _crypto(loaders.crypto_scan()))
    spy = closes.get("SPY")
    _, last = _series_last(spy)
    out["session"] = str(last.date()) if last is not None else ""
    return out


# ---------------------------------------------------------------- computed


def _sector_name(name: str, lang: str) -> str:
    from stocks.web.i18n import translate

    return translate(f"sentiment.sector_{name.lower().replace(' ', '_')}", lang)


def _signed(value: float, digits: int, lang: str) -> str:
    return fmt_num(value, digits, lang, signed=True)


def computed(f: dict, lang: str) -> dict:
    """The read with no model: a line per block from templates, and a headline
    naming the regime. Every figure is the facts' own."""
    from stocks.web.i18n import translate

    def t(key: str, **kw) -> str:
        return translate(f"today.market_fb_{key}", lang, **kw)

    lines: list[dict] = []
    regime = f.get("regime")
    label = translate(f"sentiment.regime_{regime['key']}", lang) if regime else ""
    if regime:
        lines.append({"topic": "trend", "line": t(
            "regime", label=label, score=fmt_num(regime["score"], 0, lang),
            n=regime["run"])})
    sectors = f.get("sectors") or []
    if len(sectors) >= 2 and sectors[0]["month"] is not None \
            and sectors[-1]["month"] is not None:
        lead, lag = sectors[0], sectors[-1]
        lines.append({"topic": "sector", "line": t(
            "sectors", lead=_sector_name(lead["name"], lang),
            lead_pct=_signed(lead["month"], 1, lang) + "%",
            lag=_sector_name(lag["name"], lang),
            lag_pct=_signed(lag["month"], 1, lang) + "%")})
    rates = {r["key"]: r for r in f.get("rates") or []}
    if (ten := rates.get("us10y")) is not None:
        line = t("rates", value=fmt_num(ten["value"], 2, lang)) if ten[
            "change_bp"] is None else t(
            "rates_move", value=fmt_num(ten["value"], 2, lang),
            bp=_signed(ten["change_bp"], 0, lang))
        lines.append({"topic": "rates", "line": line})
    for bank in f.get("banks") or []:
        if bank.get("days") is None or bank.get("rate") is None:
            continue
        key = f"{bank['bank']}_today" if bank["days"] == 0 else bank["bank"]
        lines.append({"topic": "macro", "line": t(
            key, rate=fmt_num(bank["rate"], 2, lang), days=bank["days"])})
    infl = {r["area"]: r for r in f.get("inflation") or []}
    if "US" in infl and "EA" in infl:
        lines.append({"topic": "macro", "line": t(
            "inflation", us=fmt_num(infl["US"]["headline"], 1, lang),
            ea=fmt_num(infl["EA"]["headline"], 1, lang))})
    crypto = f.get("crypto") or {}
    if crypto.get("fear_greed") is not None:
        line = t("crypto", value=fmt_num(crypto["fear_greed"], 0, lang)) if crypto.get(
            "fear_greed_week") is None else t(
            "crypto_week", value=fmt_num(crypto["fear_greed"], 0, lang),
            week=fmt_num(crypto["fear_greed_week"], 0, lang))
        lines.append({"topic": "crypto", "line": line})
    if regime and sectors:
        headline = t("headline", label=label, lead=_sector_name(sectors[0]["name"], lang))
    elif regime:
        headline = t("headline_regime", label=label)
    else:
        headline = t("quiet")
    return {"headline": headline, "lines": lines[:MAX_LINES + 2],
            "source": "computed", "lang": lang, "generated": time.time()}


# ------------------------------------------------------------------ written


_TASK = (
    "You write the market part of a daily investing page: what happened in "
    "the markets in the last session and the last weeks, for a reader who "
    "holds a book of shares, funds or crypto. The data is today's figures: "
    "the risk-appetite regime (0-100, its band, `run` = sessions it has held "
    "that band, `score_month` = the score a month ago), trend breadth "
    "(how many world indices trade above their 200-session average, how many "
    "sector ETFs above their 100-session average), sector ETFs against the "
    "S&P 500 over the week and the month (excess return, %), the US 10-year "
    "yield, the 2s10s curve and the high-yield spread with their month's "
    "move in basis points, the Fed's and the ECB's policy rate with their "
    "last move and days to their next decision, US and euro-area inflation, "
    "and crypto Fear & Greed (`fear_greed` today, `fear_greed_week` the "
    "reading a week ago, not a weekly figure) with bitcoin's share of the "
    "crypto market."
)
_SHAPE = (
    "Write a `headline` of at most {headline} characters naming the day's one "
    "main market fact, and between {min} and {max} `lines`, each with its "
    "`topic` (trend, sector, rates, macro or crypto) and at most {chars} "
    "characters. Different topics first; skip a topic whose data is missing "
    "rather than guessing it. A line says what moved and what it means for "
    "someone holding the asset class, in plain words, as one short sentence. "
    "Never open a line with its topic as a label (\"Rates:\"): the page "
    "already files it."
)
_RULES = (
    "Every figure you write must be in the data, rounded at most to one "
    "decimal: percentages as %, rates as %, moves in basis points as bp "
    "(English) or pb (Spanish). Never invent a figure, a date, a forecast or "
    "a name. Never tell the reader to buy or sell, never predict a price, "
    "and never say what a central bank will decide: give its next decision "
    "date or the days to it. "
    "A decision day with `days` 0 is today: the statement comes later in the "
    "day, so say it is due, not what it decided. The background notes explain "
    "how the app reads these figures: use them to interpret, never cite or "
    "mention them, and write no source names, tickers of ETFs or dates in "
    "brackets."
)
_DECIMALS = {"es": "Use a decimal comma (4,2 %), as Spanish does."}


def prompt(f: dict, lang: str) -> tuple[str, list[dict]]:
    from stocks.chat import knowledge, structured

    language = _LANG_NAME.get(lang, "English")
    system = "\n\n".join(filter(None, [
        _TASK,
        _SHAPE.format(headline=HEADLINE_CHARS, min=MIN_LINES, max=MAX_LINES,
                      chars=LINE_CHARS),
        _RULES,
        f"Write in {language}.",
        _DECIMALS.get(lang, ""),
        knowledge.excerpt(KNOWLEDGE),
    ]))
    data = {k: v for k, v in f.items() if k not in ("missing",)}
    return structured.render("WriteMarketDay", system, json.dumps(data, default=str))


_BP_RE = re.compile(
    r"([-+−]?\d+(?:[.,]\d+)?)\s*(?:bp|pb|p\.b\.|puntos básicos|basis points)\b",
    re.I,
)


def _audited(f: dict) -> dict:
    """The facts with the figures that are names counted as sourced."""
    from stocks.chat import daily

    # The breadth windows are named in the prompt ("200-session average").
    windows = [200.0, float(TREND_WINDOW_SECTORS), float(MONTH), float(WEEK)]
    return {**f, "named": daily.figures(" ".join(INDEX_NAMES)) + windows}


def _bp_miss(line: str, f: dict) -> str | None:
    """The first basis-point move in `line` that is not one of the facts' bp
    figures, or None."""
    from stocks.chat import daily

    pool: set[float] = set()
    for row in f.get("rates") or []:
        if row.get("change_bp") is not None:
            pool.add(abs(float(row["change_bp"])))
    for bank in f.get("banks") or []:
        if bank.get("last_move_bp") is not None:
            pool.add(abs(float(bank["last_move_bp"])))
    for match in _BP_RE.finditer(line):
        values = [abs(v) for v in daily.figures(match.group(1))]
        if not any(daily._matches(v, pool, 0) for v in values):
            return match.group(0)
    return None


def miss(line: str, f: dict) -> str | None:
    """The first figure in a written line the facts do not carry, or None."""
    from stocks.chat import daily

    sourced = _audited(f)
    return (daily.audit([line], sourced) or daily._bare(line, sourced)
            or _bp_miss(line, f))


# A topic written as the line's label ("Rates: …"); the page files the line
# under its topic already.
_LABEL_RE = re.compile(
    r"^(?:trends?|sectors?|rates?|macro|crypto|tendencias?|sectores?|tipos|"
    r"cripto)\s*:\s*",
    re.I,
)


def parse(raw: str, f: dict, lang: str) -> dict | None:
    """The reply as the stored read, or None to try the next provider: a
    headline that misquotes, or fewer than MIN_LINES lines left standing once
    every line with an unsourced figure is dropped."""
    from stocks.chat import structured

    try:
        data = structured.parse(raw, "WriteMarketDay")
    except Exception:  # noqa: BLE001 — off contract is a miss
        return None
    headline = " ".join(str(data.get("headline") or "").split())
    if (not headline or len(headline) > HEADLINE_CHARS * 1.5
            or miss(headline, f)):
        return None
    lines, seen = [], set()
    for row in data.get("lines") or []:
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or "").strip().lower()
        text = " ".join(str(row.get("line") or "").split())
        if _LABEL_RE.match(text):
            text = _LABEL_RE.sub("", text)
            text = text[:1].upper() + text[1:]
        if topic not in TOPICS or not text or text in seen or len(text) > LINE_MAX:
            continue
        if (wrong := miss(text, f)) is not None:
            obs.event("today.market_line_dropped", topic=topic, figure=wrong[:40])
            continue
        seen.add(text)
        lines.append({"topic": topic, "line": text})
        if len(lines) == MAX_LINES:
            break
    if len(lines) < MIN_LINES:
        return None
    return {"headline": headline, "lines": lines, "source": "llm", "lang": lang,
            "generated": time.time()}


def write(f: dict, lang: str, *, timeout_s: float = TIMEOUT_S) -> dict:
    """One language's read: the model's when one answers usefully, the
    computed one otherwise. Paid from the global free pot only — no account's
    prefs, no BYOK key."""
    from stocks.chat import engine

    try:
        system, messages = prompt(f, lang)
        card = engine.complete_attempts(
            {}, system, messages, timeout_s,
            spend_free=engine.spend_free_global,
            accept=lambda raw: parse(raw, f, lang),
        )
    except Exception as exc:  # noqa: BLE001 — the computed read stands
        obs.warn("today.market_write_failed", error_type=type(exc).__name__)
        card = None
    return card or computed(f, lang)


# ------------------------------------------------------------------- store


def load(*, restore: bool = True) -> dict:
    """The stored read, or {} when there is none (or it will not parse)."""
    if restore and storage.enabled():
        with obs.swallow("today.market_restore"):
            storage.restore(FILE)
    try:
        raw = json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) and isinstance(raw.get("facts"), dict) else {}


def save(payload: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(FILE, payload, indent=0, sort_keys=True)
    if storage.enabled():
        with obs.swallow("today.market_persist"):
            storage.persist(FILE)


def _merged(old: dict, new: dict) -> dict:
    """Today's facts over the stored ones, block by block: a block that did
    not answer this morning keeps the last one that did."""
    out = dict(new)
    kept = []
    for name in new.get("missing") or []:
        if name in (old or {}):
            out[name] = old[name]
            kept.append(name)
    out["missing"] = [m for m in new.get("missing") or [] if m not in kept]
    out["kept"] = kept
    if not out.get("session"):
        out["session"] = (old or {}).get("session") or ""
    return out


def card(stored: dict, lang: str) -> dict | None:
    """The read for `lang` as the page shows it — facts and lines together —
    or None when the file has no read in that language."""
    written = (stored.get("cards") or {}).get(lang)
    f = stored.get("facts") or {}
    if not isinstance(written, dict) or not written.get("headline"):
        return None
    return {
        "session": f.get("session") or "",
        "built_at": float(stored.get("built_at") or 0.0),
        "lang": lang,
        "source": written.get("source") or "computed",
        "headline": written["headline"],
        "lines": [ln for ln in written.get("lines") or [] if isinstance(ln, dict)],
        # A block under `missing` is absent, not null: the page reads an
        # empty list or no card for it.
        **{k: f[k] for k in ("regime", "breadth", "rates", "banks", "sectors",
                             "inflation", "crypto", "index") if f.get(k) is not None},
        "missing": list(f.get("missing") or []),
    }


def run(day: date | None = None, langs: tuple[str, ...] = ("es", "en"), *,
        dry_run: bool = False, refetch: bool = True) -> dict:
    """Build (or extend) the stored read; returns {part: status}.

    `refetch=False` reuses the stored facts and only writes the languages
    missing from them — what the API does when a reader in another language
    opens the page after this morning's build.
    """
    day = day or datetime.now(UTC).date()
    started = time.perf_counter()
    old = load()
    status: dict[str, str] = {}
    if refetch or not old.get("facts"):
        f = _merged(old.get("facts") or {}, facts(day))
        cards: dict = {}
        built_at = time.time()
    else:
        f = old["facts"]
        cards = dict(old.get("cards") or {})
        built_at = float(old.get("built_at") or time.time())
    status["facts"] = "missing: " + ",".join(f["missing"]) if f.get("missing") else "ok"
    for lang in langs:
        if lang in cards:
            continue
        written = write(f, lang)
        cards[lang] = written
        status[lang] = written["source"]
    # Languages the old file had and this run did not write keep nothing: a
    # read written from yesterday's figures would contradict today's.
    payload = {"facts": f, "cards": cards, "built_at": built_at,
               "session": f.get("session") or ""}
    obs.event("today.market_build", session=payload["session"],
              langs=",".join(langs), missing=",".join(f.get("missing") or []),
              sources=",".join(f"{k}:{v.get('source')}" for k, v in cards.items()),
              ms=round((time.perf_counter() - started) * 1000))
    if dry_run:
        status["dry_run"] = json.dumps(
            {k: card(payload, k) for k in cards}, default=str, ensure_ascii=False)[:4000]
        return status
    save(payload)
    status["saved"] = str(FILE)
    return status


# A US session's figures are settled by this hour UTC (16:00 New York is 20:00
# or 21:00 UTC; Yahoo and FRED have posted by 22:00).
SETTLED_HOUR_UTC = 22


def expected_session(now: datetime | None = None) -> str:
    """The last weekday whose US close has settled, ISO — the session a read
    built now should close on. Holidays are not known here: on one this names
    a session that never happened, the rebuild finds the same figures, and
    MIN_REBUILD_S keeps that from repeating."""
    from datetime import timedelta

    now = now or datetime.now(UTC)
    day = now.date() if now.hour >= SETTLED_HOUR_UTC else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.isoformat()


def stale(stored: dict, known_session: str | None, now: float | None = None) -> bool:
    """Whether the stored read is behind: none at all, older than the last
    session the app has prices for, or older than STALE_AFTER_S."""
    if not stored:
        return True
    now = time.time() if now is None else now
    if now - float(stored.get("built_at") or 0.0) > STALE_AFTER_S:
        return True
    session = str(stored.get("session") or "")
    return bool(known_session) and session < str(known_session)
