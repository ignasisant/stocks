"""Any crypto export, read without the user naming where it came from.

A header we know (Binance, Coinbase, Kraken, Koinly, Crypto.com...) is read
with no model; anything else that shows coins is mapped by the model and
booked by the same code. Prices come from a stub, never the network.
"""

from __future__ import annotations

import json

import pytest

from stocks.portfolio import autodetect, crypto_map, llm_map


class _Prices(crypto_map.Valuer):
    """Fixed closes per coin, in whatever fiat is asked; fiat at fixed rates."""

    def __init__(self, closes=None, rates=None):
        super().__init__()
        self.closes = closes or {}
        self.rates = rates or {}
        self.asked: list[tuple[set[str], str]] = []

    def prefetch(self, coins, fiat, since):
        self.asked.append((set(coins), fiat))

    def coin(self, coin, fiat, day):
        if coin in crypto_map.PEGS:
            return self.fiat(crypto_map.PEGS[coin], fiat, day)
        return self.closes.get(coin)

    def fiat(self, base, quote, day):
        return 1.0 if base == quote else self.rates.get((base, quote))


@pytest.fixture
def prices(monkeypatch):
    stub = _Prices({"BTC": 40000.0, "ETH": 2500.0, "DOT": 6.0, "CRO": 0.1})
    monkeypatch.setattr(crypto_map, "Valuer", lambda: stub)
    autodetect.forget()
    return stub


def _grid(text: str) -> list[list[str]]:
    return llm_map.read_grid("x.csv", text.encode())


def _rows(result):
    return [(t.date, t.ticker, t.action, round(t.quantity, 8), round(t.price, 4),
             round(t.fee, 4)) for t in result.transactions]


class _StubProvider:
    classifier_model = "stub-mini"
    default_model = "stub"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, api_key, model, system, messages):
        self.calls.append(system)
        return json.dumps(self.reply)


# ------------------------------------------------------------- normalising


@pytest.mark.parametrize(("text", "pair"), [
    ("BTCUSDT", ("BTC", "USDT")),
    ("ETH/EUR", ("ETH", "EUR")),
    ("SOL-USDC", ("SOL", "USDC")),
    ("XXBTZEUR", ("BTC", "EUR")),
    ("DOTEUR", ("DOT", "EUR")),
])
def test_split_pair(text, pair):
    assert crypto_map.split_pair(text) == pair


@pytest.mark.parametrize(("code", "coin"), [
    ("XXBT", "BTC"), ("XBT", "BTC"), ("ZEUR", "EUR"), ("XETH", "ETH"),
    ("DOT.S", "DOT"), ("ETH2", "ETH"), ("LDBTC", "BTC"), ("btc", "BTC"),
])
def test_asset_codes(code, coin):
    assert crypto_map._asset(code) == coin


@pytest.mark.parametrize(("text", "role"), [
    ("Buy", "buy"), ("Sell", "sell"), ("Staking Income", "reward"),
    ("Simple Earn Flexible Interest", "reward"), ("Withdraw", "send"),
    ("Deposit", "receive"), ("Convert", "convert"), ("Compra", "buy"),
    ("Venta", "sell"), ("Airdrop", "reward"),
])
def test_role_of(text, role):
    assert crypto_map.role_of(text) == role


def test_role_of_prefers_the_type_map():
    assert crypto_map.role_of("Deposit", {"deposit": "ignore"}) == "ignore"


def test_every_skip_reason_is_translated():
    import inspect
    import re

    from stocks.web import tx_text

    source = inspect.getsource(crypto_map)
    reasons = set(re.findall(r'_skip\([^"]*"([^"]+)"\)', source))
    assert len(reasons) > 10
    assert reasons <= set(tx_text.SKIP_REASONS), reasons - set(tx_text.SKIP_REASONS)


def test_looks_crypto():
    assert crypto_map.looks_crypto(_grid("when,what,qty\n2024-01-01,BTC,1\n"
                                         "2024-01-02,ETH,2\n"))
    assert not crypto_map.looks_crypto(_grid("when,what,qty\n2024-01-01,AAPL,1\n"
                                             "2024-01-02,MSFT,2\n"))


# ------------------------------------------------------------- known headers

BINANCE = (
    "User_ID,UTC_Time,Account,Operation,Coin,Change,Remark\n"
    "1,2024-01-05 10:00:00,Spot,Deposit,EUR,1000,\n"
    "1,2024-01-05 10:05:00,Spot,Buy Crypto,EUR,-500,\n"
    "1,2024-01-05 10:05:00,Spot,Buy Crypto,BTC,0.01,\n"
    "1,2024-02-01 00:00:00,Earn,Simple Earn Flexible Interest,BTC,0.0001,\n"
    "1,2024-02-02 00:00:00,Earn,Simple Earn Flexible Subscription,BTC,-0.01,\n"
)


