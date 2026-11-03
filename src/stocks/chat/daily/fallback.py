"""The card without a model: the same facts rendered line by line, and
the dressing every card gets before it reaches the page.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date

from stocks.chat import daily_book, signals
from stocks.chat.daily.card import (
    _SOURCE_COMPUTED,
    _WINDOW_KEYS,
    ALERTS,
    ALERTS_MAX,
    BRIEF_MISSED,
    BRIEF_PENDING,
    FOCUS_MAX,
    HEADLINE_CHARS,
    MAX_BULLETS,
    WATCH,
    DailyAction,
    _clip,
    _today,
    section_of,
)
from stocks.formatting import fmt_num


def _short_date(iso: str | None) -> str:
    """"2 Sep"-style stamp for a session date; the raw ISO when unparseable."""
    text = str(iso or "")
    try:
        return date.fromisoformat(text).strftime("%d/%m")
    except ValueError:
        return text


def _money(amount: float, currency: str, lang: str = "en") -> str:
    from stocks.config import currency_symbol

    return f"{currency_symbol(currency)}{fmt_num(amount, 0, lang, signed=True)}"


def _when(days, lang: str) -> str:
    """"today" / "tomorrow" / "in 5 days", for a date ahead."""
    from stocks.web.i18n import translate

    n = int(days or 0)
    if n <= 0:
        return translate("home.daily_when_today", lang)
    if n == 1:
        return translate("home.daily_when_tomorrow", lang)
    return translate("home.daily_when_days", lang, days=n)


def _bank(action: dict, lang: str) -> str:
    from stocks.web.i18n import translate

    return translate(f"home.daily_bank_{action.get('bank') or 'fed'}", lang)


def _rate(action: dict, lang: str = "en") -> str:
    """The policy rate as printed: the Fed's range, the ECB's single rate."""
    rate = float(action.get("rate") or 0.0)
    low = action.get("rate_low")
    if low is not None and float(low) != rate:
        return f"{fmt_num(float(low), 2, lang)}–{fmt_num(rate, 2, lang)}%"
    return f"{fmt_num(rate, 2, lang)}%"


def _deadline(action: dict, lang: str) -> str:
    """A tax deadline's own name — the tax calendar already carries one."""
    from stocks.web.i18n import has, translate

    slug = f"earnings.tax_{action.get('deadline') or ''}"
    if has(slug):
        return translate(slug, lang, year=action.get("year") or "")
    return str(action.get("deadline") or "")


def _short_line(action: dict, lang: str) -> str:
    """A few words naming one action — what a computed headline strings
    together into "the day in one line"."""
    from stocks.web.i18n import has, translate

    kind = str(action.get("kind") or "")
    slug = f"home.daily_short_{kind}"
    if not has(slug):
        return ""
    sector = str(action.get("sector") or "")
    sector_slug = f"sentiment.sector_{sector.lower().replace(' ', '_')}"
    return translate(
        slug, lang,
        ticker=str(action.get("ticker") or ""),
        when=_when(action.get("in_days", action.get("days_left")), lang),
        bank=_bank(action, lang),
        name=_deadline(action, lang) if kind == signals.TAX_DEADLINE else "",
        sector=translate(sector_slug, lang) if has(sector_slug) else sector,
        bucket=_bucket(action.get("bucket"), lang) if action.get("bucket") else "",
        subject=str(action.get("ticker") or "")
        or (translate(sector_slug, lang) if has(sector_slug) else sector),
        index=action.get("index") or "",
        trend=translate(f"home.daily_trend_{action.get('trend') or 'unknown'}", lang),
        currency=action.get("currency") or "",
        decision=translate(
            f"home.daily_decision_{action.get('decision') or 'hold'}", lang
        ),
    )


def _summary(labels: list[str]) -> str:
    """The computed headline: the first few labels, as many as fit."""
    out = ""
    for label in (lb for lb in labels if lb):
        joined = f"{out} · {label}" if out else label
        if len(joined) > HEADLINE_CHARS:
            break
        out = joined
    if not out and labels:
        out = _clip(next((lb for lb in labels if lb), ""), HEADLINE_CHARS)
    return out[:1].upper() + out[1:]


