"""`/portfolio/monthly` and the year filter on `/portfolio/fees`.

The Overview tab reads both. What is pinned here is what the reader relies on:
one point per month, taken on its last day; rates that count each trade from
the day it happened and that a big late deposit cannot lever; nothing
annualised before a year, the first year's lines what the book made since its
first trade and meeting the annual ones at a year; each month's own return
from the first month,
which a mid-month deposit cannot move; a window that crops those months
instead of rebasing them; a bridge in euros that adds up; the timing of the
trades in euros; and a fees total that is the year's own rather than the
ledger's.
"""

from __future__ import annotations

import pandas as pd
import pytest

from stocks.analysis.monthly import window
from stocks.analysis.portfolio import money_weighted_return, time_weighted_returns
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


NO_TWR = pd.Series(dtype=float)
NO_FLOWS = pd.Series(dtype=float)


def last(book):
    return book.months.iloc[-1]


def test_each_deposit_counts_from_the_day_it_went_in():
    """€1,000 for two years and €10,000 for the last one, both at 10% a year.

    Whatever the sizes and dates, money that all earned 10% a year earned 10% a
    year — the late €10k neither dilutes the early €1k nor levers it. The
    since-inception Modified Dietz this replaced read the same book as +20%
    (gain over average capital), a figure that grows with how much came late.
    """
    days = 730
    late = 365
    grow = [1.1 ** (d / 365.25) for d in range(days + 1)]
    value = [
        1000.0 * grow[d] + (10000.0 * grow[d - late] if d >= late else 0.0)
        for d in range(days + 1)
    ]
    hist = frame("2024-01-01", [0.0] * (days + 1), value)
    flows = pd.Series({hist.index[0]: 1000.0, hist.index[late]: 10000.0})

    book = window(hist, NO_TWR, flows)
    assert last(book)["money_weighted"] == pytest.approx(0.10, abs=1e-6)
    assert last(book)["gain"] == pytest.approx(value[-1] - 11000.0)


def test_a_loss_on_fresh_money_is_weighed_by_the_days_it_was_in():
    """The swing the old line drew: a book long in profit takes a big deposit
    that dips the month after. The gain goes to about zero and so does any
    honest money-weighted figure — by the same proportion as the euros, not
    multiplied by how small the old capital was."""
    days = 760
    late = 730
    hist = frame(
        "2024-01-01",
        [0.0] * (days + 1),
        [1000.0 * 1.2 ** (d / 365.25) for d in range(late)]
        + [1000.0 * 1.2 ** (late / 365.25) + 9560.0] * (days - late + 1),
    )
    flows = pd.Series({hist.index[0]: 1000.0, hist.index[late]: 10000.0})
    row = last(window(hist, NO_TWR, flows))
    assert abs(row["gain"]) < 20.0
    assert abs(row["money_weighted"]) < 0.01


def test_nothing_is_annualised_in_the_first_year():
    """+7% in a few weeks would print as a triple-digit annual rate. In the
    first year the lines are the +7% itself: what the book made since its
    first trade, both ways of asking."""
    hist = frame("2025-01-01", [0.0] * 200, [100.0] * 199 + [107.0])
    twr = pd.Series([0.0] * 198 + [0.07], index=hist.index[1:])
    book = window(hist, twr, pd.Series({hist.index[0]: 100.0}))
    assert not book.months["annual"].any()
    assert last(book)["money_weighted"] == pytest.approx(0.07)
    assert last(book)["time_weighted"] == pytest.approx(0.07)
    assert last(book)["gain"] == pytest.approx(7.0)


def test_the_lines_turn_annual_once_the_book_is_a_year_old():
    """Drawn from the first month — a blank first year read as a book with no
    returns for it — and per year from the first birthday on."""
    hist = frame("2024-01-01", [0.0] * 500, [100.0 * 1.0003**d for d in range(500)])
    twr = pd.Series(0.0003, index=hist.index[1:])
    book = window(hist, twr, pd.Series({hist.index[0]: 100.0}))
    young = book.months.index < hist.index[0] + pd.Timedelta(days=365)
    assert book.months[["money_weighted", "time_weighted"]].notna().all().all()
    assert not book.months.loc[young, "annual"].any()
    assert book.months.loc[~young, "annual"].all()
    # Before: the run so far. After: its pace per year.
    first = book.months.index[0]
    assert book.months.loc[first, "time_weighted"] == pytest.approx(
        1.0003 ** (first - hist.index[0]).days - 1
    )
    assert last(book)["time_weighted"] == pytest.approx(1.0003**365.25 - 1, rel=1e-2)


