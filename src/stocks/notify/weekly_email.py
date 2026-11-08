"""The Friday email — the week of one imported book, by mail (Resend).

The Sunday push (`notify/weekly.py`) is a headline for whoever installed a
device; this is the same week, whole, for every account that imported a
portfolio, device or not. It reads the same `compute_weekly_data` — one
`book_history`, so every figure is the same valuation and they add up — and
adds what a notification has no room for: the returns table against the index
bought with the same money (from the book's first day first), the week's own
trades, the exit rules that fired, and what the account has not set up yet
(`onboarding.account_gaps`).

Numbers only, no generated sentence: what a reader acts on from their inbox
must be a figure they can find again in the app. A section with nothing to
say is left out, never shown empty.

`compose` is pure apart from the book read and returns the subject, the
preheader and both bodies; `send_for` is what the schedule calls
(`notify/schedule.py`), and `stocks weekly-email` renders or sends one by hand.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from stocks import obs
from stocks.config import currency_symbol
from stocks.formatting import DECIMAL_COMMA, fmt_num, fmt_pct
from stocks.notify import links, mail
from stocks.notify.digest import BENCHMARK_LABEL
from stocks.notify.render import date_line
from stocks.notify.weekly import MONTH, TOP_N, WEEK, WeeklyData, compute_weekly_data
from stocks.web import ds

PREF = "notify_weekly_email"
JOB = "weekly_email"
UNSUBSCRIBE = "unsubscribe"
# A link in an old email must still stop the next one: a year, not a session.
UNSUBSCRIBE_MAX_AGE = 400 * 24 * 3600

# Light first (most inboxes), the DS dark palette where the client honours
# `prefers-color-scheme` (Apple Mail, iOS, Outlook.com).
LIGHT = {
    "page": "#F3F2F5", "card": ds.ON_BRAND, "text": ds.SURFACE_PAGE,
    "muted": ds.TEXT_FAINT, "rule": "#E4E2E8", "up": ds.SUCCESS_FILL,
    "down": ds.CRITICAL_FILL, "cta": ds.BRAND_CTA, "on_cta": ds.ON_BRAND,
}
DARK = {
    "page": ds.SURFACE_PAGE, "card": ds.SURFACE_CARD, "text": ds.TEXT_PRIMARY,
    "muted": ds.TEXT_MUTED, "rule": ds.BORDER, "up": ds.CANDLE_UP,
    "down": ds.CANDLE_DOWN,
}


@dataclass
class Activity:
    """The week's own doings in the book, in its currency."""

    buys: int = 0
    sells: int = 0
    net: float = 0.0  # bought minus sold: money that is not gain
    realized: float | None = None
    dividends: float = 0.0
    fees: float = 0.0  # negative, as `Attribution.fees`

    def __bool__(self) -> bool:
        return bool(self.buys or self.sells or self.dividends or self.fees)


@dataclass
class Fired:
    """An exit rule whose condition was met this week, as the journal set it."""

    ticker: str
    day: date
    rule: str
    level: str = ""
    quarters: int = 1
    pillars: str = ""


@dataclass
class Email:
    subject: str
    preheader: str
    html: str
    text: str
    to: str = ""
    unsubscribe: str | None = None


@dataclass
class _View:
    """Everything one email says, gathered before a line is written."""

    data: WeeklyData
    lang: str
    base_url: str | None
    activity: Activity = field(default_factory=Activity)
    fired: list[Fired] = field(default_factory=list)
    gaps: list = field(default_factory=list)
    first: bool = False
    unsubscribe: str | None = None

    def tr(self, key: str, **kw) -> str:
        from stocks.web.i18n import translate

        return translate(f"email.{key}", self.lang, **kw)

    def url(self, page: str, **query: str) -> str | None:
        return links.page_url(page, self.base_url, **query)

    # `gather` builds no view for a week without a value or a change, so
    # past it both are always there.

    @property
    def total(self) -> float:
        assert self.data.total is not None
        return self.data.total

    @property
    def week(self) -> tuple[float, float]:
        assert self.data.week is not None
        return self.data.week

    # Figures the way the reader writes them: "133.199 €" and "-1,88%" in
    # Spanish, "€133,199" and "-1.88%" in English — never a mix of both.

    def money(self, amount: float, sign: bool = False) -> str:
        text = fmt_num(amount, 0, self.lang, signed=sign)
        symbol = currency_symbol(self.data.currency)
        if self.lang.split("-")[0] in DECIMAL_COMMA:
            return f"{text} {symbol}"
        if text[0] in "+-":
            return f"{text[0]}{symbol}{text[1:]}"
        return f"{symbol}{text}"

    def signed(self, amount: float) -> str:
        return self.money(amount, sign=True)

    def pct(self, fraction: float, digits: int = 2, sign: bool = True) -> str:
        return fmt_pct(fraction, digits, self.lang, signed=sign)

    def delta(self, change: float, pct: float) -> str:
        return f"{self.signed(change)} ({self.pct(pct)})"


