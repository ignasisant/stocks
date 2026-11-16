"""Historic P/E reconstruction tests — pure math over synthetic facts, no network."""

from datetime import date, timedelta

import pandas as pd
import pytest

from stocks.analysis.pe_history import (
    discrete_quarters,
    interpret,
    pe_series,
    reconstruct_ttm_eps,
    split_factors,
    window_stats,
)


def _facts(rows):
    return pd.DataFrame(rows, columns=["end", "filed", "eps", "kind"])


FACTS = _facts([
    (date(2025, 3, 31), date(2025, 5, 1), 1.0, "Q"),
    (date(2025, 6, 30), date(2025, 8, 1), 2.0, "Q"),
    (date(2025, 9, 30), date(2025, 11, 1), 3.0, "Q"),
    (date(2025, 12, 31), date(2026, 2, 15), 10.0, "FY"),  # Q4 = 10 − 6 = 4
])


def test_split_factors_cumulative_after_end():
    splits = {date(2025, 7, 15): 10.0, date(2026, 1, 10): 2.0}
    ends = [date(2025, 3, 31), date(2025, 9, 30), date(2026, 3, 31)]
    out = split_factors(splits, ends)
    assert out[date(2025, 3, 31)] == 20.0  # both splits after this quarter
    assert out[date(2025, 9, 30)] == 2.0
    assert out[date(2026, 3, 31)] == 1.0


def test_discrete_quarters_derives_q4_from_fy():
    q = discrete_quarters(FACTS)
    assert list(q["eps"]) == [1.0, 2.0, 3.0, 4.0]
    # Derived Q4 carries the 10-K's filing date.
    assert q.iloc[-1]["filed"] == date(2026, 2, 15)


def test_discrete_quarters_skips_fy_with_missing_quarters():
    q = discrete_quarters(FACTS.drop(index=1))  # only 2 discrete quarters in year
    assert list(q["eps"]) == [1.0, 3.0]


def test_reconstruct_ttm_eps_stamped_at_filing():
    ttm = reconstruct_ttm_eps(discrete_quarters(FACTS))
    assert list(ttm) == [10.0]  # 1+2+3+4
    assert ttm.index[0] == pd.Timestamp("2026-02-15")


def test_reconstruct_ttm_eps_split_adjusts():
    factors = {date(2025, 3, 31): 2.0}  # 2:1 split after Q1
    ttm = reconstruct_ttm_eps(discrete_quarters(FACTS), factors)
    assert list(ttm) == [9.5]  # 0.5+2+3+4


def test_pe_series_as_of_join_and_positive_filter():
    ttm = pd.Series([10.0], index=pd.DatetimeIndex(["2026-02-15"]))
    close = pd.Series(
        [90.0, 120.0],
        index=pd.DatetimeIndex(["2026-02-14", "2026-02-16"]),
    )
    pe = pe_series(close, ttm)
    # Day before the filing has no known TTM figure -> dropped.
    assert list(pe.index) == [pd.Timestamp("2026-02-16")]
    assert pe.iloc[0] == pytest.approx(12.0)


def test_pe_series_drops_lossmaking():
    ttm = pd.Series([-1.0], index=pd.DatetimeIndex(["2026-01-01"]))
    close = pd.Series([50.0], index=pd.DatetimeIndex(["2026-01-02"]))
    assert pe_series(close, ttm).empty


def test_window_stats_premium_and_percentile():
    idx = pd.date_range("2025-01-01", periods=100, freq="D")
    pe = pd.Series([20.0] * 99 + [30.0], index=idx)
    st = window_stats(pe, windows={"1y": 365})
    row = st.loc["1y"]
    assert row["current"] == 30.0
    assert row["mean"] == pytest.approx(20.1)
    assert row["premium"] == pytest.approx(30.0 / 20.1 - 1)
    assert row["percentile"] == 100.0


def test_interpret_bands():
    assert interpret(90) == "expensive vs own history"
    assert interpret(10) == "cheap vs own history"
    assert interpret(50) == "in line with own history"




