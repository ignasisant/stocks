"""What the filings cannot see, on real companies.

The Review engine scores a record, and a record is the past. These pin the
readings that look forward (a business a new technology can copy, an industry
in decline, a cycle's top and bottom, profits already shrinking, pay in shares
the estimates leave out) on rows frozen from the sector scan of 2026-11-16,
then on whole books and on the sector map, which is the same engine.

No network: the fixture carries only the keys the engine reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from stocks import loaders
from stocks.analysis import review
from stocks.analysis.sectors import SectorScan
from stocks.api.app import app as fastapi_app
from tests.patching import patch_loaders

ROWS: dict[str, dict] = json.loads(
    (Path(__file__).parent / "fixtures" / "review_forward_rows.json").read_text()
)
RANK = {review.PASS: 0, review.WATCH: 1, review.BUY: 2}


def outside(ticker: str, **changed) -> review.Verdict:
    return review.judge_candidate({**ROWS[ticker], **changed}, kind="stock")


# A business a new technology can copy.


def test_adobe_reads_dearer_for_what_ai_can_copy_and_says_so():
    """The user's case: nine times earnings and a 41% return on capital read
    as a bargain, on a product a model can now write."""
    adobe = ROWS["ADBE"]
    feared = review.score(adobe)
    unafraid = review.score({**adobe, "industry": "Software - Infrastructure"})
    assert feared.threat == review.R_AI_RISK and unafraid.threat is None
    assert unafraid.cheapness - feared.cheapness > 15
    # The record is what it is: only the price is asked for more.
    assert feared.quality == pytest.approx(unafraid.quality)
    v = outside("ADBE")
    assert v.reasons.index(review.R_AI_RISK) == v.reasons.index(review.R_CHEAP) + 1
    # Growth no longer excuses the multiple.
    assert review.R_CHEAP_FOR_GROWTH not in v.reasons
    assert review.R_CHEAP_FOR_GROWTH in outside(
        "ADBE", industry="Software - Infrastructure"
    ).reasons
    # Cheap after the discount and still no buy: the two thirds are a guess
    # at what a model takes, and a guess is a caution.
    assert review.score(adobe).cheapness >= review.CHEAP
    assert v.verdict == review.WATCH
    assert review.R_CLOSE_CALL not in v.reasons
    assert outside("ADBE", industry="Software - Infrastructure").verdict == review.BUY


def test_a_ride_filed_as_software_is_not_a_business_a_model_writes():
    """The feed files Uber under application software; it sells a ride."""
    uber = {**ROWS["UBER"], "ticker": "UBER"}
    assert review.threat(uber) is None
    assert review.R_AI_RISK not in review.judge_candidate(uber, kind="stock").reasons
    assert review.score(uber).cheapness > review.score(ROWS["UBER"]).cheapness
    # By name, not by industry: the next company filed there keeps the fear,
    # and so does a row that does not say whose it is.
    assert review.threat({**uber, "ticker": "ADBE"}) == review.R_AI_RISK
    assert review.threat(ROWS["UBER"]) == review.R_AI_RISK
    # Only what a model might copy is forgiven by name, not a decline.
    tobacco = {**ROWS["MO"], "ticker": "UBER"}
    assert review.threat(tobacco) == review.R_SECULAR_DECLINE


@pytest.mark.parametrize("ticker", ["CRM", "INTU", "ACN", "IBM"])
def test_a_copyable_business_at_a_fair_price_waits(ticker):
    feared = outside(ticker)
    assert feared.verdict == review.WATCH
    assert review.R_AI_RISK in feared.reasons
    # The fear is what holds it: the same figures elsewhere are a buy.
    assert outside(ticker, industry="Software - Infrastructure").verdict == review.BUY


def test_the_fear_is_the_industrys_not_every_tech_names():
    for ticker in ("MSFT", "GOOGL", "NVDA", "META", "NFLX"):
        assert review.score(ROWS[ticker]).threat is None
    # Read on its own lens, a lender carries none whatever the label says.
    assert review.threat(ROWS["JPM"]) is None


def test_an_industry_in_decline_is_priced_at_two_thirds():
    altria, morris = outside("MO"), outside("PM")
    # 11x earnings pays for a decline decades old: a discount, not a caution.
    assert altria.verdict == review.BUY
    assert review.R_SECULAR_DECLINE not in review.cautions(ROWS["MO"])
    assert review.R_AI_RISK in review.cautions(ROWS["ADBE"])
    assert morris.verdict == review.WATCH  # 22x does not
    for v in (altria, morris):
        assert review.R_SECULAR_DECLINE in v.reasons
    assert outside("PM", industry="Beverages - Non-Alcoholic").verdict == review.BUY


def test_the_haircut_is_three_points_of_return_on_a_perpetuity():
    grows = 0.03
    worth = (review.HURDLE - grows) / (review.HURDLE + 0.03 - grows)
    assert pytest.approx(worth) == 1 - review.THREAT_HAIRCUT


# A cycle is not a level.


def test_a_memory_maker_at_four_times_its_normal_margin_waits():
    micron = outside("MU")
    assert micron.verdict == review.WATCH
    assert review.R_PEAK_MARGIN in micron.reasons
    assert review.score(ROWS["MU"]).normal_pe
    # No down year in the filed record: the industry alone says cycle.
    assert ROWS["MU"]["revenue_down_years"] == 0
    assert review.R_PEAK_MARGIN not in outside(
        "MU", industry="Software - Infrastructure"
    ).reasons


def test_a_smaller_loss_is_not_the_top_of_a_cycle():
    """Intel at a 10% margin on a median of nothing, its last twelve months
    still a loss; Boeing's margin under zero, above a worse median. Both read
    "margin at a peak" on the map, 2026-11-17."""
    for ticker in ("INTC", "BA"):
        assert review.R_PEAK_MARGIN not in outside(ticker).reasons
        assert not review.score(ROWS[ticker]).normal_pe
    # The same margin with a year's profit behind it is a top.
    assert ROWS["INTC"]["pe_ttm"] < 0
    assert review.R_PEAK_MARGIN in outside("INTC", pe_ttm=30.0).reasons
    assert review.R_PEAK_MARGIN not in outside("INTC", pe_ttm=30.0, op_margin=0.0).reasons
    # A row the feed gives no trailing P/E for is judged on its margin alone.
    assert review.R_PEAK_MARGIN in outside("INTC", pe_ttm=None).reasons


def test_growth_at_a_peak_does_not_excuse_the_multiple():
    """Micron: sales doubling with the price of memory read 20 times a normal
    year's earnings as cheap for their growth, and the price leg scored 100."""
    micron = ROWS["MU"]
    assert review.priced_growth_pe(micron) is None
    read = outside("MU")
    assert review.R_CHEAP_FOR_GROWTH not in read.reasons
    assert read.metrics["growth_pe"] is None
    # Off the peak the same growth is the business's own, and counts.
    normal = {**micron, "op_margin": micron["op_margin_median"]}
    assert review.priced_growth_pe(normal) is not None
    assert review.score(micron).cheapness < review.score(normal).cheapness


