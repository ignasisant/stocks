from stocks.data import fetch
from stocks.portfolio import transfers
from stocks.portfolio.ledger import Transaction


def tx(ticker, qty=1.0, day="2026-01-05", note=""):
    return Transaction(
        date=day, ticker=ticker, action="buy", quantity=qty, price=100.0,
        currency="EUR", fee=0.0, note=note,
    )


def test_a_broker_code_and_its_symbol_are_one_position(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda *a, **k: {"HMI": "RMS.PA"})
    monkeypatch.setattr(fetch, "code_symbol", lambda key: None)
    monkeypatch.setattr(fetch, "cached_isin_symbol", lambda key: None)
    rows = transfers.relabel([tx("HMI"), tx("RMS.PA", 2.0)])
    assert {row.ticker for row in rows} == {"RMS.PA"}


def test_unrelated_symbols_stay_apart(monkeypatch):
    monkeypatch.setattr(fetch, "ticker_aliases", lambda *a, **k: {"HMI": "RMS.PA"})
    monkeypatch.setattr(fetch, "code_symbol", lambda key: None)
    monkeypatch.setattr(fetch, "cached_isin_symbol", lambda key: None)
    rows = transfers.relabel([tx("HMI"), tx("SAN.MC")])
    assert {row.ticker for row in rows} == {"HMI", "SAN.MC"}
