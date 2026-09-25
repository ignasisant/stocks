"""Import diagnostics (stocks.portfolio.diagnostics).

Two things must hold. The fingerprint has to be *useful* — headers, encoding,
delimiter and a reason histogram, enough to fix a parser from. And it has to be
*empty of the reader's data*: this is collected silently, so the privacy
guarantee is not a comment in a docstring, it is the sentinel test at the
bottom of this file.
"""

from __future__ import annotations

import json

import pytest

from stocks import storage
from stocks.portfolio import diagnostics, platforms
from stocks.portfolio.statement import ParseResult

# Values distinctive enough that finding one anywhere in a fingerprint proves a
# leak. Chosen not to collide with anything a parser says by itself.
TICKER = "ZZZZ"
AMOUNT = "1234567.89"
DATE = "03-01-2023"
FILENAME = "Cuenta_98765432.csv"
SENTINELS = (TICKER, AMOUNT, DATE, "98765432")


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "DIAGNOSTICS_DIR", tmp_path / "imports")
    monkeypatch.setattr(storage, "_cached", {"config": None})  # bucket off
    return tmp_path / "imports"


# ------------------------------------------------------------------- masking


@pytest.mark.parametrize(
    "value,expected",
    [
        ("03-01-2023", "99-99-9999"),
        ("1.845,60", "9.999,99"),
        ("ASML", "AAAA"),
        ("NL0010273215", "AA9999999999"),
        ("Compra", "Aaaaaa"),
        ("", ""),
    ],
)
def test_mask_keeps_the_shape_and_drops_the_content(value, expected):
    assert diagnostics.mask(value) == expected


def test_mask_truncates_a_runaway_cell():
    assert len(diagnostics.mask("x" * 500)) == diagnostics.MAX_VALUE


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("unrecognised date '03-01-2023'", "unrecognised date '99-99-9999'"),
        ("missing ticker", "missing ticker"),
        ("row has non-positive price -2", "row has non-positive price -9"),
        (
            "buy row inconsistent: 3 × 45.20 = 135.60 but total is 135.55 (0.0% off)",
            "buy row inconsistent: 9 × 99.99 = 999.99 but total is 999.99 (9.9% off)",
        ),
        # An ISIN interpolated without quotes by some future parser.
        ("holding NL0010273215 has no cost", "holding AA9999999999 has no cost"),
    ],
)
def test_redact_masks_the_values_and_keeps_the_words(reason, expected):
    assert diagnostics.redact(reason) == expected


def test_redact_is_idempotent():
    once = diagnostics.redact("unrecognised date '03-01-2023'")
    assert diagnostics.redact(once) == once


def test_mask_digits_keeps_the_brand_and_drops_the_account_number():
    assert diagnostics.mask_digits("Estado_cuenta_12345678.pdf") == (
        "Estado_cuenta_99999999.pdf"
    )


# --------------------------------------------------------------- file shape


def test_sniff_reads_a_comma_csv():
    data = b"Date,Ticker,Type\n2023-01-03,ASML,BUY\n"
    out = diagnostics.sniff("statement.csv", data)
    assert out["ext"] == "csv"
    assert out["encoding"] == "utf-8-sig"
    assert out["delimiter"] == ","
    assert out["headers"] == ["Date", "Ticker", "Type"]
    assert out["rows"] == 1
    assert out["bytes"] == len(data)


def test_sniff_spots_a_semicolon_export():
    """The delimiter statement.parse_csv never looks for."""
    data = b"Fecha;Ticker;Tipo\n2023-01-03;ASML;Compra\n"
    out = diagnostics.sniff("operaciones.csv", data)
    assert out["delimiter"] == ";"
    assert out["headers"] == ["Fecha", "Ticker", "Tipo"]


def test_sniff_names_the_encoding_that_read_the_file():
    """The fingerprint reports whatever statement.decode fell back to."""
    data = "Fecha,Descripción\n2023-01-03,Comisión\n".encode("cp1252")
    out = diagnostics.sniff("extracto.csv", data)
    assert out["encoding"] == "cp1252"


def test_sniff_never_raises_on_rubbish():
    out = diagnostics.sniff("mystery.xlsx", b"not a workbook at all")
    assert out["ext"] == "xlsx"
    assert "sniff_error" in out


# ------------------------------------------------------------------ rollups


