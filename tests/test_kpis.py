"""The KPI registry (`stocks.analysis.kpis`): every figure the review reads is
registered, quality cannot read a price, and the two versions that name
persisted data move whenever the numbers do."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from stocks.analysis import fundamentals, kpis, review
from stocks.analysis.fundamentals import KPI_SOURCES, compute_metrics
from stocks.data import score_history
from tests.test_fundamentals import YEARS, sample_raw

ROWS = json.loads((Path(__file__).parent / "fixtures" / "review_rows.json").read_text())


def _assigned_keys() -> set[str]:
    """Every key `compute_metrics` writes: `m["key"] = ...` in its body and
    the dict literals the helpers it merges in (`m.update(...)`) return."""
    keys: set[str] = set()
    tree = ast.parse(inspect.getsource(compute_metrics))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.value, ast.Name)
            and node.value.id == "m"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
    for helper in (fundamentals._dividend,):
        for node in ast.walk(ast.parse(inspect.getsource(helper))):
            if isinstance(node, ast.Dict):
                keys |= {k.value for k in node.keys if isinstance(k, ast.Constant)}
    return keys


def test_every_key_compute_metrics_writes_is_registered():
    written = _assigned_keys()
    assert {"pe_ttm_reported", "dividend_yield", "peg"} <= written  # the walk works
    assert written - set(kpis.KPIS) == set()
    assert set(compute_metrics(sample_raw())) - set(kpis.KPIS) == set()


def test_every_key_the_review_reads_is_registered():
    """A figure read by name that is not in the table would pass the business
    view as business, price or not."""
    source = inspect.getsource(review)
    read = set(re.findall(r'_num\((?:metrics|biz), "(\w+)"\)', source))
    read |= set(re.findall(r'metrics\.get\("(\w+)"\)', source))
    read -= {"weight"}
    assert read, "the pattern stopped matching the engine's reads"
    assert read - set(kpis.KPIS) == set()


def test_every_ticker_page_kpi_is_registered():
    assert set(KPI_SOURCES) - set(kpis.KPIS) == set()


def test_the_business_view_refuses_a_price_loudly():
    row = ROWS[0]
    biz = kpis.business(row)
    assert biz["roe"] == row["roe"]
    for key in ("pe_fwd", "fcf_yield", "ev_ebitda", "market_cap"):
        with pytest.raises(kpis.PriceInQuality):
            biz.get(key)
        with pytest.raises(kpis.PriceInQuality):
            _ = key in biz
    assert not {k for k in biz if kpis.kpi(k).kind in ("price", "yield", "enterprise")}
    # A stored row from another version, with a key this one does not know,
    # still scores.
    assert kpis.business({"someday_kpi": 1.0})["someday_kpi"] == 1.0


@pytest.mark.parametrize("row", ROWS, ids=[r["ticker"] for r in ROWS])
def test_quality_does_not_move_with_the_price(row):
    """The scan's rows at half and double the price: quality stays put, unless
    the move carries the name across the early stage's line (`_unsold`)."""
    now = review.score(row)
    for factor in (0.5, 2.0):
        then = review.score(review.at_price(row, factor))
        if then.stage == now.stage:
            assert then.quality == now.quality


def test_a_replay_moves_every_priced_kind_and_nothing_else():
    row = {**ROWS[0], "peg": 1.5, "pe_ttm_reported": 20.0}
    then = review.at_price(row, 2.0)
    for key, value in row.items():
        kind = kpis.kpi(key).kind
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if kind == "price":
            assert then[key] == pytest.approx(value * 2), key
        elif kind == "yield":
            assert then[key] == pytest.approx(value / 2), key
        elif kind in ("business", "identity"):
            assert then[key] == value, key


# ---------------------------------------------------------------- versions


