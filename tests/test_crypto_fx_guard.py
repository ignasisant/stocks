"""The USD-pair fallback for a EUR/GBP coin converts through the ECB rate.

That rate is a second network dependency inside a Yahoo download. It failing
must cost the one pair, not the download.
"""

import pandas as pd
import pytest

from stocks import obs
from stocks.data import fetch


def _usd_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-03-01", "2024-03-04"])
    return pd.DataFrame({"Open": [10.0, 11.0], "High": [12.0, 13.0],
                         "Low": [9.0, 10.0], "Close": [10.0, 12.0]}, index=idx)


def test_a_failed_rate_feed_leaves_that_pair_unpriced_and_keeps_the_rest(monkeypatch):
    warned: list[dict] = []
    monkeypatch.setattr(obs, "warn", lambda name, **f: warned.append({"name": name, **f}))
    monkeypatch.setattr(
        fetch, "_errand",
        lambda symbols, *a, **k: {s: _usd_frame() for s in symbols},
    )

    def rates(start, end, base, quote):
        if quote == "GBP":
            raise OSError("frankfurter down")
        return {"2024-03-01": 0.9, "2024-03-04": 0.8}

    monkeypatch.setattr(fetch, "rates_range", rates)

    out = fetch._crypto_usd_fallback(["GOOD-EUR", "BAD-GBP"], "1mo", "1d", False)

    assert set(out) == {"GOOD-EUR"}
    assert out["GOOD-EUR"]["Close"].tolist() == pytest.approx([9.0, 9.6])
    assert [w["name"] for w in warned] == ["yahoo.crypto_fx_failed"]
    assert warned[0]["ticker"] == "BAD-GBP"
    assert warned[0]["via"] == "BAD-USD"
    assert "frankfurter down" in warned[0]["error"]
