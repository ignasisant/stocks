"""CNMV Art. 19 MAR tests — recorded fixtures, no network.

`tests/fixtures/cnmv/` holds what the live site served (probed 2026-10-23): a
trimmed list page and the pdfminer text of three Banco Santander forms (one
table split over four venues, an amendment, and a multi-row table that
pdfminer emits column by column).
"""

import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from stocks.data import cnmv
from stocks.data.insiders import BUY_CODE, SELL_CODE, summarize

FIXTURES = Path(__file__).parent / "fixtures" / "cnmv"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_spanish_listing():
    assert cnmv.spanish_listing("SAN.MC")
    assert cnmv.spanish_listing("itx.mc")
    assert not cnmv.spanish_listing("SAP.DE")
    assert not cnmv.spanish_listing("AAPL")


def test_numbers_and_names():
    assert cnmv._number("72101,00") == 72101.0
    assert cnmv._number("12,75") == 12.75
    assert cnmv._number("1.234,50") == 1234.5
    assert cnmv._number("1.234.567") == 1234567.0
    assert cnmv._number("12.75") == 12.75
    assert cnmv._number("") is None
    assert cnmv._number("n/a") is None
    assert cnmv._name_key("Banco Santander, S.A.") == "Banco Santander"
    assert cnmv._name_key("Industria de Diseño Textil, S.A.") == (
        "Industria de Diseño Textil"
    )


def test_parse_list():
    items = cnmv.parse_list(fixture("list_page.html"))
    assert [i["date"] for i in items] == [
        date(2026, 9, 18),
        date(2026, 9, 8),
        date(2026, 8, 17),
    ]
    assert items[0]["reg"] == "2026124532"
    # The token stays URL-encoded: it goes back into a query string as served.
    assert items[0]["token"].startswith("cFjGpMZcfkxb%2b")
    assert cnmv.parse_list("<html>nothing</html>") == []


def test_form_with_one_table_per_venue_is_merged():
    txs, amends = cnmv.parse_form(fixture("form_rows.txt"), "san.mc")
    assert amends == ""
    (tx,) = txs
    assert tx.code == SELL_CODE and not tx.acquired
    assert tx.date == date(2026, 9, 16)
    assert tx.shares == 72101 + 272315 + 34359 + 221225
    # Volume-weighted over the four venues.
    assert tx.price == pytest.approx(12.7619, abs=1e-3)
    assert (tx.ticker, tx.currency, tx.source) == ("SAN.MC", "EUR", "CNMV")
    assert tx.insider == "JOSE MARIA LINARES PEROU"
    assert tx.relationship == "Group Senior Executive Vice-President"


def test_amendment_names_the_notification_it_replaces():
    txs, amends = cnmv.parse_form(fixture("form_amendment.txt"))
    assert amends == "2026113065"
    (tx,) = txs
    assert tx.code == BUY_CODE and tx.acquired
    assert tx.shares == 6494 and tx.price == pytest.approx(12.66)
    assert tx.relationship == "Director"


def test_column_layout_and_non_trades():
    txs, _ = cnmv.parse_form(fixture("form_columns.txt"))
    (tx,) = txs
    # Three "Otros" rows of one day: shown, never counted as a buy or sell.
    assert tx.code == "O" and not tx.acquired
    assert tx.shares == 2842 + 9673 + 14745
    assert tx.price is None
    assert not summarize(txs, ref=date(2026, 3, 20), within_days=30).has_activity


def test_closely_associated_and_garbage():
    # The form's checkboxes are drawn with no-break spaces; flip the two ticks.
    lines = fixture("form_rows.txt").splitlines()
    text = "\n".join(
        "[ √ ] Persona estrechamente vinculada"
        if "Persona estrechamente" in ln
        else "[   ] Persona con responsabilidad de dirección"
        if "Persona con responsabilidad" in ln
        else ln
        for ln in lines
    )
    txs, _ = cnmv.parse_form(text)
    assert txs[0].relationship == "Closely associated"
    assert cnmv.parse_form("") == ([], "")
    assert cnmv.parse_form("not a form at all\n12/12/2026\n") == ([], "")


# --- end to end, with the network faked -----------------------------------------


@pytest.fixture
def register(tmp_path, monkeypatch):
    """A faked register: three list items, each PDF served from a fixture."""
    monkeypatch.setattr(cnmv, "MEMO_FILE", tmp_path / "cnmv.json")
    cnmv.clear_cache()
    monkeypatch.setattr("stocks.storage.restore", lambda *a, **k: None)
    monkeypatch.setattr("stocks.storage.persist", lambda *a, **k: None)

    today = date.today()
    items = [
        {"date": today - timedelta(days=10), "token": "t-sell", "reg": "2026124532"},
        {"date": today - timedelta(days=20), "token": "t-amend", "reg": "2026120682"},
        {"date": today - timedelta(days=30), "token": "t-orig", "reg": "2026113065"},
        {"date": today - timedelta(days=400), "token": "t-old", "reg": "2025000001"},
    ]
    forms = {
        "t-sell": fixture("form_rows.txt"),
        "t-amend": fixture("form_amendment.txt"),
        # The original the amendment corrects: same form, wrong share count.
        "t-orig": fixture("form_amendment.txt")
        .replace("6494,00", "6949,00")
        .replace("Modification", "Initial")
        .replace("Modificación", "Inicial"),
        "t-old": fixture("form_rows.txt"),
    }
    calls = {"pdf": 0, "pages": 0, "resolve": 0}

    def fake_get(url, timeout=20):
        calls["pdf"] += 1
        token = url.rsplit("e=", 1)[1]
        return token.encode()

    def fake_page(nif, page):
        calls["pages"] += 1
        return items if page == 0 else []

    monkeypatch.setattr(cnmv, "_get", fake_get)
    monkeypatch.setattr(cnmv, "pdf_text", lambda data: forms[data.decode()])
    monkeypatch.setattr(cnmv, "_list_page", fake_page)

    def fake_resolve(name):
        calls["resolve"] += 1
        return "A39000013" if "santander" in name.lower() else None

    monkeypatch.setattr(cnmv, "_resolve_nif", fake_resolve)
    return calls