# ------------------------------------------------------------------ gather


def _span(data: WeeklyData) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    from stocks.analysis.portfolio import window_span

    if data.hist is None:
        return None
    return window_span(pd.DatetimeIndex(data.hist.index), WEEK)


def activity(data: WeeklyData) -> Activity:
    """Trades, money in, realized gains, dividends and fees over the window
    the week's change is measured on (`window_span`), so they belong to it."""
    from stocks.analysis.return_attribution import attribution
    from stocks.portfolio import transfers

    out = Activity()
    span = _span(data)
    if span is None or data.hist is None:
        return out
    opened, closed = span[0].date().isoformat(), span[1].date().isoformat()

    def inside(day: str) -> bool:
        return opened < day[:10] <= closed

    with obs.swallow("email.trades"):
        rows = transfers.normalize(transfers.relabel(list(data.transactions)))
        out.buys = sum(1 for t in rows if t.action == "buy" and inside(t.date))
        out.sells = sum(1 for t in rows if t.action == "sell" and inside(t.date))
    with obs.swallow("email.realized"):
        sold = [s for s in data.realized if inside(s.sell_date)]
        out.realized = sum(s.gain for s in sold) if sold else None
    with obs.swallow("email.flows"):
        split = attribution(data.hist, data.transactions, start=span[0],
                            base=data.currency)
        if split is not None:
            out.net, out.dividends, out.fees = (
                split.contributions, split.dividends, split.fees,
            )
    return out


def fired_rules(journal_path, today: date) -> list[Fired]:
    """The reader's exit rules whose condition was met in the last week."""
    from stocks.chat import journal

    since = today - timedelta(days=WEEK)
    out = []
    for e in journal.criteria(journal.load(journal_path)):
        snap = e.snapshot
        if e.state != "hit":
            continue
        try:
            day = date.fromisoformat(str(snap.get("hit_day") or "")[:10])
        except ValueError:
            continue
        if since < day <= today:
            level = snap.get("level")
            out.append(Fired(
                e.ticker, day, str(snap.get("rule") or ""),
                f"{level:g}" if isinstance(level, int | float) else str(level or ""),
                int(snap.get("quarters") or 1),
                " / ".join(journal.pillars_of(snap.get("pillars"))),
            ))
    return sorted(out, key=lambda f: f.day)


def _rule_text(f: Fired, lang: str) -> str:
    """'Loss of 20 % on cost' — the journal's own wording for the rule."""
    from stocks.web.i18n import translate

    text = translate(f"journal.crit_{f.rule}", lang, level=f.level, pillars=f.pillars)
    if f.quarters > 1:
        text = translate("journal.crit_run", lang, rule=text, n=f.quarters)
    return text


def _held(data: WeeklyData) -> set[str]:
    legs = (data.hist.attrs.get("legs") if data.hist is not None else None) or {}
    return {str(t) for t, leg in legs.items() if float(leg.shares.iloc[-1]) > 0}


