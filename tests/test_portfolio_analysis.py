

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
