"""SEC 13F index: synthetic data-set zips with the real header rows."""

from __future__ import annotations

import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from stocks.chat import daily_routines
from stocks.data import holders, thirteenf

SUB = "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT"
COVER = "ACCESSION_NUMBER\tAMENDMENTTYPE\tFILINGMANAGER_NAME\tADDITIONALINFORMATION"
INFO = "ACCESSION_NUMBER\tCUSIP\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL"
X, Y = "AAA111111", "BBB222222"


def make_zip(path: Path, period: str, filings: list[tuple],
             positions: list[tuple]) -> Path:
    """filings: (accession, type, cik, name, amendment, note); positions:
    (accession, cusip, shares, put_call)."""
    sub = [SUB] + [f"{a}\t01-MAY-2026\t{t}\t{c}\t{period}"
                   for a, t, c, *_ in filings]
    cover = [COVER] + [f"{a}\t{am}\t{n}\t{note}" for a, _, _, n, am, note in filings]
    info = [INFO] + [f"{a}\t{c}\t{s * 10}\t{s}\tSH\t{p}" for a, c, s, p in positions]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUBMISSION.tsv", "\n".join(sub) + "\n")
        zf.writestr("COVERPAGE.tsv", "\n".join(cover) + "\n")
        zf.writestr("INFOTABLE.tsv", "\n".join(info) + "\n")
    return path


@pytest.fixture
def zips(tmp_path, monkeypatch):
    monkeypatch.setattr(thirteenf, "MIN_HOLDERS", 2)
    cur = make_zip(
        tmp_path / "cur.zip", "31-MAR-2026",
        [("a1", "13F-HR", 1, "ALPHA FUND", "", ""),
         ("b0", "13F-HR", 2, "Beta Capital", "", ""),
         ("b1", "13F-HR/A", 2, "Beta Capital", "RESTATEMENT", ""),
         ("a2", "13F-HR/A", 1, "ALPHA FUND", "NEW HOLDINGS", ""),
         ("c1", "13F-HR", 3, "Charlie Bank", "", "Some positions are confidential"),
         ("d1", "13F-HR", 4, "Delta Trust", "", ""),
         ("f1", "13F-HR", 6, "Foxtrot LLC", "", "")],
        [("a1", X, 100, ""), ("a1", X, 0, "Put"), ("a1", Y, 7, ""),
         ("b0", X, 999, ""), ("b1", X, 50, ""),
         ("a2", X, 1, ""),
         ("d1", Y, 10, ""),
         ("f1", X, 5, ""), ("f1", Y, 3, "")])
    prev = make_zip(
        tmp_path / "prev.zip", "31-DEC-2025",
        [("pa", "13F-HR", 1, "Alpha Fund", "", ""),
         ("pb", "13F-HR", 2, "Beta Capital", "", ""),
         ("pc", "13F-HR", 3, "Charlie Bank", "", ""),
         ("pd", "13F-HR", 4, "Delta Trust", "", ""),
         ("pe", "13F-HR", 5, "Echo Partners", "", "")],
        [("pa", X, 80, ""), ("pb", X, 40, ""), ("pc", X, 10, ""),
         ("pd", X, 30, ""), ("pe", X, 20, "")])
    return cur, prev


def fetcher(cur: Path, prev: Path):
    def fetch(path: str, dest: Path) -> Path:
        shutil.copy(cur if "new" in path else prev, dest)
        return dest
    return fetch


HTML = ('<a href="/files/x/new_form13f.zip">a</a>'
        ' <a href="/files/x/old_form13f.zip">b</a>'
        '<a href="/files/x/new_form13f.zip">dup</a>')


def test_window_zips_newest_first_unique():
    assert thirteenf.window_zips(HTML) == [
        "/files/x/new_form13f.zip", "/files/x/old_form13f.zip"]