def test_insider_transactions_end_to_end(register):
    txs = cnmv.insider_transactions("SAN.MC", issuer="Banco Santander, S.A.")
    # Newest first; the old item is outside the twelve months and never fetched;
    # the amended original is replaced by its correction.
    assert [(t.date, t.shares) for t in txs] == [
        (date(2026, 9, 16), 600000.0),
        (date(2026, 8, 10), 6494.0),
    ]
    assert {t.ticker for t in txs} == {"SAN.MC"}
    assert register["pdf"] == 3


def test_second_call_reads_the_memo_not_the_site(register):
    first = cnmv.insider_transactions("SAN.MC", issuer="Banco Santander")
    assert register["pdf"] == 3
    cnmv.clear_cache()  # a new process: only the on-disk memo survives
    again = cnmv.insider_transactions("SAN.MC", issuer="Banco Santander")
    assert register["pdf"] == 3
    assert again == first


def test_pdf_fetches_per_call_are_capped(register, monkeypatch):
    monkeypatch.setattr(cnmv, "MAX_PDFS", 2)
    txs = cnmv.insider_transactions("SAN.MC", issuer="Banco Santander")
    assert register["pdf"] == 2
    assert len(txs) == 2  # the third item waits for the next call
    cnmv.insider_transactions("SAN.MC", issuer="Banco Santander")
    assert register["pdf"] == 3


def test_failures_and_unknown_issuers_are_empty(register, monkeypatch):
    assert cnmv.insider_transactions("XYZ.MC", issuer="Nobody SA") == []
    assert cnmv.insider_transactions("SAN.MC") == []

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(cnmv, "_list_page", boom)
    assert cnmv.insider_transactions("SAN.MC", issuer="Banco Santander") == []


def test_one_bad_pdf_does_not_cost_the_rest(register, monkeypatch):
    real = cnmv.pdf_text

    def flaky(data):
        if data == b"t-sell":
            raise ValueError("corrupt pdf")
        return real(data)

    monkeypatch.setattr(cnmv, "pdf_text", flaky)
    txs = cnmv.insider_transactions("SAN.MC", issuer="Banco Santander")
    assert [t.shares for t in txs] == [6494.0]


@pytest.fixture
def slow_site(register, monkeypatch):
    """Two of the PDFs hang until released; the wait is cut to its floor."""
    gate = threading.Event()
    fast = cnmv._get

    def gated(url, timeout=20):
        if url.rsplit("e=", 1)[1] in {"t-amend", "t-orig"}:
            gate.wait(10)
        return fast(url, timeout)

    monkeypatch.setattr(cnmv, "_get", gated)
    monkeypatch.setattr(cnmv, "BUDGET_S", 0.5)  # the PDF wait floors at 1 s
    return gate


def _workers_done(timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if {"t-sell", "t-amend", "t-orig"} <= set(cnmv._memory()["pdf"]):
            return
        time.sleep(0.02)
    raise AssertionError("workers did not finish")


def test_a_partial_read_says_so_and_the_next_one_is_fuller(slow_site):
    rows, complete = cnmv.read("SAN.MC", issuer="Banco Santander")
    assert not complete
    assert [t.shares for t in rows] == [600000.0]

    slow_site.set()
    _workers_done()
    rows, complete = cnmv.read("SAN.MC", issuer="Banco Santander")
    assert complete
    assert [t.shares for t in rows] == [600000.0, 6494.0]


def test_the_loader_does_not_freeze_a_partial_read(slow_site, monkeypatch):
    from stocks.api import loaders

    monkeypatch.setattr(loaders, "issuer_name", lambda t: "Banco Santander")
    loaders._clear_eu_insiders()
    try:
        first = loaders.eu_insiders("SAN.MC")
        assert [t.shares for t in first] == [600000.0]
        # Kept for the short TTL only, not the hour a complete list gets.
        expires = loaders._cnmv_cache["SAN.MC"][0]
        assert expires - time.monotonic() <= loaders._CNMV_PARTIAL_TTL

        slow_site.set()
        _workers_done()
        monkeypatch.setattr(loaders, "_CNMV_PARTIAL_TTL", 0.0)
        loaders._cnmv_cache["SAN.MC"] = (0.0, first)  # the 60 s have passed
        assert [t.shares for t in loaders.eu_insiders("SAN.MC")] == [600000.0, 6494.0]

        # Now complete: kept for the long TTL.
        expires = loaders._cnmv_cache["SAN.MC"][0]
        assert expires - time.monotonic() > loaders._CNMV_PARTIAL_TTL
    finally:
        loaders._clear_eu_insiders()
