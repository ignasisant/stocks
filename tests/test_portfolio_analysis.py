

def test_correlation_ignores_names_with_thin_history():
    import numpy as np
    import pandas as pd

    from stocks.analysis.portfolio import correlation_matrix

    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"A": rng.normal(size=100), "B": rng.normal(size=100)})
    frame["NEW"] = np.nan
    frame.loc[95:, "NEW"] = rng.normal(size=5)
    corr = correlation_matrix(frame)
    assert pd.isna(corr.loc["NEW", "A"])
    assert not pd.isna(corr.loc["A", "B"])


def test_crypto_has_its_own_country_bucket():
    from stocks.analysis.portfolio import allocation_parts

    parts = allocation_parts(
        {"BTC-EUR": 10.0, "XYZ": 5.0}, {"XYZ": {}}, "country"
    )
    assert set(parts) == {"Crypto", "Unknown"}


def test_beta_on_misaligned_dates_raises_no_pandas_warning():
    """Prod logged Pandas4Warning ×84 from this join; it now names its sort."""
    import warnings

    import numpy as np
    import pandas as pd

    from stocks.analysis.portfolio import beta

    # Interleaved calendars (a US name against a European index): the union of
    # the two indexes has to be sorted, which is what pandas warns about.
    rng = np.random.default_rng(2)
    days = pd.bdate_range("2026-01-01", periods=90)
    mine = [d for i, d in enumerate(days) if i % 2 == 0 or i % 3 == 0]
    theirs = [d for i, d in enumerate(days) if i % 2 == 1 or i % 3 == 0]
    asset = pd.Series(rng.normal(size=len(mine)), index=pd.DatetimeIndex(mine))
    bench = pd.Series(rng.normal(size=len(theirs)), index=pd.DatetimeIndex(theirs))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert np.isfinite(beta(asset, bench))

# TTD on 2026-11-10's card: closed +15.7 % at 14.955 from 12.93, printed 18.00
# after hours. The bar's value is at the close; the move runs to the print.
_TTD_POST = {"pct": 18.0 / 12.93 - 1, "price": 18.0, "regular": 14.955, "basis": "post"}


def test_an_after_hours_move_is_counted_on_the_after_hours_price():
    import pandas as pd
    import pytest

    from stocks.analysis.portfolio import day_change

    shares = 200.0
    values = pd.DataFrame(
        {"TTD": [shares * 12.93, shares * 14.955], "MSFT": [1000.0, 1010.0]},
        index=pd.to_datetime(["2026-11-06", "2026-11-09"]),
    )
    gained, pct = day_change(values, {"TTD": _TTD_POST})
    assert gained == pytest.approx(shares * (18.0 - 12.93) + 10.0)
    assert pct == pytest.approx(gained / (shares * 12.93 + 1000.0))


def test_a_premarket_move_is_counted_from_the_close():
    import pandas as pd
    import pytest

    from stocks.analysis.portfolio import day_change

    values = pd.DataFrame(
        {"TTD": [2586.0, 2991.0]}, index=pd.to_datetime(["2026-11-09", "2026-11-10"])
    )
    pre = {"pct": 15.5 / 14.955 - 1, "price": 15.5, "regular": 14.955, "basis": "pre"}
    gained, _ = day_change(values, {"TTD": pre})
    assert gained == pytest.approx(2991.0 * (15.5 / 14.955 - 1))


def test_home_rows_count_an_after_hours_move_on_the_after_hours_price(monkeypatch):
    import pandas as pd
    import pytest

    from stocks.views import home

    shares = 200.0
    table = pd.DataFrame({"value": [shares * 14.955]}, index=["TTD"])
    values = pd.DataFrame(
        {"TTD": [shares * 12.93, shares * 14.955]},
        index=pd.to_datetime(["2026-11-06", "2026-11-09"]),
    )
    monkeypatch.setattr(home.loaders, "positions_table", lambda *a: table)
    monkeypatch.setattr(home.loaders, "basket_values", lambda *a: values)
    monkeypatch.setattr(home.loaders, "quotes", lambda tickers: {"TTD": _TTD_POST})
    monkeypatch.setattr(home, "market_live", lambda ticker: False)
    monkeypatch.setattr(
        home, "value_weights", lambda tbl: pd.Series(1.0, index=tbl.index)
    )
    row = home.enriched("db", 0.0, "USD").loc["TTD"]
    assert row["day"] == pytest.approx(shares * (18.0 - 12.93))
    assert row["day_basis"] == "post"