def test_build_and_holdings(zips, tmp_path):
    db = tmp_path / "idx.sqlite"
    fetch = fetcher(*zips)
    assert thirteenf.build(path=db, html=HTML, fetch_zip=fetch) == "built 2026-03-31"
    assert thirteenf.build(path=db, html=HTML, fetch_zip=fetch) == "current"

    def fake_post(url, jobs, **kw):
        assert len(jobs) == 2
        us = {"exchCode": "US", "marketSector": "Equity",
              "securityType": "Common Stock", "ticker": "BRK/B", "name": "Berk"}
        return [{"data": [us]},
                {"warning": "No identifier found."}]

    assert thirteenf.resolve(path=db, post=fake_post, sleep=lambda s: None) == (2, 0)
    found = thirteenf.holdings("brk-b", path=db)
    assert found is not None and found.as_of == date(2026, 3, 31)
    by = {p.manager: p for p in found.top}
    # Put rows ignored; the restatement replaces its original; a holdings-only
    # amendment adds nothing.
    assert [p.manager for p in found.top] == ["Alpha Fund", "Beta Capital", "Foxtrot LLC"]
    assert by["Alpha Fund"].shares == 100 and by["Alpha Fund"].status == "added"
    assert by["Beta Capital"].shares == 50 and by["Beta Capital"].change_pct == 25.0
    assert by["Foxtrot LLC"].status == "new" and by["Foxtrot LLC"].change_pct is None
    # Delta filed this quarter without X: sold out. Charlie withholds
    # positions and Echo did not file: neither is a sale.
    assert [p.manager for p in found.sold_out] == ["Delta Trust"]
    assert found.sold_out[0].status == "sold_out"
    assert thirteenf.holdings("NOPE", path=db) is None
    assert thirteenf.holdings("BRK-B", path=tmp_path / "missing.sqlite") is None


def test_ticker_of_picks_the_us_line():
    answer = {"data": [
        {"exchCode": "GR", "marketSector": "Equity",
         "securityType": "Common Stock", "ticker": "A"},
        {"exchCode": "US", "marketSector": "Equity", "securityType": "Common Stock",
         "ticker": "bf/b", "name": "Brown"}]}
    assert thirteenf._ticker_of(answer) == ("BF-B", "Brown")
    assert thirteenf._ticker_of({"warning": "none"}) is None


def test_resolve_stops_on_failure_and_resumes(zips, tmp_path):
    db = tmp_path / "idx.sqlite"
    thirteenf.build(path=db, html=HTML, fetch_zip=fetcher(*zips))

    def down(url, jobs, **kw):
        raise ConnectionError("rate limited")

    assert thirteenf.resolve(path=db, post=down, sleep=lambda s: None) == (0, 2)


def test_build_needs_two_windows(tmp_path):
    with pytest.raises(RuntimeError):
        thirteenf.build(path=tmp_path / "i.sqlite", html="<html></html>")


def found_13f():
    return thirteenf.Holdings(
        as_of=date(2026, 3, 31),
        top=[thirteenf.Position("Alpha Fund", 100, 1000.0, 80),
             thirteenf.Position("Foxtrot LLC", 5, 50.0, None)],
        sold_out=[thirteenf.Position("Delta Trust", 0, 300.0, 30)])


def test_institutions_prefers_13f(monkeypatch):
    monkeypatch.setattr(thirteenf, "holdings", lambda t: found_13f())
    got = holders.institutions("AAPL")
    assert got is not None and got.source == "13f"
    assert [h.status for h in got.holders] == ["added", "new"]
    assert [h.name for h in got.sold_out] == ["Delta Trust"]


def test_institutions_falls_back_to_yahoo(monkeypatch):
    import types

    import pandas as pd

    table = pd.DataFrame([{"Holder": "Yahoo Fund", "pctHeld": 0.05, "pctChange": 0.1,
                           "Date Reported": "2026-03-31"}])

    class T:
        institutional_holders = table
        major_holders = None

    monkeypatch.setitem(__import__("sys").modules, "yfinance",
                        types.SimpleNamespace(Ticker=lambda t: T()))
    monkeypatch.setattr(thirteenf, "holdings", lambda t: None)
    got = holders.institutions("ASML.AS")
    assert got is not None and got.source == "yahoo"
    assert got.holders[0].name == "Yahoo Fund"

    def broken(t):
        raise OSError("bad index")

    monkeypatch.setattr(thirteenf, "holdings", broken)
    assert holders.institutions("ASML.AS").source == "yahoo"


def test_holders_fact_carries_13f_detail():
    fact = daily_routines.holders_fact("AAPL", holders.from_13f(found_13f()))
    assert fact["source"] == "13F"
    assert fact["top"][0]["shares"] == 100 and fact["top"][0]["status"] == "added"
    assert [r["holder"] for r in fact["new"]] == ["Foxtrot LLC"]
    assert [r["holder"] for r in fact["sold_out"]] == ["Delta Trust"]
    assert [r["holder"] for r in fact["adding"]] == ["Alpha Fund"]