def test_binance_statement(prices):
    grid = _grid(BINANCE)
    spec = crypto_map.preset_spec(grid)
    assert spec is not None and spec.exchange == "binance" and spec.layout == "ledger"

    result = crypto_map.apply(grid, spec, fiat_hint="EUR")
    assert _rows(result) == [
        ("2024-01-05", "BTC-EUR", "buy", 0.01, 50000.0, 0.0),
        ("2024-02-01", "BTC-EUR", "buy", 0.0001, 40000.0, 0.0),
        ("2024-02-01", "BTC-EUR", "dividend", 0.0, 4.0, 0.0),
    ]
    assert all(t.note.startswith("binance") for t in result.transactions)


COINBASE = (
    "You can use this transaction report to inform your likely tax obligations.\n"
    "\n"
    "Transactions\n"
    "User,someone,abc\n"
    "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,"
    "Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),"
    "Fees and/or Spread,Notes\n"
    "a1,2024-03-01 12:00:00 UTC,Buy,ETH,0.5,EUR,€3000.00,€1500.00,€1510.00,"
    "€10.00,Bought 0.5 ETH for €1510.00 EUR\n"
    "a2,2024-03-10 12:00:00 UTC,Sell,ETH,0.2,EUR,€3500.00,€700.00,€695.00,"
    "€5.00,Sold 0.2 ETH for €695.00 EUR\n"
    "a3,2024-03-15 12:00:00 UTC,Convert,ETH,0.1,EUR,€3400.00,€340.00,€340.00,"
    "€0.00,Converted 0.1 ETH to 0.005 BTC\n"
    "a4,2024-03-20 12:00:00 UTC,Staking Income,ETH,0.001,EUR,€3300.00,€3.30,"
    "€3.30,€0.00,\n"
)


def test_coinbase_with_a_preamble(prices):
    grid = _grid(COINBASE)
    spec = crypto_map.preset_spec(grid)
    assert spec is not None and spec.exchange == "coinbase"

    result = crypto_map.apply(grid, spec, fiat_hint="USD")
    assert _rows(result) == [
        ("2024-03-01", "ETH-EUR", "buy", 0.5, 3000.0, 10.0),
        ("2024-03-10", "ETH-EUR", "sell", 0.2, 3500.0, 5.0),
        ("2024-03-15", "BTC-EUR", "buy", 0.005, 68000.0, 0.0),
        ("2024-03-15", "ETH-EUR", "sell", 0.1, 3400.0, 0.0),
        ("2024-03-20", "ETH-EUR", "buy", 0.001, 3300.0, 0.0),
        ("2024-03-20", "ETH-EUR", "dividend", 0.0, 3.3, 0.0),
    ]


KRAKEN = (
    '"txid","refid","time","type","subtype","aclass","asset","amount","fee","balance"\n'
    '"L1","R1","2024-01-02 10:00:00","deposit","","currency","ZEUR",1000,0,1000\n'
    '"L2","T1","2024-01-03 11:00:00","trade","","currency","ZEUR",-400,1,599\n'
    '"L3","T1","2024-01-03 11:00:00","trade","","currency","XXBT",0.01,0,0.01\n'
    '"L4","S1","2024-01-10 00:00:00","staking","","currency","DOT.S",0.5,0,0.5\n'
)


def test_kraken_ledger_groups_by_refid(prices):
    grid = _grid(KRAKEN)
    spec = crypto_map.preset_spec(grid)
    assert spec is not None and spec.exchange == "kraken"

    result = crypto_map.apply(grid, spec)
    assert _rows(result) == [
        ("2024-01-03", "BTC-EUR", "buy", 0.01, 40000.0, 1.0),
        ("2024-01-10", "DOT-EUR", "buy", 0.5, 6.0, 0.0),
        ("2024-01-10", "DOT-EUR", "dividend", 0.0, 3.0, 0.0),
    ]


KOINLY = (
    "Date,Sent Amount,Sent Currency,Received Amount,Received Currency,Fee Amount,"
    "Fee Currency,Net Worth Amount,Net Worth Currency,Label,Description,TxHash\n"
    "2024-01-01 10:00 UTC,1000,USD,0.025,BTC,,,1000,USD,,,\n"
    "2024-02-01 10:00 UTC,0.01,BTC,0.2,ETH,,,500,USD,,,\n"
)