def _criterion_slots(action: dict, lang: str) -> dict:
    """The placeholders of an exit-rule line: the rule in words, the figure
    it reads today and how far it still is (or how far past)."""
    from stocks.web.i18n import translate

    rule = str(action.get("rule") or "below")
    price = rule == "below"
    level = float(action.get("level") or 0)
    value = float(action.get("value") or 0)
    text = translate(f"home.daily_crit_{rule}", lang,
                     level=fmt_num(level, 2 if price else
                                   0 if level.is_integer() else 1, lang))
    if int(action.get("quarters") or 1) > 1:
        text = translate("home.daily_crit_run", lang, rule=text,
                         n=int(action["quarters"]))
    return {
        "ticker": str(action.get("ticker") or ""),
        "rule": text,
        "value": fmt_num(value, 2, lang) if price
        else f"{fmt_num(value, 1, lang)}%",
        "gap": f"{fmt_num(float(action.get('gap_pct') or 0), 1, lang)}"
        + ("%" if price else " pp"),
        # An event rule reads a passage, not a figure (`chat/exit_judge.py`).
        "quote": str(action.get("quote") or ""),
        "source": str(action.get("source") or ""),
    }


_PLAN_KINDS = frozenset({
    signals.PLAN_DRIFT, signals.PLAN_LIMIT, signals.CONTRIBUTION_DUE,
    signals.RESERVE, signals.NO_EXIT_RULE, signals.PLAN_MISSING,
    signals.CASH_STALE,
})


def _share(value, lang: str, digits: int = 0) -> str:
    """A plan percentage as printed: "35%"."""
    return f"{fmt_num(float(value or 0), digits, lang)}%"


def _bucket(name, lang: str) -> str:
    """A plan bucket's own label, the one the plan form shows."""
    from stocks.web.i18n import translate

    return translate(f"profile.plan_bucket_{name or 'stocks'}", lang)


def _sector_label(sector: str, lang: str) -> str:
    from stocks.web.i18n import has, translate

    slug = f"sentiment.sector_{sector.lower().replace(' ', '_')}"
    return translate(slug, lang) if has(slug) else sector


def _plan_line(action: dict, lang: str, ccy: str) -> str:
    """A line about the reader's plan (`signals.plan_candidates`)."""
    from stocks.web.i18n import translate

    kind = str(action.get("kind") or "")
    key = f"home.daily_act_{kind}"
    if kind == signals.PLAN_DRIFT:
        return translate(
            f"{key}_{action.get('side') or 'over'}", lang,
            bucket=_bucket(action.get("bucket"), lang),
            actual=_share(action.get("actual_pct"), lang),
            target=_share(action.get("target_pct"), lang),
            band=fmt_num(float(action.get("band_pp") or 0), 0, lang),
        )
    if kind == signals.PLAN_LIMIT:
        scope = str(action.get("scope") or "position")
        return translate(
            f"{key}_{scope}", lang, ticker=str(action.get("ticker") or ""),
            sector=_sector_label(str(action.get("sector") or ""), lang),
            weight=_share(action.get("weight_pct"), lang),
            cap=_share(action.get("cap_pct"), lang),
        )
    if kind == signals.CONTRIBUTION_DUE:
        line = translate(
            key, lang, amount=_money(abs(float(action.get("amount") or 0)),
                                     ccy, lang).replace("+", ""),
            when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")),
        )
        under = [_bucket(b, lang) for b in action.get("under") or []]
        if under:
            return line + " " + translate(f"{key}_under", lang,
                                          buckets=", ".join(under))
        return line + " " + translate(f"{key}_even", lang)
    if kind == signals.RESERVE:
        return translate(
            f"{key}_{action.get('state') or 'low'}", lang,
            cash=_share(action.get("cash_pct"), lang, 1),
            min=_share(action.get("min_pct"), lang),
            max=_share(action.get("max_pct"), lang),
        )
    if kind == signals.NO_EXIT_RULE:
        return translate(key, lang, ticker=str(action.get("ticker") or ""),
                         weight=_share(action.get("weight_pct"), lang))
    if kind == signals.PLAN_MISSING:
        return translate(key, lang)
    if kind == signals.CASH_STALE:
        return translate(key, lang, days=str(int(action.get("days") or 0)))
    return ""