def gather(label: str, paths, prefs: dict, day: date,
           base_url: str | None = None) -> _View | str:
    """The view of one account's week, or why there is none."""
    from stocks.web.onboarding import account_gaps

    base = str(prefs.get("currency") or "EUR").upper()
    data = compute_weekly_data(paths.watchlist, paths.db, base, today=day)
    if data.total is None or data.week is None:
        return "no book"
    lang = str(prefs.get("language") or "en")
    view = _View(data, lang, base_url if base_url is not None else links.app_base())
    view.activity = activity(data)
    with obs.swallow("email.rules"):
        view.fired = fired_rules(paths.journal, day)
    with obs.swallow("email.gaps"):
        view.gaps = account_gaps(prefs, paths, email=prefs.get("email"),
                                 held=_held(data), unpriced=data.missing,
                                 today=day, lang=lang)
    view.first = JOB not in (prefs.get("schedule_last") or {})
    view.unsubscribe = unsubscribe_url(label, view.base_url)
    return view


# ------------------------------------------------------------------ links


def unsubscribe_token(label: str) -> str | None:
    from stocks import session

    return session.seal(UNSUBSCRIBE, {"s": label, "j": JOB})


def unsubscribe_label(token: str) -> str | None:
    """The account a token was sealed for, or None if it is not ours."""
    from stocks import session

    payload = session.unseal(UNSUBSCRIBE, token or "", UNSUBSCRIBE_MAX_AGE)
    if not payload or payload.get("j") != JOB:
        return None
    label = payload.get("s")
    return label if isinstance(label, str) and label else None


def unsubscribe_url(label: str, base_url: str | None) -> str | None:
    token = unsubscribe_token(label)
    if not token:
        return None
    return links.page_url("email/unsubscribe", base_url, t=token)


# ------------------------------------------------------------------ text


def subject(view: _View) -> str:
    return view.tr("subject", change=view.delta(*view.week),
                   value=view.money(view.total))


def preheader(view: _View) -> str:
    d = view.data
    parts = []
    lead = d.since_days if d.since_days in d.benchmark else WEEK
    index = d.benchmark.get(lead)
    if index is not None:
        parts.append(view.tr("preheader_index", index=BENCHMARK_LABEL,
                             period=view.tr(_label(d, lead)).lower(),
                             pct=view.pct(index)))
    if d.earnings:
        parts.append(view.tr("preheader_earnings", n=len(d.earnings)))
    return " · ".join(parts)


def _label(d: WeeklyData, days: int) -> str:
    if days == d.since_days:
        return "row_since"
    return {WEEK: "row_week", MONTH: "row_month"}.get(days, "row_ytd")


def _rows(d: WeeklyData) -> list[tuple[int, tuple[float, float]]]:
    """(days, (gain, pct)) for since start, week, month and YTD — the book's
    whole span first (CLAUDE.md: a later window forgives what came before)."""
    rows = []
    if d.since_days and d.since is not None:
        rows.append((d.since_days, d.since))
    for days, value in ((WEEK, d.week), (MONTH, d.month), (d.ytd_days, d.ytd)):
        if value is not None and days != d.since_days and days > 0:
            rows.append((days, value))
    return rows


def _row_name(view: _View, days: int) -> str:
    d = view.data
    name = view.tr(_label(d, days))
    if days == d.since_days and d.start:
        name += f" ({date_line(d.start, view.lang)} {d.start.year})"
    return name


def _ahead(view: _View) -> list[tuple[int, str]]:
    d = view.data
    out = []
    for e in d.earnings:
        if e.date is not None:
            out.append((e.days_until or 0, view.tr(
                "ahead_earnings", ticker=e.ticker, date=date_line(e.date, view.lang))))
    for div in d.ex_dividends:
        line = view.tr("ahead_ex", ticker=div.ticker,
                       date=date_line(div.ex_date, view.lang))
        if cash := d.dividend_cash.get(div.ticker):
            line += " · " + view.tr("ahead_cash", amount=view.money(cash))
        out.append((div.days_until, line))
    return sorted(out, key=lambda e: e[0])


def _as_of(view: _View) -> str:
    d = view.data
    return view.tr("as_of", date=date_line(d.as_of or d.date, view.lang))


def _unpriced_note(view: _View) -> bool:
    """The footer names what is held at cost unless the setup section above
    already does: one disclosure, never the same list twice."""
    return bool(view.data.missing) and not any(g.key == "unpriced" for g in view.gaps)