def test_a_row_shows_the_growth_pe_only_where_the_price_read_it():
    """Altria showed "P/E per growth 11.3x" beside Buy: the price had left
    the figure out (an industry in decline), the row had not."""
    altria = outside("MO")
    assert altria.verdict == review.BUY
    assert altria.metrics["growth_pe"] is None
    assert review.R_CHEAP_FOR_GROWTH not in altria.reasons
    for ticker in ("ADBE", "JPM", "RWE.DE"):  # a fear, a bank, a utility
        assert outside(ticker).metrics["growth_pe"] is None
    # Where the price does read it, the row shows that very figure.
    google = outside("GOOGL")
    assert google.metrics["growth_pe"] == review.priced_growth_pe(ROWS["GOOGL"])
    assert google.metrics["growth_pe"] is not None


def test_a_machinery_maker_at_the_bottom_of_its_cycle_is_not_sold():
    deere = review.judge_held(ROWS["DE"], weight=0.03, risk_share=0.03, names=20)
    assert deere.verdict == review.HOLD
    assert review.R_TROUGH_MARGIN in deere.reasons
    assert review.score(ROWS["DE"]).normal_pe
    elsewhere = {**ROWS["DE"], "industry": "Specialty Retail"}
    plain = review.judge_held(elsewhere, weight=0.03, risk_share=0.03, names=20)
    assert review.R_TROUGH_MARGIN not in plain.reasons
    assert review.score(elsewhere).cheapness < review.score(ROWS["DE"]).cheapness


