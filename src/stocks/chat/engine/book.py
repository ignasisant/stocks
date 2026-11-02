"""The portfolio as the system prompt reads it: holdings, sector exposure
and the tax rules that apply to the account.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from stocks import obs
from stocks.chat import clock
from stocks.config import currency_symbol

if TYPE_CHECKING:
    import pandas as pd



def _fmt_money(x, currency: str = "EUR") -> str:
    sym = currency_symbol(currency)
    # x == x screens NaN
    return f"{sym}{x:,.0f}" if x is not None and x == x else "n/a"


def _known(x) -> bool:
    """A figure that can be printed: neither None nor NaN."""
    return x is not None and x == x


def _day_move(pct: float, as_of, basis) -> str:
    """A position's day move as the snapshot words it: the session's date,
    and the extended-hours print when that is what it runs to. Bare "today"
    was how the chat read ServiceNow's pre-report session as the reaction to
    a report that had it 18 % lower after the bell."""
    day = clock.session(as_of)
    if basis == "pre":
        return f"premarket{day} {pct:+.1%}"
    if basis == "post":
        return f"session{day} incl. after-hours {pct:+.1%}"
    return f"session{day} {pct:+.1%}"


def book_snapshot(
    tbl: pd.DataFrame | None, watchlist: Path, currency: str = "EUR"
) -> str:
    """The system prompt's snapshot of the user's real book.

    `tbl` is the live-priced positions frame (web: cached enriched_positions;
    headless: enriched_frame) or None — then the watchlist's positions
    (shares/cost only) are the fallback. Watchlist-but-not-held names are
    appended either way.
    """
    from stocks.analysis.portfolio import priced_totals
    from stocks.config import load_watchlist
    from stocks.config import positions as load_positions

    if tbl is not None and not tbl.empty:
        lines = []
        for tk, r in tbl.iterrows():
            pnl_pct, day_pct, wt = r.get("pnl_pct"), r.get("day_pct"), r.get("weight")
            # A book with no price at all comes back as None, not NaN.
            lines.append(
                f"- {tk}: {r['shares']:g} sh"
                f" | value {_fmt_money(r['value'], currency)}"
                f" | cost {_fmt_money(r['cost'], currency)}"
                + (f" | P/L {pnl_pct:+.1%} ({_fmt_money(r['pnl'], currency)})"
                   if _known(pnl_pct) else "")
                + (f" | weight {wt:.0%}" if _known(wt) else "")
                + (f" | {_day_move(day_pct, r.get('day_asof'), r.get('day_basis'))}"
                   if _known(day_pct) else "")
            )
        _cost, total, unpriced = priced_totals(tbl)
        total_pnl = tbl["pnl"].dropna().sum()
        book = (
            f"Holdings (live market data, {currency}). Total book "
            f"{_fmt_money(total, currency)}, unrealised P/L "
            f"{_fmt_money(total_pnl, currency)}"
            # Otherwise the model reads a partly priced book as a shrunken one
            # and answers "you are down" about a download, not a market.
            + (f" — {unpriced} of {len(tbl)} positions have no live price and"
               " are excluded from both totals" if unpriced else "")
            + ". Each day move is dated with the session it belongs to: a "
            "date before today is the last completed session, not today"
            + ":\n" + "\n".join(lines)
            + sector_exposure(tbl)
        )
        held = set(tbl.index)
    else:
        holds = load_positions(watchlist)
        book = (
            "Positions (from watchlist; no live valuation):\n"
            + "\n".join(
                f"- {h.ticker}: {h.shares:g} shares"
                + (f" @ {h.cost:g} avg cost" if h.cost else "")
                for h in holds
            )
            if holds
            else "(no open positions)"
        )
        held = {h.ticker for h in holds}

    watching = [
        h.ticker for h in load_watchlist(watchlist) if h.ticker not in held
    ]
    if watching:
        book += "\n\nAlso on the watchlist (not held): " + ", ".join(watching)
    return book


def held_in(book: str) -> set[str]:
    """The tickers `book_snapshot` lists as positions."""
    return set(re.findall(r"^- ([^:\s]+): ", book, re.MULTILINE))


def enriched_frame(db: Path, base: str = "EUR") -> pd.DataFrame | None:
    """The frame the Home page is written from (`api.home.enriched`): value,
    cost, P/L, weight and day move per position, off the book's one shared
    download. The assistant used to price the book itself — its own fetch at
    spot — and could tell the reader a total the Portfolio tile did not show.
    None when there is no ledger, no open position, or Yahoo is refusing (the
    assistant answers from the rest of its context rather than failing)."""
    from stocks.api import home, loaders

    try:
        tbl = home.enriched(str(db), loaders.db_mtime(str(db)), base)
    except Exception as exc:
        obs.warn("chat.positions_unavailable",
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return None
    return None if tbl.empty else tbl


def reporting_currency(prefs: dict | None) -> str:
    """The account's reporting currency from its prefs, EUR when unset."""
    return str((prefs or {}).get("currency") or "EUR").upper()


