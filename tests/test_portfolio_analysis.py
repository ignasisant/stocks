

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
