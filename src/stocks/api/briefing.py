"""Writing the daily card over HTTP: the facts, the job, and what a poll sees.

`web/daily_ui.py` is the Streamlit half of this: it builds the facts from the
frames Home already loaded, starts `chat.daily.generate` in a thread, waits
`GRACE_S` for it, and otherwise paints the computed card with a line saying a
briefing is still being written while a timed fragment polls for the answer.
The React Home has none of those frames and no script run to hang a thread off,
so this module is the same machine rebuilt around requests:

* `POST /daily` asks for today's card. A stored one that still stands comes
  straight back and spends nothing. Otherwise the facts are built from this
  API's own loaders, one generation starts, and the request waits `GRACE_S` —
  a provider that answers inside it lands in the response; a slower one leaves
  a *job* behind and the response says `pending`, carrying the computed card so
  the section is never empty.
* `GET /daily` is what the client polls. It never starts anything (a GET that
  could spend the allowance is a GET a prefetch could empty), but it does see
  the job: pending while the thread runs, and — when the model gave nothing
  back — the computed card the job was holding, so a failed generation does
  not quietly hand the reader yesterday's briefing.

The job applies its own side effects when it finishes, on its own thread: the
spent free unit goes to prefs.json and the card to daily_action.json. In
Streamlit that is `_collect()` on the script thread, because a session owns its
files and its toasts; here nothing owns the request after it has answered, and
a card that was paid for must be stored whether or not anybody polls for it.

Attempted at most once per account per key (action day, language, session):
a provider that is down stays down for the next few seconds, and a client that
re-POSTs on every mount would otherwise spend the allowance on the same
failure. "Regenerate" is the explicit way past that guard, and it abandons a
job already in flight rather than waiting on it — the unit that job spent is
lost, which is the cheaper of the two prices, exactly as in `daily_ui`.

Process-local, like every cache in this API. A second container knows nothing
of a job the first one started; the worst that costs is one more generation,
and the stored card makes even that rare.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from stocks import accounts, obs
from stocks.analysis.portfolio import basket_change, us_market_open
from stocks.api import home, loaders
from stocks.api.cache import ttl_cache
from stocks.api.deps import reporting_currency
from stocks.chat import daily, engine, signals
from stocks.data.crypto import is_crypto

# How long `POST /daily` holds the request for a briefing before answering
# `pending`. The same number the Streamlit card waits: the free chain usually
# answers well inside it, and everything past it is a spinner on a card the
# reader could already be reading the computed version of.
GRACE_S = 2.5

# What the client is told to wait between polls. Reported, not enforced: the
# poll is a GET of a small JSON read.
POLL_S = 1.5


@dataclass
class Job:
    """One generation in flight (or just finished) for one account."""

    key: tuple
    forced: bool
    computed: daily.DailyAction | None
    started: float = field(default_factory=time.time)
    done: bool = False
    action: daily.DailyAction | None = None
    # Set by a Regenerate that overtook this job: it may finish, but it must
    # not store a card the reader already asked to replace.
    abandoned: bool = False


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def job_for(paths, key: tuple) -> Job | None:
    """The account's job for `key`, or None — a job for another key is stale."""
    with _lock:
        job = _jobs.get(str(paths.root))
    return job if job is not None and job.key == key else None


def key_for(day: date, lang: str, session: str | None) -> tuple:
    """What a card and its one generation attempt are keyed on.

    The session is in it for the reason `daily.is_fresh` gives: a card written
    before the open quotes the previous close, and when the next session lands
    that card is stale hours before the 09:00 rollover. Rekeying retires the
    "already tried" guard with it.
    """
    return (day.isoformat(), lang, session or "")


# ------------------------------------------------------------------- facts


@ttl_cache(900.0, max_entries=1)
def _card_closes() -> dict[str, pd.Series]:
    """The market symbols the card reads — `web.market_data.card_closes`.

    The Streamlit loader is an `st.cache_data`; this is the same one request,
    shared by every account in the process, behind this API's own memo.
    """
    from stocks.analysis.portfolio import load_closes
    from stocks.web.market_data import CARD_PERIOD, CARD_TICKERS

    return load_closes(list(CARD_TICKERS), period=CARD_PERIOD)


@ttl_cache(86400.0, max_entries=32)
def _meta(tickers: tuple[str, ...]) -> dict[str, dict]:
    """Sector / country / currency per ticker. These four fields do not move."""
    from stocks.analysis.portfolio import load_meta

    return load_meta(list(tickers))


