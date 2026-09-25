"""Sector screen — a comparable cohort per sector, and the best three in it.

Replaces the watchlist screener, which could only rank names you had already
chosen. Here the cohort is built for you: the sector ETF's basket, widened
with listed companies outside the US, scanned nightly (stocks sector-scan) and
scored by the same percentile ranking the comps table uses.

What the podium claims, and what it does not: it is the best three *of this
cohort*, on valuation and quality only. No momentum, no analyst targets, no
margin of safety. The help text under it says so, because a medal invites the
opposite reading.

Reading order is the layout's whole job. The podium is the reason to open this
page, so it comes first; the written read sits under it; the cohort table —
seventeen rows nobody scans top to bottom — comes last.
"""

from __future__ import annotations

import streamlit as st
from yfinance.exceptions import YFRateLimitError

from stocks.analysis.screener import (
    DEFAULT_COLUMNS,
    LOWER_IS_BETTER,
    Filter,
    apply_filters,
    format_frame,
    metrics_frame,
    rank,
)
from stocks.analysis.sectors import SECTORS, load_scan, scan_sector
from stocks.analysis.sentiment import SECTOR_ETFS
from stocks.web import auth, css, empty, notices, sector_ui
from stocks.web.i18n import has
from stocks.web.i18n import t as tr
from stocks.web.kpi_text import kpi_desc, kpi_label
from stocks.web.portfolio_data import db_mtime, held_tickers
from stocks.web.tables import responsive_ticker_table_html, ticker_cell
from stocks.web.widgets import is_mobile

_MOBILE = is_mobile()
_NONCE = "sector_nonce"      # per-sector cache buster for a live rescan
_PENDING = "sector_rescan"   # the sector a click asked to rescan, consumed below

# The podium's own rules. Three places in one card rather than three nested
# cards: a bordered tile inside a bordered card is the "cards inside cards"
# shape that makes a dense page unreadable, and the rule between columns
# separates them for free. Every value below is a DS token — the rank badge
# borrows the brand accent for first place and the sunken surface for the
# other two, so the podium reads in one glance without colour it invented.
_CSS = """
.ag-pod { display:flex; gap:.55rem; align-items:baseline; }
.ag-pod-n {
  flex:0 0 auto; min-width:1.35rem; height:1.35rem; line-height:1.35rem;
  text-align:center; border-radius:var(--ag-radius-xs);
  font-size:var(--ag-fs-2xs); font-weight:700;
  background:var(--ag-surface-sunken); color:var(--ag-text-muted);
}
.ag-pod-1 { background:var(--ag-brand-accent); color:var(--ag-surface-page); }
.ag-pod-score {
  font-size:var(--ag-fs-2xl); font-weight:700; line-height:1.15;
  color:var(--ag-text-primary); font-variant-numeric:tabular-nums;
}
.ag-pod-score span {
  font-size:var(--ag-fs-xs); font-weight:500; color:var(--ag-text-muted);
}
.ag-pod-why {
  font-size:var(--ag-fs-xs); color:var(--ag-text-muted);
  font-variant-numeric:tabular-nums;
}
.ag-pod-why i { font-style:normal; margin:0 .4rem; opacity:.55; }
@media (min-width: 641px) {
  [data-testid="stHorizontalBlock"]:has(.ag-pod) [data-testid="stColumn"]
    + [data-testid="stColumn"] {
    border-left:1px solid var(--ag-border); padding-left:1.1rem;
  }
}
"""

st.title(tr("sector.title"))


def _label(sector: str) -> str:
    """The sector's name in the reader's language.

    Pulse already ships all eleven (its rotation table names the same buckets),
    so this page adds no copy of its own for them.
    """
    key = f"sentiment.sector_{sector.lower().replace(' ', '_')}"
    return tr(key) if has(key) else sector


@st.cache_data(ttl=3600, show_spinner=False)
def _stored(_nonce: int) -> dict:
    """The nightly scan, restored from the bucket at most once an hour.

    `_nonce` is bumped by the refresh button so a live rescan is visible
    immediately instead of waiting out the TTL.
    """
    return load_scan()


@st.cache_data(ttl=3600, show_spinner=False)
def _live(sector: str, _nonce: int):
    """One sector rescanned on demand — the whole cohort, straight from Yahoo."""
    return scan_sector(sector)