def test_reasons_is_a_histogram_not_a_row_list():
    result = ParseResult(skipped=[
        {"row": i, "type": "BUY", "reason": f"unrecognised date '0{i}-01-2023'"}
        for i in range(1, 6)
    ])
    assert diagnostics.reasons(result) == {"unrecognised date '99-99-9999'": 5}


def test_reasons_keeps_only_the_commonest():
    result = ParseResult(skipped=[
        {"row": i, "type": "x", "reason": f"reason {chr(97 + i)}"}
        for i in range(diagnostics.MAX_REASONS + 5)
    ])
    assert len(diagnostics.reasons(result)) == diagnostics.MAX_REASONS


def test_date_hint_settles_day_first_when_a_day_runs_past_twelve():
    result = ParseResult(skipped=[
        {"row": 2, "reason": "unrecognised date '03-01-2023'"},
        {"row": 3, "reason": "unrecognised date '28-02-2023'"},
    ])
    assert diagnostics.date_hint(result) == {
        "likely": "DD-MM-YYYY", "separator": "-", "samples": 2
    }


def test_date_hint_admits_when_it_cannot_tell():
    result = ParseResult(skipped=[{"row": 2, "reason": "unrecognised date '03/01/2023'"}])
    hint = diagnostics.date_hint(result)
    assert hint is not None
    assert hint["likely"] == "ambiguous"
    assert hint["separator"] == "/"


def test_date_hint_is_absent_when_no_date_failed():
    result = ParseResult(skipped=[{"reason": "missing ticker"}])
    assert diagnostics.date_hint(result) is None


# -------------------------------------------------------------- fingerprint


def test_fingerprint_carries_what_a_fix_needs():
    data = b"Date,Ticker,Type\n2023-01-03,ASML,BUY\n"
    fp = diagnostics.fingerprint("revolut", "statement.csv", data)
    assert fp["platform"] == "revolut"
    assert fp["surface"] == "import"
    assert fp["headers"] == ["Date", "Ticker", "Type"]
    assert fp["imported"] == 0


def test_fingerprint_redacts_the_exception_message():
    error = ValueError("unrecognised date '03-01-2023'")
    fp = diagnostics.fingerprint("degiro", "x.csv", b"", error=error)
    assert fp["error_type"] == "ValueError"
    assert fp["error"] == "unrecognised date '99-99-9999'"


def test_failed_is_true_for_an_import_that_produced_nothing():
    assert diagnostics.failed({"imported": 0, "skipped": 0})
    assert diagnostics.failed({"imported": 5, "skipped": 2})
    assert not diagnostics.failed({"imported": 5, "skipped": 0})


# -------------------------------------------------------------------- sinks


def test_report_logs_and_keeps_only_the_failures(sandbox, caplog):
    broken = ParseResult(skipped=[{"row": 2, "reason": "missing ticker"}])
    with caplog.at_level("INFO", logger="stocks"):
        fp = diagnostics.report("revolut", "s.csv", b"Date,Ticker\n", broken)
    assert "id" in fp
    assert len(list(sandbox.glob("*.json"))) == 1
    record = caplog.records[-1]
    assert record.event == "import.parse"
    assert record.ok is False
    assert record.top_reason == "missing ticker"


def test_report_keeps_no_artifact_for_a_clean_import(sandbox):
    clean = ParseResult(transactions=[object()])  # type: ignore[list-item]
    diagnostics.report("revolut", "s.csv", b"Date,Ticker\n", clean)
    assert not sandbox.exists() or not list(sandbox.glob("*.json"))


def test_stored_reads_back_what_report_wrote(sandbox):
    broken = ParseResult(skipped=[{"row": 2, "reason": "missing ticker"}])
    fp = diagnostics.report("degiro", "s.csv", b"Date\n", broken)
    items = diagnostics.stored()
    assert len(items) == 1
    assert items[0]["platform"] == "degiro"
    assert diagnostics.find(fp["id"]) == items[0]


def test_record_failure_never_propagates(monkeypatch, sandbox):
    monkeypatch.setattr(
        diagnostics.storage, "persist",
        lambda p: (_ for _ in ()).throw(OSError("bucket down")),
    )
    assert diagnostics.record({"ts": "2026-09-17T10:00:00Z"}) is None


# ------------------------------------------------------- the privacy guard


