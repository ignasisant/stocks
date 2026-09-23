"""Import transactions from a broker statement into the ledger.

The user picks the source platform (see portfolio/platforms.py for the
registry — Revolut CSV/PDF, generic ledger-format CSV, …); parsing is
delegated to that platform, everything downstream is shared.

Flow: pick platform -> upload -> parse (no writes) -> validate ->
tiered preview -> commit.

The preview separates rows into three tiers so a bad export can't corrupt
cost basis silently:

* importable — parsed clean; committed on button press
* warnings   — importable but flagged (unknown ticker, possible duplicate)
* rejected   — failed validation (future date, oversell, malformed ticker);
  quarantined, never committed. Fix the export or add them manually.

Rows the parser skips by design (cash movements, fees, tax corrections) are
listed separately; stock splits are auto-resolved to a ratio when the held
quantity at the split date makes the ratio unambiguous.

Two repairs run beside the import, because a statement cannot carry what they
fix: splits the book never heard about (`stocks.portfolio.corporate`, on
request — it prices every holding against Yahoo) and shares that only changed
broker but read as a sale (`stocks.portfolio.transfers`, every run — it reads
the ledger alone). Both propose; neither writes until the reader says so.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from stocks import obs
from stocks.data import fetch
from stocks.portfolio import (
    corporate,
    demo,
    diagnostics,
    last_import,
    platforms,
    transfers,
)
from stocks.portfolio.ledger import add_many, all_transactions, clear, delete_many
from stocks.portfolio.validate import known_tickers, validate
from stocks.web import auth, logos, skeletons, tx_text
from stocks.web.i18n import t as tr
from stocks.web.widgets import (
    brand_logo,
    data_table,
    is_mobile,
    stacked_table_html,
    ticker_table_html,
)

# Imports write the personal ledger — no anonymous access.
auth.require_login()

st.title(tr("import.title"))

# Everything on this page reads/writes the session user's own book.
paths = auth.user_paths()

st.caption(tr("import.intro_caption"))

ledger = all_transactions(paths.db)
if st.session_state.pop("imports_cleared", False):
    st.toast(tr("import.toast_cleared"), icon=":material/delete_forever:")
# A commit reruns the page with its inputs emptied (see the commit button), so
# the outcome is carried across that rerun rather than printed under a preview
# that no longer exists. What the reader lands on instead is the last-import
# block below: the same numbers, plus the undo.
_committed = st.session_state.pop("import_committed", None)
if _committed:
    st.success(tr("import.commit_success", **_committed))
    st.caption(tr("import.commit_help"))

demo_rows = [t for t in ledger if demo.is_demo(t)]

with st.container(horizontal=True, vertical_alignment="center"):
    st.metric(tr("import.metric_in_ledger"), len(ledger))
    with st.popover(
        tr("import.clear_all_imports"),
        icon=":material/delete_forever:",
        disabled=not ledger,
    ):
        st.markdown(tr("import.clear_all_confirm", n=len(ledger)))
        if st.button(
            tr("import.delete_everything"),
            type="primary",
            icon=":material/delete_forever:",
        ):
            clear(paths.db)
            last_import.forget(paths.last_import)
            st.session_state["imports_cleared"] = True
            st.rerun()


if demo_rows:
    # Not a warning here: on this page the demo book is on its way out, and
    # what the reader needs to know is that importing is what removes it.
    st.caption(tr("import.demo_rows_caption", n=len(demo_rows)))


def _tx_frame(txs) -> pd.DataFrame:
    # Display only — the rows committed below come from `validation`, so the
    # translated verb never reaches the ledger.
    return pd.DataFrame(
        {
            "date": t.date, "ticker": t.ticker,
            "action": tx_text.action_label(t.action),
            "quantity": t.quantity, "price": t.price, "fee": t.fee,
            "currency": t.currency, "note": t.note,
        }
        for t in txs
    )


# Shared Positions-style table look for the previews.
_TX_FMT = {"quantity": "{:,.4f}", "price": "{:,.2f}", "fee": "{:,.2f}"}
_TX_LEFT = ("date", "action", "currency", "note")
_TX_COLS = ("date", "ticker", "action", "quantity", "price", "fee",
            "currency", "note", "warnings", "errors")


def _tx_table(frame: pd.DataFrame, *, rich: bool = True) -> None:
    # rich=False skips the logo/name lookup — rejected rows carry malformed
    # symbols, and resolving each one costs a network round-trip.
    # Eight columns pan off a phone. With a resolvable symbol the preview goes
    # dense (quantity + price on the right, date/action/notes on the wrapping
    # dim line); rejected rows have no symbol to hang a dense row off, so they
    # stack as label/value cards instead.
    if not rich and is_mobile():
        st.html(
            stacked_table_html(
                frame, title="ticker", fmt=_TX_FMT,
                labels=tx_text.labels(*_TX_COLS),
            )
        )
        return
    st.html(
        ticker_table_html(
            frame,
            fmt=_TX_FMT,
            labels=tx_text.labels(*_TX_COLS),
            ticker_col="ticker" if rich else None,
            left_cols=_TX_LEFT + ("warnings", "errors"),
            mobile={
                "value": "quantity",
                "delta": "price",
                "sub": ("date", "action")
                + tuple(
                    c for c in ("note", "warnings", "errors") if c in frame.columns
                ),
                "wrap": True,
            },
        )
    )


# ------------------------------------------------- corporate actions the book missed
# A statement prints trades and not the 20:1 split between them, so a position
# bought before one and never sold keeps a pre-split share count and a pre-split
# cost basis forever — the import-time rescue in validate.py only fires when a
# *sell* comes up short, and a position nobody sold never comes up short.
# stocks.portfolio.corporate finds them from the buy price instead.
#
# The scan costs a Yahoo round-trip per ticker, so it runs on request and the
# answer is held for the session rather than re-priced on every rerun.
_SPLIT_SCAN = "corporate_split_scan"
_SPLIT_COLS = ("ticker", "date", "ratio", "held_before", "held_after", "evidence")

real_rows = demo.without(ledger)

with st.container(horizontal=True, vertical_alignment="center"):
    _scan_now = st.button(
        tr("import.scan_splits"),
        icon=":material/troubleshoot:",
        disabled=not real_rows,
    )
    st.caption(tr("import.scan_splits_help"))

if _scan_now:
    # The shimmer takes the shape of the findings table, in the place it will
    # appear — a Yahoo round-trip per holding is seconds, not milliseconds.
    with skeletons.slot("table", rows=3, cols=5, title=True):
        st.session_state[_SPLIT_SCAN] = corporate.missing_splits(
            real_rows, splits=fetch.splits, close_on=fetch.close_on
        )
    st.rerun()

_gaps = st.session_state.get(_SPLIT_SCAN)
if _gaps is not None and not _gaps:
    st.success(tr("import.scan_splits_clean"))
elif _gaps:
    st.warning(tr("import.splits_found", n=len(_gaps)))
    data_table(
        pd.DataFrame(
            {
                "ticker": m.ticker,
                "date": m.tx.date,
                "ratio": f"{m.ratio:g}:1",
                "held_before": m.held_before,
                "held_after": m.held_after,
                "evidence": tr(
                    "import.split_evidence",
                    price=f"{m.priced_at:,.2f}",
                    date=m.priced_on,
                    close=f"{m.market_close:,.2f}",
                ),
            }
            for m in _gaps
        ),
        title="ticker",  # phone cards head on the symbol, like every other table
        fmt={"held_before": "{:,.4f}", "held_after": "{:,.4f}"},
        labels=tx_text.labels(*_SPLIT_COLS),
        hide_index=True,
    )
    if st.button(
        tr("import.apply_splits", n=len(_gaps)),
        type="primary",
        icon=":material/call_split:",
    ):
        add_many([m.tx for m in _gaps], paths.db)
        st.session_state.pop(_SPLIT_SCAN, None)
        st.session_state["splits_applied"] = len(_gaps)
        st.rerun()
    st.caption(tr("import.apply_splits_help"))

if n_applied := st.session_state.pop("splits_applied", 0):
    st.toast(tr("import.toast_splits_applied", n=n_applied), icon=":material/call_split:")


# ------------------------------------------------ shares that only changed broker
# A statement cannot say "these shares moved" — DEGIRO prints the departure as
# a sale at the market price, and the receiving broker prints the arrival as a
# balance. Left alone the book reports a gain nobody made and restarts a
# holding period that never stopped. stocks.portfolio.transfers finds the pairs
# from the one thing a sale-and-repurchase could not produce: an arrival
# carrying the basis the shares already had. It reads the ledger and nothing
# else, so unlike the split scan there is no network call and no button — the
# question is answered on every run.
_MOVE_COLS = ("ticker", "quantity", "from", "to", "date", "gain", "basis")

# logos.yahoo_symbol is the app's own ISIN -> symbol lookup: watchlist
# aliases first, then Yahoo's, cached on disk and in session. transfers only
# calls it for a row that already looks like a move in every other way.
_moves = transfers.propose(real_rows, resolve=logos.yahoo_symbol)
if _moves:
    st.warning(tr("import.moves_found", n=len(_moves)))
    data_table(
        pd.DataFrame(
            {
                "ticker": m.ticker_in,
                "quantity": m.quantity,
                "from": m.broker_out,
                "to": m.broker_in,
                "date": m.date_out,
                "gain": tr(
                    "import.move_gain",
                    amount=f"{m.phantom_gain:,.2f} {m.currency}",
                ),
                "basis": tr(
                    "import.move_basis",
                    basis=f"{m.basis_in:,.2f}",
                    sold=f"{m.booked_at:,.2f}",
                ),
            }
            for m in _moves
        ),
        title="ticker",
        fmt={"quantity": "{:,.4f}"},
        labels=tx_text.labels(*_MOVE_COLS),
        hide_index=True,
    )
    if st.button(
        tr("import.apply_moves", n=len(_moves)),
        type="primary",
        icon=":material/swap_horiz:",
    ):
        # The departure stops being a sale, and both labels become one
        # security so the replay can see that the shares never left. Shared
        # with the assistant's copy of this offer (transfers.accept).
        st.session_state["moves_applied"] = transfers.accept(_moves, paths.db)
        st.rerun()
    st.caption(tr("import.apply_moves_help"))

if n_moves := st.session_state.pop("moves_applied", 0):
    st.toast(tr("import.toast_moves_applied", n=n_moves), icon=":material/swap_horiz:")


def _platform_option_md(key: str) -> str:
    """Segmented-control label: brand logo (markdown image) + name."""
    p = platforms.by_key(key)
    src = brand_logo(p.key, p.domain)
    img = f"![{p.label}]({src}) " if src else ""
    return f"{img}{p.label}"


def _pick_platform() -> platforms.Platform:
    """The source-platform picker, one control per form factor.

    Options are keys, not Platform objects: Streamlit's default-value check
    converts a dataclass default via its dataframe logic (exploding it into
    field values), which raises "default not part of the options".

    Seven brands, each a logo plus a name as long as "Interactive Brokers",
    do not fit one phone-width row: the mobile stylesheet joins segmented
    cells edge to edge (`flex: 1 1 0`) and refuses to ellipsize their labels,
    so the strip overruns the viewport and the brands read as a smear. Phones
    get a dropdown instead — plain text, because a selectbox option renders
    no markdown image, and its first entry is the same default.
    """
    keys = [p.key for p in platforms.PLATFORMS]
    if is_mobile():
        return platforms.by_key(
            st.selectbox(
                tr("import.importing_from"),
                keys,
                format_func=lambda k: platforms.by_key(k).label,
            )
        )
    return platforms.by_key(
        st.segmented_control(
            tr("import.importing_from"),
            keys,
            format_func=_platform_option_md,
            default=platforms.PLATFORMS[0].key,
            required=True,  # clicking the active segment must not deselect it
        )
    )


platform = _pick_platform()

ASSETS = Path(__file__).resolve().parents[1] / "assets"
_SAMPLE = "import_sample"  # session key: the staged example statement


class _Sample:
    """The shipped example statement, shaped like an st.file_uploader value.

    Everything below this point reads `.name` and `.getvalue()` and nothing
    else, so the example rides the identical path a real upload does — parse,
    validate, preview, commit, last-import record, undo. A separate "load demo
    data" route would be the thing that drifts from the real one, and would
    also have to invent a ledger; this is a statement, parsed for real.
    """

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _sample_offer(platform: platforms.Platform) -> None:
    """Offer the example statement to an account with nothing to import yet.

    Only on the empty path: an account that already has a ledger has no use
    for it, and a button that adds someone else's trades to a real book would
    be a trap rather than a tour.
    """
    if not platform.sample:
        return
    path = ASSETS / platform.sample
    if not path.is_file():  # a trimmed deploy — say nothing rather than fail
        return
    st.caption(tr("import.sample_caption", platform=platform.label))
    if st.button(tr("import.sample_button"), icon=":material/science:"):
        st.session_state[_SAMPLE] = (platform.key, path.name, path.read_bytes())
        st.rerun()


# Both input widgets carry a nonce the commit below bumps. Streamlit keeps a
# widget's value across reruns, so without it a committed statement stays in
# the box: every later click re-parses it, re-enables the commit button, and
# one stray press writes the same batch twice (flagged as duplicates, not
# refused). Changing the key is the only way to empty a file_uploader from
# Python — its value cannot be assigned after instantiation.
_NONCE = "import_input_nonce"
_nonce = st.session_state.get(_NONCE, 0)

# Key the uploader by platform too, so switching platforms drops the staged
# file — a statement must never be parsed by another platform's parser.
uploaded = st.file_uploader(
    tr(
        "import.uploader_label",
        platform=platform.label,
        types=", ".join(t.upper() for t in platform.file_types),
    ),
    type=list(platform.file_types),
    key=f"upload_{platform.key}_{_nonce}",
)

XSRF_COOKIE = "_streamlit_xsrf"


def _upload_is_blocked() -> bool:
    """True when this browser cannot complete an upload, whatever it clicks.

    Streamlit PUTs the file to /_stcore/upload_file with an XSRF header that
    has to match the `_streamlit_xsrf` cookie, and answers 403 when it does
    not (starlette_routes._check_xsrf). A browser that drops the cookie —
    the app framed inside another origin, hardened privacy settings — fails
    that check in the browser's network tab, where the page never sees it:
    Python is handed "no file", exactly like an untouched widget. The cookie
    itself is readable from here, so this one failure mode can be named
    before the reader burns a click on it.

    No cookies at all means no browser (AppTest, bare mode), not a blocked
    one — a false alarm on the working path would be worse than silence.
    """
    try:
        if not st.get_option("server.enableXsrfProtection"):
            return False
        cookies = st.context.cookies
    except Exception:  # noqa: BLE001 — a hint, never a reason to fail the page
        return False
    return bool(cookies) and XSRF_COOKIE not in cookies


# Second door into the same pipeline, for a reader whose browser will not hand
# over a file at all: the 403 above, managed Chrome with file dialogs switched
# off (FileSelectionDialogsAllowed), a work phone that does the same. All of
# them reach Python as "no file", so the page cannot ask — it can only offer a
# route that needs no dialog, no cookie and no PUT. The pasted statement
# becomes the same `.name`/`.getvalue()` object the uploader hands back, so
# parse, validation, preview, commit and undo are the ones already written
# below.
_B64 = re.compile(r"[A-Za-z0-9+/=\s]+")
# Enough of a blob that a short CSV of pure letters can't be mistaken for one.
_B64_MIN = 64
_MAGIC = ((b"%PDF", "pdf"), (b"PK\x03\x04", "xlsx"))


def _pasted_file(text: str) -> tuple[str, bytes] | str:
    """(filename, bytes) for pasted text, or the extension it cannot be given.

    A CSV pastes as itself. A PDF or XLSX has no text form at all, so the way
    in for those is base64 (`base64 -i statement.pdf | pbcopy`) — recognised
    by decoding it and reading the magic bytes, not by trusting a label. The
    extension has to be one this platform parses: the filename is what picks
    the branch inside the parser (revolut PDF vs CSV, clicktrade xlsx vs
    csv), so handing it a PDF it does not read would fail deep in a parser
    instead of here.
    """
    compact = "".join(text.split())
    if len(compact) >= _B64_MIN and _B64.fullmatch(compact):
        try:
            blob = base64.b64decode(compact, validate=True)
        except (binascii.Error, ValueError):
            blob = b""
        for magic, ext in _MAGIC:
            if blob.startswith(magic):
                if ext not in platform.file_types:
                    return ext
                return f"pasted.{ext}", blob
    return "pasted.csv", text.encode("utf-8")


_blocked = _upload_is_blocked()
with st.expander(
    tr("import.paste_expander"),
    icon=":material/content_paste:",
    expanded=_blocked,
):
    if _blocked:
        st.warning(tr("import.paste_blocked"))
    st.caption(tr("import.paste_caption"))
    # Keyed by platform for the same reason the uploader is: switching
    # platform must not leave one broker's statement in another's parser.
    _pasted = st.text_area(
        tr("import.paste_label", platform=platform.label),
        key=f"paste_{platform.key}_{_nonce}",
        height=160,
        placeholder=tr("import.paste_placeholder"),
    ).strip()

# Which door it came through, recorded on the diagnostic: a reader who pastes
# is usually a reader whose upload could not work, and that is a fact worth
# having as a number rather than as a support message.
_surface = "import"
if uploaded is None and _pasted:
    _file = _pasted_file(_pasted)
    if isinstance(_file, str):  # a format this platform has no parser for
        st.error(
            tr(
                "import.paste_wrong_type",
                kind=_file.upper(),
                platform=platform.label,
                types=", ".join(t.upper() for t in platform.file_types),
            )
        )
        st.stop()
    uploaded = _Sample(*_file)
    _surface = "paste"

# Kept across reruns, not consumed on the run that staged it: there are two
# interactions (the wipe checkbox, the commit button) between staging the
# example and importing it, and st.file_uploader's own value survives those
# the same way. Dropped when a real upload arrives or the platform changes —
# a statement must never be parsed by another platform's parser — and cleared
# on commit below.
staged = st.session_state.get(_SAMPLE)
if uploaded is not None or (staged and staged[0] != platform.key):
    st.session_state.pop(_SAMPLE, None)
    staged = None
if uploaded is None and staged is not None:
    uploaded = _Sample(staged[1], staged[2])
if uploaded is None:
    record = last_import.load(paths.last_import)
    if record is None:
        st.info(platform.hint)
        if len(demo_rows) == len(ledger):  # nothing real to lose
            _sample_offer(platform)
        st.stop()

    # Committed imports live in the ledger (SQLite) — nothing to re-upload.
    # Show what the last commit did and offer to undo exactly that batch.
    st.subheader(tr("import.last_import"))
    when = datetime.fromisoformat(record.imported_at).strftime("%Y-%m-%d %H:%M UTC")
    st.markdown(
        tr(
            "import.last_import_summary",
            filename=record.filename,
            platform=platforms.by_key(record.platform).label,
            n=len(record.tx_ids),
            when=when,
        )
        + (tr("import.ledger_wiped_suffix") if record.wiped else "")
    )

    batch_ids = set(record.tx_ids)
    still_in_ledger = [t for t in ledger if t.id in batch_ids]
    if len(still_in_ledger) < len(record.tx_ids):
        st.caption(
            tr("import.rows_no_longer", n=len(record.tx_ids) - len(still_in_ledger))
        )
    if still_in_ledger:
        with st.expander(tr("import.imported_rows_still", n=len(still_in_ledger))):
            _tx_table(_tx_frame(still_in_ledger))

    with st.container(horizontal=True):
        if st.button(
            tr("import.clear_last_import", n=len(still_in_ledger)),
            icon=":material/delete:",
            disabled=not still_in_ledger,
        ):
            delete_many(record.tx_ids, paths.db)
            last_import.forget(paths.last_import)
            st.rerun()
        if st.button(tr("import.dismiss_record"), icon=":material/close:"):
            last_import.forget(paths.last_import)
            st.rerun()
    st.caption(tr("import.last_import_help"))
    st.stop()


@st.cache_data(ttl=86400, show_spinner=False)
def _ticker_exists(ticker: str) -> bool | None:
    """Live yfinance existence check for symbols the EDGAR map doesn't know."""
    try:
        import yfinance as yf

        return bool(yf.Ticker(ticker).fast_info.get("lastPrice"))
    except Exception:
        return None  # network down ≠ ticker invalid