def test_a_cyclical_at_a_loss_or_near_its_median_is_no_trough():
    deere = ROWS["DE"]
    assert review._at_trough(deere)
    assert not review._at_trough({**deere, "op_margin": -0.02})
    assert not review._at_trough({**deere, "op_margin": deere["op_margin_median"]})
    # A weak business priced for perfection is still sold at its bottom.
    tesla = review.judge_held(ROWS["TSLA"], weight=0.03, risk_share=0.03, names=20)
    assert tesla.verdict == review.SELL


# Profits already shrinking.


@pytest.mark.parametrize("ticker", ["HD", "EQNR.OL"])
def test_profits_falling_on_a_lower_margin_stop_a_buy(ticker):
    v = outside(ticker)
    assert v.verdict == review.WATCH
    assert review.R_SHRINKING in v.reasons
    assert outside(ticker, net_income_cagr=0.02).verdict == review.BUY


def test_falling_profits_on_a_margin_that_held_are_only_named():
    bhp = outside("BHP.L")
    assert ROWS["BHP.L"]["net_income_cagr"] <= -review.EARNINGS_SHRINK
    assert review.R_SHRINKING in bhp.reasons
    assert bhp.verdict == review.BUY


# The forward P/E is the owner's.

PAID_IN_SHARES = {
    "pe_fwd": 20.0, "ps": 5.0, "sbc_revenue": 0.10, "fcf_yield": 0.05,
    "ev_ebitda": 15.0, "ev": 1e11, "roic": 0.30, "op_margin": 0.30, "moat": 80.0,
}


def test_pay_in_shares_comes_off_the_forward_earnings():
    # 5% earnings yield less 2% of the cap handed to staff: 3%, so 33x.
    assert review.owner_pe(PAID_IN_SHARES) == pytest.approx(1 / 0.03)
    charged = review.score(PAID_IN_SHARES)
    free = review.score({**PAID_IN_SHARES, "sbc_revenue": 0.0})
    assert charged.cheapness < free.cheapness
    assert charged.quality == pytest.approx(free.quality)
    shown = review.judge_candidate(PAID_IN_SHARES).metrics
    assert shown["pe_owner"] == pytest.approx(1 / 0.03)
    assert shown["pe_fwd"] == 20.0


def test_the_charge_never_passes_the_filed_pe_nor_the_ceiling():
    # An estimate that is already the filed kind: the trailing P/E pays it.
    filed = {**PAID_IN_SHARES, "pe_ttm": 25.0}
    assert review.owner_pe(filed) == pytest.approx(25.0)
    growing = {**filed, "revenue_growth": 0.25, "revenue_cagr": 0.25}
    assert review.owner_pe(growing) is None  # 25 / 1.25: the estimate stands
    # Pay that eats the adjusted profit reads only "dear".
    eaten = {**PAID_IN_SHARES, "sbc_revenue": 0.30}
    assert review.owner_pe(eaten) == review.PE_CEILING


def test_a_token_grant_a_lender_and_a_trailing_pe_are_left_as_they_are():
    token = {**PAID_IN_SHARES, "sbc_revenue": review.SHARE_PAY_MIN - 0.001}
    bank = {**PAID_IN_SHARES, "industry": "Banks - Regional"}
    trailing = {**PAID_IN_SHARES, "pe_fwd": None, "pe_ttm": 22.0}
    for metrics in (token, bank, trailing):
        assert review.owner_pe(metrics) is None
        assert review.judge_candidate(metrics).metrics["pe_owner"] is None
    assert outside("PG").metrics["pe_owner"] is None
    assert outside("ADBE").metrics["pe_owner"] > ROWS["ADBE"]["pe_fwd"]


def test_an_estimate_the_last_year_cannot_be_squared_with_is_dropped():
    """Tokyo Electron: 7x forward on 49x trailing, a feed that missed a
    split. The forward P/E made it the cheapest chip name on the map."""
    tel = ROWS["8035.T"]
    assert review._estimate_broken(tel, tel["pe_fwd"])
    v = outside("8035.T")
    assert review.R_TRAILING_PE in v.reasons
    assert v.verdict == review.WATCH
    assert review.score(tel).cheapness < review.CHEAP
    # A margin under its median is a bad year to recover from, not an error.
    recovering = {**tel, "op_margin": tel["op_margin_median"] - 0.05}
    assert not review._estimate_broken(recovering, tel["pe_fwd"])
    # Real growth clears it: Micron and Nvidia keep their estimates.
    for ticker in ("MU", "NVDA", "ADBE", "RWE.DE"):
        row = ROWS[ticker]
        assert not review._estimate_broken(row, row["pe_fwd"])