def test_at_a_year_the_two_readings_meet():
    """The first year's IRR is the annual one over the span as a whole: the
    same flows priced to zero with each date's time as a share of the span.
    So it is the annual rate compounded over the span's years — equal to it
    at one year, and the line carries on across the birthday without a step.
    A deposit late in the span still weighs by the share it was in."""
    index = pd.date_range("2022-04-06", periods=1462, freq="D")
    value = pd.Series(
        [
            1000.0 * 1.3 ** (d / 365.25) + (4000.0 if d >= 1300 else 0.0)
            for d in range(1462)
        ],
        index=index,
    )
    flows = pd.Series({index[0]: 1000.0, index[1300]: 4000.0})
    annual = money_weighted_return(value, flows)
    whole = money_weighted_return(value, flows, annual=False)
    years = (index[-1] - index[0]).days / 365.25
    assert whole == pytest.approx((1 + annual) ** years - 1)


def picks(days: str, price: list[float], buys: dict[int, float]):
    """A book that holds one price path: each buy on its day, at that day's
    price, and the daily TWR `book_history` would hand `window`."""
    index = pd.date_range(days, periods=len(price), freq="D")
    units, value = 0.0, []
    for d, p in enumerate(price):
        units += buys.get(d, 0.0) / p
        value.append(units * p)
    hist = pd.DataFrame({"injected": [0.0] * len(price), "value": value}, index=index)
    flows = pd.Series({index[d]: amount for d, amount in buys.items()})
    return hist, time_weighted_returns(hist["value"], flows), flows


def test_each_month_has_its_own_return_from_the_first_month():
    """A book three months old: the annual rates wait for a year, and each
    month still says what the picks did in it — +2%, −3%, +5%, as they are,
    not stretched to a year."""
    jan, feb, mar = 31, 28, 31
    price = (
        [100.0 * 1.02 ** ((d + 1) / jan) for d in range(jan)]
        + [102.0 * 0.97 ** ((d + 1) / feb) for d in range(feb)]
        + [102.0 * 0.97 * 1.05 ** ((d + 1) / mar) for d in range(mar)]
    )
    # The first trade is on 1 January at the day's close.
    price[0] = 100.0
    hist, twr, flows = picks("2025-01-01", price, {0: 1000.0})
    months = window(hist, twr, flows).months

    assert months["month_return"].tolist() == pytest.approx([0.02, -0.03, 0.05])
    # The lines beside them are the same months compounded, since the first trade.
    run = [1.02 - 1, 1.02 * 0.97 - 1, 1.02 * 0.97 * 1.05 - 1]
    assert months["time_weighted"].tolist() == pytest.approx(run)
    assert months["money_weighted"].tolist() == pytest.approx(run)


def test_a_deposit_mid_month_does_not_move_the_months_return():
    """€1k in, €10k more on the 15th, the picks up 10% over the month. The
    month's return is the picks' 10% — not the value's 1,000% jump, and not
    the gain over some average of the capital, which the fresh money would
    have levered."""
    price = [100.0] * 15 + [100.0 * 1.1 ** ((d + 1) / 16) for d in range(16)]
    hist, twr, flows = picks("2025-01-01", price, {0: 1000.0, 14: 10000.0})
    row = last(window(hist, twr, flows))

    assert row["month_return"] == pytest.approx(0.10)
    assert row["value"] / 1000.0 - 1 > 9  # the euros did jump
    assert row["time_weighted"] == pytest.approx(0.10)  # the only month so far


def test_the_months_compound_to_the_return_since_the_first_trade():
    days = 500
    price = [100.0 * (1 + 0.01 * ((d % 7) - 3)) * 1.0005**d for d in range(days)]
    hist, twr, flows = picks("2024-03-10", price, {0: 1000.0, 45: 500.0, 300: -200.0})
    months = window(hist, twr, flows).months

    assert months["month_return"].notna().all()
    assert (1 + months["month_return"]).prod() - 1 == pytest.approx(
        float((1 + twr).prod() - 1)
    )


def test_a_window_keeps_each_months_whole_return():
    """A window that opens mid-month crops to the month-ends after it; the
    first one still carries its whole calendar month, not the days left of it
    after the window's first day."""
    days = 200
    price = [100.0 * 1.001**d for d in range(days)]
    hist, twr, flows = picks("2025-01-01", price, {0: 1000.0})
    whole = window(hist, twr, flows)
    part = window(hist, twr, flows, start=pd.Timestamp("2025-03-15"))

    assert part.months.index[0] == pd.Timestamp("2025-03-31")
    assert part.months["month_return"].iloc[0] == pytest.approx(1.001**31 - 1)
    pd.testing.assert_series_equal(
        part.months["month_return"],
        whole.months.loc[part.months.index, "month_return"],
    )


def test_the_bridge_adds_up_to_todays_value():
    """Opening value, plus buys, less sales, plus the gain: today, to the cent,
    and the last row's `invested` is the first three."""
    hist = frame("2025-01-01", [0.0] * 120, [1000.0] * 40 + [1500.0] * 40 + [1300.0] * 40)
    flows = pd.Series(
        {hist.index[0]: 1000.0, hist.index[40]: 600.0, hist.index[80]: -150.0}
    )
    book = window(hist, NO_TWR, flows, start=hist.index[10])
    assert book.opening == pytest.approx(1000.0)
    assert (book.bought, book.sold) == (pytest.approx(600.0), pytest.approx(150.0))
    assert book.opening + book.contributed + book.gain == pytest.approx(book.closing)
    # The rows stay the book's own: injected since the first trade.
    assert last(book)["invested"] == pytest.approx(1450.0)