_raw = uploaded.getvalue()
# Streamlit reruns this whole script on every click, so an unguarded report
# would file one diagnostic per checkbox toggle. Key it on the bytes: one
# upload, one fingerprint, however many reruns it survives.
_DIAGNOSED = "_import_diagnosed"
# Keyed on the platform too, not the bytes alone: picking the wrong broker,
# failing, and picking another is the most informative thing a reader does
# here, and a bytes-only key would record only the first attempt.
_digest = f"{hashlib.sha256(_raw).hexdigest()[:12]}:{platform.key}"
_upload_name = uploaded.name


def _diagnose(**outcome) -> None:
    """Record what this statement did, anonymised (portfolio.diagnostics)."""
    if st.session_state.get(_DIAGNOSED) == _digest:
        return
    st.session_state[_DIAGNOSED] = _digest
    diagnostics.report(
        platform.key, _upload_name, _raw, surface=_surface, **outcome
    )


try:
    result = platform.parse(uploaded.name, _raw)
except Exception as exc:  # noqa: BLE001 — reported, then refused politely
    # A parser that raises used to reach the reader as Streamlit's red box and
    # reach us not at all. platforms.py decodes utf-8-sig with no fallback, so
    # a latin-1 export dies right here; the fingerprint names the encoding.
    _diagnose(error=exc)
    st.error(
        tr("import.no_rows_parsed", platform=platform.label, hint=platform.hint)
    )
    st.stop()