def _request_rescan(name: str) -> None:
    """Ask for a live rescan of `name` on the next run.

    A session flag rather than the button's own return value, because two
    things ask for this — the header button and the empty card's only way out
    — and a callback's click is over before the script that would act on it
    starts.
    """
    st.session_state[_PENDING] = name


css.inject(_CSS)

# The sector picker is the whole navigation of this page, so it goes first and
# stays put: everything below is a function of it. The refresh sits beside it
# but deliberately quieter — it is a rare action that costs a minute of Yahoo.
_pick, _act = st.columns([3, 1], vertical_alignment="bottom")
sector = _pick.selectbox(tr("sector.pick"), SECTORS, format_func=_label)
# Full width in its column, which is what every other paired control in the
# app does. Sizing it off `is_mobile()` was tried and reverted: that is UA
# sniffing, it misses a narrow window entirely, and a conditional that does not
# reliably fire is worse than no conditional.
_act.button(
    tr("sector.refresh"), icon=":material/refresh:", width="stretch",
    key=f"sector_refresh_{sector}", on_click=_request_rescan, args=(sector,),
)

refresh = st.session_state.pop(_PENDING, "") == sector
nonces = st.session_state.setdefault(_NONCE, {})
if refresh:
    nonces[sector] = nonces.get(sector, 0) + 1
nonce = nonces.get(sector, 0)

scan = None
if refresh:
    # A line, not a spinner: loading state in this app is a skeleton in the
    # shape of what is coming. This names which sector is being rebuilt, since
    # a live rescan is the one action here that takes a minute, and it sits
    # where the click was rather than under the content it will replace.
    _status = st.empty()
    _status.caption(tr("sector.refreshing", sector=_label(sector)))
    try:
        scan = _live(sector, nonce)
    except (YFRateLimitError, OSError) as exc:
        # The stored cohort is still good; say the refresh failed and use it.
        notices.data_toast(exc)
        st.caption(tr("sector.source_down", sector=_label(sector)))
    _status.empty()
if scan is None:
    scan = _stored(nonce).get(sector)

if scan is None or not scan.tickers:
    empty.state(
        tr("sector.empty_title"),
        tr("sector.empty_body"),
        event="sector.no_scan",
        icon="donut_small",
        on_click=lambda: _request_rescan(sector),
        key=f"sector_scan_now_{sector}",
        label=tr("sector.refresh"),
        cta_icon="refresh",
        preview="table",
        preview_kw={"rows": 5, "cols": 6},
    )
    st.stop()

st.caption(tr("sector.as_of", date=scan.as_of))

_db = str(auth.user_paths().db)
held = tuple(held_tickers(_db, db_mtime(_db)))

# ------------------------------------------------------------------ the podium


def _why(ticker: str) -> str:
    """The two figures that carry a place, in the units the verdict prints.

    ROIC and P/E rather than the full KPI row: the score is a mean of
    eighteen, and quoting all of them under a headline number explains
    nothing. These two say "compounds well" and "costs this much", which is
    the trade the reader is actually making between the three.
    """
    # `scan` is never None below the empty state above — but that guard ends
    # the run with `st.stop()`, which is a runtime fact and not one a reader
    # (or a checker) can see from inside a function defined after it.
    metrics = scan.metrics if scan else []
    row = next(
        (m for m in metrics if str(m.get("ticker", "")).upper() == ticker.upper()),
        {},
    )

    def num(key: str, suffix: str, scale: float = 1.0) -> str:
        value = row.get(key)
        if not isinstance(value, (int, float)) or value != value:
            return f"{kpi_label(key)} n/a"
        return f"{kpi_label(key)} {value * scale:,.1f}{suffix}"

    return "<i>·</i>".join((num("roic", "%", 100), num("pe_ttm", "x")))