def render_text(view: _View) -> str:
    """The plain-text part: the same sections, the same order."""
    d, tr, ccy = view.data, view.tr, view.data.currency
    out = [tr("heading"), "",
           f"{tr('value')}: {view.money(view.total)}",
           f"{tr('week')}: {view.delta(*view.week)}"]
    if round(view.activity.net):
        out.append(_net_line(view))
    rows = _rows(d)
    if rows:
        out += ["", tr("returns_title", index=BENCHMARK_LABEL)]
        for days, (gain, pct) in rows:
            line = f"- {_row_name(view, days)}: {view.delta(gain, pct)}"
            if (bench := d.benchmark.get(days)) is not None:
                other = view.delta(d.benchmark_gain[days], bench)
                line += f" · {BENCHMARK_LABEL} {other}"
            out.append(line)
        if d.benchmark:
            out.append(tr("returns_note", currency=ccy))
    if d.best or d.worst:
        out += ["", tr("movers_title")]
        for ticker, amount, pct in [*d.best, *d.worst]:
            out.append(f"- {ticker} {view.signed(amount)}"
                       + (f" ({view.pct(pct, 1)})" if pct is not None else ""))
    if view.activity:
        out += ["", tr("activity_title")]
        out += [f"- {k}: {v}" for k, v, _ in _activity_rows(view)]
    if view.fired:
        out += ["", tr("rules_title")]
        out += [f"- {_fired_line(view, f)}" for f in view.fired]
    if ahead := _ahead(view):
        out += ["", tr("ahead_title")] + [f"- {line}" for _, line in ahead]
    if conc := _concentration(view):
        out += ["", tr("conc_title")] + [f"- {line}" for line in conc]
    if view.gaps:
        out += ["", tr("gaps_title")]
        for gap in view.gaps:
            url = view.url(gap.page, **gap.query)
            out.append(f"- {tr('gap_' + gap.key, **gap.args)}")
            if url:
                out.append(f"  {tr('gap_' + gap.key + '_cta')}: {url}")
    out += ["", _as_of(view)]
    if _unpriced_note(view):
        out.append(tr("unpriced_note", names=", ".join(d.missing)))
    out.append(tr("not_advice"))
    if home := view.url(links.PORTFOLIO):
        out.append(f"{tr('open')}: {home}")
    if view.first:
        out.append(tr("first"))
    if view.unsubscribe:
        out.append(f"{tr('unsubscribe')}: {view.unsubscribe}")
    return "\n".join(out) + "\n"


def _net_line(view: _View) -> str:
    net = view.activity.net
    key = "net_bought" if net > 0 else "net_sold"
    return view.tr(key, amount=view.money(abs(net)))


def _activity_rows(view: _View) -> list[tuple[str, str, float | None]]:
    """(label, figure, tone) — tone signs the figure's colour, None is plain."""
    a, tr = view.activity, view.tr
    rows: list[tuple[str, str, float | None]] = []
    if a.buys:
        rows.append((tr("act_buys"), str(a.buys), None))
    if a.sells:
        rows.append((tr("act_sells"), str(a.sells), None))
    if round(a.net):
        rows.append((tr("act_net_bought" if a.net > 0 else "act_net_sold"),
                     view.money(abs(a.net)), None))
    if a.realized is not None:
        rows.append((tr("act_realized"), view.signed(a.realized), a.realized))
    if round(a.dividends):
        rows.append((tr("act_dividends"), view.money(a.dividends), None))
    if round(a.fees):
        rows.append((tr("act_fees"), view.money(abs(a.fees)), None))
    return rows


def _fired_line(view: _View, f: Fired) -> str:
    return view.tr("rules_line", ticker=f.ticker, rule=_rule_text(f, view.lang),
                   date=date_line(f.day, view.lang))


def _concentration(view: _View) -> list[str]:
    d, tr = view.data, view.tr
    out = []
    if d.top_weight is not None:
        out.append(tr("conc_top", n=TOP_N, pct=view.pct(d.top_weight, 0, sign=False)))
    if d.largest:
        out.append(tr("conc_largest", ticker=d.largest[0],
                      pct=view.pct(d.largest[1], 1, sign=False)))
    if d.effective_names is not None and d.effective_names == d.effective_names:
        out.append(tr("conc_effective", n=fmt_num(d.effective_names, 1, view.lang)))
    return out