if not result.transactions and not result.skipped:
    _diagnose(result=result)
    st.error(
        tr("import.no_rows_parsed", platform=platform.label, hint=platform.hint)
    )
    st.stop()

# The wipe decision must precede validation: duplicate flags, split-ratio
# derivation and the oversell replay all read the prior ledger. Validating
# against rows that are about to be wiped rejects sells whose "missing" buys
# are merely doubled, and makes real split ratios underivable.
wipe = st.checkbox(tr("import.wipe_checkbox"))

# Validation re-derives split ratios and replays every sell against the prior
# ledger, and looks unknown symbols up live — seconds on a full statement. The
# preview shimmers as the table it is about to become, heading included, so
# the commit button below keeps its place on the page.
_preview = skeletons.reserve("table", rows=6, cols=5, title=True)
validation = validate(
    result,
    [] if wipe else demo.without(ledger),
    known=known_tickers(paths.watchlist, paths.db),
    lookup=_ticker_exists,
    # Only consulted for a ticker whose sells overshoot: a statement that
    # prints trades and no corporate actions is missing the split, not the
    # buys (stocks.portfolio.validate._market_splits).
    splits=fetch.splits,
)

# Everything the parse and the validation learned, in one anonymised record:
# what the file looked like, which rows fell out and why. This is the line
# that turns "some brokers fail" into a queryable fact.
_diagnose(result=result, validation=validation)