def go_of(item: dict) -> str:
    """Where a line's reader goes to act on it: the page that resolves the
    trigger, as a shell path with its query. Empty for a context line, and
    for a line only about one name (a 52-week low, an alert, a filing): its
    ticker cell already opens that name's page."""
    kind = str(item.get("kind") or "")
    if kind in (signals.PLAN_DRIFT, signals.RESERVE, signals.PLAN_MISSING,
                signals.CASH_STALE):
        return "/profile?tab=plan"
    if kind in (signals.PLAN_LIMIT, signals.CONTRIBUTION_DUE,
                signals.CONCENTRATION, signals.DRAWDOWN):
        return "/review"
    if kind in (signals.HARVEST, signals.TAX_DEADLINE, signals.TAX_YEAR_END,
                signals.TAX_BRACKET, signals.REPURCHASE_CLEAR):
        return "/portfolio?tab=tax"
    if kind in (signals.EARNINGS, signals.EARNINGS_RESULT):
        return "/earnings"
    if kind in (signals.CRITERION_HIT, signals.CRITERION_NEAR,
                signals.NO_EXIT_RULE):
        return "/profile?tab=journal"
    if kind == signals.SECTOR_TILT:
        return "/sector"
    return ""


def _criterion_key(key: str, action: dict) -> str:
    """An event rule's line quotes what it was met on instead of a figure."""
    from stocks.chat import journal

    return f"{key}_event" if action.get("rule") in journal.EVENT_RULES else key


def _flag(action: dict, lang: str) -> str:
    """What a filing flag's filing says, in a clause: "it says past accounts
    can no longer be relied on"."""
    from stocks.web.i18n import translate

    flag = str(action.get("flag") or "late").replace(".", "_")
    return translate(f"home.daily_flag_{flag}", lang)


