"""The daily brief's company sources, parsed offline: press headlines
(`data.news`), 8-K current reports (`data.edgar`) and big investors
(`data.holders`).

What is tested is what the card is allowed to say from them:

* a headline counts for a company only when its title names it — a ticker's
  feed is mostly roundups tagged with every name they mention;
* an 8-K is the kinds of news its items report, and one filed only for its
  exhibits is no news;
* holders' stakes and quarterly changes are percent numbers, dated as of the
  quarter they were reported for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from stocks.data import edgar, holders, news

TODAY = date(2026, 10, 4)


def _stamp(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp())


def _story(title: str, day: date = TODAY, **over) -> dict:
    return {"title": title, "publisher": "Wire", "link": "https://x.test/a",
            "providerPublishTime": _stamp(day), "type": "STORY", **over}


def test_a_headline_counts_only_when_it_names_the_company():
    stories = [
        _story("Nvidia unveils a new chip"),
        _story("5 dividend stocks to buy now"),
        _story("NVDA slides after the open"),
        _story("Nvidia unveils a new chip"),  # syndicated twice
    ]
    found = news.parse(stories, "NVDA", "Nvidia Corp", today=TODAY, days=3, limit=5)
    assert [h.title for h in found] == ["Nvidia unveils a new chip",
                                        "NVDA slides after the open"]
    assert found[0].published == TODAY and found[0].publisher == "Wire"


def test_old_headlines_and_the_limit_keep_the_list_short():
    stories = [_story(f"Nvidia story {i}", TODAY - timedelta(days=i)) for i in range(5)]
    found = news.parse(stories, "NVDA", "Nvidia", today=TODAY, days=3, limit=2)
    assert [h.title for h in found] == ["Nvidia story 0", "Nvidia story 1"]
    old = news.parse(stories, "NVDA", "Nvidia", today=TODAY, days=3, limit=9)
    assert "Nvidia story 4" not in [h.title for h in old]


def test_a_venue_suffix_and_a_generic_name_are_not_what_matches():
    assert news.about("SAP raises its cloud outlook", "SAP.DE", "SAP SE")
    # "Banco" is every bank; "Santander" is this one.
    assert news.about("Santander beats estimates", "SAN.MC", "Banco Santander, S.A.")
    assert not news.about("Banco Sabadell rallies", "SAN.MC", "Banco Santander, S.A.")
    # A ticker in lower case is a word, not the symbol.
    assert not news.about("A san francisco startup raises", "SAN.MC", None)


def test_a_non_us_listing_is_searched_by_its_name_when_the_symbol_finds_none(
        monkeypatch):
    asked = []

    def search(query, count):
        asked.append(query)
        return [] if query == "SAN.MC" else [_story("Santander sells a stake")]

    monkeypatch.setattr(news, "_search", search)
    found = news.headlines("SAN.MC", "Banco Santander, S.A.", today=TODAY)
    assert asked == ["SAN.MC", "Banco Santander, S.A."]
    assert [h.title for h in found] == ["Santander sells a stake"]


def _subs(*rows) -> dict:
    keys = ("form", "filingDate", "items", "accessionNumber", "primaryDocument")
    return {"filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}


def test_an_8k_is_the_news_its_items_report():
    subs = _subs(
        ("8-K", "2026-10-02", "5.02,9.01", "0001-26-000001", "d1.htm"),
        ("8-K", "2026-09-30", "9.01", "0001-26-000002", "d2.htm"),
        ("10-Q", "2026-09-29", "", "0001-26-000003", "q.htm"),
        ("8-K/A", "2026-09-29", "2.02", "0001-26-000004", "d4.htm"),
        ("8-K", "2026-08-01", "1.01", "0001-26-000005", "d5.htm"),
    )
    found = edgar.parse_current_reports("1045810", subs, since=date(2026, 9, 27))
    assert [(r.form, r.filed.isoformat(), r.items) for r in found] == [
        ("8-K", "2026-10-02", ("5.02",)), ("8-K/A", "2026-09-29", ("2.02",))]
    assert found[0].topics == ["director or officer change"]
    assert found[0].url == ("https://www.sec.gov/Archives/edgar/data/1045810/"
                            "000126000001/d1.htm")


def test_holders_are_percent_numbers_dated_by_their_quarter():
    table = pd.DataFrame({
        "Date Reported": pd.to_datetime(["2026-06-30"] * 3),
        "Holder": ["Blackrock Inc.", "AQR Capital", "Vanguard"],
        "pctHeld": [0.0694, 0.0485, 0.0504],
        "Shares": [1, 2, 3], "Value": [1, 2, 3],
        "pctChange": [-0.1559, 0.4852, 0.0015],
    })
    major = pd.DataFrame({"Value": [0.0123, 1.0037]},
                         index=["insidersPercentHeld", "institutionsPercentHeld"])
    found = holders.parse(table, major)
    assert found.as_of == date(2026, 6, 30)
    assert (found.institutions_pct, found.insiders_pct) == (100.37, 1.23)
    assert [(h.name, h.pct_held, h.change_pct) for h in found.holders][0] == (
        "Blackrock Inc.", 6.94, -15.59)
    assert [h.name for h in found.adding] == ["AQR Capital"]
    assert [h.name for h in found.cutting] == ["Blackrock Inc."]


def test_no_holders_and_no_shares_is_none():
    assert holders.parse(pd.DataFrame(), pd.DataFrame()) is None
    assert holders.parse(None, None) is None
