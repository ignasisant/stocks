"""A fund's wrapper and its fit with the book, read without the network.

The rows that matter are the ones the page got wrong or could not say: an
emerging-markets fund quoted in London read against the FTSE 100, a world
ETF whose top ten are the reader's own tech names, two lines of one index
that differ in class, domicile and hedge.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.analysis import fund_fit, fund_wrapper
from stocks.api.app import app as fastapi_app
from stocks.data.funds import FundHolding, FundProfile
from tests.patching import patch_loaders

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize(
    ("ticker", "name", "share_class", "domicile", "tracks", "exposure", "bench"),
    [
        ("EIMI.L", "iShares Core MSCI EM IMI UCITS ETF USD (Acc)",
         "acc", "IE", "MSCI EM IMI", "em", "EEM"),
        ("VWCE.DE", "Vanguard FTSE All-World UCITS ETF USD Accumulation",
         "acc", "IE", "FTSE All-World", "world", "ACWI"),
        ("EXSA.DE", "iShares STOXX Europe 600 UCITS ETF (DE) EUR (Dist)",
         "dist", "DE", "STOXX Europe 600", "europe", "^STOXX50E"),
        ("SPY", "State Street SPDR S&P 500 ETF Trust",
         "dist", "US", "S&P 500", "us", "^GSPC"),
        ("QQQ", "Invesco QQQ Trust", "dist", "US", "NASDAQ-100", "nasdaq", "^IXIC"),
    ],
)
def test_the_name_says_class_domicile_index_and_market(
    ticker, name, share_class, domicile, tracks, exposure, bench
):
    read = fund_wrapper.read(ticker, name)
    assert read.share_class == share_class
    assert read.domicile == domicile
    assert read.tracks == tracks
    assert read.exposure == exposure
    assert read.benchmark is not None and read.benchmark.ticker == bench


def test_the_isin_names_the_domicile_and_a_hedge_its_currency():
    read = fund_wrapper.read(
        "IBCH.DE", "iShares MSCI World EUR Hedged UCITS ETF (Acc)", isin="IE00B441G979"
    )
    assert read.domicile == "IE" and read.ucits
    assert read.hedged == "EUR"
    assert read.tracks == "MSCI World"
    assert not read.synthetic
    swap = fund_wrapper.read("XDWD.DE", "Xtrackers MSCI World Swap UCITS ETF 1C")
    assert swap.synthetic


def test_a_silent_name_leaves_the_field_unknown():
    read = fund_wrapper.read("XYZ.DE", "Some Thematic UCITS ETF")
    # An issuer that domiciles in several countries proves nothing either.
    assert fund_wrapper.read("XDWD.DE", "Xtrackers MSCI World UCITS ETF").domicile is None
    assert read.share_class is None and read.domicile is None
    assert read.exposure is None and read.benchmark is None


def test_an_asian_basket_quoted_in_europe_trades_while_its_market_sleeps():
    # London opens as Hong Kong closes: no shared stretch at all.
    assert fund_wrapper.trade_window("EIMI.L", "em", date(2026, 11, 6)) is False


def test_a_world_fund_in_frankfurt_is_tightest_once_new_york_opens():
    start, end = fund_wrapper.trade_window("VWCE.DE", "world", date(2026, 11, 6))
    assert (start.astimezone().utcoffset() is not None)
    assert start.hour == 9 and start.minute == 30  # New York's open, its zone
    assert end.hour == 17 and end.minute == 30  # Xetra's close, its zone


def test_a_line_on_its_own_market_has_nothing_to_say():
    assert fund_wrapper.trade_window("SPY", "us", date(2026, 11, 6)) is None
    assert fund_wrapper.trade_window("XYZ.TO", "us", date(2026, 11, 6)) is None


def _held(label, symbol, name, weight):
    return fund_fit.Held(label=label, symbol=symbol, name=name, weight=weight)


def test_overlap_finds_a_holding_by_symbol_or_by_name():
    book = [
        _held("AAPL", "AAPL", "Apple Inc.", 0.2),
        _held("TSM", "TSM", "Taiwan Semiconductor Manufacturing Company Limited", 0.1),
        _held("1101.TW", "1101.TW", "Taiwan Cement Corp", 0.05),
    ]
    found = fund_fit.overlap(
        [
            ("AAPL", "Apple Inc", 0.05),
            ("2330.TW", "Taiwan Semiconductor Manufacturing Co Ltd", 0.09),
            ("2317.TW", "Hon Hai Precision Industry Co Ltd", 0.02),
        ],
        book,
    )
    assert [(o.held.label, o.fund_weight) for o in found] == [
        ("AAPL", 0.05), ("TSM", 0.09)]


def test_the_book_without_a_held_fund_takes_its_sectors_back_out():
    # Half the book is the fund (60% tech); the other half is all tech stocks.
    rows = fund_fit.sectors(
        {"Technology": 0.8, "Financials": 0.2, "Unknown": 0.0},
        {"Technology": 0.6, "Financials": 0.4},
        0.5,
    )
    by = {r.label: r for r in rows}
    assert by["Technology"].without == pytest.approx(1.0)
    assert by["Financials"].without == pytest.approx(0.0)
    assert "Unknown" not in by
    unheld = fund_fit.sectors({"Technology": 1.0}, {"Technology": 0.3}, None)
    assert unheld[0].without is None


# ---------------------------------------------------------------- the route


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture
def account(monkeypatch, tmp_path):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    patch_loaders(monkeypatch, "db_mtime", lambda db: 1.0)
    return paths


WORLD = FundProfile(
    ticker="VWCE.DE",
    name="Vanguard FTSE All-World UCITS ETF USD Accumulation",
    quote_type="ETF",
    currency="EUR",
    holdings=(
        FundHolding("NVDA", "NVIDIA Corp", 0.05),
        FundHolding("AAPL", "Apple Inc", 0.045),
        FundHolding("MSFT", "Microsoft Corp", 0.04),
    ),
    sectors=(("Technology", 0.3), ("Financials", 0.15)),
)


def _book() -> pd.DataFrame:
    rows = {"AAPL": 40.0, "NVDA": 20.0, "VWCE": 40.0}
    return pd.DataFrame(
        {"value": list(rows.values()), "cost": list(rows.values())},
        index=pd.Index(list(rows), name="ticker"),
    )


def _offline(monkeypatch, profile=WORLD):
    patch_loaders(monkeypatch, "fund_profile", lambda t: profile)
    patch_loaders(monkeypatch, "positions_table", lambda db, m, base: _book())
    patch_loaders(
        monkeypatch, "display_symbol",
        lambda label: "VWCE.DE" if label == "VWCE" else label,
    )
    patch_loaders(monkeypatch, "listing_names", lambda symbols: {
        "AAPL": "Apple Inc.", "NVDA": "NVIDIA Corporation"})
    patch_loaders(monkeypatch, "basket_report", lambda *a: None)
    patch_loaders(monkeypatch, "ledger_state", lambda *a: type("S", (), {"txs": []})())


def test_fit_names_the_held_companies_the_fund_repeats(client, account, monkeypatch):
    _offline(monkeypatch)
    body = client.get("/v1/ticker/VWCE.DE/fund/fit",
                      params={"account": EMAIL}, headers=AUTH).json()
    assert body["held"] is True
    assert body["fund_share"] == pytest.approx(0.4)
    assert {o["symbol"] for o in body["overlap"]} == {"AAPL", "NVDA"}
    assert body["overlap_weight"] == pytest.approx(0.095)
    assert body["spread"] is None  # no fills to measure


def test_a_company_gets_an_empty_fit(client, account, monkeypatch):
    _offline(monkeypatch, profile=None)
    body = client.get("/v1/ticker/AAPL/fund/fit",
                      params={"account": EMAIL}, headers=AUTH).json()
    assert body["held"] is False and body["overlap"] == []


def test_the_fund_card_carries_its_wrapper(client, account, monkeypatch):
    profile = replace(WORLD, average_traded=5e6, traded_currency="EUR")
    patch_loaders(monkeypatch, "fund_profile", lambda t: profile)
    patch_loaders(monkeypatch, "asset_kind", lambda t: "equity_fund")
    body = client.get("/v1/ticker/VWCE.DE/fund", headers=AUTH).json()
    assert body["average_traded"] == 5e6
    assert body["wrapper"]["share_class"] == "acc"
    assert body["wrapper"]["exposure"] == "world"
    assert body["wrapper"]["tracks"] == "FTSE All-World"


def test_an_em_fund_in_london_reads_against_emerging_markets(monkeypatch):
    from stocks.api.routes.ticker import read_trend

    asked: list[str] = []
    em = replace(WORLD, ticker="EIMI.L",
                 name="iShares Core MSCI EM IMI UCITS ETF USD (Acc)")
    patch_loaders(monkeypatch, "asset_kind", lambda t: "equity_fund")
    patch_loaders(monkeypatch, "fund_profile", lambda t: em)
    patch_loaders(monkeypatch, "daily_bars", lambda t: pd.DataFrame())
    patch_loaders(monkeypatch, "daily_closes",
                  lambda t, period: asked.append(t) or pd.Series(dtype=float))
    read_trend("EIMI.L")
    assert asked == ["EEM"]  # not the FTSE 100 its listing would pick