def _market(tbl, hist, currency: str) -> list:
    """The market-wide candidates, or none of them — `daily_ui._market`.

    The one part of the card with a download of its own, and the only part
    that can be slow or fail on its own: a card that says nothing about the
    index is the card this was before, so any failure is an empty list.
    """
    from stocks.analysis.portfolio import allocation
    from stocks.web.market_data import index_month_base

    try:
        closes = _card_closes()
        weights = tbl["weight"].dropna() if tbl is not None and "weight" in tbl else None
        sectors = pd.Series(dtype=float)
        if weights is not None and len(weights):
            names = tuple(sorted(str(t) for t in weights.index))
            sectors = allocation(
                {str(t): float(w) for t, w in weights.items()}, _meta(names), "sector"
            )
        ccy = None
        if tbl is not None and not tbl.empty and {"ccy", "weight"} <= set(tbl.columns):
            ccy = tbl.groupby("ccy")["weight"].sum()
        month = basket_change(hist, 30) if hist is not None and not hist.empty else None
        return signals.market_candidates(
            closes,
            book_sectors=sectors,
            bench_sectors=loaders.benchmark_sectors(),
            currency_weights=ccy,
            book_month_pct=None if not month else month[1] * 100,
            bench_month_pct=index_month_base(closes, currency) * 100,
            currency=currency,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        obs.warn(
            "daily_action.market_unavailable",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return []


def _jurisdiction(prefs: dict):
    """The account's tax jurisdiction, or None — only the harvest line reads it."""
    try:
        from stocks.portfolio import tax
        from stocks.portfolio.tax import prefs as tax_prefs

        return tax.get(tax_prefs.resolve(prefs)[0])
    except Exception:  # noqa: BLE001 — a calendar-year figure beats no card
        return None


def _day_move(tbl, hist) -> tuple[float, float] | None:
    """The "Today" figure the KPI row shows, so the card cannot contradict it.

    `home.py`'s rule: in a regular US session the basket's close-to-close day;
    outside one, the per-row day (already re-read from the quote burst) summed
    against the value it moved from.
    """
    if tbl is None or tbl.empty:
        return None
    if not us_market_open():
        moved = float(tbl["day"].dropna().sum())
        value = float(tbl["value"].dropna().sum())
        start = value - moved
        return moved, (moved / start if start else 0.0)
    return basket_change(hist, 1) if hist is not None and not hist.empty else None


def build_facts(paths, prefs: dict, day: date, stored) -> dict | None:
    """What today's card is written from, or None when there is nothing to say.

    Everything `daily_ui.render` is handed by the page — positions, the basket
    history, the "Today" figure, the earnings pass, the 52-week scan, the
    watchlist's alerts and the realised sales — read here off the same loaders
    the other Home routes use, so the briefing is written from the numbers on
    the screen beside it and the downloads are the ones those routes already
    paid for. Each input degrades alone: a throttled calendar is a card with no
    earnings line, not a card that is not there.

    None for an account with neither a position nor a watchlist entry, which is
    the one case the Streamlit page clears the slot for.
    """
    db = str(paths.db)
    mtime = loaders.db_mtime(db)
    ccy = reporting_currency(paths)
    positions, realized = [], []
    try:
        _, positions, realized = loaders.ledger_state(db, mtime, ccy)
    except Exception as exc:  # noqa: BLE001 — a watchlist-only card still stands
        obs.warn("daily_action.ledger_unavailable", error_type=type(exc).__name__)
    entries = home.holdings(paths)
    if not (positions or entries):
        return None

    tbl = hist = None
    if positions:
        try:
            tbl = home.enriched(db, mtime, ccy)
            hist = loaders.basket_values(db, mtime, ccy).dropna(how="all")
        except Exception as exc:  # noqa: BLE001 — alerts and 52w still work
            obs.warn("daily_action.prices_unavailable", error_type=type(exc).__name__)
            tbl = hist = None

    owned = {p.ticker for p in positions}
    tags = {h.ticker for h in entries if h.tags}
    favourites = {h.ticker for h in entries if h.favorite}
    earn = tuple(
        sorted(t for t in owned | favourites | tags if not is_crypto(t) and not _fund(t))
    )
    events = []
    try:
        events = list(loaders.earnings_calendar(earn)[0]) if earn else []
    except Exception:  # noqa: BLE001
        events = []

    extremes: list = []
    closes: dict[str, list[float]] = {}
    try:
        year = home.year_closes(home.closes_tuple(entries, owned))
        extremes = home.scan_extremes(home.extremes_scope(entries, owned), year)
        closes = {t: c[-2:] for t, c in year.items()}
    except Exception:  # noqa: BLE001
        pass

    return daily.build_facts(
        tbl,
        hist,
        currency=ccy,
        day=_day_move(tbl, hist),
        earnings=events,
        extremes=extremes,
        signals=signals.candidates(
            holdings=entries,
            tbl=tbl,
            closes=closes,
            realized=realized,
            earnings=events,
            extremes=extremes,
            market=_market(tbl, hist, ccy),
            shown=stored.shown if stored else None,
            jurisdiction=_jurisdiction(prefs),
            currency=ccy,
            today=day,
        ),
    )


def _fund(ticker: str) -> bool:
    """Cache-only fund check — funds do not report earnings."""
    from stocks.data.funds import is_fund

    try:
        return bool(is_fund(ticker, fetch=False))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------- job


def _store(paths, job: Job, prefs: dict, facts: dict, stored, spent: bool) -> None:
    """Apply a finished generation's side effects — `daily_ui._collect`.

    The free counter is merged into prefs.json rather than the whole dict
    written back: the prefs were read when the job started, up to half a minute
    ago, and a settings change made in that window must not be undone by a
    card. Only a model's card is stored — a computed one is free to rebuild,
    and storing it would block the upgrade to a real briefing once the
    allowance resets.
    """
    from stocks.web import auth

    if spent:
        counters = {k: v for k, v in prefs.items() if k.startswith("free_msgs::")}
        try:
            accounts.update_prefs(paths.prefs, counters)
        except Exception as exc:  # noqa: BLE001 — a lost count, not a lost card
            obs.warn("daily_action.prefs_unsaved", error_type=type(exc).__name__)
    action = job.action
    if action is None or job.abandoned:
        return
    card = action.to_dict()
    card["recent"] = daily.remembered(stored, action.headline)
    # The triggers this card was offered, stamped today: tomorrow's candidates
    # are ranked against it so the card turns over even when the book does not.
    card["shown"] = daily.seen(stored, facts, date.fromisoformat(action.day))
    try:
        auth.save_action(card, paths.action)
    except Exception as exc:  # noqa: BLE001 — the reader still gets the card
        obs.warn("daily_action.unsaved", error_type=type(exc).__name__)


def start(
    paths,
    prefs: dict,
    facts: dict,
    lang: str,
    day: date,
    stored,
    *,
    key: tuple,
    forced: bool,
) -> Job:
    """Start one generation in a background thread, and wait GRACE_S for it.

    Returns the job either way; `done` says which of the two it is. A job this
    call overtakes (Regenerate while the automatic one is still out) is marked
    abandoned so it cannot store over the reader's fresh request.
    """
    from stocks.web import auth

    job = Job(
        key=key,
        forced=forced,
        computed=None if forced else daily.computed(facts, lang, day),
    )
    with _lock:
        previous = _jobs.get(str(paths.root))
        if previous is not None and not previous.done:
            previous.abandoned = True
        _jobs[str(paths.root)] = job

    profile = auth.load_profile(prefs)
    spent = False

    def spend(p: dict) -> bool:
        nonlocal spent
        ok = engine.spend_free_quota(p)
        spent = spent or ok
        return ok

    def work() -> None:
        try:
            job.action = daily.generate(
                prefs,
                profile,
                facts,
                lang,
                day,
                recent=stored.recent if stored else [],
                spend_free=spend,
            )
        except Exception as exc:  # noqa: BLE001 — generate swallows its own; a
            # thread that died silently would leave the client polling forever.
            obs.warn(
                "daily_action.generate_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
        finally:
            try:
                _store(paths, job, prefs, facts, stored, spent)
            finally:
                # Last, so a poll that sees `done` also sees the stored file.
                if job.computed is None and job.action is None:
                    # A forced job that got nothing still owes the reader a
                    # card: the computed one, built now rather than up front
                    # so a Regenerate shows its wait line and not a stand-in.
                    job.computed = daily.computed(facts, lang, day)
                job.done = True

    thread = threading.Thread(target=work, name="daily-action", daemon=True)
    thread.start()
    thread.join(GRACE_S)
    return job


def now_day() -> tuple[datetime, date]:
    """The server's local now and the action day it falls in.

    The server's zone stands in for the reader's, as `GET /daily` has always
    done: the deploy runs in the zone its readers are in, and the card's
    freshness is judged on the day it was stamped with, not on a clock.
    """
    now = datetime.now().astimezone()
    return now, daily.action_day(now)