with st.container(border=True, key="ag_sector_podium"):
    st.subheader(tr("sector.podium_title"))
    if not scan.podium:
        st.caption(tr("sector.no_podium"))
    else:
        places = st.columns(len(scan.podium))
        for place, (box, ticker) in enumerate(
            zip(places, scan.podium, strict=False), start=1
        ):
            with box:
                badge = "ag-pod-n ag-pod-1" if place == 1 else "ag-pod-n"
                st.html(
                    f'<div class="ag-pod"><span class="{badge}">{place}</span>'
                    f"<span>{ticker_cell(ticker)}</span></div>"
                )
                score = scan.scores.get(ticker)
                shown = f"{score * 100:.0f}" if isinstance(score, float) else "n/a"
                st.html(
                    f'<div class="ag-pod-score">{shown}<span>/100</span></div>'
                    f'<div class="ag-pod-why">{_why(ticker)}</div>'
                )
    st.caption(tr("sector.podium_help", cohort=len(scan.tickers)))

# ----------------------------------------------------------------- the verdict
# Reserved and filled back to back: nothing slow sits between them, but the
# slot is what the polling fragment redraws into when a generation lands after
# the script has finished.
sector_ui.render(sector_ui.reserve(), scan, held)

# ------------------------------------------------------------------- the table

df = metrics_frame(list(scan.metrics))

st.subheader(tr("sector.table_title"))
st.caption(
    tr("sector.cohort_caption", n=len(scan.tickers), etf=SECTOR_ETFS.get(sector, ""))
)
label = {k: kpi_label(k) for k in df.columns}
options = list(df.columns)

# Phones: the sidebar starts collapsed — put the controls in the main area,
# folded into an expander above the results they filter.
if _MOBILE:
    _controls = st.expander(tr("sector.screen_filters"), icon=":material/tune:")
else:
    _controls = st.sidebar

default_cols = [c for c in DEFAULT_COLUMNS if c in options]
if _MOBILE:
    default_cols = default_cols[:4]

with _controls:
    if not _MOBILE:
        st.header(tr("sector.screen"))
    sort_by = st.selectbox(
        tr("sector.rank_by"),
        options,
        index=options.index("roic") if "roic" in options else 0,
        format_func=lambda k: label.get(k, k),
    )
    if kpi_desc(sort_by):
        st.caption(kpi_desc(sort_by))
    ascending = st.checkbox(tr("sector.ascending"), value=sort_by in LOWER_IS_BETTER)
    columns = st.multiselect(
        tr("sector.columns"),
        options,
        default=default_cols,
        format_func=lambda k: label.get(k, k),
    )
    st.divider()
    st.caption(tr("sector.filters_caption"))
    filters: list[Filter] = []
    for key, kind, default in (
        ("pe_ttm", "max", 40.0),
        ("roic", "min", 0.15),
        ("fcf_yield", "min", 0.03),
    ):
        if key not in options:
            continue
        if st.checkbox(
            f"{label[key]} {'≤' if kind == 'max' else '≥'}",
            key=f"chk_{key}",
            help=kpi_desc(key) or None,
        ):
            val = st.number_input(label[key], value=default, key=f"val_{key}")
            filters.append(Filter(key, kind, val))

view = apply_filters(df, filters)
view = rank(view, sort_by, ascending=ascending)
if columns:
    view = view[[c for c in columns if c in view.columns]]

st.caption(tr("sector.pass_caption", n=len(view), total=len(df)))
disp = format_frame(view).rename(columns=label)
disp.insert(0, "ticker", disp.index)

# The ranked-by metric is the row's headline number on a phone; the rest go in
# the dim line under the symbol. Switched by viewport WIDTH, not User-Agent:
# a narrow desktop window and an iPad (which sends no "Mobi") both need the
# rows, and only responsive_ticker_table_html gives them that.
_lead = label.get(sort_by, sort_by)
if _lead not in disp.columns:
    _lead = next((c for c in disp.columns if c != "ticker"), "")
_sub = [c for c in disp.columns if c not in ("ticker", _lead)]
st.html(
    responsive_ticker_table_html(
        disp,
        mobile={
            "value": _lead,
            "sub": tuple(_sub),
            "sub_labels": {c: c for c in _sub},
            "wrap": True,
        },
        mobile_names=True,
    )
)
st.download_button(
    tr("sector.download_csv"),
    df.to_csv().encode(),
    f"{sector.lower().replace(' ', '_')}.csv",
    "text/csv",
    icon=":material/download:",
)

with st.expander(tr("sector.metrics_help"), icon=":material/help:"):
    for k in options:
        if kpi_desc(k):
            st.markdown(f"**{kpi_label(k)}** — {kpi_desc(k)}")