def _stub_feeds(monkeypatch, facts, *, fmp_facts=None, quote=None, rate=None):
    """Offline pe_vs_history: EDGAR answers `facts`, prices are flat 40.

    `quote` is Yahoo's profile for the listing (currency, trailingEps) and
    `rate` the one filing-to-quote FX rate every day. Returns the list of
    periods the price download was asked for.
    """
    import yfinance as yf

    from stocks.data import edgar, fetch, fmp, fx

    asked: list[str] = []

    def history(ticker, period="1y", interval="1d"):
        asked.append(period)
        idx = pd.bdate_range(end="2026-11-13", periods=2600)
        return pd.DataFrame({"Close": [40.0] * len(idx)}, index=idx)

    def rates(start, end, base, quote_ccy):
        if rate is None:
            raise RuntimeError("no rate")
        return {str(d.date()): rate for d in pd.bdate_range(start, end)}

    monkeypatch.setattr(edgar, "diluted_eps_facts", lambda t: facts)
    monkeypatch.setattr(fmp, "has_key", lambda: fmp_facts is not None)
    monkeypatch.setattr(fmp, "diluted_eps_facts", lambda t: fmp_facts)
    monkeypatch.setattr(fetch, "fetch_history", history)
    monkeypatch.setattr(fetch, "info", lambda t: quote or {})
    monkeypatch.setattr(fx, "rates_range", rates)
    monkeypatch.setattr(
        yf, "Ticker", lambda t: type("T", (), {"splits": pd.Series(dtype=float)})()
    )
    return asked


def _quarters(n, first=date(2015, 3, 31), currency="USD"):
    ends = [(pd.Timestamp(first) + pd.DateOffset(months=3 * i)).date() for i in range(n)]
    out = _facts([(e, e + timedelta(days=35), 1.0, "Q") for e in ends])
    out["currency"] = currency
    return out


def _years(first=2016, last=2025, eps=400.0, currency="JPY"):
    """A 20-F filer's fiscal years to March, each filed in June."""
    out = _facts([
        (date(y, 3, 31), date(y, 6, 20), eps, "FY") for y in range(first, last + 1)
    ])
    out["currency"] = currency
    return out


def test_price_history_reaches_back_as_far_as_the_longest_range(monkeypatch):
    """A "10y" button over a 5y download draws five years and averages five."""
    from stocks.analysis import pe_history

    asked = _stub_feeds(monkeypatch, _quarters(40))

    out = pe_history.pe_vs_history("MO")

    longest = max(pe_history.DISPLAY_WINDOWS.values())
    assert asked and int(asked[0].rstrip("y")) * 365 >= longest
    reach = out["pe"].index.max() - out["pe"].index.min()
    assert reach >= pd.Timedelta(days=longest - 30)
    assert out["basis"] == "ttm"


def test_a_20f_filer_draws_its_fiscal_years_in_the_filing_currency(monkeypatch):
    """Sony: years only, JPY EPS under a dollar line of one share. Price 40 USD
    at 0.01 USD/JPY is 4000 JPY, over 400 JPY of EPS: 10x."""
    from stocks.analysis import pe_history

    _stub_feeds(
        monkeypatch, _years(last=2026),
        quote={"currency": "USD", "trailingEps": 4.4}, rate=0.01,
    )

    out = pe_history.pe_vs_history("SONY")

    assert out["source"] == "SEC EDGAR"
    assert out["basis"] == "annual"
    assert out["pe"].iloc[-1] == pytest.approx(10.0)
    assert out["current"] == pytest.approx(10.0)


def test_a_receipt_for_several_shares_is_not_drawn(monkeypatch):
    """Toyota's ADR is ten shares: its dollar EPS reads ten times the filed
    one, and a line drawn over it would be ten times too dear."""
    from stocks.analysis import pe_history

    _stub_feeds(
        monkeypatch, _years(last=2026),
        quote={"currency": "USD", "trailingEps": 40.0}, rate=0.01,
    )

    out = pe_history.pe_vs_history("TM")

    assert out["source"] is None
    assert out["pe"].empty


def test_a_foreign_filer_without_a_rate_or_a_quote_is_not_drawn(monkeypatch):
    from stocks.analysis import pe_history

    _stub_feeds(monkeypatch, _years(), quote={"currency": "USD", "trailingEps": 4.0})
    assert pe_history.pe_vs_history("SONY")["source"] is None

    _stub_feeds(monkeypatch, _years(), quote={}, rate=0.01)
    assert pe_history.pe_vs_history("SONY")["source"] is None


def test_a_missing_annual_filing_stops_the_line_and_blanks_today(monkeypatch):
    """Sony's June-2026 20-F is not in the SEC's XBRL: the June-2025 figure
    stands its year and then the line stops. Nothing reads as today's, and the
    windows still end at the last close."""
    from stocks.analysis import pe_history

    _stub_feeds(
        monkeypatch, _years(last=2025),
        quote={"currency": "USD", "trailingEps": 4.4}, rate=0.01,
    )

    out = pe_history.pe_vs_history("SONY")

    last_filed = pd.Timestamp("2025-06-20")
    assert out["pe"].index.max() <= last_filed + pd.Timedelta(
        days=pe_history.ANNUAL_MAX_AGE_DAYS
    )
    assert out["as_of"] == pd.Timestamp("2026-11-13")
    assert out["current"] is None
    one_year = out["stats"].loc["1y"]
    assert pd.isna(one_year["percentile"]) and pd.isna(one_year["premium"])
    assert one_year["n"] < 260  # the year to the last close, not to the last point


