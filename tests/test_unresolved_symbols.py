"""Held names whose ledger label Yahoo does not quote: ISINs and bare codes.

The price download places them (ISIN lookup, venue search) instead of holding
them at cost for good, and says so once, not on every request. No network:
`yf.download` and Yahoo's search are replaced.
"""

import pandas as pd

from stocks import obs
from stocks.data import fetch, symbols

ISIN = "US89677Q1076"


def _frame(syms: list[str], gone: set[str]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=3)
    cols = {
        (s, field): [10.0, 11.0, 12.0]
        for s in syms
        if s.upper() not in gone
        for field in ("Open", "Close")
    }
    if not cols:
        return pd.DataFrame(columns=pd.MultiIndex.from_arrays([[], []]))
    return pd.DataFrame(cols, index=idx, columns=pd.MultiIndex.from_tuples(cols))


def _fake_download(asked: list[list[str]], gone: set[str]):
    def download(syms, **_):
        asked.append(list(syms))
        sink = getattr(fetch._download_log, "sink", None)
        if sink is not None:
            for s in syms:
                if s.upper() in gone:
                    sink[s.upper()] = "No data found, symbol may be delisted"
        return _frame(list(syms), gone)

    return download


def _isolate_isins(monkeypatch, tmp_path):
    monkeypatch.setattr(symbols, "ISIN_CACHE", tmp_path / "isin_symbols.json")
    monkeypatch.setattr(symbols, "_isin_memo", None)
    monkeypatch.setattr(symbols, "_isin_misses", set())
    # The developer's own watchlist aliases may already name the ISIN.
    monkeypatch.setattr(fetch, "ticker_aliases", lambda: {})


def test_isin_label_is_priced_through_its_symbol(monkeypatch, tmp_path):
    _isolate_isins(monkeypatch, tmp_path)
    monkeypatch.setattr(
        symbols,
        "_quotes",
        lambda q, n, min_len=0: [
            {"symbol": "TCG.F", "quoteType": "EQUITY"},
            {"symbol": "TCOM", "quoteType": "EQUITY"},
        ],
    )
    asked: list[list[str]] = []
    monkeypatch.setattr(fetch.yf, "download", _fake_download(asked, set()))

    out = fetch.fetch_many([ISIN, "AAPL"])

    assert set(out) == {ISIN, "AAPL"}, "keyed by the ledger's label"
    assert sorted(asked[0]) == ["AAPL", "TCOM"], "Yahoo is asked the symbol"
    assert fetch.resolve(ISIN) == "TCOM", "and resolves it locally afterwards"


def test_unplaced_isin_is_looked_up_once(monkeypatch, tmp_path):
    _isolate_isins(monkeypatch, tmp_path)
    calls: list[str] = []

    def quotes(q, n, min_len=0):
        calls.append(q)
        return []

    monkeypatch.setattr(symbols, "_quotes", quotes)
    monkeypatch.setattr(fetch.yf, "download", _fake_download([], {ISIN}))

    fetch.fetch_many([ISIN])
    fetch.fetch_many([ISIN])

    assert calls == [ISIN], "a miss is remembered for the process"


def test_bare_code_disowned_by_yahoo_is_placed_on_its_venue(monkeypatch):
    asked: list[list[str]] = []
    monkeypatch.setattr(fetch.yf, "download", _fake_download(asked, {"SIE", "IFX"}))
    monkeypatch.setattr(
        symbols,
        "_quotes",
        lambda q, n, min_len=0: [
            {"symbol": f"{q.split('.')[0]}.DE", "quoteType": "EQUITY"}
        ],
    )
    monkeypatch.setattr(symbols, "_save_code_cache", lambda cache: None)

    out = fetch.fetch_many(["SIE", "IFX"], currencies={"SIE": "EUR", "IFX": "EUR"})

    assert set(out) == {"SIE", "IFX"}
    assert sorted(asked[-1]) == ["IFX.DE", "SIE.DE"]
    assert fetch.resolve("SIE") == "SIE.DE"
    assert not fetch.unlisted(["SIE", "IFX"]), "no longer a disowned name"


def test_dollar_code_is_never_given_a_suffix(monkeypatch):
    monkeypatch.setattr(fetch.yf, "download", _fake_download([], {"ORGN"}))

    def boom(*_a, **_k):
        raise AssertionError("no venue search for a dollar code")

    monkeypatch.setattr(symbols, "_quotes", boom)

    assert fetch.fetch_many(["ORGN"], currencies={"ORGN": "USD"}) == {}
    assert fetch.unlisted(["ORGN"]) == {"ORGN"}


def test_code_without_a_venue_line_is_not_reasked(monkeypatch):
    monkeypatch.setattr(fetch.yf, "download", _fake_download([], {"ZZZQ"}))
    calls: list[str] = []

    def quotes(q, n, min_len=0):
        calls.append(q)
        return []

    monkeypatch.setattr(symbols, "_quotes", quotes)

    fetch.fetch_many(["ZZZQ"], currencies={"ZZZQ": "EUR"})
    first = len(calls)
    for _ in range(3):
        assert fetch.fetch_many(["ZZZQ"], currencies={"ZZZQ": "EUR"}) == {}
    assert first > 0
    assert len(calls) == first, "the miss is remembered for the process"


def test_warn_once_is_once_per_key(monkeypatch):
    obs._once.clear()
    seen: list[str] = []
    monkeypatch.setattr(obs, "warn", lambda name, **f: seen.append(name))

    assert obs.warn_once("x.event", "A") is True
    assert obs.warn_once("x.event", "A") is False
    assert obs.warn_once("x.event", "B") is True
    assert seen == ["x.event", "x.event"]


def test_unlisted_verdict_is_logged_once_across_flips(monkeypatch):
    obs._once.clear()
    seen: list[list[str]] = []

    def warn(name, **fields):
        if name == "yahoo.unlisted":
            seen.append(fields["tickers"])

    monkeypatch.setattr(obs, "warn", warn)
    monkeypatch.setattr(fetch.yf, "download", _fake_download([], {"ORGN"}))

    fetch.fetch_many(["ORGN"])
    fetch.clear_unlisted()  # a fresh verdict, as after a priced/throttled round
    fetch.fetch_many(["ORGN"])

    assert seen == [["ORGN"]]