def portfolio_context(watchlist: Path, db: Path, currency: str = "EUR") -> str:
    """The book snapshot for the system prompt, from explicit paths."""
    tbl = enriched_frame(db, currency) if db.exists() else None
    return book_snapshot(tbl, watchlist, currency)


def sector_exposure(tbl: pd.DataFrame | None) -> str:
    """The snapshot's sector line: the book by sector, funds looked through,
    as a share of the whole book and of its equity part.

    Both, because they answer different questions and the model was guessing
    at both — it told a reader whose Home card said "technology is 51% of your
    equity" that tech was about 30% of their book. "How much of my money is
    tech" is the first share; the second is the one the Home card compares
    with the index, and it reads larger on a book that is part crypto or
    unclassified. Empty when the split cannot be read: the snapshot stands
    without it.
    """
    from stocks.api import briefing
    from stocks.chat.signals import NOT_EQUITY

    try:
        sectors = briefing.book_sectors(tbl)
    except Exception as exc:  # noqa: BLE001 — a metadata lookup, best-effort
        obs.warn("chat.sectors_unavailable",
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return ""
    sectors = sectors[sectors > 0].sort_values(ascending=False)
    total = float(sectors.sum())
    if sectors.empty or not total:
        return ""
    equity = sectors.drop(labels=list(NOT_EQUITY), errors="ignore")
    outside = sectors[sectors.index.isin(NOT_EQUITY)]
    covered = float(equity.sum())
    parts = [f"{name} {w / total:.1%} / {w / covered:.1%}" for name, w in equity.items()]
    line = ("\n\nSector exposure, funds looked through (share of the whole "
            "book / of its equity part): " + (", ".join(parts) or "none"))
    if not outside.empty:
        line += "; outside any equity sector: " + ", ".join(
            f"{name} {w / total:.1%}" for name, w in outside.items())
    return line + "."


_MATCHING_EN = {
    "fifo": "first in, first out (the oldest shares are sold first)",
    "lifo": "last in, first out (the newest shares are sold first)",
    "average": "at the average cost of every share held",
    "s104": ("by the share-identification rules: same day, then the next 30 "
             "days, then the section 104 pool at average cost"),
}
_WINDOW_UNIT_EN = {"d": "days", "m": "months"}


def tax_rules(prefs: dict, today: date | None = None) -> str:
    """The tax rules the app applies to this account, for the system prompt.

    Without them the model recites a tax system from memory, and did: a
    Spanish filer was told gains are taxed at 19–26% "if you sell after more
    than a year" and that there is no repurchase rule — three errors in one
    sentence, about rules the Tax tab applies correctly. Written from the
    Jurisdiction the replay itself uses, so the prose and the engine cannot
    disagree. Rules only, no figures: a figure needs a replay of the ledger,
    which the what-if runs when a sale is actually asked about
    (`chat/whatif.py`).
    """
    import calendar

    from stocks.portfolio import tax
    from stocks.portfolio.tax import es
    from stocks.portfolio.tax import prefs as tax_prefs

    code, _how = tax_prefs.resolve(prefs or {})
    jur = tax.get(code)
    day = today or date.today()
    month, first = jur.year_start
    year = (
        "the calendar year" if (month, first) == (1, 1)
        else f"a year opening on {first} {calendar.month_name[month]}"
    )
    lines = [
        jur.summary,
        f"Tax year: {year}; the current one is "
        f"{jur.year_label(jur.tax_year_of(day.isoformat()))}.",
        f"Sales are matched to lots {_MATCHING_EN.get(jur.matching, jur.matching)}.",
        "Short- and long-term gains are taxed differently: the holding period "
        "matters." if jur.splits_holding_period
        else "A gain is taxed the same whatever the holding period.",
    ]
    if jur.code == es.CODE:
        scale = "; ".join(
            f"{rate:.0%} above" if upper == float("inf")
            else f"{rate:.0%} up to {upper:,.0f}"
            for upper, rate in es.brackets_for(day.year)
        )
        lines.append(f"Savings-base scale ({jur.currency}, marginal): {scale}.")
    window = jur.repurchase_window
    if window[:-1].isdigit() and window[-1] in _WINDOW_UNIT_EN:
        lines.append(
            "A loss is deferred, not deductible that year, when the same "
            f"security is also bought within {window[:-1]} "
            f"{_WINDOW_UNIT_EN[window[-1]]} of the sale."
            + ("" if jur.window_reaches("BTC-EUR") else
               " The rule covers shares and funds, not crypto: a coin sold at "
               "a loss can be bought straight back.")
        )
    if jur.carryforward_years is None:
        lines.append("Net losses carry forward indefinitely.")
    elif jur.carryforward_years:
        lines.append(f"Net losses carry forward {jur.carryforward_years} years.")
    else:
        lines.append("Losses do not carry forward.")
    return (
        "\n\nTax rules the app applies to this account (its own engine, the one "
        "the Tax tab reports from). Use these rather than what you remember, "
        "and call any figure you derive from them an estimate:\n"
        + "\n".join(f"- {line}" for line in lines)
    )