importable = validation.importable
with _preview.container():
    st.subheader(tr("import.preview", summary=validation.summary))
    if importable:
        _tx_table(_tx_frame(importable))
    else:
        st.warning(tr("import.no_importable"))

if validation.flagged:
    st.warning(tr("import.rows_with_warnings", n=len(validation.flagged)))
    _tx_table(
        pd.DataFrame(
            {
                "date": c.tx.date, "ticker": c.tx.ticker,
                "action": tx_text.action_label(c.tx.action),
                "quantity": c.tx.quantity, "price": c.tx.price,
                "warnings": tx_text.issues_text(c.warnings),
            }
            for c in validation.flagged
        )
    )

if validation.rejected:
    st.error(tr("import.rows_rejected", n=len(validation.rejected)))
    _tx_table(
        pd.DataFrame(
            {
                "date": c.tx.date, "ticker": c.tx.ticker,
                "action": tx_text.action_label(c.tx.action),
                "quantity": c.tx.quantity, "price": c.tx.price,
                "errors": tx_text.issues_text(c.errors),
            }
            for c in validation.rejected
        ),
        rich=False,
    )
    st.caption(tr("import.rejected_help"))

if result.skipped:
    with st.expander(tr("import.skipped_rows", n=len(result.skipped))):
        data_table(
            pd.DataFrame(result.skipped),
            labels=tx_text.labels("row", "type", "reason"),
            hide_index=True,
        )
        if platform.key == "revolut":
            st.caption(tr("import.skipped_caption_revolut"))
        else:
            st.caption(tr("import.skipped_caption_generic"))

