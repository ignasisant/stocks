"""The daily card's sections (stocks.chat.daily, daily_book, daily_routines).

With no brief the card reads in three fixed sections — Portfolio, Today's
alerts, Worth a look; with one, the alerts and then a section per line of the
brief. What is tested here is what each promises:

* Portfolio is computed: the book's day, week and month against the index,
  only with the index in hand, and the month drawn from the same anchoring;
* every alert that fired is on the card, whatever the model wrote;
* a brief is answered from data fetched for it, line by line: a line quoting
  a figure the data does not carry goes, not the card; a brief no model wrote
  says so (`missed`), and one still being fetched says that (`pending`);
* the card spends at most FREE_UNITS of the account's free allowance a day;
* the charts are attached after the card is built, never through the facts.

Pure: no network, no clock.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pandas as pd

from stocks.chat import (
    charts,
    daily,
    daily_book,
    daily_routines,
    learnings,
    market,
    signals,
)

TODAY = date(2026, 9, 29)

INDEX = {
    "name": "S&P 500",
    "symbol": "SPY",
    "currency": "EUR",
    "as_of": "2026-09-28",
    "day_pct": 0.3,
    "week_pct": 1.1,
    "month_pct": None,
}

ALERT = {
    "kind": "alert_hit", "ticker": "AAPL", "rule": "above", "level": 260.0,
    "price": 265.0, "held": True, "gap_pct": 1.92, "sessions": 1,
    "key": "alert_hit:AAPL",
}
EARNINGS = {
    "kind": "earnings", "ticker": "NVDA", "in_days": 3, "date": "2026-10-02",
    "held": True, "phase": "soon", "key": "earnings:NVDA",
}


def book_facts(**over) -> dict:
    return {
        "date": TODAY.isoformat(),
        "currency": "EUR",
        "day": {"pct": 0.8, "amount": 120.0},
        "week": {"pct": 1.5, "amount": 220.0},
        "month": {"pct": -2.0, "amount": -300.0},
        "index": dict(INDEX),
        "actions": [dict(ALERT), dict(EARNINGS)],
    } | over


BRIEF = {
    "asks": [
        {"n": 1, "ask": "how is NVDA doing"},
        {"n": 2, "ask": "is ASML above 700?"},
        {"n": 3, "ask": "my insiders"},
    ],
    "sig": "abc123",
    "quotes": [{"ticker": "NVDA", "price": 182.5, "currency": "USD",
                "change_pct": 1.25}],
    "insiders": [{"ticker": "NVDA", "window_days": 30, "buys": 0, "sells": 2,
                  "sell_value": 4200000.0, "currency": "USD"}],
}


def daily_series(start: str, values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ------------------------------------------------------------- the portfolio


def test_a_window_is_anchored_as_the_basket_anchors_it():
    s = daily_series("2026-09-01", [100.0 + i for i in range(29)])  # to Sep 29
    assert daily_book.change(s, 1) == s.iloc[-1] / s.iloc[-2] - 1
    # The week opens on the last close at least seven calendar days back.
    assert daily_book.change(s, 7) == s.iloc[-1] / s.loc["2026-09-22"] - 1
    assert daily_book.change(s, 60) is None


def test_the_index_facts_carry_each_window(monkeypatch):
    s = daily_series("2026-08-20", [500.0 + i for i in range(41)])
    monkeypatch.setattr(daily_book, "index_series", lambda closes, ccy: (s, "EUR"))
    facts = daily_book.index_facts({}, "EUR")
    assert facts["name"] == "S&P 500" and facts["currency"] == "EUR"
    assert facts["as_of"] == s.index[-1].date().isoformat()
    assert facts["day_pct"] == round((540 / 539 - 1) * 100, 2)
    assert set(facts) >= {"week_pct", "month_pct"}


def test_no_index_means_no_section():
    assert daily_book.section(book_facts(index=None)) == {}
    assert daily_book.section(book_facts(index={})) == {}


def test_the_section_is_the_book_against_the_index():
    section = daily_book.section(book_facts())
    assert section["index"] == "S&P 500" and section["currency"] == "EUR"
    assert [r["window"] for r in section["rows"]] == ["day", "week", "month"]
    assert section["rows"][0] == {
        "window": "day", "pct": 0.8, "amount": 120.0, "index_pct": 0.3,
    }
    # The index's month did not download: the book's row stands without it.
    assert section["rows"][2]["index_pct"] is None


def test_a_watchlist_only_account_has_no_section():
    facts = book_facts(day={}, week={}, month={})
    assert daily_book.section(facts) == {}


def test_the_month_is_drawn_as_growth_from_its_first_day(monkeypatch):
    idx = pd.date_range("2026-08-20", "2026-09-29", freq="D")
    hist = pd.DataFrame(
        {"A": [100.0 + i for i in range(len(idx))],
         # Priced only from mid-window: summed over the names priced at both
         # ends, as basket_change sums them, so it is left out.
         "B": [None] * 20 + [50.0] * (len(idx) - 20)},
        index=idx,
    )
    spy = daily_series("2026-08-15", [400.0 + i for i in range(46)])
    monkeypatch.setattr(daily_book, "index_series", lambda closes, ccy: (spy, "EUR"))
    lines = daily_book.chart(hist, {}, "EUR", label="Your portfolio")
    book, index = lines
    assert book["symbol"] == daily_book.BOOK and book["label"] == "Your portfolio"
    assert book["values"][0] == 100.0
    start = hist["A"].loc["2026-08-30"]
    assert book["values"][-1] == round(hist["A"].iloc[-1] / start * 100, 4)
    assert book["index"] is True and index["index"] is True
    assert index["symbol"] == "SPY" and index["values"][0] == 100.0
    assert index["dates"][0] == book["dates"][0]


def test_no_history_draws_nothing():
    assert daily_book.chart(None, {}, "EUR") == []
    one = pd.DataFrame({"A": [1.0]}, index=pd.date_range("2026-09-29", periods=1))
    assert daily_book.chart(one, {}, "EUR") == []


def test_build_facts_drops_the_month_against_the_index_once_the_section_says_it():
    tbl = pd.DataFrame(
        {"value": [1000.0], "cost": [900.0], "pnl_pct": [0.11], "weight": [1.0],
         "day_pct": [0.01]},
        index=["NVDA"],
    )
    bench = signals.Signal(signals.VS_BENCH, "", 44, {"gap_pp": -3.4})
    without = daily.build_facts(tbl, signals=[bench], today=TODAY)
    assert [a["kind"] for a in without["actions"]] == [signals.VS_BENCH]
    month = dict(INDEX, month_pct=2.0)
    brief = daily_routines.seeded([learnings.Learning("r1", "how is NVDA",
                                                      kind="routine")])
    facts = daily.build_facts(tbl, signals=[bench], today=TODAY, index=month,
                              brief=brief)
    assert not facts.get("actions")
    assert facts["index"] == month
    assert facts["brief"] == {"asks": [{"n": 1, "ask": "how is NVDA"}],
                              "sig": brief["sig"], "pending": True}


# ------------------------------------------------------------------ alerts


def test_an_alert_is_filed_under_alerts_and_the_rest_under_watch():
    assert daily.section_of(ALERT) == daily.ALERTS
    assert daily.section_of(EARNINGS) == daily.WATCH
    assert daily.section_of({"kind": "", "key": "line:0"}) == daily.WATCH


def test_a_fired_alert_the_model_left_out_is_on_the_card_first():
    raw = json.dumps({
        "headline": "NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert [i["key"] for i in card.items] == ["alert_hit:AAPL", "earnings:NVDA"]
    assert "AAPL" in card.items[0]["line"]


def test_an_alert_the_model_wrote_is_not_said_twice():
    raw = json.dumps({
        "headline": "AAPL crossed your 260 alert",
        "items": [
            {"key": "earnings:NVDA", "line": "NVDA reports in 3 days"},
            {"key": "alert_hit:AAPL", "line": "AAPL crossed 260, now 265"},
        ],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert [i["key"] for i in card.items] == ["earnings:NVDA", "alert_hit:AAPL"]


def test_the_model_card_carries_the_computed_portfolio_section():
    raw = json.dumps({
        "headline": "Portfolio +0.8% vs S&P 500 +0.3%; NVDA reports Friday",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts())
    assert card.book == daily_book.section(book_facts())


def test_a_headline_misquoting_the_index_is_rejected():
    raw = json.dumps({
        "headline": "Portfolio +0.8% vs S&P 500 +0.9%",
        "items": [{"key": "earnings:NVDA", "line": "NVDA reports in 3 days"}],
    })
    assert daily.parse(raw, day=TODAY, lang="en", facts=book_facts()) is None


# ------------------------------------------------------------------- brief


def _reply(sections, headline="NVDA up 1.25%; insiders selling") -> str:
    return json.dumps({"headline": headline, "sections": sections})


def test_a_brief_is_answered_a_section_per_line_below_the_alerts():
    raw = _reply([
        {"asks": [1], "title": "NVDA",
         "lines": [{"line": "NVDA at 182.50, up 1.25% today."}]},
        {"asks": [3], "title": "Insiders",
         "lines": [{"key": "earnings:NVDA",
                    "line": "Two NVDA insider sales in 30 days."}]},
    ])
    card = daily.parse(raw, day=TODAY, lang="en", known={"NVDA", "AAPL"},
                       facts=book_facts(brief=BRIEF))
    assert card.brief == daily.BRIEF_WRITTEN and card.brief_sig == "abc123"
    # The alert that fired is on top, whatever the brief asked.
    assert [i["key"] for i in card.items] == ["alert_hit:AAPL"]
    assert [s["title"] for s in card.sections] == ["NVDA", "Insiders"]
    first, second = card.sections
    assert first["asks"] == [1] and first["chart"] is None
    assert first["lines"][0]["tickers"] == ["NVDA"]
    assert first["lines"][0]["key"].startswith("brief:")
    # An exact key ties the line to its trigger, for its "see more".
    assert second["lines"][0]["key"] == "earnings:NVDA"
    assert [e["line"] for e in card.entries][1:] == [
        "NVDA at 182.50, up 1.25% today.", "Two NVDA insider sales in 30 days."]
    assert card.focus == []


def test_a_line_misquoting_the_data_goes_and_its_empty_section_with_it():
    raw = _reply([
        {"asks": [1], "lines": [
            {"line": "NVDA at 182.50."},
            # 183.90 is in no fact: this line goes, the one above stays.
            {"line": "NVDA could reach 183.90 by Friday."},
        ]},
        # 640 is in no fact either, and it was the section's only line.
        {"asks": [2], "lines": [{"line": "Not yet: ASML trades at 640."}]},
    ])
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(brief=BRIEF))
    assert [len(s["lines"]) for s in card.sections] == [1]
    # No title written: the ask stands in for it.
    assert card.sections[0]["title"] == "how is NVDA doing"


def test_the_brief_s_own_figures_count_as_sourced():
    raw = _reply([{"asks": [2], "title": "ASML",
                   "lines": [{"line": "No ASML price today to set against 700."}]}],
                 headline="No ASML price today")
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(brief=BRIEF))
    line = card.sections[0]["lines"][0]["line"]
    assert line == "No ASML price today to set against 700."


def test_a_brief_reply_with_no_section_standing_is_a_miss():
    facts = book_facts(brief=BRIEF)
    assert daily.parse(_reply([]), day=TODAY, lang="en", facts=facts) is None
    raw = _reply([{"asks": [1], "lines": [{"line": "NVDA at 182.50."}]}],
                 headline="Portfolio +0.8% vs S&P 500 +0.9%")
    assert daily.parse(raw, day=TODAY, lang="en", facts=facts) is None


def test_a_bare_price_is_audited_but_counts_names_and_years_are_not():
    facts = book_facts(brief=BRIEF)
    assert daily._bare("NVDA at 182.50", facts) is None
    assert daily._bare("NVDA at 183.90", facts) == "183.90"
    assert daily._bare("NVDA at 640", facts) == "640"
    sourced = {**facts, "named": daily.figures(daily_book.INDEX_NAME)}
    assert daily._bare(
        "Up 3 months running, ahead of the S&P 500 in 2026; 7203.T and Q3 aside",
        sourced,
    ) is None


def test_a_figure_scaled_by_a_word_is_read_at_its_scale():
    facts = {"insiders": [{"ticker": "GOOG", "sell_value": 28257.35},
                          {"ticker": "NVDA", "sell_value": 550219127.85}]}
    assert daily._bare("GOOG insiders sold 28,3 k USD", facts) is None
    assert daily._bare("NVDA insiders sold 550 M USD", facts) is None
    assert daily._bare("NVDA insiders sold 560 M USD", facts) == "560"
    # A scale only ever accepts: 3M the company is not three million.
    assert daily._bare("3M and 28,3k", facts) is None


def test_a_brief_no_model_wrote_stands_in_with_the_default_card():
    pending = daily.computed(book_facts(brief={**BRIEF, "pending": True}), "en", TODAY)
    assert pending.brief == daily.BRIEF_PENDING and pending.sections == []
    missed = daily.computed(book_facts(brief=BRIEF), "en", TODAY)
    assert missed.brief == daily.BRIEF_MISSED and missed.brief_sig == "abc123"
    # The default card under it, alerts and all.
    assert [i["key"] for i in missed.items] == ["alert_hit:AAPL", "earnings:NVDA"]
    assert daily.computed(book_facts(), "en", TODAY).brief == ""


def test_the_prompt_is_the_brief_s_when_there_is_one():
    system, _ = daily.prompt(book_facts(brief=BRIEF), {}, "en")
    assert "BRIEF" in system and "Proposal:" in system
    default, _ = daily.prompt(book_facts(), {}, "en")
    assert "BRIEF" not in default


def test_the_brief_is_filed_in_the_thread_under_its_titles():
    raw = _reply([{"asks": [1], "title": "NVDA",
                   "lines": [{"line": "NVDA at 182.50, up 1.25% today."}]}])
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(brief=BRIEF))
    text = daily.thread_text(card)
    assert "**NVDA**\n- NVDA at 182.50, up 1.25% today." in text
    assert text.index("AAPL") < text.index("**NVDA**")


def test_the_brief_s_names_are_looked_up_in_past_conversations():
    names = daily.talked_names(book_facts(brief=BRIEF))
    assert "NVDA" in names and "AAPL" in names


def test_a_stored_brief_card_reads_back_as_written():
    raw = _reply([{"asks": [1], "title": "NVDA",
                   "lines": [{"line": "NVDA at 182.50."}]}])
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(brief=BRIEF))
    again = daily.DailyAction.from_dict(card.to_dict())
    assert again.sections == card.sections
    assert again.brief == daily.BRIEF_WRITTEN and again.brief_sig == "abc123"


def _routine(rid: str, text: str, tickers=()) -> learnings.Learning:
    return learnings.Learning(rid, text, kind="routine", tickers=tuple(tickers))


def test_the_brief_is_its_lines_numbered_and_its_wording_signed():
    brief = [_routine("r1", "- how is nvda\n\n2) my insiders"),
             _routine("r2", "• events")]
    assert daily_routines.asks(brief) == [
        {"n": 1, "ask": "how is nvda"}, {"n": 2, "ask": "my insiders"},
        {"n": 3, "ask": "events"},
    ]
    sig = daily_routines.signature(brief)
    assert len(sig) == 12 and sig == daily_routines.signature(list(brief))
    assert sig != daily_routines.signature(brief[:1])
    assert daily_routines.signature([]) == ""
    assert daily_routines.seeded([]) == {}


def test_a_list_typed_on_one_line_is_asked_item_by_item():
    inline = _routine("r1", "Resume mi cartera - Eventos de la semana (máx. 7 días) "
                            "- Insiders - Revisa kill criteria.")
    assert [a["ask"] for a in daily_routines.asks([inline])] == [
        "Resume mi cartera", "Eventos de la semana (máx. 7 días)", "Insiders",
        "Revisa kill criteria.",
    ]
    # One dash is prose, not a list.
    prose = _routine("r2", "S&P 500 - Nasdaq, cómo cerraron")
    assert [a["ask"] for a in daily_routines.asks([prose])] == [
        "S&P 500 - Nasdaq, cómo cerraron"]


def test_a_lone_capital_is_a_placeholder_unless_followed():
    known = {"US STEEL": "X"}
    assert daily_routines.symbols(["X", "Y", "NVDA"], {}) == ["NVDA"]
    assert daily_routines.symbols(["X", "Y", "NVDA"], known) == ["X", "NVDA"]


def _quiet(monkeypatch):
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None: [])
    monkeypatch.setattr(
        market, "quotes",
        lambda names, **_: [market.Quote(n, price=100.0, currency="USD", prev_close=80.0)
                            for n in names],
    )


def test_gather_fetches_the_quotes_the_brief_names(monkeypatch):
    _quiet(monkeypatch)
    facts, drawn = daily_routines.gather(
        [_routine("r1", "how is nvda", ["NVDA"])],
        watchlist=None, db=None, base="EUR", lookup=lambda name: "",
    )
    assert drawn == {}
    assert facts == {
        "asks": [{"n": 1, "ask": "how is nvda"}],
        "sig": daily_routines.signature([_routine("r1", "how is nvda")]),
        "quotes": [{"ticker": "NVDA", "price": 100.0, "currency": "USD",
                    "change_pct": 25.0}],
    }


def test_gather_reads_each_source_the_brief_asks_for(monkeypatch):
    from stocks.data.insiders import InsiderTx

    _quiet(monkeypatch)
    sale = InsiderTx(date=TODAY - timedelta(days=3), insider="Jane Doe",
                     relationship="CFO", code="S", acquired=False, shares=1000.0,
                     price=180.0, ticker="NVDA", currency="USD", source="sec")
    seen = []

    def insiders(ticker):
        seen.append(ticker)
        return [sale] if ticker == "NVDA" else []

    alert = type("A", (), {"type": "below", "price": 150.0, "pct": None,
                           "level": None, "window": None})()
    holding = type("H", (), {"ticker": "NVDA", "alerts": [alert]})()
    note = learnings.Learning("n1", "sell NVDA below 150", kind="decision",
                              tickers=("NVDA",))
    sources = daily_routines.Sources(
        calendar=lambda names: ([], []),
        insiders=insiders,
        ex_dividends=lambda names: [],
        held=("NVDA", "ASML.AS", "BTC-EUR"),
        followed=("NVDA",),
        entries=(holding,),
        notes=(note,),
    )
    facts, _ = daily_routines.gather(
        [_routine("r1", "eventos de esta semana\ninsiders\nmis criterios de salida")],
        watchlist=None, db=None, base="EUR", lookup=lambda name: "", day=TODAY,
        sources=sources,
    )
    # Form 4 speaks for US listings only.
    assert seen == ["NVDA"]
    nvda = facts["insiders"][0]
    assert (nvda["sells"], nvda["latest"][0]["insider"]) == (1, "Jane Doe")
    assert facts["events"]["days"] == daily_routines.AHEAD_DAYS
    assert facts["events"]["earnings"] == [] and facts["events"]["ex_dividends"] == []
    exits = facts["exits"]
    assert exits["alerts"][0] == {"ticker": "NVDA", "type": "below", "price": 150.0,
                                       "now": 100.0, "distance_pct": 50.0}
    assert exits["notes"] == [{"kind": "decision", "text": "sell NVDA below 150",
                               "tickers": ["NVDA"]}]
    assert "missing" not in facts


def test_a_source_that_fails_or_runs_late_is_named_missing(monkeypatch):
    _quiet(monkeypatch)

    def insiders(ticker):
        if ticker == "SLOW":
            time.sleep(0.5)
        if ticker == "BAD":
            raise RuntimeError("throttled")
        return []

    facts, _ = daily_routines.gather(
        [_routine("r1", "insiders")], watchlist=None, db=None, base="EUR",
        lookup=lambda n: "", budget_s=0.1, day=TODAY,
        sources=daily_routines.Sources(insiders=insiders, held=("OK", "BAD", "SLOW")),
    )
    assert [r["ticker"] for r in facts["insiders"]] == ["OK"]
    assert facts["missing"] == ["insiders"]
    # A source the caller does not have is missing too, not silent.
    facts, _ = daily_routines.gather(
        [_routine("r1", "insiders")], watchlist=None, db=None, base="EUR",
        lookup=lambda n: "", day=TODAY,
    )
    assert facts["missing"] == ["insiders"]


def test_gather_reads_the_press_the_sec_and_the_big_investors(monkeypatch):
    from stocks.data import edgar, holders, news
    from stocks.data.insiders import InsiderTx

    _quiet(monkeypatch)
    asked: dict[str, list[str]] = {"news": [], "filings": [], "holders": [], "eu": []}

    def headlines(ticker):
        asked["news"].append(ticker)
        return [news.Headline("Nvidia unveils a chip", "Wire", TODAY, "u")] \
            if ticker == "NVDA" else []

    def filings(ticker):
        asked["filings"].append(ticker)
        return [edgar.CurrentReport("8-K", TODAY - timedelta(days=2), ("5.02",), "u"),
                edgar.CurrentReport("8-K", TODAY - timedelta(days=20), ("1.01",), "u")]

    def institutions(ticker):
        asked["holders"].append(ticker)
        return holders.Institutions(
            as_of=date(2026, 6, 30), institutions_pct=71.4, insiders_pct=None,
            holders=[holders.Holder("Blackrock", 8.06, 0.85),
                     holders.Holder("FMR", 4.26, 3.24),
                     holders.Holder("Big Seller", 1.2, -12.5)])

    def eu_insiders(ticker):
        asked["eu"].append(ticker)
        return [InsiderTx(date=TODAY - timedelta(days=1), insider="Hans",
                          relationship="CEO", code="P", acquired=True,
                          shares=100.0, price=50.0, ticker=ticker,
                          currency="EUR", source="BaFin")]

    sources = daily_routines.Sources(
        insiders=lambda t: [], eu_insiders=eu_insiders, news=headlines,
        filings=filings, holders=institutions,
        held=("NVDA", "SAP.DE", "SAN.MC", "BTC-EUR", "^GSPC"),
    )
    facts, _ = daily_routines.gather(
        [_routine("r1", "noticias, 8-K y grandes inversores de AMD\ninsiders", ["AMD"])],
        watchlist=None, db=None, base="EUR", lookup=lambda name: "", day=TODAY,
        sources=sources,
    )
    # The brief's own names first, then the book; no coins or indices.
    assert asked["news"] == ["AMD", "NVDA", "SAP.DE", "SAN.MC"]
    # The SEC speaks for US listings, BaFin for German ones.
    assert sorted(asked["filings"]) == ["AMD", "NVDA"] == sorted(asked["holders"])
    assert asked["eu"] == ["SAP.DE"]
    assert facts["news"][1] == {"ticker": "NVDA", "headlines": [
        {"date": TODAY.isoformat(), "publisher": "Wire",
         "title": "Nvidia unveils a chip"}]}
    # The week's 8-Ks only.
    assert facts["filings"][0]["filings"] == [
        {"date": (TODAY - timedelta(days=2)).isoformat(), "form": "8-K",
         "items": ["director or officer change"]}]
    nvda = facts["holders"][1]
    assert (nvda["as_of"], nvda["institutions_pct"]) == ("2026-06-30", 71.4)
    assert [h["holder"] for h in nvda["adding"]] == ["FMR"]
    assert [h["holder"] for h in nvda["cutting"]] == ["Big Seller"]
    german = next(r for r in facts["insiders"] if r.get("source") == "BaFin")
    assert (german["ticker"], german["buys"], german["currency"]) == ("SAP.DE", 1, "EUR")
    assert "missing" not in facts


def test_a_company_source_the_caller_lacks_is_missing(monkeypatch):
    _quiet(monkeypatch)
    facts, _ = daily_routines.gather(
        [_routine("r1", "las noticias y los grandes inversores")], watchlist=None,
        db=None, base="EUR", lookup=lambda n: "", day=TODAY,
        sources=daily_routines.Sources(held=("NVDA",)),
    )
    assert facts["missing"] == ["holders", "news"]


def test_headlines_are_sourced_for_the_audit():
    facts = {"brief": {"asks": [], "news": [{"ticker": "NVDA", "headlines": [
        {"title": "The $2.4 trillion chipmaker", "date": "2026-10-04"}]}]}}
    assert 2.4 in daily._sourced(facts)["asked"]


def test_gather_draws_the_chart_a_line_asks_for(monkeypatch):
    line = charts.Line(
        symbol="NVDA", currency="USD", dates=("2026-09-01", "2026-09-29"),
        values=(100.0, 110.0), first=100.0, first_on="2026-09-01", last=110.0,
        last_on="2026-09-29", high=112.0, high_on="2026-09-20", low=98.0,
        low_on="2026-09-03", sessions=20, along=(),
    )
    monkeypatch.setattr(charts, "wants", lambda text: text.startswith("chart"))
    monkeypatch.setattr(charts, "targets", lambda text, known, base, lookup: ["NVDA"])
    monkeypatch.setattr(charts, "build", lambda symbols, window, base, book=None:
                        charts.Chart(window, (line,)))
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None: [])
    monkeypatch.setattr(market, "quotes", lambda names, **_: [])
    facts, drawn = daily_routines.gather(
        [_routine("r1", "how is the book\nchart NVDA")], watchlist=None, db=None,
        base="EUR", lookup=lambda name: "",
    )
    chart = facts["charts"][0]
    assert chart["n"] == 2 and chart["window"] == daily_routines.WINDOW
    assert chart["lines"][0]["ticker"] == "NVDA"
    assert chart["lines"][0]["change_pct"] == 10.0
    assert list(drawn) == [2]
    assert drawn[2]["series"][0]["values"] == [100.0, 110.0]


def test_routines_are_read_only_with_memory_on(tmp_path):
    chat = tmp_path / "chat.json"
    path = learnings.path_for(chat)
    learnings.add(path, "how is NVDA doing every morning", kind="routine")
    learnings.add(path, "I invest for ten years", kind="context")
    found = daily_routines.load({}, chat)
    assert [r.kind for r in found] == ["routine"]
    assert daily_routines.load({"chat_memory": False}, chat) == []
    assert daily_routines.load({}, None) == []


# ------------------------------------------------------- the free allowance


def test_the_card_spends_at_most_its_share_of_the_allowance():
    prefs: dict = {}
    spent = []

    def spend(p):
        spent.append(1)
        return True

    results = [daily.spend_unit(prefs, TODAY, spend) for _ in range(3)]
    assert results == [True, True, False]
    assert len(spent) == daily.FREE_UNITS == 2
    assert prefs[daily.UNITS_KEY] == {"day": TODAY.isoformat(), "used": 2}
    # A new day, a new share, in the same key.
    assert daily.spend_unit(prefs, TODAY + timedelta(days=1), spend) is True
    assert prefs[daily.UNITS_KEY] == {
        "day": (TODAY + timedelta(days=1)).isoformat(), "used": 1,
    }


def test_a_refused_unit_is_not_counted():
    prefs: dict = {}
    assert daily.spend_unit(prefs, TODAY, lambda p: False) is False
    assert daily.UNITS_KEY not in prefs


def test_generate_routes_every_unit_through_the_card_s_share(monkeypatch):
    prefs = {daily.UNITS_KEY: {"day": TODAY.isoformat(), "used": daily.FREE_UNITS}}
    asked = []

    def complete(prefs, system, messages, timeout_s, *, spend_free, accept):
        asked.append(spend_free(prefs))
        return None

    monkeypatch.setattr(daily.engine, "complete_attempts", complete)
    monkeypatch.setattr(daily.engine, "user_memory", lambda *a, **k: ([], []))
    daily.generate(prefs, {}, book_facts(), "en", TODAY, spend_free=lambda p: True)
    assert asked == [False]


# ----------------------------------------------------------- the computed card


def test_the_computed_card_opens_on_the_book_against_the_index():
    card = daily.computed(book_facts(), "en", TODAY)
    assert card.headline.startswith("Portfolio +0.80% vs the S&P 500 +0.30%")
    assert card.book["rows"][0]["pct"] == 0.8
    assert [i["key"] for i in card.items] == ["alert_hit:AAPL", "earnings:NVDA"]


def test_a_quiet_day_leaves_the_move_to_the_portfolio_section():
    card = daily.computed(book_facts(actions=[]), "en", TODAY)
    assert card.book
    assert not any("+0.80%" in b for b in card.bullets)


def test_without_the_index_the_computed_card_is_as_it_was():
    card = daily.computed(book_facts(index=None, actions=[]), "en", TODAY)
    assert card.book == {}
    assert any("+0.80%" in b for b in card.bullets)


# ------------------------------------------------------------- the charts


def test_charts_are_attached_after_the_card_is_built():
    raw = _reply([{"asks": [1, 2], "title": "NVDA",
                   "lines": [{"line": "NVDA at 182.50."}]}])
    card = daily.parse(raw, day=TODAY, lang="en", facts=book_facts(brief=BRIEF))
    month = [{"symbol": "@BOOK", "dates": ["2026-09-01"], "values": [100.0]}]
    drawn = {2: {"window": "1m", "rebased": False, "series": []}}
    dressed = daily.dressed(card, month, drawn)
    assert dressed.book["chart"] == month
    assert dressed.sections[0]["chart"] == drawn[2]
    assert "chart" not in card.book  # the card itself is left as built
    stored = daily.DailyAction.from_dict(dressed.to_dict())
    assert stored.book["chart"] == month
    assert stored.sections[0]["chart"] == drawn[2]


def test_a_card_without_a_book_takes_no_chart():
    card = daily.computed(book_facts(index=None), "en", TODAY)
    assert daily.dressed(card, [{"symbol": "@BOOK"}]).book == {}
    assert daily.dressed(None, []) is None