def _action_line(action: dict, lang: str, ccy: str) -> str:
    """One computed action as a sentence. Empty for a kind with no template."""
    from stocks.web.i18n import translate

    kind = str(action.get("kind") or "")
    ticker = str(action.get("ticker") or "")
    key = f"home.daily_act_{kind}"

    def money(value) -> str:
        """An amount with no sign: these lines say "a 2,400 loss", and a "+"
        in front of a loss reads as the opposite of what it is."""
        return _money(abs(float(value or 0.0)), ccy, lang).replace("+", "")

    if kind in (signals.CRITERION_HIT, signals.CRITERION_NEAR):
        return translate(_criterion_key(key, action), lang,
                         **_criterion_slots(action, lang))
    if kind in (signals.ALERT_HIT, signals.ALERT_NEAR):
        rule = translate(f"home.daily_rule_{action.get('rule') or 'below'}", lang)
        return translate(
            key, lang, ticker=ticker, rule=rule,
            level=fmt_num(float(action.get('level') or 0), 2, lang),
            price=fmt_num(float(action.get('price') or 0), 2, lang),
            gap=f"{fmt_num(float(action.get('gap_pct') or 0), 1, lang)}%",
        )
    if kind == signals.EARNINGS:
        return translate(
            key if action.get("held", True) else f"{key}_watched", lang,
            ticker=ticker, when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")),
        )
    if kind == signals.EARNINGS_RESULT:
        if action.get("eps_estimate") is None:
            return translate(
                f"{key}_plain", lang, ticker=ticker,
                date=_short_date(action.get("date")),
                eps=fmt_num(float(action.get('reported_eps') or 0), 2, lang),
            )
        return translate(
            key, lang, ticker=ticker, date=_short_date(action.get("date")),
            eps=fmt_num(float(action.get('reported_eps') or 0), 2, lang),
            est=fmt_num(float(action.get('eps_estimate') or 0), 2, lang),
            surprise=f"{fmt_num(float(action.get('surprise_pct') or 0), 1, lang,
                signed=True)}%",
            verdict=translate(
                "home.daily_beat" if action.get("beat") else "home.daily_missed", lang
            ),
        )
    if kind == signals.FILING_FLAG:
        return translate(key, lang, ticker=ticker,
                         date=_short_date(action.get("date")),
                         what=_flag(action, lang))
    if kind == signals.MACRO_EVENT:
        return translate(
            key, lang, bank=_bank(action, lang),
            when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")), rate=_rate(action, lang),
        )
    if kind == signals.MACRO_RESULT:
        decision = str(action.get("decision") or "hold")
        return translate(
            f"{key}_{decision}", lang, bank=_bank(action, lang),
            bp=abs(int(action.get("change_bp") or 0)),
            rate=_rate(action, lang), date=_short_date(action.get("date")),
        )
    if kind == signals.TAX_DEADLINE:
        return translate(
            key, lang, name=_deadline(action, lang),
            when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("date")),
        )
    if kind == signals.TAX_YEAR_END:
        line = translate(
            key, lang, when=_when(action.get("days_left"), lang),
            end=_short_date(action.get("end")),
            gain=_money(float(action.get("gain_ytd") or 0.0), ccy, lang),
        )
        if float(action.get("open_losses") or 0) >= signals.HARVEST_MIN:
            line += " " + translate(
                "home.daily_act_tax_year_end_losses", lang,
                losses=money(action.get("open_losses")),
            )
        return line
    if kind == signals.TAX_BRACKET:
        return translate(
            key, lang, gain=money(action.get("gain_ytd")),
            room=money(action.get("room")),
            rate=f"{fmt_num(float(action.get('rate_pct') or 0), 0, lang)}%",
            next=f"{fmt_num(float(action.get('next_rate_pct') or 0), 0, lang)}%",
        )
    if kind == signals.REPURCHASE_CLEAR:
        return translate(
            key, lang, ticker=ticker, loss=money(action.get("loss")),
            sold=_short_date(action.get("sell_date")),
            when=_when(action.get("in_days"), lang),
            date=_short_date(action.get("clear_date")),
        )
    if kind == signals.HARVEST:
        line = translate(
            key, lang, ticker=ticker, loss=money(action.get("loss")),
            offset=money(action.get("offset")),
            gain=money(action.get("gain_ytd")),
        )
        # The repurchase window is the trap that goes with the arithmetic, so
        # it rides the same line — as a localized phrase built from the
        # jurisdiction's bare token ("2m", "30d", "28d").
        window = str(action.get("repurchase_window") or "")
        if window in _WINDOW_KEYS:
            line += " " + translate(f"home.daily_window_{window}", lang)
        return line
    if kind == signals.DRAWDOWN:
        # Unsigned: the sentence already says "under your cost".
        return translate(
            key, lang, ticker=ticker,
            pct=f"{fmt_num(abs(float(action.get('pnl_pct') or 0)), 1, lang)}%",
            amount=money(action.get("pnl")),
        )
    if kind == signals.CONCENTRATION:
        return translate(
            key, lang, ticker=ticker,
            weight=f"{fmt_num(float(action.get('weight_pct') or 0), 0, lang)}%",
        )
    if kind in _PLAN_KINDS:
        return _plan_line(action, lang, ccy)
    if kind == signals.LOW_52W:
        return translate(
            key, lang, ticker=ticker,
            price=fmt_num(float(action.get('price') or 0), 2, lang),
            gap=f"{fmt_num(float(action.get('gap_pct') or 0), 1, lang)}%",
        )
    if kind == signals.MARKET:
        # Breadth rides the same line when it could be read: the index level
        # and how much of the market is behind it are one reading, and split
        # over two lines they read as two unrelated facts.
        line = translate(
            key, lang, index=action.get("index") or "",
            trend=translate(f"home.daily_trend_{action.get('trend')}", lang),
            dip=f"{fmt_num(abs(float(action.get('from_high_pct') or 0)), 1, lang)}%",
        )
        if action.get("sectors_read"):
            line += " " + translate(
                "home.daily_act_market_breadth", lang,
                hit=action.get("sectors_in_uptrend"),
                total=action.get("sectors_read"),
            )
        return line
    if kind == signals.SECTOR_TILT:
        # The sector labels are Yahoo's English spellings; the Pulso page
        # already carries a translation for each, so the card borrows it and
        # prints the raw label only for a bucket that has none.
        from stocks.web.i18n import has

        sector = str(action.get("sector") or "")
        slug = f"sentiment.sector_{sector.lower().replace(' ', '_')}"
        line = translate(
            key, lang,
            sector=translate(slug, lang) if has(slug) else sector,
            own=f"{fmt_num(float(action.get('own_pct') or 0), 0, lang)}%",
            index=f"{fmt_num(float(action.get('index_pct') or 0), 0, lang)}%",
            tilt=fmt_num(float(action.get('tilt_pp') or 0), 0, lang, signed=True),
        )
        excess = action.get("excess_month_pct")
        if excess is not None:
            line += " " + translate(
                "home.daily_act_sector_tilt_excess", lang,
                excess=f"{fmt_num(float(excess), 1, lang, signed=True)}%",
            )
        return line
    if kind == signals.VS_BENCH:
        return translate(
            key, lang, index=action.get("index") or "",
            book=f"{fmt_num(float(action.get('book_month_pct') or 0), 1, lang,
                signed=True)}%",
            bench=f"{fmt_num(float(action.get('index_month_pct') or 0), 1, lang,
                signed=True)}%",
            gap=fmt_num(abs(float(action.get('gap_pp') or 0)), 1, lang),
        )
    if kind == signals.FX:
        return translate(
            key, lang, currency=action.get("currency") or "",
            share=f"{fmt_num(float(action.get('share_pct') or 0), 0, lang)}%",
            move=f"{fmt_num(float(action.get('move_month_pct') or 0), 1, lang,
                signed=True)}%",
            drag=f"{fmt_num(float(action.get('drag_month_pct') or 0), 1, lang,
                signed=True)}%",
        )
    return ""


