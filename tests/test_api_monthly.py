"""`/portfolio/monthly` and the year filter on `/portfolio/fees`.

The Overview tab reads both. What is pinned here is what the reader relies on:
one point per month, taken on its last day; a return that weighs each deposit by
how long it was in, not only by how big it was; and a fees total that is the
year's own rather than the ledger's.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.analysis.monthly import month_ends
from stocks.portfolio.ledger import Transaction
from tests import test_api_history as history

# The history suite's account, pricing and cache fixtures, reused by name.
client, book, priced = history.client, history.book, history.priced
token, _cold_caches = history.token, history._cold_caches
AUTH, WHO = history.AUTH, history.WHO


def get(client, path: str, **params) -> dict:
    response = client.get(f"/v1/portfolio/{path}", params={**WHO, **params}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def frame(days: str, injected: list[float], value: list[float]) -> pd.DataFrame:
    index = pd.date_range(days, periods=len(injected), freq="D")
    return pd.DataFrame({"injected": injected, "value": value}, index=index)


def test_a_late_deposit_counts_for_the_time_it_was_in():
    """€100 in for ten days earning €10, then €900 more on the last day.

    Over what was injected that reads 1%; over the capital actually at work it is
    the €10 on ~€190 of average capital — the late euros did not earn it.
    """
    hist = frame("2025-01-01", [100.0] * 9 + [1000.0], [100.0] * 9 + [1010.0])
    row = month_ends(hist, pd.Series(dtype=float)).iloc[-1]
    assert row["pnl"] == pytest.approx(10.0)
    assert row["money_weighted"] == pytest.approx(10.0 / 190.0)
    assert row["money_weighted"] > row["pnl"] / row["injected"]


def test_one_row_per_month_on_its_last_day():
    hist = frame("2025-01-30", [100.0] * 5, [100.0, 101.0, 102.0, 103.0, 104.0])
    rows = month_ends(hist, pd.Series(dtype=float))
    assert [str(d.date()) for d in rows.index] == ["2025-01-31", "2025-02-03"]
    assert rows["value"].tolist() == [101.0, 104.0]


def test_no_capital_is_no_return_not_a_sign_flip():
    hist = frame("2025-01-01", [0.0, 0.0], [0.0, 0.0])
    assert month_ends(hist, pd.Series(dtype=float))["money_weighted"].isna().all()


def test_the_endpoint_reports_each_month_since_the_first_trade(client, book, priced):
    book(
        [
            Transaction(
                "2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 110.0})

    months = get(client, "monthly")["months"]
    today = pd.Timestamp.today()
    assert months[0]["month"] == "2024-01"
    assert months[-1]["month"] == f"{today:%Y-%m}"
    assert months[0]["pnl"] == pytest.approx(100.0)
    assert months[0]["injected"] == pytest.approx(1000.0)


def test_fees_can_be_asked_for_one_year(client, book, priced):
    book(
        [
            Transaction(
                "2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 2.0, note="revolut"
            ),
            Transaction(
                "2025-03-03", "AAPL", "buy", 1, 100.0, "EUR", 5.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 100.0})

    assert get(client, "fees", year=2025)["explicit"] == pytest.approx(5.0)
    assert get(client, "fees", year=2023)["explicit"] == 0.0