# Attribution. Every broker parser stamps its own name as the note's first
# word, which is what the Fees and Custody views read the book by
# (fees.broker_of); a generic ledger CSV can come from anywhere and stamps
# nothing, so its origin is asked for here and written in on commit. Required:
# a batch imported unattributed shows up in those views under whatever its
# notes happened to start with, and is tedious to fix afterwards.
origin = platforms.detected_broker(importable)
if importable and not origin:
    origin = st.selectbox(
        tr("import.broker"),
        platforms.broker_options(),
        index=None,
        format_func=lambda k: (
            tr("import.broker_other") if k == platforms.OTHER
            else platforms.broker_label(k)
        ),
        placeholder=tr("import.broker_pick"),
        accept_new_options=True,  # naming the real broker beats "other"
        help=tr("import.broker_help"),
    ) or ""

st.divider()
if st.button(tr("import.commit_button"), type="primary",
             disabled=not importable or not origin):
    if wipe:
        clear(paths.db)
    # The first real import is what the demo book was borrowed against: an
    # invented cost basis must never end up mixed into a real one.
    demo.clear(paths.db)
    ids = add_many(platforms.stamp_broker(importable, origin), paths.db)
    # Imported: the staging slot has done its job, and leaving it filled would
    # re-offer the same rows for a second commit on the next rerun.
    st.session_state.pop(_SAMPLE, None)
    last_import.save(
        last_import.ImportRecord(
            filename=uploaded.name,
            imported_at=datetime.now(UTC).isoformat(timespec="seconds"),
            tx_ids=ids,
            wiped=wipe,
            platform=platform.key,
        ),
        paths.last_import,
    )
    # The denominator for every failure rate: without it the logs say how often
    # an import breaks but not out of how many.
    obs.event(
        "import.committed",
        platform=platform.key,
        broker=origin,
        n=len(ids),
        wiped=wipe,
    )
    # Empty both inputs and start the page again. A statement left in the
    # uploader (or in the paste box) is re-parsed on every later click with
    # the commit button live, and the ledger it would be committed against is
    # now the one that already holds it — a second press duplicates the batch
    # under duplicate warnings rather than being refused. The rerun lands on
    # the last-import block: the same numbers, plus the undo for them.
    st.session_state[_NONCE] = _nonce + 1
    st.session_state["import_committed"] = {
        "n": len(ids),
        "total": len(all_transactions(paths.db)),
    }
    st.rerun()