def computed(facts: dict, lang: str, day: date) -> DailyAction:
    """The card without a model: the computed actions, stated.

    Shown whenever generation is unavailable — no provider configured, the
    free allowance spent, every candidate down. It is the reason the card can
    live on the dashboard at all, and it degrades honestly rather than
    thinly: the triggers are the same ones the model would have been given, so
    what the reader loses is the ordering judgement and the phrasing, not the
    substance. With nothing triggered it says so and falls back to the day's
    figure, which is the truthful version of "no action today".

    A brief is not written here: it is the reader's own words, and only a
    model answers those. The card says whether its brief is still being
    fetched or was missed today (`brief`), and stands in with the default.
    """
    from stocks.web.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"home.daily_fb_{key}", lang, **kw)

    ccy = str(facts.get("currency") or "EUR")
    session = facts.get("session") or {}
    book = daily_book.section(facts)
    items: list[dict] = []
    labels: list[str] = []
    room = {ALERTS: ALERTS_MAX, WATCH: MAX_BULLETS}
    for action in facts.get("actions") or []:
        line = _action_line(action, lang, ccy)
        if not line:
            continue
        kind = str(action.get("kind") or "")
        ticker = str(action.get("ticker") or "")
        item = {
            "key": str(action.get("key") or signals.key_of(kind, action)),
            "kind": kind,
            "line": line,
            "tickers": [ticker] if ticker else [],
        }
        if room[section_of(item)] <= 0:
            continue
        room[section_of(item)] -= 1
        items.append(item)
        labels.append(_short_line(action, lang))
    bullets = [i["line"] for i in items]
    focus = [t for i in items for t in i["tickers"]]
    lead = [_book_label(facts, lang)] if book else []

    if items:
        # The headline names the day's few things; the lines below say each
        # in full. Never the top line cut to fit: that ends mid-word.
        headline = _summary(lead + labels) or tr("one_action")
    else:
        # Nothing triggered. The day's move is context, not an action — say
        # the quiet part first so the card never poses a figure as a decision.
        # With the Portfolio section on the card the move is there already.
        change = {} if book else facts.get("day") or {}
        plan = facts.get("plan") or {}
        holds = bool(plan.get("on_track"))
        headline = _summary(lead + [tr("plan_holds" if holds else "no_actions")])
        if holds and plan.get("next_contribution"):
            bullets.append(tr(
                "plan_next",
                date=_short_date(plan["next_contribution"]),
                amount=_money(abs(float(plan.get("amount") or 0)), ccy,
                              lang).replace("+", ""),
            ))
        if change.get("pct") is not None:
            # "Portfolio +0.19% today" is a lie off-hours: the figure is the
            # last completed session's. Same rule the model is held to.
            bullets.append(tr(
                "day" if session.get("is_today", True) else "day_session",
                pct=f"{fmt_num(change['pct'], 2, lang, signed=True)}%",
                amount=_money(change.get("amount") or 0.0, ccy, lang),
                date=_short_date(session.get("date")),
            ))
        soon = facts.get("earnings_soon") or []
        if soon:
            bullets.append(tr(
                "earnings",
                tickers=", ".join(e["ticker"] for e in soon[:3]),
                days=soon[0]["in_days"],
            ))
            focus += [e["ticker"] for e in soon[:2]]
        if not bullets:
            bullets.append(tr("nothing"))
        items = [
            {"key": f"line:{n}", "kind": "", "line": b, "tickers": []}
            for n, b in enumerate(bullets)
        ]

    return DailyAction(
        day=day.isoformat(),
        headline=_clip(headline, HEADLINE_CHARS),
        bullets=bullets,
        focus=list(dict.fromkeys(focus))[:FOCUS_MAX],
        as_of=str(session.get("date") or ""),
        source=_SOURCE_COMPUTED,
        lang=lang,
        generated=time.time(),
        items=items,
        book=book,
        brief=_brief_state(facts),
        brief_sig=str((facts.get("brief") or {}).get("sig") or ""),
    )


