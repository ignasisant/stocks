"""Market pulse — one screen, read in five seconds, thirty, or three minutes.

The page used to be nine cards of equal weight stacked down a scroll, with the
one thing no other site can give — what the regime does to *this* reader's own
positions — sitting at the bottom of it. This is the same information ranked
by how much of it a reader actually needs:

* **Five seconds.** The hero: the composite score, its band, how long it has
  held that band, and beside it one sentence joining the regime to the book,
  plus the three figures that carry the most of it (equity beta, correlation
  with the long bond, dollar share).
* **Thirty seconds.** Why: the composite's eight inputs with their own
  direction, and the four readings that only exist as a trend.
* **Three minutes.** The detail: the six long tables — indices, gauges, rates,
  inflation, rotation, cross-asset — behind one tab strip, so nothing is lost
  and the scroll is one card instead of six.

**Direction over level.** Almost every row here is the same shape: the level,
the change over four horizons, a sparkline, and where the series sits in its
own trend. That is deliberate. A 10-year yield at 4.79% is a fact; "+33bp over
three months while the curve went nowhere" is the reading, and a smooth drift
and a spike-and-round-trip land on the identical three-month delta, which is
what the sparkline is for. `stocks.analysis.sentiment` owns that arithmetic
and `stocks.web.trend_ui` owns the row.

**Personalisation is the point, not a decoration.** A VIX percentile is the
same number for everyone; "your book is 71% dollar-priced and the dollar fell
1.2% this month" is not. So the hero's right half is the reader's own, the
indices are reordered by the geography they hold and say which of their money
sits there, and the rotation table is joined to their own sector weights.

Every block degrades on its own. Yahoo throttles datacenter IPs (the hosted
deploy hits this routinely) and FRED tarpits some User-Agents, so a failed
fetch keeps its heading, says which source died and offers a retry, instead of
taking the page down.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from datetime import datetime
from urllib.error import URLError

import pandas as pd
import streamlit as st
from yfinance.exceptions import YFRateLimitError

from stocks.analysis import sentiment as sm
from stocks.analysis.portfolio import (
    allocation,
    beta,
    holdings_from_positions,
    load_closes,
    load_meta,
    market_value_weights_base,
    portfolio_returns,
    returns_frame,
)
from stocks.data import macro
from stocks.web import auth, css, market_data, notices, skeletons, spark, trend_ui
from stocks.web.ds import (
    BORDER,
    BORDER_FOCUS,
    BRAND_ACCENT,
    CANDLE_DOWN,
    CANDLE_UP,
    DOWN_COLOR,
    DOWN_FILL,
    FS_2XS,
    FS_LG,
    FS_MD,
    FS_SM,
    FS_XL,
    FS_XS,
    PURPLE_400,
    PURPLE_800,
    PURPLE_900,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    RADIUS_XS,
    SUCCESS_FILL,
    SURFACE_CARD,
    SURFACE_HOVER,
    SURFACE_PAGE,
    TEXT_FAINT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    UP_COLOR,
    WARN_COLOR,
    WARN_EDGE,
    WARN_FILL,
    WARN_FILL_SOFT,
    is_mobile,
)
from stocks.web.i18n import t as tr
from stocks.web.portfolio_data import _window, db_mtime, held_closes, ledger_state
from stocks.web.trend_ui import TrendRow

REPORT_CCY = "EUR"

# Who to name when a block cannot be drawn. A reader who is told "the source is
# down" and not which one cannot tell a Yahoo throttle (wait a minute) from a
# FRED outage (wait a day), and the two are the page's most common failures.
ORIGIN_YAHOO = "Yahoo Finance"
ORIGIN_FRED = "FRED"
ORIGIN_EUROSTAT = "Eurostat"

# The regime meter's gradient stops, straight off the Pulse canvas. The ends
# are the DS market fills; these three are the interpolation steps between
# them — a dimmed amber through the caution band, a neutral grey through the
# wide middle where the honest reading is "no signal", and one green step
# before the solid fill. They exist only here, which is why they are literals
# rather than tokens.
METER_CAUTION = "#8A5A00"
METER_NEUTRAL = "#4E4B57"
METER_APPETITE = "#2A6B12"

# Two years of prices: the trailing-year percentile needs a full year of
# history before it can score anything, and the 200-session trend average
# needs most of another.
HISTORY = "2y"

# Windows quoted across the page, in trading sessions. Named because these
# numbers appear in a dozen places and must mean the same thing in all of them.
DAY, WEEK, MONTH, QUARTER, YEAR = 1, 5, 21, 63, 252
# How much of a series the sparklines draw. A quarter is long enough to show a
# shape and short enough that the current move is not a flat line at the right
# edge of two years.
SPARK_DAYS = 90
# Lookback for "is this rolling statistic drifting?" — one quarter, matching
# the longest horizon in the change columns.
DRIFT_DAYS = QUARTER
# Rolling window for the correlation and beta series. 60 sessions is short
# enough to move inside a regime and long enough not to be noise.
ROLL = 60

st.title(tr("sentiment.title"))

# The change columns, in one place: every block renders the same four, so the
# columns line up down the whole page and the reader learns them once.
HORIZONS = {"week": WEEK, "month": MONTH, "quarter": QUARTER, "year": YEAR}
CHIP_LABELS = [tr(f"sentiment.h_{name}") for name in HORIZONS]
STATE_NAMES = {
    key: tr(f"sentiment.state_{key}")
    for key in ("up", "turning_up", "turning_down", "down", "unknown", "stale")
}


# --------------------------------------------------------------- cached loads
@st.cache_data(ttl=900, show_spinner=False)
def _closes(period: str) -> dict[str, pd.Series]:
    """Close series for every symbol on the page, in ONE bulk request.

    15-minute ttl: this is a page about right now, and one download of ~50
    symbols is the whole price side of it.
    """
    return load_closes(sm.all_tickers(), period=period)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _rates() -> dict[str, pd.Series]:
    """The FRED block: yields, curve slopes, spreads, breakevens, policy rates."""
    return macro.fred_many(list(RATE_ROWS) + ["NFCI"])


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _inflation() -> pd.DataFrame:
    return macro.inflation()


# SPY's sector split — the benchmark the reader's tilt is measured against.
# Shared with the dashboard's daily card rather than cached twice: it is the
# same 24-hour call, and one entry means whichever screen the reader opens
# first pays for it (web/market_data.py).
_benchmark_sectors = market_data.benchmark_sectors


@st.cache_data(ttl=3600, show_spinner=False)
def _book(tickers: tuple[str, ...], db: str, mtime: float):
    """Weights, return frame and the three allocation splits for one ledger.

    `db`/`mtime` are arguments rather than closure reads on purpose: cache
    entries are shared across sessions, and keying on the session's positions
    through a closure would serve one account's book to another whose ticker
    tuple happened to match.
    """
    positions = [
        p for p in ledger_state(db, mtime, REPORT_CCY)[1] if p.ticker in tickers
    ]
    if not positions:
        return None
    holdings = holdings_from_positions(positions)
    held = [h.ticker for h in holdings]
    # The book's shared download (portfolio_data.held_closes) — hot whenever
    # Home ran first — cut to the two years this tab has always read, so the
    # return frame and its beta are the same numbers as before.
    closes = {
        t: s for t, s in _window(held_closes(db, mtime), 24).items()
        if t in set(held) and not s.empty
    }
    prices = {t: float(s.iloc[-1]) for t, s in closes.items() if not s.empty}
    meta = load_meta(held)
    weights = market_value_weights_base(positions, prices, meta, REPORT_CCY)
    return {
        "weights": weights,
        "returns": returns_frame(closes),
        "sector": allocation(weights, meta, "sector"),
        "country": allocation(weights, meta, "country"),
        "currency": allocation(weights, meta, "currency"),
    }


# The rates block, as (FRED id, i18n suffix, whether a rise is the unwelcome
# direction). `up_is_bad` is not decoration: rising yields and widening spreads
# are the unwelcome direction, but a *steepening* curve is the healthy one —
# inversion is the warning there — so colouring every rise red would paint the
# curve rows backwards. Policy rates are neutral: they are a fact about the
# central bank, not a market move.
RATE_ROWS: dict[str, tuple[str, int]] = {
    "DGS10": ("us10y", -1),
    "DFII10": ("us10y_real", -1),
    "T10Y2Y": ("curve_2s10s", +1),
    "T10Y3M": ("curve_3m10y", +1),
    "BAMLH0A0HYM2": ("hy_spread", -1),
    "BAMLC0A0CM": ("ig_spread", -1),
    "T5YIE": ("breakeven5y", -1),
    "DFEDTARU": ("policy_fed", 0),
    "ECBDFR": ("policy_ecb", 0),
}


# ----------------------------------------------------------------------- CSS
# One sheet for the page's own blocks plus the shared trend rows. No "<"
# anywhere in here, comments included: DOMPurify silently drops a whole style
# block that contains one (see stocks.web.css).
css.inject(
    f"""
    .ag-kicker {{ font-family: "Martian Mono", monospace; font-size: {FS_2XS};
                  font-weight: 500; letter-spacing: 0.06em; color: {TEXT_MUTED};
                  display: flex; align-items: center; gap: 0.5rem;
                  flex-wrap: wrap; }}
    .ag-kicker-own {{ color: {PURPLE_400}; }}
    .ag-badge {{ font-family: "Instrument Sans", sans-serif; font-size: {FS_2XS};
                 font-weight: 600; letter-spacing: 0; padding: 0.1rem 0.4rem;
                 border-radius: {RADIUS_XS}; background: {PURPLE_900};
                 color: {PURPLE_400}; }}
    .ag-mono {{ font-family: "Martian Mono", monospace; font-size: {FS_2XS};
                font-weight: 500; color: {TEXT_FAINT}; }}
    .ag-help {{ font-size: {FS_SM}; line-height: 1.55; color: {TEXT_MUTED};
                margin: 0; }}
    .ag-help b {{ color: {TEXT_SECONDARY}; font-weight: 500; }}

    .ag-pulse {{ display: flex; flex-direction: column; gap: 0.75rem; }}
    .ag-pulse-head {{ display: flex; align-items: flex-end; gap: 1rem;
                      flex-wrap: wrap; }}
    .ag-pulse-score {{ font-family: Epilogue, sans-serif; font-weight: 800;
                       font-size: 3.6rem; line-height: 0.85;
                       letter-spacing: -0.02em; color: {TEXT_PRIMARY}; }}
    .ag-pulse-band {{ display: flex; flex-direction: column; gap: 0.4rem;
                      padding-bottom: 0.2rem; align-items: flex-start; }}
    .ag-pulse-run {{ font-size: {FS_SM}; color: {TEXT_SECONDARY}; }}
    .ag-pulse-deltas {{ margin-left: auto; display: flex; flex-direction: column;
                        gap: 0.35rem; align-items: flex-end; }}
    .ag-pulse-chips {{ display: flex; gap: 0.5rem; }}
    .ag-delta {{ display: flex; gap: 0.35rem; align-items: baseline;
                 background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                 border-radius: {RADIUS_SM}; padding: 0.3rem 0.6rem; }}
    .ag-delta i {{ font-style: normal; font-size: {FS_XS}; color: {TEXT_MUTED}; }}
    .ag-delta b {{ font-family: "Martian Mono", monospace; font-weight: 500;
                   font-size: {FS_MD}; }}
    .ag-pill {{ font-size: {FS_XS}; font-weight: 600; padding: 0.15rem 0.55rem;
                border-radius: {RADIUS_PILL}; white-space: nowrap; }}
    .ag-pill-lg {{ font-size: {FS_MD}; padding: 0.25rem 0.75rem; }}

    .ag-meter {{ position: relative; height: 16px; border-radius: {RADIUS_PILL};
                 background: linear-gradient(90deg, {DOWN_FILL} 0%,
                   {DOWN_FILL} 14%, {METER_CAUTION} 30%, {METER_NEUTRAL} 44%,
                   {METER_NEUTRAL} 56%, {METER_APPETITE} 72%,
                   {SUCCESS_FILL} 88%, {SUCCESS_FILL} 100%); }}
    .ag-meter-flat {{ background: {SURFACE_HOVER}; }}
    .ag-meter-pin {{ position: absolute; top: -7px; bottom: -7px; width: 5px;
                     border-radius: 3px; background: {TEXT_PRIMARY};
                     box-shadow: 0 0 0 2px {SURFACE_CARD}; }}
    .ag-meter-ghost {{ position: absolute; top: -5px; bottom: -5px; width: 2px;
                       border-radius: 2px; background: {TEXT_SECONDARY}; }}
    .ag-meter-scale {{ display: flex; justify-content: space-between;
                       font-family: "Martian Mono", monospace;
                       font-size: {FS_2XS}; font-weight: 500;
                       color: {TEXT_FAINT}; }}

    .ag-sparkbox {{ display: flex; align-items: center; gap: 0.75rem;
                    background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                    border-radius: {RADIUS_MD}; padding: 0.7rem 0.8rem; }}
    .ag-sparkbox-l {{ display: flex; flex-direction: column; gap: 0.1rem;
                      flex: none; width: 6.5rem; }}
    .ag-sparkbox-l span:first-child {{ font-size: {FS_XS};
                                       color: {TEXT_MUTED}; }}
    .ag-sparkbox-l span:last-child {{ font-family: "Martian Mono", monospace;
                                      font-size: {FS_XS}; font-weight: 500;
                                      color: {TEXT_SECONDARY}; }}
    .ag-sparkbox .ag-spark {{ display: block; }}
    .ag-sparkbox-y {{ display: flex; flex-direction: column;
                      justify-content: space-between; height: 56px; flex: none;
                      font-family: "Martian Mono", monospace;
                      font-size: {FS_2XS}; font-weight: 500;
                      color: {TEXT_FAINT}; }}

    .ag-side {{ display: flex; flex-direction: column; gap: 0.7rem; }}
    .ag-lede {{ margin: 0; font-size: {FS_XL}; line-height: 1.35;
                font-weight: 600; color: {TEXT_PRIMARY}; text-wrap: pretty; }}
    .ag-lede em {{ font-style: normal; font-family: Epilogue, sans-serif; }}
    .ag-srow {{ display: flex; align-items: center; gap: 0.6rem;
                background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                border-radius: {RADIUS_SM}; padding: 0.55rem 0.7rem; }}
    .ag-srow-l {{ flex: 1; font-size: {FS_SM}; color: {TEXT_SECONDARY}; }}
    .ag-srow-v {{ font-family: Epilogue, sans-serif; font-weight: 800;
                  font-size: {FS_LG}; color: {TEXT_PRIMARY}; }}
    .ag-more {{ font-size: {FS_SM}; font-weight: 600; color: {BRAND_ACCENT};
                text-decoration: none; }}
    .ag-more:hover {{ color: {PURPLE_400}; }}
    .ag-invite {{ border: 1px dashed {BORDER_FOCUS}; border-radius: {RADIUS_MD};
                  padding: 1rem; display: flex; flex-direction: column;
                  gap: 0.65rem; }}
    .ag-invite p {{ margin: 0; font-size: {FS_LG}; line-height: 1.4;
                    font-weight: 600; color: {TEXT_PRIMARY}; }}

    .ag-sec-head {{ display: flex; align-items: baseline; gap: 0.6rem;
                    flex-wrap: wrap; margin-bottom: 0.2rem; }}
    h3.ag-sec-t {{ margin: 0; padding: 0; font-family: "Instrument Sans",
                   sans-serif; font-size: {FS_LG}; font-weight: 600;
                   color: {TEXT_PRIMARY}; }}
    .ag-sec-head .ag-spacer {{ flex: 1; }}

    .ag-comp {{ display: flex; flex-direction: column; gap: 0.6rem; }}
    .ag-comp-row {{ display: grid; grid-template-columns: 13rem minmax(0, 1fr)
                    4.4rem; align-items: center; gap: 0.85rem; }}
    .ag-comp-row.ag-dim {{ opacity: 0.55; }}
    .ag-comp-l {{ display: flex; flex-direction: column; gap: 0.05rem;
                  min-width: 0; }}
    .ag-comp-l span:first-child {{ font-size: {FS_MD}; font-weight: 500;
                                   color: {TEXT_PRIMARY}; }}
    .ag-comp-sub {{ font-size: {FS_XS}; line-height: 1.35; color: {TEXT_MUTED}; }}
    .ag-comp-track {{ position: relative; height: 8px;
                      border-radius: {RADIUS_PILL}; background: {SURFACE_HOVER}; }}
    .ag-comp-track.ag-empty {{ border: 1px dashed {BORDER_FOCUS};
                               box-sizing: border-box; }}
    .ag-comp-fill {{ position: absolute; top: 0; bottom: 0; left: 0;
                     border-radius: {RADIUS_PILL}; }}
    .ag-comp-mark {{ position: absolute; top: -4px; bottom: -4px; width: 2px;
                     background: {TEXT_PRIMARY}; opacity: 0.75; }}
    .ag-comp-none {{ position: absolute; left: 50%; top: -6px;
                     transform: translateX(-50%);
                     font-family: "Martian Mono", monospace;
                     font-size: {FS_2XS}; color: {TEXT_MUTED};
                     white-space: nowrap; }}
    .ag-comp-v {{ font-family: "Martian Mono", monospace; font-weight: 500;
                  font-size: {FS_SM}; text-align: right; color: {TEXT_PRIMARY};
                  font-variant-numeric: tabular-nums; }}

    .ag-strip {{ display: flex; align-items: flex-start; gap: 0.5rem;
                 background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                 border-radius: {RADIUS_SM}; padding: 0.55rem 0.7rem;
                 font-size: {FS_SM}; line-height: 1.5; color: {TEXT_SECONDARY}; }}
    .ag-strip b {{ color: {TEXT_PRIMARY}; }}
    .ag-ico {{ font-family: "Material Symbols Rounded"; font-size: 18px;
               line-height: 1.3; font-weight: 400; flex: none;
               font-variation-settings: "FILL" 0, "wght" 300;
               color: {WARN_COLOR}; }}

    .ag-tcards {{ display: flex; flex-direction: column; gap: 0.55rem; }}
    .ag-tcard {{ background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                 border-radius: {RADIUS_MD}; padding: 0.7rem 0.85rem;
                 display: flex; align-items: center; gap: 0.75rem; }}
    .ag-tcard-col {{ flex-direction: column; align-items: stretch; gap: 0.3rem; }}
    .ag-tcard-txt {{ flex: 1; display: flex; flex-direction: column; gap: 0.1rem;
                     min-width: 0; }}
    .ag-tcard-l {{ font-size: {FS_SM}; color: {TEXT_SECONDARY}; }}
    .ag-tcard-n {{ font-size: {FS_XS}; line-height: 1.4; color: {TEXT_MUTED}; }}
    .ag-tcard-v {{ font-family: Epilogue, sans-serif; font-weight: 800;
                   font-size: {FS_XL}; color: {TEXT_PRIMARY};
                   font-variant-numeric: tabular-nums; }}
    .ag-tcard-w {{ font-size: {FS_LG}; font-weight: 600; color: {TEXT_PRIMARY}; }}

    .ag-bk {{ display: grid; gap: 0.6rem;
              grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }}
    .ag-bk-tile {{ background: {SURFACE_PAGE}; border: 1px solid {BORDER};
                   border-radius: {RADIUS_MD}; padding: 0.8rem;
                   display: flex; flex-direction: column; gap: 0.4rem; }}
    .ag-bk-l {{ font-size: {FS_SM}; color: {TEXT_SECONDARY}; }}
    .ag-bk-v {{ font-family: Epilogue, sans-serif; font-weight: 800;
                font-size: 1.6rem; line-height: 1; color: {TEXT_PRIMARY};
                font-variant-numeric: tabular-nums; }}
    .ag-bk-n {{ font-size: {FS_XS}; line-height: 1.45; color: {TEXT_MUTED}; }}
    .ag-notes {{ display: grid; gap: 0.45rem 1.2rem;
                 grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr)); }}
    .ag-note {{ display: flex; gap: 0.55rem; align-items: flex-start;
                font-size: {FS_SM}; line-height: 1.55; color: {TEXT_SECONDARY}; }}
    .ag-note::before {{ content: ""; margin-top: 0.45rem; width: 5px;
                        height: 5px; border-radius: {RADIUS_PILL};
                        background: {BRAND_ACCENT}; flex: none; }}
    .ag-note b {{ color: {TEXT_PRIMARY}; font-weight: 500; }}

    .ag-down {{ border: 1px solid {WARN_EDGE}; background: {WARN_FILL_SOFT};
                border-radius: {RADIUS_MD}; padding: 0.9rem;
                display: flex; flex-direction: column; gap: 0.45rem; }}
    .ag-down-t {{ font-size: {FS_LG}; font-weight: 600; color: {TEXT_PRIMARY}; }}
    .ag-down-b {{ font-size: {FS_SM}; line-height: 1.55; color: {TEXT_SECONDARY}; }}

    .ag-jump {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .ag-jump a {{ font-size: {FS_SM}; font-weight: 600; padding: 0.5rem 0.75rem;
                  border-radius: {RADIUS_PILL}; background: {SURFACE_CARD};
                  border: 1px solid {BORDER}; color: {TEXT_SECONDARY};
                  text-decoration: none; white-space: nowrap; }}
    .ag-jump a:first-child {{ background: {PURPLE_900};
                              border-color: {PURPLE_800}; color: {PURPLE_400}; }}

    /* The hero's two halves are Streamlit columns, so the divider between
       them is a border on the second one. Never a border-top: app.py stamps
       the card look on any block whose computed top border is above zero. */
    .st-key-ag_hero div[data-testid="stColumn"]:last-child {{
      border-left: 1px solid {BORDER}; padding-left: 1.4rem;
    }}
    .st-key-ag_why div[data-testid="stColumn"]:last-child {{
      border-left: 1px solid {BORDER}; padding-left: 1.4rem;
    }}
    @media (max-width: 640px) {{
      .ag-pulse-score {{ font-size: 3rem; }}
      .ag-pulse-deltas {{ margin-left: auto; }}
      .ag-comp-row {{ grid-template-columns: minmax(0, 1fr) 4rem;
                      gap: 0.3rem 0.6rem; }}
      .ag-comp-track {{ grid-column: 1 / -1; }}
      .ag-sparkbox-l {{ display: none; }}
      .st-key-ag_hero div[data-testid="stColumn"]:last-child,
      .st-key-ag_why div[data-testid="stColumn"]:last-child {{
        border-left: 0; padding-left: 0; border-top: 0;
      }}
    }}
    """
    + trend_ui.css(chip_labels=CHIP_LABELS)
)


# ------------------------------------------------------------------- helpers
def _pct(v: float, digits: int = 1) -> str:
    return "n/a" if v != v else f"{v:+.{digits}%}"


def _num(v: float, digits: int = 2) -> str:
    return "n/a" if v != v else f"{v:.{digits}f}"


def _slug(ticker: str) -> str:
    """A ticker as an i18n key fragment: `^GSPC` to `gspc`, `GC=F` to `gc_f`."""
    return "".join(
        c if c.isalnum() else "_" for c in ticker.lower().lstrip("^")
    ).strip("_")


def _tip(*parts: str) -> str | None:
    """The hover explanation for one row, or None when there is no copy for it.

    Every detail table names things a reader is assumed to already know — VIX,
    2s10s, MOVE, RSP over SPY — and the page assumed it too. These say what the
    row is in one sentence, and a row the catalogs have nothing to say about
    simply gets no dot rather than a key printed as text.
    """
    key = "sentiment.tip_" + "_".join(parts)
    text = tr(key)
    return None if text == key else text


def _label(key: str, fallback: str) -> str:
    """Translation for `key`, or `fallback` when the catalogs have no entry.

    `i18n.t` returns the key itself for a miss, which is the right default for
    a hardcoded key (a missing string shows up loudly in review) and the wrong
    one for keys built from upstream data: Yahoo can invent a sector spelling
    tomorrow, and this page must print that spelling rather than
    "sentiment.sector_whatever".
    """
    text = tr(key)
    return fallback if text == key else text


def _score_color(score: float) -> str:
    """Colour for a 0-100 risk-appetite score: red at the fear end, green at
    the appetite end, neutral grey through the middle band."""
    if score != score:
        return TEXT_MUTED
    if score < 40:
        return CANDLE_DOWN
    if score < 60:
        return TEXT_SECONDARY
    return CANDLE_UP


# Regime pill fills. Solid market pills, like every other verdict on the page:
# euphoria takes the caution amber rather than a deeper green, because the top
# of the scale is a risk reading and not a better version of "appetite".
_REGIME_PILL = {
    "stress": (DOWN_FILL, DOWN_COLOR),
    "caution": (WARN_FILL, WARN_COLOR),
    "neutral": (SURFACE_HOVER, TEXT_SECONDARY),
    "appetite": (SUCCESS_FILL, UP_COLOR),
    "euphoria": (WARN_FILL, WARN_COLOR),
    "unknown": (SURFACE_HOVER, TEXT_MUTED),
}


def _pill(text: str, back: str, fore: str, *, large: bool = False) -> str:
    klass = "ag-pill ag-pill-lg" if large else "ag-pill"
    return (
        f'<span class="{klass}" style="background:{back};color:{fore}">'
        f"{html.escape(text)}</span>"
    )


def _drift_pill(now: float, then: float, *, digits: int = 2, welcome: int = 0) -> str:
    """The "and where it was" pill that rides every personalised figure.

    A beta of 1.05 is unremarkable; a beta that was 0.82 a quarter ago means
    the book got materially more market-sensitive without the reader buying
    anything, because the regime moved under it. So the pill is the drift, not
    a price change — and it stays neutral unless the move is big enough to
    matter, since a 0.02 wobble on a rolling statistic is noise.
    """
    if now != now or then != then:
        return ""
    text = tr("sentiment.drift_pill", value=f"{then:.{digits}f}")
    change = now - then
    if abs(change) < 0.05:
        return _pill(text, SURFACE_CARD, TEXT_SECONDARY)
    if welcome == 0:
        return _pill(text, WARN_FILL, WARN_COLOR)
    good = change > 0 if welcome > 0 else change < 0
    return (
        _pill(text, SUCCESS_FILL, UP_COLOR)
        if good
        else _pill(text, DOWN_FILL, DOWN_COLOR)
    )


def _pct_chips(series: pd.Series, *, welcome: int = 1) -> list[tuple[str, int]]:
    """Percent-change chips for a price series, one per horizon.

    `welcome` is +1 when a rise is the good direction and -1 when a fall is, so
    a falling volatility index and a rising equity index both read green.
    """
    moves = sm.pct_changes(series, HORIZONS)
    out = []
    for name in HORIZONS:
        value = moves.get(name)
        if value is None:
            continue
        direction = 0 if value == 0 else welcome * (1 if value > 0 else -1)
        out.append((f"{value:+.1%}", direction))
    return out


def _bp_chips(series: pd.Series, *, welcome: int) -> list[tuple[str, int]]:
    """Basis-point chips for a rate or spread, one per horizon.

    A yield's move is quoted in basis points, not percent: "10y +33bp" is how
    it is discussed everywhere, and a percent change of a percentage rate
    ("+7.4%") is a number that reads like a price move and is not one.
    """
    moves = sm.changes(series, HORIZONS)
    out = []
    for name in HORIZONS:
        value = moves.get(name)
        if value is None:
            continue
        points = value * 100
        direction = 0 if points == 0 else welcome * (1 if points > 0 else -1)
        out.append((f"{points:+.0f}bp", direction))
    return out


def _tail(series: pd.Series, days: int = SPARK_DAYS) -> list[float]:
    return [float(v) for v in series.dropna().iloc[-days:]]


def _head(
    title: str, anchor: str, *, hint: str = "", badge: str = "", right: str = ""
) -> str:
    """A section heading with its own anchor, and the aside that qualifies it.

    The anchor is what the phone's jump chips scroll to, so it has to be a
    real id on a real heading rather than a styled div.
    """
    parts = [
        f'<h3 class="ag-sec-t" id="{anchor}">{html.escape(title)}</h3>',
    ]
    if badge:
        parts.append(f'<span class="ag-badge">{html.escape(badge)}</span>')
    if hint:
        parts.append(f'<span class="ag-mono">{html.escape(hint)}</span>')
    if right:
        parts.append('<span class="ag-spacer"></span>')
        parts.append(f'<span class="ag-mono">{html.escape(right)}</span>')
    return f'<div class="ag-sec-head">{"".join(parts)}</div>'


def _hero_spark(history: pd.Series, *, width: int = 520, height: int = 56) -> str:
    """The composite's own 90 sessions, drawn on the meter's fixed 0-100 scale.

    Fixed range, not autoscaled: this line sits under a 0-100 meter and a
    reader compares the two by eye, so an autoscaled version of the same
    series — where a 12-point wobble fills the box — would contradict the pin
    it is drawn beside. Guides at 20 and 80 mark the outer bands.

    An SVG behind a `span` rather than a Plotly figure, for the same reason
    every other sparkline here is one: it costs one polyline inside the block
    it belongs to instead of a React chart with its own resize observer. The
    data-URI wrapper is not decoration either — `st.html` strips an inline
    `svg` outright (see stocks.web.spark).
    """
    series = [float(v) for v in history.dropna().iloc[-SPARK_DAYS:]]
    if len(series) < 2:
        return ""
    pad = 3.0
    span = height - 2 * pad

    def _y(value: float) -> float:
        return pad + (1.0 - max(0.0, min(100.0, value)) / 100.0) * span

    points = " ".join(
        f"{i / (len(series) - 1) * (width - 2) + 1:.1f},{_y(v):.1f}"
        for i, v in enumerate(series)
    )
    guides = "".join(
        f'<line x1="0" y1="{_y(level):.1f}" x2="{width}" y2="{_y(level):.1f}" '
        f'stroke="{BORDER}" stroke-width="1" stroke-dasharray="3 4"/>'
        for level in (20, 80)
    )
    return spark.embed(
        f'<svg xmlns="{spark.SVG_NS}" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" preserveAspectRatio="none">'
        f'{guides}<polyline points="{points}" fill="none" '
        f'stroke="{BRAND_ACCENT}" stroke-width="1.8" stroke-linejoin="round"/>'
        "</svg>",
        css=f"flex:1 1 auto;min-width:0;height:{height}px",
    )


def _table_block(
    box,
    rows: list[TrendRow],
    *,
    title: str,
    source: str,
    note: str,
    label_key: str,
    value_key: str,
    chip_labels: Sequence[str] | None = None,
) -> None:
    """One tab's table: what it is, where it came from, the rows, the reading."""
    with box.container():
        st.html(
            '<div class="ag-sec-head">'
            f'<span class="ag-tcard-w">{html.escape(title)}</span>'
            f'<span class="ag-mono">{html.escape(source)}</span></div>'
        )
        st.html(
            trend_ui.rows_html(
                rows,
                chip_labels=list(chip_labels or CHIP_LABELS),
                label_label=tr(label_key),
                value_label=tr(value_key),
                spark_label=tr("sentiment.col_shape"),
                state_label=tr("sentiment.col_trend"),
                state_names=STATE_NAMES,
            )
        )
        st.caption(note)


def _source_down(
    box,
    *,
    title: str,
    source: str,
    origin: str,
    message_key: str,
    retry: Callable[[], None] | None = None,
    key: str = "",
    anchor: str = "",
) -> None:
    """Resolve a slot with the reason its source is missing, and a way back.

    Every path out of a reserved slot has to end in `container()` or `clear()`
    or the shimmer outlives the load, and a failed fetch is a path. The block
    keeps its heading and its count — anchor included, so the phone's jump
    strip still lands on it — and the reader learns exactly what is missing
    rather than only that something is.
    """
    head = (
        _head(title, anchor, right=source)
        if anchor
        else '<div class="ag-sec-head">'
        f'<span class="ag-tcard-w">{html.escape(title)}</span>'
        f'<span class="ag-mono">{html.escape(source)}</span></div>'
    )
    with box.container():
        st.html(
            head + '<div class="ag-down">'
            f'<span class="ag-down-t">{html.escape(tr(message_key + "_title"))}'
            "</span>"
            f'<span class="ag-down-b">{html.escape(tr(message_key))}</span>'
            "</div>"
        )
        stamp = tr(
            "sentiment.down_stamp",
            time=datetime.now().strftime("%H:%M:%S"),
            source=origin,
        )
        if retry is not None:
            if st.button(
                tr("sentiment.down_retry"),
                key=f"pulse_retry_{key}",
                icon=":material/refresh:",
            ):
                retry()
                st.rerun()
        st.caption(stamp)


# ----------------------------------------------------------------- the slots
# Every card is reserved here, in page order, before a single byte is fetched.
# Streamlit sends the elements a script emits in the order it emits them, so
# these shimmering cards reach the browser in the first delta batch and each
# one is then replaced in place as the fetch it waits on lands. The reader sees
# the page's whole shape immediately and watches it fill.
#
# The hero is two slots inside one card because its halves arrive at different
# times: the composite needs prices and FRED, the personal half needs a ledger
# replay and a second price download. Half-loaded is therefore a real state,
# and the design draws it — the score resolved on the left, the reader's own
# figures still shimmering on the right — rather than holding the whole card
# back for its slowest input.
SLOTS: dict[str, skeletons.Slot] = {}

_hero = st.container(border=True, key="ag_hero")
with _hero:
    _hero_left, _hero_right = st.columns([1.35, 1], gap="medium")
SLOTS["pulse"] = skeletons.reserve(
    "metrics", n=1, title=True, container=_hero_left
)
SLOTS["side"] = skeletons.reserve(
    "cards", n=3, lines=1, title=True, container=_hero_right
)

# On a phone the four sections are four full screens, so a strip that jumps
# between them earns its place directly under the summary; on a desktop they
# are all within one scroll and it would be chrome for its own sake.
if is_mobile():
    st.html(
        '<div class="ag-jump">'
        + "".join(
            f'<a href="#{anchor}">{html.escape(tr(key))}</a>'
            for anchor, key in (
                ("ag-pulse", "sentiment.jump_summary"),
                ("ag-why", "sentiment.jump_why"),
                ("ag-book", "sentiment.jump_book"),
                ("ag-detail", "sentiment.jump_detail"),
            )
        )
        + "</div>"
    )

_why = st.container(border=True, key="ag_why")
with _why:
    _why_left, _why_right = st.columns([1.25, 1], gap="medium")
SLOTS["components"] = skeletons.reserve(
    "rows", rows=len(sm.COMPONENT_KEYS), container=_why_left
)
SLOTS["snapshot"] = skeletons.reserve(
    "cards", n=4, lines=2, title=True, container=_why_right
)

_book_card = st.container(border=True, key="ag_book")
SLOTS["book"] = skeletons.reserve(
    "metrics", n=5, title=True, container=_book_card
)

# The detail card and its tab strip exist before any fetch, so the counts are
# on screen from first paint and each tab can be filled by whichever stage
# unblocks it — the tables inside do not arrive together and must not wait for
# each other.
# (slot key, heading, badge on the tab, rows the skeleton reserves). The badge
# and the row count differ where a tab holds more than one table, which is why
# the badge is a string and not the count itself.
DETAIL_TABS: tuple[tuple[str, str, str, int], ...] = (
    ("indices", "sentiment.indices_title", str(len(sm.INDICES)), len(sm.INDICES)),
    ("gauges", "sentiment.risk_title", str(len(sm.GAUGES)), len(sm.GAUGES)),
    ("rates", "sentiment.rates_title", str(len(RATE_ROWS)), len(RATE_ROWS)),
    (
        "inflation",
        "sentiment.inflation_title",
        str(len(macro.INFLATION_AREAS)),
        len(macro.INFLATION_AREAS) + 1,
    ),
    (
        "rotation",
        "sentiment.rotation_title",
        f"{len(sm.SECTOR_ETFS)}+{len(sm.FACTOR_PAIRS)}",
        len(sm.SECTOR_ETFS),
    ),
    ("cross", "sentiment.cross_title", str(len(sm.MACRO_ASSETS)), len(sm.MACRO_ASSETS)),
)

_detail = st.container(border=True, key="ag_detail")
with _detail:
    st.html(
        _head(
            tr("sentiment.detail_title"),
            "ag-detail",
            hint=tr("sentiment.detail_hint"),
        )
    )
    _tab_boxes = dict(
        zip(
            [key for key, _title, _badge, _rows in DETAIL_TABS],
            st.tabs(
                [
                    f"{tr(title)} :gray-badge[{badge}]"
                    for _key, title, badge, _rows in DETAIL_TABS
                ]
            ),
            strict=True,
        )
    )
for _key, _title, _badge, _rows in DETAIL_TABS:
    SLOTS[_key] = skeletons.reserve(
        "table", rows=_rows, cols=8, container=_tab_boxes[_key]
    )
# The rotation tab carries a second table under the first — the factor pairs
# are a different question about the same rotation, and splitting them into
# their own tab would hide one behind the other.
SLOTS["factors"] = skeletons.reserve(
    "table", rows=len(sm.FACTOR_PAIRS), cols=8, container=_tab_boxes["rotation"]
)


# ------------------------------------------------------------------ the hero
def render_pulse(box, closes: dict[str, pd.Series], rates: dict[str, pd.Series]):
    """The composite: score, band, how long it has held it, and its own path.

    Returns the `Pulse` so the block below can print its components without
    building the whole thing twice.
    """
    pulse = sm.pulse(closes, hy_spread=rates.get("BAMLH0A0HYM2"))
    back, fore = _REGIME_PILL[pulse.regime]
    score_text = "n/a" if pulse.score != pulse.score else f"{pulse.score:.0f}"
    # The pin sits at the score's own position on the 0-100 track; a NaN score
    # parks it mid-scale under an "n/a" headline rather than at zero, which
    # would read as "maximum fear".
    known = pulse.score == pulse.score
    pin = max(0.0, min(100.0, pulse.score)) if known else 50.0
    history = pulse.history

    def _delta(ago: int) -> float:
        if len(history) <= ago:
            return float("nan")
        return float(history.iloc[-1]) - float(history.iloc[-ago - 1])

    deltas = [(name, _delta(HORIZONS[name])) for name in ("week", "month")]
    delta_html = "".join(
        f'<span class="ag-delta"><i>{html.escape(tr(f"sentiment.h_{name}"))}</i>'
        f'<b style="color:'
        f"{CANDLE_UP if value > 0 else CANDLE_DOWN if value < 0 else TEXT_MUTED}"
        f'">{value:+.1f}</b></span>'
        for name, value in deltas
        if value == value
    )
    # A ghost pin at the month-ago score: the delta as a distance on the same
    # track, which is easier to read than a signed number beside it.
    ghost = ""
    month_ago = dict(deltas).get("month", float("nan"))
    if month_ago == month_ago and known:
        ghost_pos = max(0.0, min(100.0, pin - month_ago))
        ghost = (
            f'<div class="ag-meter-ghost" style="left:calc({ghost_pos:.1f}% '
            '- 1px)"></div>'
        )
    run = sm.regime_run(history)
    stamp = tr("sentiment.regime_run", n=run) if run else ""
    scale = (
        f'<span>0 {html.escape(tr("sentiment.regime_stress")).upper()}</span>'
        "<span>20</span>"
        f'<span>40 {html.escape(tr("sentiment.regime_neutral")).upper()} 60</span>'
        "<span>80</span>"
        f'<span>{html.escape(tr("sentiment.regime_euphoria")).upper()} 100</span>'
    )

    with box.container():
        st.html(
            '<div class="ag-pulse">'
            f'<div class="ag-kicker" id="ag-pulse">'
            f'{html.escape(tr("sentiment.kicker_pulse"))}</div>'
            '<div class="ag-pulse-head">'
            f'<span class="ag-pulse-score">{score_text}</span>'
            '<span class="ag-pulse-band">'
            + _pill(tr(f"sentiment.regime_{pulse.regime}"), back, fore, large=True)
            + f'<span class="ag-pulse-run">{html.escape(stamp)}</span></span>'
            '<span class="ag-pulse-deltas">'
            f'<span class="ag-pulse-chips">{delta_html}</span>'
            f'<span class="ag-mono">{html.escape(tr("sentiment.delta_unit"))}'
            "</span></span></div>"
            f'<div class="ag-meter{"" if known else " ag-meter-flat"}">{ghost}'
            f'<div class="ag-meter-pin" style="left:calc({pin:.1f}% - 2.5px)">'
            "</div></div>"
            f'<div class="ag-meter-scale">{scale}</div>'
            f'<p class="ag-help">{html.escape(tr("sentiment.pulse_help"))}</p>'
            "</div>"
        )

        spark = _hero_spark(history)
        if spark:
            window = history.iloc[-SPARK_DAYS:]
            span = tr(
                "sentiment.spark_range",
                lo=f"{window.min():.0f}",
                hi=f"{window.max():.0f}",
            )
            st.html(
                '<div class="ag-sparkbox"><div class="ag-sparkbox-l">'
                f'<span>{html.escape(tr("sentiment.spark_window", n=SPARK_DAYS))}'
                f'</span><span>{html.escape(span)}</span></div>'
                f"{spark}"
                '<div class="ag-sparkbox-y">'
                "<span>80</span><span>50</span><span>20</span></div></div>"
            )

        stamp_line = tr(
            "sentiment.pulse_stamp",
            date="" if pulse.as_of is None else pulse.as_of.strftime("%Y-%m-%d"),
            live=len(pulse.components),
            total=len(sm.COMPONENT_KEYS),
        )
        st.html(f'<span class="ag-mono">{html.escape(stamp_line)}</span>')
    return pulse


def _side_invite(box, *, message_key: str, note_key: str, cta: str) -> None:
    """The hero's right half when there is no book to read the regime against.

    There is no honest version of this panel for an empty ledger, so it says
    what it would show and offers the one step that would fill it, rather than
    inventing a beta of 1.00 and a dollar share of zero.
    """
    with box.container():
        st.html(
            '<div class="ag-side">'
            f'<div class="ag-kicker ag-kicker-own">'
            f'{html.escape(tr("sentiment.side_kicker"))}</div>'
            '<div class="ag-invite">'
            f"<p>{html.escape(tr(message_key))}</p>"
            f'<span class="ag-help">{html.escape(tr(note_key))}</span>'
            "</div></div>"
        )
        if cta == "signin":
            if auth.auth_configured():
                st.button(
                    tr("sentiment.book_signin_cta"),
                    icon=":material/login:",
                    on_click=auth.login,
                    type="primary",
                    key="pulse_signin",
                )
        elif st.button(
            tr("sentiment.book_import_cta"),
            icon=":material/upload_file:",
            type="primary",
            key="pulse_import",
        ):
            st.switch_page("app_pages/import_transactions.py")


def render_side(box, closes: dict[str, pd.Series], book: dict | None, pulse) -> None:
    """The hero's right half: this regime, restated as what it does here.

    Three figures, chosen because they are the ones a reader can act on: how
    much of the index's move lands on their basket, whether their bonds are
    still hedging their equities, and how much of their value is priced in a
    currency they do not spend.
    """
    if not auth.is_logged_in():
        _side_invite(
            box,
            message_key="sentiment.book_signed_out",
            note_key="sentiment.book_signed_out_note",
            cta="signin",
        )
        return
    if book is None:
        _side_invite(
            box,
            message_key="sentiment.book_empty",
            note_key="sentiment.book_empty_note",
            cta="import",
        )
        return
    if not closes:
        _source_down(
            box,
            title=tr("sentiment.book_title"),
            source=tr("sentiment.src_book"),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            key="side",
        )
        return

    port = sm.naive_index(portfolio_returns(book["returns"], book["weights"]))
    rows: list[tuple[str, str, str]] = []

    equity = float("nan")
    spx = closes.get("^GSPC")
    if spx is not None and not spx.dropna().empty and not port.empty:
        bench = sm.naive_index(spx.dropna().pct_change().iloc[1:])
        equity = beta(port, bench)
        rolling = sm.rolling_beta(port, bench, window=ROLL)
        now, then = sm.drift(rolling, ago=DRIFT_DAYS)
        rows.append((
            tr("sentiment.beta_equity"),
            "n/a" if equity != equity else f"{equity:.2f}",
            _drift_pill(now, then),
        ))

    tlt = closes.get("TLT")
    if tlt is not None and not tlt.dropna().empty and not port.empty:
        own = sm.rolling_correlation((1 + port).cumprod(), tlt, window=ROLL)
        now, then = sm.drift(own, ago=DRIFT_DAYS)
        if now == now:
            rows.append((
                tr("sentiment.side_corr"),
                f"{now:+.2f}",
                _drift_pill(now, then),
            ))

    usd_share = float(book["currency"].get("USD", 0.0))
    fx_moves = {}
    eurusd = closes.get("EURUSD=X")
    if eurusd is not None and not eurusd.dropna().empty:
        # EURUSD=X is dollars per euro, so the dollar's move against the euro
        # is the inverse of the pair's move — inverting here is the difference
        # between a drag and a tailwind.
        move = sm.pct_over(eurusd, MONTH)
        if move == move:
            fx_moves["USD"] = 1.0 / (1.0 + move) - 1.0
    drag, _contributions = sm.fx_exposure(book["currency"], fx_moves, base=REPORT_CCY)
    fx_pill = ""
    if drag == drag:
        back, fore = (
            (SUCCESS_FILL, UP_COLOR) if drag >= 0 else (DOWN_FILL, DOWN_COLOR)
        )
        fx_pill = _pill(tr("sentiment.fx_pill", value=_pct(drag, 2)), back, fore)
    rows.append((tr("sentiment.usd_share"), f"{usd_share:.0%}", fx_pill))

    # The sentence is the whole point of the panel: a number a reader has to
    # interpret is a number most readers will not.
    stance = (
        "amplify" if equity > 1.05 else "cushion" if equity < 0.95 else "track"
    )
    _back, tint = _REGIME_PILL[pulse.regime]
    lede = tr(
        "sentiment.side_lede",
        regime=(
            f'<span style="color:{tint}">'
            f'{html.escape(tr(f"sentiment.regime_{pulse.regime}"))}</span>'
        ),
        stance=html.escape(tr(f"sentiment.stance_{stance}")),
        beta=f"<em>{'n/a' if equity != equity else f'{equity:.2f}'}</em>",
        usd=f"<em>{usd_share:.0%}</em>",
    )
    row_html = "".join(
        f'<div class="ag-srow"><span class="ag-srow-l">{html.escape(label)}</span>'
        f'<span class="ag-srow-v">{html.escape(value)}</span>{pill}</div>'
        for label, value, pill in rows
    )
    with box.container():
        st.html(
            '<div class="ag-side">'
            '<div class="ag-kicker ag-kicker-own">'
            f'{html.escape(tr("sentiment.side_kicker"))}'
            f'<span class="ag-badge">{html.escape(tr("sentiment.side_badge"))}'
            "</span></div>"
            f'<p class="ag-lede">{lede}</p>'
            f"{row_html}"
            f'<p class="ag-help">{tr("sentiment.side_help")}</p>'
            f'<a class="ag-more" href="#ag-book">'
            f'{html.escape(tr("sentiment.side_more"))}</a>'
            "</div>"
        )


# ------------------------------------------------------------------- why
def render_components(box, pulse) -> None:
    """The composite's eight inputs, each with its own direction and level.

    The whole argument for building our own index instead of showing someone
    else's is here: the number explains itself. A component that could not be
    built keeps its row, dimmed and named, because "we are missing the credit
    leg today" is information and a silently shorter average is not.
    """
    live = {c.key: c for c in pulse.components}
    rows = []
    for key in sm.COMPONENT_KEYS:
        name = html.escape(tr(f"sentiment.comp_{key}"))
        sub = html.escape(tr(f"sentiment.comp_{key}_sub"))
        comp = live.get(key)
        if comp is None:
            rows.append(
                '<div class="ag-comp-row ag-dim">'
                f'<span class="ag-comp-l"><span>{name}</span>'
                f'<span class="ag-comp-sub">{sub}</span></span>'
                '<span class="ag-comp-track ag-empty">'
                f'<span class="ag-comp-none">'
                f'{html.escape(tr("sentiment.comp_none"))}</span></span>'
                '<span class="ag-comp-v" style="color:'
                f'{TEXT_MUTED}">n/a</span></div>'
            )
            continue
        mark = ""
        if comp.then == comp.then:
            mark = (
                '<span class="ag-comp-mark" style="left:calc('
                f'{max(0.0, min(100.0, comp.then)):.0f}% - 1px)"></span>'
            )
        rows.append(
            '<div class="ag-comp-row">'
            f'<span class="ag-comp-l"><span>{name}</span>'
            f'<span class="ag-comp-sub">{sub}</span></span>'
            '<span class="ag-comp-track">'
            f'<span class="ag-comp-fill" style="width:{comp.score:.0f}%;'
            f'background:{_score_color(comp.score)}"></span>{mark}</span>'
            f'<span class="ag-comp-v">{html.escape(comp.text)}</span></div>'
        )

    with box.container():
        st.html(
            _head(
                tr("sentiment.why_title"),
                "ag-why",
                hint=tr("sentiment.why_hint"),
            )
            + f'<div class="ag-comp">{"".join(rows)}</div>'
        )
        # What the score is missing, said out loud. A composite that quietly
        # averages six inputs one day and eight the next is a different number
        # wearing the same name.
        if pulse.missing:
            icon = '<span class="ag-ico">warning</span>'
            body = tr(
                "sentiment.pulse_missing",
                names=", ".join(
                    f"<b>{html.escape(tr(f'sentiment.comp_{k}'))}</b>"
                    for k in pulse.missing
                ),
                live=len(pulse.components),
                total=len(sm.COMPONENT_KEYS),
                floor=sm.MIN_COMPONENTS,
            )
        else:
            icon = (
                f'<span class="ag-ico" style="color:{CANDLE_UP}">'
                "check_circle</span>"
            )
            body = html.escape(
                tr("sentiment.pulse_complete", total=len(sm.COMPONENT_KEYS))
            )
        st.html(f'<div class="ag-strip">{icon}<span>{body}</span></div>')


def render_snapshot(
    box, closes: dict[str, pd.Series], rates: dict[str, pd.Series]
) -> None:
    """Four readings that only exist as trends: none has a level worth printing."""
    cards: list[str] = []

    def _card(label: str, value: str, note: str) -> str:
        return (
            '<div class="ag-tcard"><span class="ag-tcard-txt">'
            f'<span class="ag-tcard-l">{html.escape(label)}</span>'
            f'<span class="ag-tcard-n">{html.escape(note)}</span></span>'
            f'<span class="ag-tcard-v">{html.escape(value)}</span></div>'
        )

    # Trend breadth, twice over. Not today's advance-decline — how many markets
    # are in an uptrend at all. An index at a high with a third of its sectors
    # below trend is a narrowing market, and the index level cannot say so.
    hits, total = sm.above_ma_share(closes, [i.ticker for i in sm.INDICES], YEAR - 52)
    if total:
        cards.append(
            _card(
                tr("sentiment.breadth_indices"),
                f"{hits}/{total}",
                tr("sentiment.breadth_indices_note", n=YEAR - 52),
            )
        )
    s_hits, s_total = sm.above_ma_share(
        closes, list(sm.SECTOR_ETFS.values()), sm.TREND_SLOW
    )
    if s_total:
        cards.append(
            _card(
                tr("sentiment.breadth_sectors"),
                f"{s_hits}/{s_total}",
                tr("sentiment.breadth_sectors_note", n=sm.TREND_SLOW),
            )
        )

    # Stock/bond correlation: the level IS the story. Negative means bonds
    # cushion an equity drawdown; positive means both legs fall together and
    # the diversification a reader thinks they have is not there.
    if "SPY" in closes and "TLT" in closes:
        corr = sm.rolling_correlation(closes["SPY"], closes["TLT"], window=ROLL)
        now, then = sm.drift(corr, ago=DRIFT_DAYS)
        if now == now:
            cards.append(
                _card(
                    tr("sentiment.stock_bond_corr"),
                    f"{now:+.2f}",
                    (
                        tr("sentiment.drift_note", value=_num(then)) + " · "
                        if then == then
                        else ""
                    )
                    + tr("sentiment.stock_bond_corr_note"),
                )
            )

    # The rates quadrant: a slope move crossed with a yield move. Four regimes,
    # four different macro stories, and the yield level tells none of them.
    if "DGS10" in rates and "T10Y2Y" in rates:
        quad = sm.rate_quadrant(rates["DGS10"], rates["T10Y2Y"], days=QUARTER)
        if quad != "unknown":
            y_move = sm.changes(rates["DGS10"], {"q": QUARTER}).get("q", 0.0) * 100
            s_move = sm.changes(rates["T10Y2Y"], {"q": QUARTER}).get("q", 0.0) * 100
            cards.append(
                '<div class="ag-tcard ag-tcard-col">'
                '<span style="display:flex;align-items:center;gap:0.6rem">'
                f'<span class="ag-tcard-l" style="flex:1">'
                f'{html.escape(tr("sentiment.rates_regime"))}</span>'
                f'<span class="ag-tcard-w">'
                f'{html.escape(tr(f"sentiment.quad_{quad}"))}</span></span>'
                f'<span class="ag-mono">'
                + html.escape(
                    tr(
                        "sentiment.quad_note",
                        yields=f"{y_move:+.0f}bp",
                        slope=f"{s_move:+.0f}bp",
                    )
                )
                + "</span>"
                f'<span class="ag-tcard-n">'
                f'{html.escape(tr(f"sentiment.quad_meaning_{quad}"))}</span></div>'
            )

    if not cards:
        _source_down(
            box,
            title=tr("sentiment.snapshot_title"),
            source=tr("sentiment.src_derived"),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            key="snapshot",
            anchor="ag-snapshot",
        )
        return
    with box.container():
        st.html(
            _head(
                tr("sentiment.snapshot_title"),
                "ag-snapshot",
                hint=tr("sentiment.snapshot_hint"),
            )
            + f'<div class="ag-tcards">{"".join(cards)}</div>'
        )


# -------------------------------------------------------------- your book
def render_book(box, closes: dict[str, pd.Series], book: dict | None) -> None:
    """The five sensitivities, and whether they are themselves drifting.

    Fixed weights on purpose: this reads what the account owns NOW under the
    current regime, not how it has performed (the Portfolio page owns that).
    """
    if not auth.is_logged_in() or book is None or not closes:
        # The hero's right half already carries the invitation; repeating it
        # in full here would be the same empty state twice on one screen.
        reason = (
            "sentiment.book_signed_out"
            if not auth.is_logged_in()
            else "sentiment.book_empty"
            if book is None
            else "sentiment.prices_unavailable"
        )
        with box.container():
            st.html(
                _head(tr("sentiment.book_title"), "ag-book")
                + f'<span class="ag-help">{html.escape(tr(reason))}</span>'
            )
        return

    # Both sides go through naive_index — a book of European and US names
    # carries two exchange timezones, and beta() intersects on the index, so
    # leaving the zones on would silently regress over an empty overlap.
    port = sm.naive_index(portfolio_returns(book["returns"], book["weights"]))
    bench_returns = {
        ticker: sm.naive_index(closes[ticker].dropna().pct_change().iloc[1:])
        for ticker in sm.BENCHMARKS
        if ticker in closes and not closes[ticker].dropna().empty
    }

    def _tile(label: str, value: str, pill: str, note: str) -> str:
        return (
            '<div class="ag-bk-tile">'
            f'<span class="ag-bk-l">{html.escape(label)}</span>'
            f'<span class="ag-bk-v">{html.escape(value)}</span>'
            f"{pill}"
            f'<span class="ag-bk-n">{html.escape(note)}</span></div>'
        )

    def _beta_tile(ticker: str, suffix: str) -> str:
        """A beta tile whose pill is the drift, not the level."""
        series = bench_returns.get(ticker)
        label = tr(f"sentiment.beta_{suffix}")
        note = tr(f"sentiment.beta_{suffix}_help")
        if series is None or port.empty:
            return _tile(label, "n/a", "", note)
        level = beta(port, series)
        rolling = sm.rolling_beta(port, series, window=ROLL)
        now, then = sm.drift(rolling, ago=DRIFT_DAYS)
        return _tile(
            label,
            "n/a" if level != level else f"{level:.2f}",
            _drift_pill(now, then),
            note,
        )

    # FX: what part of the last month's return came from currency rather than
    # from the assets. A EUR investor holding US names is short EUR whether
    # they meant to be or not.
    fx_moves = {}
    eurusd = closes.get("EURUSD=X")
    if eurusd is not None and not eurusd.dropna().empty:
        move = sm.pct_over(eurusd, MONTH)
        if move == move:
            fx_moves["USD"] = 1.0 / (1.0 + move) - 1.0
    drag, contributions = sm.fx_exposure(book["currency"], fx_moves, base=REPORT_CCY)
    usd_share = float(book["currency"].get("USD", 0.0))
    fx_pill = ""
    if drag == drag:
        back, fore = (
            (SUCCESS_FILL, UP_COLOR) if drag >= 0 else (DOWN_FILL, DOWN_COLOR)
        )
        fx_pill = _pill(tr("sentiment.fx_pill", value=_pct(drag, 2)), back, fore)

    tiles = [
        _beta_tile("^GSPC", "equity"),
        _beta_tile("TLT", "duration"),
        _beta_tile("HYG", "credit"),
        _beta_tile("EEM", "em"),
        _tile(
            tr("sentiment.usd_share"),
            f"{usd_share:.0%}",
            fx_pill,
            tr("sentiment.usd_share_help"),
        ),
    ]

    notes = []
    # Is the book's own diversification working? The stock/bond correlation in
    # the snapshot is the market's; this one is theirs.
    if "TLT" in bench_returns and not port.empty:
        own = sm.rolling_correlation(
            (1 + port).cumprod(), closes["TLT"], window=ROLL
        )
        now, then = sm.drift(own, ago=DRIFT_DAYS)
        if now == now:
            notes.append(
                tr(
                    "sentiment.book_bond_corr",
                    value=f"<b>{_num(now)}</b>",
                    prior=_num(then) if then == then else "n/a",
                )
            )
    if drag == drag and not contributions.empty:
        colour = CANDLE_UP if drag >= 0 else CANDLE_DOWN
        notes.append(
            tr(
                "sentiment.fx_note",
                value=f'<span style="color:{colour}">{_pct(drag, 2)}</span>',
            )
        )
    if not book["sector"].empty and "SPY" in closes:
        top = book["sector"].head(3)
        excess = sm.relative_strength(closes, sm.SECTOR_ETFS, "SPY", MONTH)
        leading = [
            _label(f"sentiment.sector_{name.lower().replace(' ', '_')}", name)
            for name in top.index
            if name in excess.index and excess[name] > 0
        ]
        lagging = [
            _label(f"sentiment.sector_{name.lower().replace(' ', '_')}", name)
            for name in top.index
            if name in excess.index and excess[name] <= 0
        ]
        if leading:
            notes.append(
                tr("sentiment.note_leading", names=f"<b>{', '.join(leading)}</b>")
            )
        if lagging:
            notes.append(
                tr("sentiment.note_lagging", names=f"<b>{', '.join(lagging)}</b>")
            )

    with box.container():
        st.html(
            _head(
                tr("sentiment.book_title"),
                "ag-book",
                badge=tr("sentiment.book_badge"),
                right=tr("sentiment.book_src"),
            )
            + f'<div class="ag-bk">{"".join(tiles)}</div>'
        )
        if notes:
            st.html(
                '<div class="ag-notes">'
                + "".join(f'<span class="ag-note">{n}</span>' for n in notes)
                + "</div>"
            )
        st.caption(tr("sentiment.book_help"))


# --------------------------------------------------------------- the detail
def render_indices(
    box, closes: dict[str, pd.Series], country_weights: pd.Series | None
) -> None:
    """Headline indices, ordered by the geography the reader actually holds."""
    order = sm.INDICES
    pinned = country_weights is not None and not country_weights.empty
    weights = (
        {str(k): float(v) for k, v in country_weights.items()} if pinned else {}
    )
    if pinned:
        order = tuple(sm.pin_order(sm.INDICES, country_weights))
    rows = []
    for idx in order:
        series = closes.get(idx.ticker)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        # What share of the reader's own money sits in the countries this
        # index stands for. A pinned order says "these matter to you" without
        # saying how much; this says how much.
        share = sum(weights.get(c, 0.0) for c in idx.countries)
        rows.append(
            TrendRow(
                label=idx.name,
                hint=_tip("index", _slug(idx.ticker)),
                sub=(
                    tr("sentiment.index_weight", pct=f"{share:.0%}")
                    if share >= 0.01
                    else None
                ),
                value=f"{float(clean.iloc[-1]):,.0f}",
                chips=_pct_chips(clean),
                spark=_tail(clean),
                state=sm.trend_state(clean),
            )
        )
    if not rows:
        _source_down(
            box,
            title=tr("sentiment.indices_title"),
            source=tr("sentiment.src_prices", n=len(sm.INDICES)),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key="indices",
        )
        return
    note = tr("sentiment.trend_help", n=sm.TREND_SLOW)
    if pinned:
        note = tr("sentiment.indices_pinned") + " " + note
    _table_block(
        box,
        rows,
        title=tr("sentiment.indices_title"),
        source=tr("sentiment.src_prices", n=len(sm.INDICES)),
        note=note,
        label_key="sentiment.col_index",
        value_key="sentiment.col_last",
    )


def render_gauges(box, closes: dict[str, pd.Series]) -> None:
    """Volatility gauges: level, direction, and where in their own year."""
    # A tile is "stale" relative to the freshest bar in the row, not to the
    # calendar: on a Monday morning every gauge is Friday's and none of them is
    # stale. Taken across the whole row so it does not hinge on any one symbol
    # being present.
    last_bars = [
        closes[g.ticker].dropna().index[-1]
        for g in sm.GAUGES
        if g.ticker in closes and not closes[g.ticker].dropna().empty
    ]
    newest = max(last_bars) if last_bars else None
    rows = []
    for gauge in sm.GAUGES:
        series = closes.get(gauge.ticker)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        welcome = -1 if gauge.high_is_fear else 1
        # The last column is the percentile pair rather than a 12-month change:
        # for a volatility index "where in its own year" and "where it was a
        # month ago" is the reading, and a 12-month percent change on a
        # mean-reverting series is close to meaningless. It prints uncoloured —
        # a percentile is a position, not a verdict.
        chips = _pct_chips(clean, welcome=welcome)[:3]
        now = sm.percentile_now(clean)
        then = sm.percentile_then(clean, ago=MONTH)
        if now == now:
            pair = f"p{now:.0f}" if then != then else f"p{now:.0f} ({then:.0f})"
            chips.append((pair, 0))
        stale = newest is not None and (newest - clean.index[-1]).days > 7
        rows.append(
            TrendRow(
                label=gauge.name,
                hint=_tip("gauge", _slug(gauge.ticker)),
                sub=tr(f"sentiment.gauge_{gauge.ticker.lstrip('^').lower()}_sub"),
                value=gauge.fmt.format(float(clean.iloc[-1])),
                chips=chips,
                spark=_tail(clean),
                state="stale" if stale else sm.trend_state(clean),
                dim=stale,
                note=(
                    tr(
                        "sentiment.gauge_stale",
                        date=clean.index[-1].strftime("%Y-%m-%d"),
                    )
                    if stale
                    else None
                ),
            )
        )
    if not rows:
        _source_down(
            box,
            title=tr("sentiment.risk_title"),
            source=tr("sentiment.src_gauges", n=len(sm.GAUGES)),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key="gauges",
        )
        return
    _table_block(
        box,
        rows,
        title=tr("sentiment.risk_title"),
        source=tr("sentiment.src_gauges", n=len(sm.GAUGES)),
        note=tr("sentiment.risk_help"),
        label_key="sentiment.col_gauge",
        value_key="sentiment.col_level",
        chip_labels=[*CHIP_LABELS[:3], tr("sentiment.col_pctl")],
    )


def render_rates(box, rates: dict[str, pd.Series]) -> None:
    """Yields, curve slopes and credit spreads, in basis points per horizon."""
    rows = []
    for sid, (suffix, welcome) in RATE_ROWS.items():
        series = rates.get(sid)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        rows.append(
            TrendRow(
                label=tr(f"sentiment.{suffix}"),
                hint=_tip("rate", suffix),
                # The explanation was a hover tooltip and is now a line: a
                # phone has no hover, and a 10-year TIPS yield is not
                # self-explanatory from its name on any device.
                sub=tr(f"sentiment.{suffix}_help"),
                value=f"{float(clean.iloc[-1]):.2f}%",
                chips=_bp_chips(clean, welcome=welcome),
                spark=_tail(clean),
                # A policy rate steps when a committee decides and is flat in
                # between, so a moving-average trend label on it would be noise
                # dressed as a signal.
                state=None if welcome == 0 else sm.trend_state(clean),
            )
        )
    if not rows:
        _source_down(
            box,
            title=tr("sentiment.rates_title"),
            source=tr("sentiment.src_fred", n=len(RATE_ROWS)),
            origin=ORIGIN_FRED,
            message_key="sentiment.macro_unavailable",
            retry=_rates.clear,
            key="rates",
        )
        return
    note = tr("sentiment.rates_help")
    nfci = rates.get("NFCI")
    if nfci is not None and not nfci.dropna().empty:
        clean = nfci.dropna()
        note += " " + tr(
            "sentiment.nfci_note",
            value=_num(float(clean.iloc[-1])),
            change=_num(sm.changes(clean, {"q": QUARTER}).get("q", float("nan"))),
        )
    _table_block(
        box,
        rows,
        title=tr("sentiment.rates_title"),
        source=tr("sentiment.src_fred", n=len(RATE_ROWS)),
        note=note,
        label_key="sentiment.col_rate",
        value_key="sentiment.col_level",
    )


def render_inflation(box, infl: pd.DataFrame) -> None:
    """Annual inflation per area, with the direction the trend has turned."""
    if infl.empty:
        _source_down(
            box,
            title=tr("sentiment.inflation_title"),
            source=tr("sentiment.src_inflation", n=len(macro.INFLATION_AREAS)),
            origin=ORIGIN_EUROSTAT,
            message_key="sentiment.macro_unavailable",
            retry=_inflation.clear,
            key="inflation",
        )
        return
    rows = []
    for _i, row in infl.iterrows():
        area = str(row["area"])
        headline = float(row["headline"])
        chips: list[tuple[str, int]] = []
        core = row["core"]
        chips.append((f"{core:.1f}%" if core == core else "n/a", 0))
        for column in ("prior", "six_months"):
            past = row[column]
            if past != past:
                chips.append(("n/a", 0))
                continue
            delta = headline - float(past)
            # Inflation rising is the unwelcome direction, so the sign is
            # inverted relative to a price move.
            chips.append((
                f"{delta:+.1f}pp",
                0 if delta == 0 else (-1 if delta > 0 else 1),
            ))
        chips.append((str(row["period"]), 0))
        rows.append(
            TrendRow(
                label=_label(f"sentiment.area_{area}", area),
                hint=_tip("area", area),
                value=f"{headline:.1f}%",
                chips=chips,
                spark=[float(v) for v in row["path"]],
                state=None,
            )
        )
    _table_block(
        box,
        rows,
        title=tr("sentiment.inflation_title"),
        source=tr("sentiment.src_inflation", n=len(macro.INFLATION_AREAS)),
        note=tr("sentiment.inflation_help")
        + " "
        + tr("sentiment.inflation_momentum_help"),
        label_key="sentiment.col_area",
        value_key="sentiment.col_headline",
        chip_labels=[
            tr("sentiment.col_core"),
            tr("sentiment.col_vs_prior"),
            tr("sentiment.col_vs_six"),
            tr("sentiment.col_period"),
        ],
    )


def render_rotation(
    box, factors_box, closes: dict[str, pd.Series], book: dict | None
) -> None:
    """Sector and factor leadership, joined to the reader's own weights."""
    excess_m = sm.relative_strength(closes, sm.SECTOR_ETFS, "SPY", MONTH)
    excess_q = sm.relative_strength(closes, sm.SECTOR_ETFS, "SPY", QUARTER)
    if excess_m.empty:
        _source_down(
            box,
            title=tr("sentiment.rotation_title"),
            source=tr("sentiment.src_rotation"),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key="rotation",
        )
        factors_box.clear()
        return

    bench = _benchmark_sectors()
    weights = None
    tilts = pd.Series(dtype=float)
    if book is not None and not book["sector"].empty:
        weights = book["sector"]
        if bench:
            tilts = sm.tilt(weights, pd.Series(bench, dtype=float))
    top_sector = (
        str(weights.index[0]) if weights is not None and not weights.empty else ""
    )

    rows = []
    for name in excess_m.index:
        etf = sm.SECTOR_ETFS.get(name)
        series = closes.get(etf) if etf else None
        own = float(weights.get(name, 0.0)) if weights is not None else float("nan")
        spy_weight = float(bench.get(name, float("nan"))) if bench else float("nan")
        tilt_value = (
            float(tilts.get(name, float("nan"))) if not tilts.empty else float("nan")
        )
        quarter = excess_q.get(name, float("nan"))
        chips: list[tuple[str, int]] = [
            (
                "n/a" if quarter != quarter else f"{quarter:+.2%}",
                0 if quarter != quarter else (1 if quarter > 0 else -1),
            ),
            ("n/a" if own != own else f"{own:.1%}", 0),
            ("n/a" if spy_weight != spy_weight else f"{spy_weight:.1%}", 0),
            (
                "n/a" if tilt_value != tilt_value else f"{tilt_value * 100:+.1f}pp",
                0,
            ),
        ]
        # A sector the reader does not hold is not a blank: not holding it is
        # an active underweight, and the largest ones are exactly the rows a
        # blank would hide.
        sub = None
        if weights is not None:
            if name == top_sector:
                sub = tr("sentiment.sector_top")
            elif own <= 0 and spy_weight == spy_weight and spy_weight > 0:
                sub = tr("sentiment.sector_not_held")
        rows.append(
            TrendRow(
                label=_label(
                    f"sentiment.sector_{name.lower().replace(' ', '_')}", name
                ),
                hint=_tip("sector", name.lower().replace(" ", "_")),
                sub=sub,
                value=f"{float(excess_m[name]):+.2%}",
                chips=chips,
                spark=_tail(series.dropna()) if series is not None else [],
                state=sm.trend_state(series) if series is not None else None,
            )
        )

    note = tr("sentiment.rotation_help")
    if weights is not None:
        caught = sm.rotation_capture(weights, excess_m)
        if caught == caught:
            note += " " + tr("sentiment.rotation_capture", value=_pct(caught, 2))
    _table_block(
        box,
        rows,
        title=tr("sentiment.rotation_title"),
        source=tr("sentiment.src_rotation"),
        note=note,
        label_key="sentiment.col_sector",
        value_key="sentiment.col_excess_month",
        chip_labels=[
            tr("sentiment.col_excess_quarter"),
            tr("sentiment.col_your_weight"),
            tr("sentiment.col_spy_weight"),
            tr("sentiment.col_tilt"),
        ],
    )

    pair_rows = []
    for key, first, second in sm.FACTOR_PAIRS:
        if first not in closes or second not in closes:
            continue
        ratio = (closes[first] / closes[second]).dropna()
        pair_rows.append(
            TrendRow(
                label=tr(f"sentiment.pair_{key}"),
                hint=_tip("pair", key),
                value=f"{float(ratio.iloc[-1]):.3f}",
                chips=_pct_chips(ratio),
                spark=_tail(ratio),
                state=sm.trend_state(ratio),
            )
        )
    if not pair_rows:
        factors_box.clear()
        return
    _table_block(
        factors_box,
        pair_rows,
        title=tr("sentiment.factors_title"),
        source=tr("sentiment.src_factors", n=len(sm.FACTOR_PAIRS)),
        note=tr("sentiment.factors_help"),
        label_key="sentiment.col_pair",
        value_key="sentiment.col_ratio",
    )


def render_cross(box, closes: dict[str, pd.Series]) -> None:
    """The dollar, metals, energy and crypto — the read behind the equity move."""
    rows = []
    for ticker, name, fmt in sm.MACRO_ASSETS:
        series = closes.get(ticker)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        rows.append(
            TrendRow(
                label=name,
                hint=_tip("asset", _slug(ticker)),
                sub=(
                    tr("sentiment.fx_base")
                    if ticker == "EURUSD=X"
                    else None
                ),
                value=fmt.format(float(clean.iloc[-1])),
                chips=_pct_chips(clean),
                spark=_tail(clean),
                state=sm.trend_state(clean),
            )
        )
    if not rows:
        _source_down(
            box,
            title=tr("sentiment.cross_title"),
            source=tr("sentiment.src_prices", n=len(sm.MACRO_ASSETS)),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key="cross",
        )
        return
    _table_block(
        box,
        rows,
        title=tr("sentiment.cross_title"),
        source=tr("sentiment.src_prices", n=len(sm.MACRO_ASSETS)),
        note=tr("sentiment.cross_help"),
        label_key="sentiment.col_asset",
        value_key="sentiment.col_last",
    )


# ------------------------------------------------------------------- the load
# Four stages, each filling the slots it unblocks the moment its fetch returns.
# The order is by what the page owes the reader soonest, not by page order:
# prices arrive first and light up the tabs that need nothing else, then the
# FRED pull completes the composite, then the ledger personalises what it can,
# then Eurostat fills the last tab. A stage that fails resolves its own slots
# with a reason and the rest of the page carries on.

# --- stage 1: prices. One bulk download of ~50 symbols.
closes: dict[str, pd.Series] = {}
try:
    closes = _closes(HISTORY)
except (YFRateLimitError, URLError) as exc:
    # Throttled or unreachable: the toast says which, and every card that
    # needed prices says so in place of its content.
    notices.data_toast(exc)
except Exception:
    closes = {}

if closes:
    render_gauges(SLOTS["gauges"], closes)
    render_cross(SLOTS["cross"], closes)
else:
    # Covers the exceptions above and the third path neither of them sees: a
    # fetch that succeeded and returned nothing. Every reserved slot has to be
    # resolved or its shimmer outlives the load.
    _TAB_TITLES = {key: title for key, title, _badge, _rows in DETAIL_TABS}
    for _name in ("gauges", "cross", "indices", "rotation"):
        _source_down(
            SLOTS[_name],
            title=tr(_TAB_TITLES[_name]),
            source=tr("sentiment.src_yahoo"),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key=_name,
        )
    SLOTS["factors"].clear()

# --- stage 2: FRED. Small CSVs behind a six-hour disk cache, so this is
# usually instant; the composite's credit leg and the whole rates tab wait on
# it, and the composite falls back to an ETF proxy if it never arrives.
rates: dict[str, pd.Series] = {}
pulse = sm.Pulse(score=float("nan"), missing=sm.COMPONENT_KEYS)
if closes:
    try:
        rates = _rates()
    except Exception:
        rates = {}
    pulse = render_pulse(SLOTS["pulse"], closes, rates)
    render_components(SLOTS["components"], pulse)
    render_snapshot(SLOTS["snapshot"], closes, rates)
else:
    for _name, _title, _anchor in (
        ("pulse", "sentiment.pulse_title", "ag-pulse"),
        ("components", "sentiment.why_title", "ag-why"),
        ("snapshot", "sentiment.snapshot_title", "ag-snapshot"),
    ):
        _source_down(
            SLOTS[_name],
            title=tr(_title),
            source=tr("sentiment.src_derived"),
            origin=ORIGIN_YAHOO,
            message_key="sentiment.prices_unavailable",
            retry=_closes.clear,
            key=_name,
            anchor=_anchor,
        )
if rates:
    render_rates(SLOTS["rates"], rates)
else:
    _source_down(
        SLOTS["rates"],
        title=tr("sentiment.rates_title"),
        source=tr("sentiment.src_fred", n=len(RATE_ROWS)),
        origin=ORIGIN_FRED,
        message_key="sentiment.macro_unavailable",
        retry=_rates.clear,
        key="rates",
    )

# --- stage 3: the ledger. The slowest stage by far — a share-matching replay,
# a second price download for the held names, and one Yahoo profile fetch per
# holding for the sector/country/currency splits. Four blocks wait on it, and
# the indices only when there is an account whose geography could reorder them:
# an anonymous visitor gets that tab at stage 1 speed instead.
book = None
pins_possible = auth.is_logged_in()
if closes and not pins_possible:
    render_indices(SLOTS["indices"], closes, None)

if pins_possible:
    _db = str(auth.user_paths().db)
    try:
        _mtime = db_mtime(_db)
        _held = tuple(
            sorted({p.ticker for p in ledger_state(_db, _mtime, REPORT_CCY)[1]})
        )
        if _held:
            book = _book(_held, _db, _mtime)
    except (YFRateLimitError, URLError) as exc:
        notices.data_toast(exc)
    except Exception:
        book = None
    if closes:
        render_indices(
            SLOTS["indices"], closes, book["country"] if book else None
        )

render_side(SLOTS["side"], closes, book, pulse)
if closes:
    render_rotation(SLOTS["rotation"], SLOTS["factors"], closes, book)
render_book(SLOTS["book"], closes, book)

# --- stage 4: Eurostat. Nothing else depends on it, so it goes last and its
# tab is the only one still shimmering while it runs.
try:
    _infl = _inflation()
except Exception:
    _infl = pd.DataFrame()
render_inflation(SLOTS["inflation"], _infl)

st.caption(tr("sentiment.sources", stamp=macro.as_of()))