def _digest(payload) -> str:
    text = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _rounded(value):
    """Nine significant figures: a platform's last bit of a `pow` must not
    move the digest, and `round(x, 6)` does nothing at 1e11."""
    if isinstance(value, float):
        return float(f"{value:.9g}")
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def _fingerprint_raw():
    """`sample_raw` with the inputs its plain version leaves out: estimates
    for the forward P/E, goodwill, share-based pay, a dividend, a balance."""
    raw = sample_raw()
    raw.info.update(
        {
            "epsCurrentYear": 7.4,
            "epsForward": 8.1,
            "nextFiscalYearEnd": int(datetime(2026, 9, 30, tzinfo=UTC).timestamp()),
            "dividendYield": 0.5,
            "payoutRatio": 0.15,
            "revenueGrowth": 0.06,
            "heldPercentInsiders": 0.01,
            "industry": "Consumer Electronics",
            "financialCurrency": "USD",
            "averageVolume": 5e7,
        }
    )
    raw.balance.loc["Goodwill"] = [20e9] * 5
    raw.balance.loc["Total Assets"] = [360e9] * 5
    raw.balance.loc["Stockholders Equity"] = [70e9] * 5
    raw.balance.loc["Cash And Cash Equivalents"] = [30e9] * 5
    raw.cashflow.loc["Stock Based Compensation"] = [11e9, 10e9, 9e9, 8e9, 7e9]
    raw.cashflow.loc["Operating Cash Flow"] = [110e9, 104e9, 100e9, 92e9, 80e9]
    raw.cashflow.loc["Cash Dividends Paid"] = [-15e9] * 5
    raw.cashflow.loc["Capital Expenditure"] = [-12e9] * 5
    raw.cashflow.loc["Depreciation And Amortization"] = [10e9] * 5
    raw.balance.loc["Notes Receivable"] = [40e9] * 5
    raw.balance.loc["Investment Properties"] = [5e9] * 5
    # A quarter of the profit one-off: the trailing P/E is on normalized
    # income and the reported one kept beside it.
    raw.income_q = pd.DataFrame(
        {
            "Net Income": [33e9, 32e9, 30e9, 31e9],
            "Normalized Income": [26e9, 25e9, 24e9, 25e9],
        },
        index=YEARS[:4],
    ).T
    return raw


def _burning_raw():
    """A cash burner: the runway."""
    raw = sample_raw()
    raw.cashflow.loc["Free Cash Flow"] = [-20e9] * 5
    raw.info["totalCash"] = 50e9
    return raw


def _pence_raw():
    """A line quoted in pence, filed in pounds, estimated in pounds: the
    forward P/E's unit and the converted figures."""
    raw = _fingerprint_raw()
    raw.ticker = "TEST.L"
    raw.info.update(
        {
            "currency": "GBp",
            "financialCurrency": "GBP",
            "currentPrice": 1369.6,
            "epsCurrentYear": 0.48,
            "epsForward": 0.51,
        }
    )
    return raw


class _Day(date):
    @classmethod
    def today(cls):
        return cls(2026, 6, 1)


def _metrics_digest(monkeypatch, day: type[date] = _Day) -> str:
    monkeypatch.setattr(fundamentals, "date", day)
    # A fixed rate, so the digest never reads a live one.
    monkeypatch.setattr(fundamentals.fx, "spot", lambda *a, **k: (1.25, "2026-06-01"))
    return _digest(
        [
            _rounded(compute_metrics(raw()))
            for raw in (_fingerprint_raw, _burning_raw, _pence_raw)
        ]
    )


#: Bump `kpis.VERSION` and pin the new digest when this fails: a memo or a
#: recorded score under the old version is not the same figure any more.
METRICS = (3, "9da4725fa160fb3f")


def test_metrics_change_only_with_their_version(monkeypatch):
    assert (kpis.VERSION, _metrics_digest(monkeypatch)) == METRICS


def _scores_digest() -> str:
    return _digest(
        [
            [_rounded(dataclasses.asdict(review.score(r))) for r in ROWS],
            [
                _rounded(dataclasses.asdict(review.score(review.at_price(r, 0.5))))
                for r in ROWS
            ],
        ]
    )


#: Bump `review.FORMULA` and pin the new digest when this fails: the map's
#: history under the old scale would draw a move nobody made.
SCORES = ("3.2", "fc7620acc5f1257a")


def test_scores_change_only_with_their_scale():
    assert (review.SCALE, _scores_digest()) == SCORES


def test_the_score_history_file_is_named_by_the_scale():
    assert score_history.NAME == f"history-{review.SCALE}.json"