# A lower price never reads dearer.

CROSSING = {
    "pe_fwd": 10.0, "fcf_yield": 0.09, "ev_ebitda": 8.0, "ev": 1e11,
    "market_cap": 9e10, "roic": 0.30, "op_margin": 0.30, "moat": 70.0,
    "dividend_yield": 0.034,
}


def test_a_yield_crossing_the_dividend_bar_does_not_step_the_price_down():
    """At 3.4% the yield was out; a 5% lower price put it in at the bar,
    under every other input, and the name read dearer for it."""
    now = review.score(CROSSING)
    lower = review.score(review.at_price(CROSSING, 0.95))
    assert review.at_price(CROSSING, 0.95)["dividend_yield"] > review.DIVIDEND_LEG_MIN
    assert lower.cheapness > now.cheapness
    # Where it is the cheapest reading it still counts.
    rich = {**CROSSING, "pe_fwd": 30.0, "ev_ebitda": 25.0, "fcf_yield": 0.02}
    paying = review.score({**rich, "dividend_yield": 0.06})
    assert paying.cheapness > review.score(rich).cheapness


@settings(max_examples=400, deadline=None)
@given(
    st.sampled_from(sorted(ROWS)),
    st.floats(min_value=0.5, max_value=1.5),
    st.floats(min_value=0.5, max_value=1.5),
)
def test_a_lower_price_never_reads_dearer_nor_a_worse_verdict(ticker, one, other):
    low, high = sorted((one, other))
    cheaper = review.at_price(ROWS[ticker], low)
    dearer = review.at_price(ROWS[ticker], high)
    a, b = review.score(cheaper), review.score(dearer)
    if a.stage != b.stage or a.suspect or b.suspect:
        return  # another ruler, or inputs the scores refuse
    if a.cheapness is None or b.cheapness is None:
        return
    assert a.cheapness >= b.cheapness - 1e-9
    assert a.quality == pytest.approx(b.quality)
    was = review.judge_candidate(dearer, kind="stock").verdict
    then = review.judge_candidate(cheaper, kind="stock").verdict
    if was in RANK and then in RANK:
        assert RANK[then] >= RANK[was]


# Whole books: what Sell or add tells each one.

#: An add the book's own sales do not pay for: held, with the weight new
#: money would take it to.
NEW_MONEY = "add with new money"


def plan(book: dict[str, float]) -> dict[str, str]:
    """The verdicts on a book of stocks, the rest of it in one world fund."""
    rows = [(ROWS[ticker], weight, "stock") for ticker, weight in book.items()]
    rest = 1 - sum(book.values())
    if rest > 0.01:
        rows.append((None, rest, "equity_fund"))
    names = sum(review.company(kind) for _, _, kind in rows)
    judged = [
        (w, review.judge_held(m, weight=w, risk_share=w, kind=kind, names=names))
        for m, w, kind in rows
    ]
    out = review.redeploy(judged)
    return {
        ticker: NEW_MONEY if review.R_NEW_MONEY in v.reasons else v.verdict
        for ticker, v in zip(book, out, strict=False)
    }


def test_a_software_book_is_not_added_to_however_cheap_it_reads():
    names = ("ADBE", "CRM", "INTU", "IBM", "ACN", "UBER", "MSFT", "CTSH")
    book = dict.fromkeys(names, 0.03)
    assert plan(book) == dict.fromkeys(names, review.HOLD)
    # Adobe and Cognizant clear both bars after the discount: the fear alone
    # holds them, and the same rows filed elsewhere are added to.
    for ticker in ("ADBE", "CTSH"):
        scores = review.score(ROWS[ticker])
        assert scores.quality >= review.GOOD and scores.cheapness >= review.CHEAP
        moved = {**ROWS[ticker], "industry": "Software - Infrastructure"}
        held = review.judge_held(moved, weight=0.03, risk_share=0.03, names=20)
        assert held.verdict == review.ADD