def test_fmp_quarters_in_a_foreign_currency_pass_the_same_check(monkeypatch):
    """FMP's Alibaba: CNY quarters under an eight-share dollar ADR read 3.2x."""
    from stocks.analysis import pe_history

    fmp_facts = _quarters(8, first=date(2024, 12, 31), currency="CNY")
    _stub_feeds(
        monkeypatch, _years(first=2024, last=2024), fmp_facts=fmp_facts,
        quote={"currency": "USD", "trailingEps": 4.6}, rate=0.14,
    )

    assert pe_history.pe_vs_history("BABA")["source"] is None


def test_fmp_is_tried_when_edgar_facts_draw_nothing(monkeypatch):
    from stocks.analysis import pe_history

    years = _years(first=2024, last=2024)
    _stub_feeds(monkeypatch, years, fmp_facts=_quarters(8, first=date(2024, 12, 31)))

    out = pe_history.pe_vs_history("SONY")

    assert out["source"] == "FMP"
    assert not out["pe"].empty


def test_annual_eps_split_adjusts_and_keeps_the_year_each_filing_made_known():
    """Sony's first IFRS figures, before and after its 2024 5:1 split, land on
    the values its later 20-F restated them to."""
    from stocks.analysis.pe_history import annual_eps

    facts = _facts([
        (date(2008, 3, 31), date(2010, 6, 28), 351.10, "FY"),
        (date(2010, 3, 31), date(2010, 6, 28), -40.66, "FY"),
        (date(2023, 3, 31), date(2023, 6, 20), 754.95, "FY"),
        (date(2024, 3, 31), date(2024, 6, 25), 785.68, "FY"),
        (date(2025, 3, 31), date(2025, 6, 20), 187.92, "FY"),
    ])
    factors = split_factors({date(2024, 10, 9): 5.0}, list(facts["end"]))

    known = annual_eps(facts, factors)

    assert known[pd.Timestamp("2010-06-28")] == pytest.approx(-40.66 / 5)
    assert known[pd.Timestamp("2023-06-20")] == pytest.approx(150.99)
    assert known[pd.Timestamp("2024-06-25")] == pytest.approx(157.136)
    assert known[pd.Timestamp("2025-06-20")] == pytest.approx(187.92)


def test_pe_series_max_age_drops_days_on_an_old_figure():
    close = pd.Series(10.0, index=pd.bdate_range("2024-01-01", "2026-06-30"))
    known = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2024-01-01", "2025-01-01"]),
    )

    pe = pe_series(close, known, max_age_days=100)

    assert pe.index.max() <= pd.Timestamp("2025-04-11")
    assert pd.Timestamp("2024-06-03") not in pe.index  # gap before the 2025 filing
    assert pe[pd.Timestamp("2025-01-01")] == pytest.approx(5.0)


def test_window_stats_counts_back_from_the_last_close():
    pe = pd.Series(
        range(1, 101), index=pd.bdate_range("2025-01-01", periods=100), dtype=float
    )

    stats = window_stats(pe, windows={"1y": 365}, end=pd.Timestamp("2026-03-01"))

    assert stats.loc["1y", "n"] < 100
    assert pd.isna(stats.loc["1y", "current"])
    assert pd.isna(stats.loc["1y", "percentile"])


def test_edgar_reads_ifrs_years_beside_us_gaap_in_the_filers_own_currency(monkeypatch):
    """Sony moved from us-gaap to ifrs-full with fiscal 2021. Both halves are
    read; where a year is in both the earliest filing wins; a convenience
    figure in another currency is not kept beside the yen."""
    from stocks.data import edgar

    def fact(start, end, filed, val):
        return {"start": start, "end": end, "filed": filed, "val": val, "form": "20-F"}

    payload = {"facts": {
        "us-gaap": {"EarningsPerShareDiluted": {"units": {"JPY/shares": [
            fact("2019-04-01", "2020-03-31", "2020-06-26", 461.23),
            fact("2020-04-01", "2021-03-31", "2021-06-22", 936.90),
        ]}}},
        "ifrs-full": {"DilutedEarningsLossPerShare": {"units": {
            "JPY/shares": [
                fact("2020-04-01", "2021-03-31", "2022-06-28", 823.77),
                fact("2021-04-01", "2022-03-31", "2022-06-28", 705.16),
            ],
            "USD/shares": [fact("2021-04-01", "2022-03-31", "2022-06-28", 5.8)],
        }}},
    }}
    monkeypatch.setattr(edgar, "company_facts", lambda t: payload)

    df = edgar.diluted_eps_facts("SONY")

    assert list(df["eps"]) == [461.23, 936.90, 705.16]
    assert set(df["currency"]) == {"JPY"}
    assert set(df["kind"]) == {"FY"}
