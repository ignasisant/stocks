"""CFTC Commitments of Traders — parsing, net positioning, crowding.

No network: `stocks.data.cot.get_bytes` is stubbed with payloads recorded from
publicreporting.cftc.gov on 2026-10-27 (trimmed to a few reports and the fields
the `$select` asks for), so the dataset ids, the field names and the
net-position arithmetic stay pinned when the host is unreachable.
"""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from stocks.data import cot

# TFF futures-only (gpe5-46if): E-mini S&P 500 and Bitcoin.
TFF_ROWS = [
    {"report_date_as_yyyy_mm_dd": "2026-10-13T00:00:00.000",
     "cftc_contract_market_code": "13874A", "open_interest_all": "1900000",
     "lev_money_positions_long": "130000", "asset_mgr_positions_long": "1100000",
     "lev_money_positions_short": "500000", "asset_mgr_positions_short": "200000"},
    {"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
     "cftc_contract_market_code": "13874A", "open_interest_all": "1935470",
     "lev_money_positions_long": "135034", "asset_mgr_positions_long": "1101642",
     "lev_money_positions_short": "506279", "asset_mgr_positions_short": "200265"},
    {"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
     "cftc_contract_market_code": "133741", "open_interest_all": "21040",
     "lev_money_positions_long": "5466", "asset_mgr_positions_long": "4851",
     "lev_money_positions_short": "10408", "asset_mgr_positions_short": "1852"},
]
# Legacy futures-only (6dca-aqww): gold and WTI.
LEGACY_ROWS = [
    {"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
     "cftc_contract_market_code": "088691", "open_interest_all": "402279",
     "noncomm_positions_long_all": "237142", "noncomm_positions_short_all": "37277"},
    {"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
     "cftc_contract_market_code": "067651", "open_interest_all": "1835144",
     "noncomm_positions_long_all": "335112", "noncomm_positions_short_all": "245787"},
]


def test_tff_net_is_leveraged_funds_plus_asset_managers():
    frames = cot.parse(TFF_ROWS, cot.TFF_FIELDS)
    spx = frames["13874A"]
    assert list(spx["net"]) == [
        130000 + 1100000 - 500000 - 200000,
        135034 + 1101642 - 506279 - 200265,
    ]
    assert frames["133741"]["net"].iloc[-1] == 5466 + 4851 - 10408 - 1852
    assert spx["oi"].iloc[-1] == 1935470


def test_legacy_net_is_non_commercials():
    frames = cot.parse(LEGACY_ROWS, cot.LEGACY_FIELDS)
    assert frames["088691"]["net"].iloc[-1] == 237142 - 37277
    assert frames["067651"]["net"].iloc[-1] == 335112 - 245787


def test_a_row_with_a_missing_figure_is_dropped_not_zeroed():
    bad = {**TFF_ROWS[0], "lev_money_positions_short": None}
    assert cot.parse([bad], cot.TFF_FIELDS) == {}


def test_every_market_names_a_known_dataset_and_a_unique_key():
    assert {m.dataset for m in cot.MARKETS} <= {cot.TFF, cot.LEGACY}
    assert len({m.key for m in cot.MARKETS}) == len(cot.MARKETS)
    assert len({m.code for m in cot.MARKETS}) == len(cot.MARKETS)


def test_the_query_asks_for_the_markets_codes_and_a_three_year_window():
    url = cot._url(cot.TFF, ["13874A", "133741"], cot.TFF_FIELDS, date(2023, 9, 1))
    assert "gpe5-46if" in url
    assert "13874A" in url and "133741" in url
    assert "2023-09-01" in url


@pytest.fixture
def served(monkeypatch):
    """Serve each dataset's recorded rows by the dataset id in the URL."""
    log = []

    def get_bytes(url, **kw):
        log.append(url)
        rows = TFF_ROWS if cot.TFF in url else LEGACY_ROWS
        return json.dumps(rows).encode()

    monkeypatch.setattr(cot, "get_bytes", get_bytes)
    return log


def test_fetch_keys_by_market_and_asks_each_dataset_once(served):
    frames = cot.fetch(today=date(2026, 10, 27))
    assert set(frames) == {"sp500", "bitcoin", "gold", "crude"}
    assert len(served) == 2


def test_an_unreachable_host_is_no_markets_not_an_exception(monkeypatch):
    def boom(url, **kw):
        raise OSError("down")

    monkeypatch.setattr(cot, "get_bytes", boom)
    assert cot.fetch() == {}


def test_a_non_list_answer_is_no_markets(monkeypatch):
    monkeypatch.setattr(cot, "get_bytes", lambda url, **kw: b'{"error": true}')
    assert cot.fetch() == {}


def frame(nets, oi=1000.0):
    index = pd.date_range("2023-10-03", periods=len(nets), freq="7D")
    return pd.DataFrame({"net": nets, "oi": oi}, index=index)


MARKET = cot.MARKETS[0]


def test_the_most_long_week_in_three_years_is_crowded_long():
    nets = [*np.linspace(-100, 100, 120), 500.0]
    r = cot.reading(MARKET, frame(nets))
    assert r is not None
    assert r.percentile == 100.0
    assert r.crowded == "long"
    assert r.zscore is not None and r.zscore > 2
    assert r.week_change == pytest.approx(500.0 - 100.0)
    assert r.net_pct_oi == pytest.approx(50.0)


def test_the_most_short_week_is_crowded_short_and_a_middle_one_is_neither():
    low = cot.reading(MARKET, frame([*np.linspace(-100, 100, 120), -500.0]))
    mid = cot.reading(MARKET, frame([*np.linspace(-100, 100, 120), 0.0]))
    assert low is not None and low.crowded == "short"
    assert mid is not None and mid.crowded is None


def test_too_short_a_history_has_no_reading():
    assert cot.reading(MARKET, frame(list(range(10)))) is None


def test_the_window_is_the_last_three_years_only():
    # An extreme old print beyond 156 weeks must not move today's percentile.
    nets = [10_000.0] + [0.0] * 155 + [1.0]
    r = cot.reading(MARKET, frame(nets))
    assert r is not None
    assert r.percentile == 100.0


def test_a_flat_history_has_no_zscore():
    r = cot.reading(MARKET, frame([5.0] * 80))
    assert r is not None and r.zscore is None


def test_readings_come_in_market_order_and_skip_missing_ones():
    frames = {"gold": frame(list(range(80))), "sp500": frame(list(range(80)))}
    assert [r.key for r in cot.readings(frames)] == ["sp500", "gold"]