def test_a_cyclical_book_waits_at_the_peak_holds_at_the_bottom_and_sells_the_weak():
    book = dict.fromkeys(
        ("MU", "NVDA", "DE", "TSLA", "INTC", "EQNR.OL", "BHP.L", "8035.T"), 0.03
    )
    assert plan(book) == {
        "NVDA": review.ADD, "BHP.L": review.ADD,
        "MU": review.HOLD,  # peak margin
        "DE": review.HOLD,  # trough margin
        "EQNR.OL": review.HOLD,  # profits shrinking
        "8035.T": review.HOLD,  # dear once the broken estimate is dropped
        "TSLA": review.SELL, "INTC": review.SELL,
    }


def test_an_income_book_is_not_added_to_for_the_yield_alone():
    book = dict.fromkeys(
        ("MO", "PM", "PG", "MCD", "T", "JPM", "HD", "RWE.DE", "WPP.L"), 0.03
    )
    assert plan(book) == {
        "MO": NEW_MONEY, "PG": NEW_MONEY, "MCD": NEW_MONEY,
        "PM": review.HOLD,  # a declining industry at 22x
        "T": review.HOLD, "WPP.L": review.HOLD,  # cheap, not good enough
        "JPM": review.HOLD, "RWE.DE": review.HOLD,  # good, not cheap
        "HD": review.HOLD,  # profits shrinking
    }


def test_a_concentrated_book_cuts_the_big_one_sells_the_weak_and_feeds_the_rest():
    book = {
        "ADBE": 0.40, "TSLA": 0.20, "MU": 0.15, "BKNG": 0.10, "BA": 0.10, "PYPL": 0.05,
    }
    assert plan(book) == {
        "ADBE": review.TRIM, "TSLA": review.SELL, "BA": review.SELL,
        "MU": review.HOLD, "BKNG": review.ADD, "PYPL": review.ADD,
    }


# The sector map: the same engine over a cohort.

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
COHORTS = {
    "Technology": ("ADBE", "CRM", "INTU", "IBM", "MSFT", "NVDA", "MU", "8035.T", "INTC"),
    "Consumer Defensive": ("MO", "PM", "PG"),
    "Industrials": ("DE", "BA"),
}
MAP = {
    "NVDA": review.BUY, "MO": review.BUY, "PG": review.BUY,
    "ADBE": review.WATCH, "CRM": review.WATCH, "INTU": review.WATCH, "IBM": review.WATCH,
    "MSFT": review.WATCH, "MU": review.WATCH, "8035.T": review.WATCH,
    "PM": review.WATCH,
    "INTC": review.PASS, "DE": review.PASS, "BA": review.PASS,
}


@pytest.fixture
def cold_cache():
    loaders.sector_scans.cache_clear()
    yield
    loaders.sector_scans.cache_clear()