def _revolut_csv_with_sentinels() -> bytes:
    """A Revolut export whose every row breaks, carrying marker values."""
    rows = [
        "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency",
        f"{DATE},{TICKER},BUY,,{AMOUNT},{AMOUNT},USD",          # no quantity
        f"{DATE},{TICKER},BUY,2,-{AMOUNT},{AMOUNT},USD",        # negative price
        f"{DATE},,BUY,2,{AMOUNT},{AMOUNT},USD",                 # missing ticker
        f"{DATE},{TICKER},CASH TOP-UP,,,{AMOUNT},USD",          # skipped by type
    ]
    return ("\n".join(rows) + "\n").encode()


def test_no_user_values_escape_into_the_fingerprint(sandbox):
    """The guarantee the whole feature rests on.

    A parser written later that interpolates a value without quoting it fails
    here rather than in production.
    """
    data = _revolut_csv_with_sentinels()
    result = platforms.by_key("revolut").parse(FILENAME, data)
    assert result.skipped, "fixture must actually break, or this proves nothing"

    fp = diagnostics.report("revolut", FILENAME, data, result)
    blob = json.dumps(fp, ensure_ascii=False)
    for sentinel in SENTINELS:
        assert sentinel not in blob, f"{sentinel!r} leaked into {blob}"


def test_the_stored_artifact_is_clean_too(sandbox):
    data = _revolut_csv_with_sentinels()
    result = platforms.by_key("revolut").parse(FILENAME, data)
    diagnostics.report("revolut", FILENAME, data, result)
    written = next(iter(sandbox.glob("*.json"))).read_text()
    for sentinel in SENTINELS:
        assert sentinel not in written


def test_the_skipped_row_audit_is_never_carried_over():
    """ParseResult.skipped entries hold date/ticker/quantity/amount per row.

    `reasons()` reads one key out of them and must keep reading only that one.
    """
    result = ParseResult(skipped=[{
        "row": 2, "type": "BUY", "reason": "missing ticker",
        "date": DATE, "ticker": TICKER, "amount": AMOUNT, "currency": "USD",
    }])
    assert diagnostics.reasons(result) == {"missing ticker": 1}


# ------------------------------------------------------------- the rollups


def _filed(ts: str, platform: str, user: str, reason: str = "missing ticker") -> dict:
    return {"ts": ts, "platform": platform, "user": user, "reasons": {reason: 1}}


def test_recent_keeps_what_falls_inside_the_window(monkeypatch):
    monkeypatch.setattr(diagnostics.time, "time", lambda: 1789000000.0)
    now = diagnostics.time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", diagnostics.time.gmtime(1789000000.0)
    )
    old = diagnostics.time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", diagnostics.time.gmtime(1789000000.0 - 48 * 3600)
    )
    items = [_filed(old, "degiro", "a"), _filed(now, "revolut", "b")]
    assert [i["platform"] for i in diagnostics.recent(items, hours=24)] == ["revolut"]


def test_hotspots_ignores_a_broker_only_one_reader_tripped_over():
    items = [_filed("2026-09-17T10:00:00Z", "degiro", "a")]
    assert diagnostics.hotspots(items, threshold=3) == []


def test_hotspots_counts_readers_apart_from_attempts():
    """Three readers is a parser bug; one reader retrying three times is not."""
    items = [
        _filed("2026-09-17T10:00:00Z", "degiro", "a", "unrecognised date '99-99-9999'"),
        _filed("2026-09-17T11:00:00Z", "degiro", "a", "unrecognised date '99-99-9999'"),
        _filed("2026-09-17T12:00:00Z", "degiro", "b", "missing ISIN"),
    ]
    spot = diagnostics.hotspots(items, threshold=3)[0]
    assert spot["platform"] == "degiro"
    assert spot["count"] == 3
    assert spot["readers"] == 2
    assert spot["top_reason"] == "unrecognised date '99-99-9999'"


def test_hotspots_counts_a_crash_as_its_own_reason():
    items = [
        {"ts": "2026-09-17T10:00:00Z", "platform": "revolut", "user": "a",
         "error_type": "UnicodeDecodeError"}
        for _ in range(3)
    ]
    assert diagnostics.hotspots(items, threshold=3)[0]["top_reason"] == (
        "UnicodeDecodeError"
    )


def test_headers_survive_verbatim_because_they_are_the_brokers_schema():
    """The one field deliberately not masked — and the most useful one."""
    data = b"Fecha valor,Producto,ISIN,Numero,Precio\n2023-01-03,x,y,1,2\n"
    fp = diagnostics.fingerprint("degiro", "Transactions.csv", data)
    assert fp["headers"] == ["Fecha valor", "Producto", "ISIN", "Numero", "Precio"]