def test_a_window_crops_the_months_it_does_not_rebase_them():
    """Picking last year is zooming into the full chart: the same since-
    inception figures, only the months after the window opens — not a book
    that starts from nothing on the window's first day."""
    days = 800
    hist = frame("2024-01-01", [0.0] * days, [1000.0 * 1.001**d for d in range(days)])
    twr = pd.Series(0.001, index=hist.index[1:])
    flows = pd.Series({hist.index[0]: 1000.0})
    whole = window(hist, twr, flows)
    part = window(hist, twr, flows, start=pd.Timestamp("2025-06-30"))

    expected = whole.months[whole.months.index > part.start]
    pd.testing.assert_frame_equal(part.months, expected)
    assert part.months["time_weighted"].iloc[0] > 0.3  # the book's run, not zero
    # The euros are the window's own.
    assert part.opening == pytest.approx(float(hist["value"].loc["2025-06-30"]))


def test_timing_is_the_euros_the_dates_of_the_trades_made():
    """€1k in, €1k more halfway, then the picks rise 20%. At a steady pace the
    same money would be worth 1000·1.2 + 1000·1.2^½; it is worth 2,400, so the
    second deposit's timing made the difference."""
    value = [1000.0] * 60 + [2000.0] + [2400.0] * 50
    hist = frame("2025-01-01", [0.0] * 111, value)
    twr = pd.Series(0.0, index=hist.index[1:])
    twr.iloc[60] = 0.2  # index[61]: 2,000 → 2,400
    flows = pd.Series({hist.index[0]: 1000.0, hist.index[60]: 1000.0})
    book = window(hist, twr, flows, start=hist.index[10])
    assert book.timing == pytest.approx(2400.0 - (1200.0 + 1000.0 * 1.2**0.5))


def test_one_row_per_month_on_its_last_day():
    hist = frame("2025-01-30", [0.0] * 5, [100.0, 101.0, 102.0, 103.0, 104.0])
    rows = window(hist, NO_TWR, NO_FLOWS).months
    assert [str(d.date()) for d in rows.index] == ["2025-01-31", "2025-02-03"]
    assert rows["value"].tolist() == [101.0, 104.0]


def test_no_capital_is_no_return_not_a_sign_flip():
    hist = frame("2024-01-01", [0.0] * 400, [0.0] * 400)
    assert window(hist, NO_TWR, NO_FLOWS).months["money_weighted"].isna().all()


def test_the_endpoint_reports_each_month_since_the_first_trade(client, book, priced):
    book(
        [
            Transaction(
                "2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 110.0})

    data = get(client, "monthly")
    months = data["months"]
    today = pd.Timestamp.today()
    assert data["window"] == "inception"
    assert months[0]["month"] == "2024-01"
    assert months[-1]["month"] == f"{today:%Y-%m}"
    assert months[0]["gain"] == pytest.approx(100.0)
    assert months[0]["invested"] == pytest.approx(1000.0)
    # The first year is there, what the book made since its first trade; the
    # rest is per year.
    assert months[0]["money_weighted"] is not None
    assert months[0]["annual"] is False
    assert months[-1]["annual"] is True
    assert data["opening"] == 0.0
    assert data["contributed"] == pytest.approx(1000.0)

    # Today's rates are the Overview tile's and Rendimiento real's, not a
    # second opinion on them.
    performance = get(client, "performance")
    assert months[-1]["money_weighted"] == pytest.approx(performance["irr"])
    assert months[-1]["time_weighted"] == pytest.approx(performance["twr_annualised"])
    # Each month's own return is there from the first month, and the months
    # compound to the TWR since the first trade.
    assert months[0]["month_return"] is not None
    growth = 1.0
    for month in months:
        growth *= 1 + month["month_return"]
    assert growth - 1 == pytest.approx(performance["twr_cumulative"])


def test_a_window_opens_on_its_own_close(client, book, priced):
    book(
        [
            Transaction(
                "2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 110.0})

    data = get(client, "monthly", window="ytd")
    assert data["start"] == f"{pd.Timestamp.today().year - 1}-12-31"
    assert data["opening"] + data["contributed"] + data["gain"] == pytest.approx(
        data["closing"]
    )
    # The months are the since-inception ones this year, not re-taken from it.
    whole = get(client, "monthly")["months"]
    assert data["months"] == [m for m in whole if m["date"] > data["start"]]


def test_an_unknown_window_is_refused(client, book, priced):
    book(
        [
            Transaction(
                "2024-01-02", "AAPL", "buy", 10, 100.0, "EUR", 0.0, note="revolut"
            ),
        ]
    )
    priced({"AAPL": 110.0})
    response = client.get(
        "/v1/portfolio/monthly", params={**WHO, "window": "3y"}, headers=AUTH
    )
    assert response.status_code == 422


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