# ------------------------------------------------------------------ html


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _tone(value: float | None) -> str:
    if value is None or not round(value, 6):
        return ""
    return "up" if value > 0 else "down"


def _fig(text: str, value: float | None) -> str:
    tone = _tone(value)
    if not tone:
        return _e(text)
    return f'<span class="{tone}" style="color:{LIGHT[tone]}">{_e(text)}</span>'


def _ticker(view: _View, ticker: str) -> str:
    url = links.ticker_url(ticker, view.base_url)
    if not url:
        return f"<b>{_e(ticker)}</b>"
    return (f'<a href="{_e(url)}" class="text" style="color:{LIGHT["text"]};'
            f'font-weight:600;text-decoration:none">{_e(ticker)}</a>')


def _section(title: str, body: str) -> str:
    return (
        '<tr><td class="card" style="padding:20px 24px 4px;background:'
        f'{LIGHT["card"]}"><h2 class="text" style="margin:0 0 10px;font-size:15px;'
        f'font-weight:600;color:{LIGHT["text"]}">{_e(title)}</h2>{body}</td></tr>'
    )


def _table(rows: list[list[str]], head: list[str] | None = None) -> str:
    """A rule-separated table; the first column left, the rest right."""
    cell = (f'padding:7px 0;border-top:1px solid {LIGHT["rule"]};font-size:14px;'
            'font-variant-numeric:tabular-nums')
    out = ['<table role="presentation" width="100%" cellpadding="0" '
           'cellspacing="0" style="border-collapse:collapse;margin-bottom:12px">']
    if head:
        out.append("<tr>" + "".join(
            f'<th class="muted" align="{"left" if i == 0 else "right"}" '
            f'style="padding:0 0 6px;font-size:12px;font-weight:500;'
            f'color:{LIGHT["muted"]}">{_e(h)}</th>'
            for i, h in enumerate(head)) + "</tr>")
    for row in rows:
        out.append("<tr>" + "".join(
            f'<td class="rule" align="{"left" if i == 0 else "right"}" '
            f'style="{cell}{";padding-left:12px" if i else ""}">{c}</td>'
            for i, c in enumerate(row)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _button(label: str, url: str) -> str:
    return (
        f'<a href="{_e(url)}" class="cta" style="display:inline-block;'
        f'background:{LIGHT["cta"]};color:{LIGHT["on_cta"]};padding:11px 20px;'
        'border-radius:8px;font-size:14px;font-weight:600;text-decoration:none">'
        f"{_e(label)}</a>"
    )


def _hero(view: _View) -> str:
    change, pct = view.week
    note = (f'<p class="muted" style="margin:10px 0 0;font-size:13px;color:'
            f'{LIGHT["muted"]}">{_e(_net_line(view))}</p>'
            if round(view.activity.net) else "")
    return (
        f'<tr><td class="card" style="padding:28px 24px 20px;background:{LIGHT["card"]}">'
        f'<p class="muted" style="margin:0;font-size:13px;color:{LIGHT["muted"]}">'
        f'{_e(view.tr("value"))}</p>'
        f'<p class="text" style="margin:2px 0 0;font-size:30px;font-weight:700;'
        f'color:{LIGHT["text"]};font-variant-numeric:tabular-nums">'
        f'{_e(view.money(view.total))}</p>'
        f'<p style="margin:6px 0 0;font-size:16px;font-weight:600">'
        f'<span class="muted" style="color:{LIGHT["muted"]};font-weight:500">'
        f'{_e(view.tr("week"))}</span> '
        f'{_fig(view.delta(change, pct), change)}</p>{note}</td></tr>'
    )


def _returns(view: _View) -> str:
    d, ccy = view.data, view.data.currency
    rows = []
    for days, (gain, pct) in _rows(d):
        bench = d.benchmark.get(days)
        if bench is None:
            index, diff = "—", "—"
        else:
            other = d.benchmark_gain[days]
            index = _fig(view.delta(other, bench), other)
            diff = _fig(view.signed(gain - other), gain - other)
        rows.append([_e(_row_name(view, days)), _fig(view.delta(gain, pct), gain),
                     index, diff])
    if not rows:
        return ""
    body = _table(rows, [view.tr("col_period"), view.tr("col_you"),
                         BENCHMARK_LABEL, view.tr("col_diff")])
    if d.benchmark:
        body += _note(view.tr("returns_note", currency=ccy))
    return _section(view.tr("returns_title", index=BENCHMARK_LABEL), body)


def _note(text: str) -> str:
    return (f'<p class="muted" style="margin:0 0 14px;font-size:12px;'
            f'color:{LIGHT["muted"]}">{_e(text)}</p>')


def _movers(view: _View) -> str:
    d = view.data
    rows = [
        [_ticker(view, t), _fig(view.signed(amount), amount),
         _fig(view.pct(pct, 1), pct) if pct is not None else "—"]
        for t, amount, pct in [*d.best, *d.worst]
    ]
    if not rows:
        return ""
    return _section(view.tr("movers_title"), _table(
        rows, ["", view.tr("col_effect"), view.tr("col_price")]))


def _activity(view: _View) -> str:
    if not view.activity:
        return ""
    rows = [[_e(k), _fig(v, tone)] for k, v, tone in _activity_rows(view)]
    return _section(view.tr("activity_title"), _table(rows))


def _rules(view: _View) -> str:
    if not view.fired:
        return ""
    rows = [[_ticker(view, f.ticker),
             _e(_rule_text(f, view.lang)) + " · " + _e(date_line(f.day, view.lang))]
            for f in view.fired]
    return _section(view.tr("rules_title"), _table(rows))


def _ahead_html(view: _View) -> str:
    ahead = _ahead(view)
    if not ahead:
        return ""
    return _section(view.tr("ahead_title"), _table([[_e(line)] for _, line in ahead]))


def _concentration_html(view: _View) -> str:
    lines = _concentration(view)
    if not lines:
        return ""
    return _section(view.tr("conc_title"), _table([[_e(line)] for line in lines]))


def _gaps(view: _View) -> str:
    if not view.gaps:
        return ""
    rows = []
    for gap in view.gaps:
        url = view.url(gap.page, **gap.query)
        cta = view.tr(f"gap_{gap.key}_cta")
        link = (f'<a href="{_e(url)}" class="link" style="color:{LIGHT["cta"]};'
                f'font-weight:600;text-decoration:none;white-space:nowrap">'
                f"{_e(cta)} ›</a>" if url else "")
        rows.append([_e(view.tr(f"gap_{gap.key}", **gap.args)), link])
    return _section(view.tr("gaps_title"), _table(rows))


def _footer(view: _View) -> str:
    d, tr = view.data, view.tr
    lines = [_as_of(view)]
    if _unpriced_note(view):
        lines.append(tr("unpriced_note", names=", ".join(d.missing)))
    lines.append(tr("not_advice"))
    if view.first:
        lines.append(tr("first"))
    text = "".join(
        f'<p class="muted" style="margin:0 0 6px;font-size:12px;color:'
        f'{LIGHT["muted"]}">{_e(line)}</p>' for line in lines)
    links_row = []
    if settings := view.url("profile", tab="notify"):
        links_row.append(f'<a href="{_e(settings)}" class="muted" style="color:'
                         f'{LIGHT["muted"]}">{_e(tr("settings"))}</a>')
    if view.unsubscribe:
        links_row.append(f'<a href="{_e(view.unsubscribe)}" class="muted" style="'
                         f'color:{LIGHT["muted"]}">{_e(tr("unsubscribe"))}</a>')
    button = ""
    if home := view.url(links.PORTFOLIO):
        button = f'<p style="margin:4px 0 18px">{_button(tr("open"), home)}</p>'
    return (
        f'<tr><td class="card" style="padding:20px 24px 24px;background:{LIGHT["card"]}">'
        f"{button}{text}"
        + (f'<p style="margin:10px 0 0;font-size:12px">{" · ".join(links_row)}</p>'
           if links_row else "")
        + "</td></tr>"
    )


_DARK_CSS = (
    ":root{color-scheme:light dark;supported-color-schemes:light dark}"
    "@media (prefers-color-scheme:dark){"
    f".page{{background:{DARK['page']}!important}}"
    f".card{{background:{DARK['card']}!important}}"
    f".text{{color:{DARK['text']}!important}}"
    f".muted{{color:{DARK['muted']}!important}}"
    f".rule{{border-color:{DARK['rule']}!important}}"
    f".up{{color:{DARK['up']}!important}}"
    f".down{{color:{DARK['down']}!important}}"
    "}"
)


def render_html(view: _View, preheader_text: str = "") -> str:
    d = view.data
    title = view.tr("heading")
    week_of = view.tr("week_of", date=date_line(d.as_of or d.date, view.lang))
    sections = "".join([
        _hero(view), _returns(view), _movers(view), _activity(view),
        _rules(view), _ahead_html(view), _concentration_html(view), _gaps(view),
        _footer(view),
    ])
    hidden = (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{_e(preheader_text)}{'&#8199;&#65279;&#847; ' * 30}</div>"
        if preheader_text else ""
    )
    return (
        f'<!doctype html><html lang="{_e(view.lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        f"<title>{_e(title)}</title><style>{_DARK_CSS}</style></head>"
        f'<body class="page" style="margin:0;padding:0;background:{LIGHT["page"]};'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
        f'Arial,sans-serif;color:{LIGHT["text"]}">{hidden}'
        f'<table role="presentation" class="page" width="100%" cellpadding="0" '
        f'cellspacing="0" style="background:{LIGHT["page"]}"><tr>'
        '<td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;border-radius:12px;overflow:hidden">'
        f'<tr><td class="page" style="padding:0 4px 12px;background:{LIGHT["page"]}">'
        f'<p class="muted" style="margin:0;font-size:13px;color:{LIGHT["muted"]}">'
        f"TopStocks · {_e(week_of)}</p>"
        f'<h1 class="text" style="margin:4px 0 0;font-size:20px;color:{LIGHT["text"]}">'
        f"{_e(title)}</h1></td></tr>"
        f"{sections}</table></td></tr></table></body></html>"
    )


# ------------------------------------------------------------------ send


def compose(label: str, paths, prefs: dict, day: date, *,
            base_url: str | None = None) -> Email | str:
    """One account's email, or why there is none ("no book")."""
    view = gather(label, paths, prefs, day, base_url)
    if isinstance(view, str):
        return view
    pre = preheader(view)
    return Email(
        subject=subject(view), preheader=pre, html=render_html(view, pre),
        text=render_text(view), to=str(prefs.get("email") or ""),
        unsubscribe=view.unsubscribe,
    )


def send_for(label: str, paths, prefs: dict, day: date, *, to: str | None = None,
             base_url: str | None = None) -> str:
    """Compose and send one account's Friday email; the run's status.

    `to` sends a one-off copy elsewhere (`stocks weekly-email --to`) without an
    idempotency key, so a second test goes out too. A recipient Resend refuses
    as undeliverable switches the email off — mailing it weekly would only
    hurt the sender's standing for everyone else."""
    if not mail.configured():
        return "skipped: email not configured"
    if not (to or prefs.get(PREF, True)):
        return "skipped: off"
    email = compose(label, paths, prefs, day, base_url=base_url)
    if isinstance(email, str):
        return f"skipped: {email}"
    recipient = to or email.to
    if not recipient:
        return "skipped: no address"
    sent = mail.send(
        recipient, email.subject, email.html, email.text,
        unsubscribe=email.unsubscribe,
        idempotency_key=None if to else f"{JOB}-{label}-{day.isoformat()}",
    )
    if sent.undeliverable and not to:
        from stocks import accounts

        accounts.update_prefs(paths.prefs, {PREF: False})
        obs.warn("email.disabled", reason="undeliverable", status=sent.status)
    return f"sent {sent.id}" if sent.ok else f"not sent: {sent.status or sent.error}"