def _brief_state(facts: dict) -> str:
    brief = facts.get("brief")
    if not brief:
        return ""
    return BRIEF_PENDING if brief.get("pending") else BRIEF_MISSED


def _book_label(facts: dict, lang: str) -> str:
    """"Portfolio +0.80% vs S&P 500 +0.30%" — the computed headline's lead."""
    from stocks.web.i18n import translate

    own = (facts.get("day") or {}).get("pct")
    index = facts.get("index") or {}
    if own is None:
        return ""
    if index.get("day_pct") is None:
        return translate(
            "home.daily_short_book_alone", lang,
            pct=f"{fmt_num(own, 2, lang, signed=True)}%",
        )
    words = {
        "pct": f"{fmt_num(own, 2, lang, signed=True)}%",
        "index": index.get("name") or daily_book.INDEX_NAME,
        "bench": f"{fmt_num(float(index['day_pct']), 2, lang, signed=True)}%",
    }
    # Before New York opens, the book's day already has Europe's session in it
    # while the index's is still the last US close: two days set side by side
    # as one would read as a comparison that never happened.
    theirs = str(index.get("as_of") or "")
    ours = str((facts.get("day") or {}).get("as_of") or "")
    if theirs and ours and theirs != ours:
        weekday = date.fromisoformat(theirs).weekday()
        return translate("home.daily_short_book_split", lang, **words,
                         day=translate(f"home.weekday_{weekday}", lang))
    return translate("home.daily_short_book", lang, **words)


def dressed(
    action: DailyAction | None,
    chart: list[dict] | None = None,
    drawn: dict[int, dict] | None = None,
) -> DailyAction | None:
    """`action` with its charts attached: the month under the Portfolio
    section, and each brief line's own under the section answering it
    (`drawn`, keyed by the line's `n`).

    Charts never go through `facts` — the model is given what they show
    (`daily_routines.chart_fact`), never the series — so a card is built
    without them and dressed after.
    """
    if action is None:
        return None
    book = dict(action.book)
    if book and chart:
        book["chart"] = chart
    drawn = drawn or {}
    sections = [
        {**sec, "chart": next((drawn[n] for n in sec.get("asks") or [] if n in drawn),
                              sec.get("chart"))}
        for sec in action.sections
    ]
    return replace(action, book=book, sections=sections)


def with_today(action: DailyAction | None, facts: dict) -> DailyAction | None:
    """`action` with the Today page's computed sections (`facts["today"]`,
    `today_sections.gather`), keeping any note the model wrote for one.

    The rows are never the model's: a card written before they were gathered,
    or by a model that skipped them, gets them all the same.
    """
    today = (facts or {}).get("today")
    if action is None or not isinstance(today, dict):
        return action
    notes = {sec["id"]: sec.get("note") or "" for sec in action.today}
    sections = [
        {**sec, "note": notes.get(sec["id"]) or sec.get("note") or ""}
        for sec in _today(today.get("sections"))
    ]
    return replace(action, today=sections, shape=str(today.get("shape") or ""))