def test_koinly_swaps_value_a_coin_to_coin_trade(prices):
    grid = _grid(KOINLY)
    spec = crypto_map.preset_spec(grid)
    assert spec is not None and spec.exchange == "koinly"

    result = crypto_map.apply(grid, spec)
    assert _rows(result) == [
        ("2024-01-01", "BTC-USD", "buy", 0.025, 40000.0, 0.0),
        ("2024-02-01", "ETH-USD", "buy", 0.2, 2500.0, 0.0),
        ("2024-02-01", "BTC-USD", "sell", 0.01, 50000.0, 0.0),
    ]


def test_usdt_only_history_is_booked_in_the_account_currency():
    # USDT is a coin, not cash: paying with it disposes of it (fee included),
    # valued at its peg in the account's currency.
    stub = _Prices({"BTC": 40000.0}, rates={("USD", "EUR"): 0.9})
    grid = _grid(
        "Date(UTC),Market,Type,Price,Amount,Total,Fee,Fee Coin\n"
        "2024-01-01 10:00:00,BTCUSDT,BUY,40000,0.01,400,0.4,USDT\n"
    )
    spec = crypto_map.preset_spec(grid)
    result = crypto_map.apply(grid, spec, fiat_hint="EUR", valuer=stub)
    assert _rows(result) == [
        ("2024-01-01", "BTC-EUR", "buy", 0.01, 36000.0, 0.0),
        ("2024-01-01", "USDT-EUR", "sell", 400.4, 0.9, 0.36),
    ]


def test_a_header_can_name_the_currency():
    grid = _grid("Fecha,Tipo,Moneda,Cantidad,Importe EUR\n"
                 "01/04/2024,Compra,BTC,0.01,400\n")
    spec = crypto_map.Spec("", "rows", 0, {"date": 0, "type": 1, "asset": 2,
                                           "quantity": 3, "total": 4},
                           date_format="%d/%m/%Y")
    result = crypto_map.apply(grid, spec, valuer=_Prices())
    assert _rows(result) == [("2024-04-01", "BTC-EUR", "buy", 0.01, 40000.0, 0.0)]


# ------------------------------------------------------------- the model

UNKNOWN = (
    "Fecha;Operación;Moneda;Cantidad;Importe EUR\n"
    "01/04/2024;Compra;BTC;0,01;400,00\n"
    "02/04/2024;Compra;ETH;0,2;500,00\n"
    "05/04/2024;Recompensa;ETH;0,001;2,50\n"
)

CRYPTO_REPLY = {
    "exchange": "Bit2Me", "layout": "rows", "header_row": 0,
    "columns": {"date": 0, "type": 1, "asset": 2, "quantity": 3, "total": 4},
    "date_format": "%d/%m/%Y", "decimal": ",", "thousands": ".",
    "type_map": {"Compra": "buy", "Recompensa": "reward"},
}


def test_an_unknown_crypto_export_is_mapped_by_the_model(prices):
    provider = _StubProvider(CRYPTO_REPLY)
    found = autodetect.read("movimientos.csv", UNKNOWN.encode(), provider,
                            fiat="EUR")

    assert found.label == "Bit2Me"
    assert _rows(found.result)[:2] == [
        ("2024-04-01", "BTC-EUR", "buy", 0.01, 40000.0, 0.0),
        ("2024-04-02", "ETH-EUR", "buy", 0.2, 2500.0, 0.0),
    ]
    assert all(t.note.startswith("bit2me") for t in found.result.transactions)
    assert len(provider.calls) == 1


def test_a_known_header_needs_no_model(prices):
    found = autodetect.read("statement.csv", BINANCE.encode(), None, fiat="EUR")
    assert found.label == "Binance" and len(found.result.transactions) == 3


def test_a_share_file_never_asks_the_crypto_mapper(prices):
    provider = _StubProvider({
        "header_row": 0,
        "columns": {"date": 0, "ticker": 1, "action": 2, "quantity": 3, "price": 4},
        "date_format": "%d/%m/%Y", "decimal": ",", "thousands": ".",
        "action_map": {"Compra": "buy"},
    })
    found = autodetect.read("extracto.csv",
                            b"Fecha;Valor;Operacion;Titulos;Precio\n"
                            b"02/01/2024;AAPL;Compra;10;180,50\n", provider)
    assert [t.ticker for t in found.result.transactions] == ["AAPL"]
    assert all(crypto_map._SYSTEM not in system for system in provider.calls)


def test_a_declined_crypto_mapping_falls_back_to_the_share_mapper(prices):
    provider = _StubProvider({"layout": None})
    found = autodetect.read("movimientos.csv", UNKNOWN.encode(), provider)
    assert found.label == ""
    assert any(crypto_map._SYSTEM in system for system in provider.calls)