@pytest.fixture
def scanned(cold_cache, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    scans = {
        sector: SectorScan(
            sector=sector,
            as_of="2026-11-16",
            tickers=tickers,
            metrics=tuple({"ticker": t, **ROWS[t]} for t in tickers),
            scores={},
            podium=(),
        )
        for sector, tickers in COHORTS.items()
    }
    patch_loaders(monkeypatch, "sector_scans", lambda: scans)


@pytest.mark.parametrize("sector", sorted(COHORTS))
def test_the_sector_map_places_each_company_where_the_review_would(scanned, sector):
    payload = TestClient(fastapi_app).get(f"/v1/sectors/{sector}", headers=AUTH).json()
    judged = {row["ticker"]: row["judged"] for row in payload["rows"]}
    assert {t: j["verdict"] for t, j in judged.items()} == {
        t: MAP[t] for t in COHORTS[sector]
    }
    for ticker, read in judged.items():
        scores = review.score(ROWS[ticker])
        assert read["cheapness"] == pytest.approx(scores.cheapness)
        if scores.threat:
            assert scores.threat in read["reasons"]


# Networks: one industry on a ruler that tells its names apart.


def test_networks_are_priced_against_each_other_not_against_software():
    """On the common ranges AT&T, Verizon and Comcast all read 99 or 100 and
    T-Mobile 89: six times EBITDA is every network's price, not a bargain."""
    price = {t: review.score(ROWS[t]).cheapness for t in ("CMCSA", "T", "VZ", "TMUS")}
    assert price["CMCSA"] > price["T"] > price["VZ"] > price["TMUS"]
    assert price["CMCSA"] - price["TMUS"] > 30
    assert price["TMUS"] < review.CHEAP <= price["VZ"]
    for ticker, cheap in price.items():
        common = {**ROWS[ticker], "industry": "Specialty Retail"}
        assert review.score(common).cheapness > cheap
        # The record is read on the common ranges, as everyone's.
        assert review.score(common).quality == pytest.approx(
            review.score(ROWS[ticker]).quality
        )


def test_a_network_carries_a_utilitys_debt():
    geared = {**ROWS["T"], "net_debt_ebitda": 4.0}
    assert review.R_DEBT not in outside("T", net_debt_ebitda=4.0).reasons
    assert review.debt_line(geared) == review.REGULATED_DEBT
    assert review.R_DEBT in outside("T", net_debt_ebitda=5.2).reasons


# A maker that lends to its buyers.

#: Receivables over assets, read off the feed 2026-11-17 (the scan of the
#: 16th did not carry the figure).
OWED = {"DE": 0.56, "TSLA": 0.03}


def test_a_lending_arm_changes_what_the_maker_is_told_never_its_score():
    """Deere read "heavy debt" at 4.8 times EBITDA: the debt is John Deere
    Financial's, borrowed against the loans its customers owe."""
    plain = ROWS["DE"]
    deere = {**plain, "receivable_share": OWED["DE"]}
    assert review.lending_arm(deere) and not review.lending_arm(plain)
    before, after = outside("DE"), review.judge_candidate(deere, kind="stock")
    assert review.R_DEBT in before.reasons and review.R_DEBT not in after.reasons
    assert after.reasons[0] == review.R_LENDING_ARM
    assert set(before.reasons) - set(after.reasons) == {review.R_DEBT}
    # No leg leaves the score: what it would be scored on instead is a guess.
    assert (after.verdict, after.quality, after.cheapness) == (
        before.verdict, before.quality, before.cheapness,
    )
    held = review.judge_held(deere, weight=0.03, risk_share=0.03, names=20)
    assert held.verdict == review.HOLD and review.R_DEBT not in held.reasons


def test_a_low_return_on_a_loan_book_is_not_named_against_the_maker():
    toyota = {**ROWS["DE"], "roic": 0.049, "roic_ex_goodwill": 0.049}
    assert review.R_LOW_ROIC in review.judge_candidate(toyota, kind="stock").reasons
    lending = {**toyota, "receivable_share": 0.41}
    read = review.judge_candidate(lending, kind="stock")
    assert review.R_LOW_ROIC not in read.reasons
    assert review.score(lending).quality == review.score(toyota).quality


def test_a_maker_on_thin_equity_is_still_told_its_debt_is_heavy():
    """Ford: 12% of its assets are its own."""
    ford = {**ROWS["DE"], "receivable_share": 0.44, "equity_share": 0.12}
    assert review.indebted(ford)
    assert review.R_DEBT in review.judge_candidate(ford, kind="stock").reasons
    assert not review.indebted({**ford, "equity_share": 0.22})
    assert not review.indebted({**ford, "equity_share": None})


def test_a_maker_that_sells_for_cash_is_read_as_before():
    tesla = {**ROWS["TSLA"], "receivable_share": OWED["TSLA"]}
    assert not review.lending_arm(tesla)
    assert review.judge_candidate(tesla, kind="stock") == outside("TSLA")
    # Nor is it an arm for the receivables alone: a contractor is owed too.
    builder = {**ROWS["DE"], "industry": "Engineering & Construction"}
    assert not review.lending_arm({**builder, "receivable_share": 0.56})
    assert review.R_DEBT in review.judge_candidate(
        {**builder, "receivable_share": 0.56}, kind="stock"
    ).reasons


def test_the_map_carries_the_owners_pe_and_the_fear(scanned):
    payload = TestClient(fastapi_app).get("/v1/sectors/Technology", headers=AUTH).json()
    adobe = next(r["judged"] for r in payload["rows"] if r["ticker"] == "ADBE")
    assert adobe["metrics"]["pe_owner"] > adobe["metrics"]["pe_fwd"]
    assert review.R_AI_RISK in adobe["reasons"]
    micron = next(r["judged"] for r in payload["rows"] if r["ticker"] == "MU")
    assert review.R_PEAK_MARGIN in micron["reasons"]
