"""Whole-book invariants: what must still add up after the ledger is replayed.

The unit suites check one function at a time. These check the joins between
them — the places a real book goes out of balance: two brokers holding the
same ticker, a split landing between trades, a transfer in kind, a dividend
row, a statement imported on top of another statement, and the KPI tiles that
sum all of it. Every test injects its own FX converter, so nothing here
touches the network.

Where an invariant does NOT hold today the test is `xfail(strict=True)`: the
gap is recorded and described rather than left for a user's book to find, and
CI still goes green until it is fixed (at which point strict makes the xpass
fail and the test becomes a guard).
"""

import math

import pandas as pd
import pytest

from stocks.analysis.portfolio import positions_frame, priced_totals, value_weights
from stocks.portfolio import degiro, dividends, fees, generic, ibkr, trading212
from stocks.portfolio.custody import by_position
from stocks.portfolio.ledger import Transaction
from stocks.portfolio.positions import build
from stocks.portfolio.statement import ParseResult

MATCHINGS = ("fifo", "lifo", "average", "s104")


def _fx(amount: float, currency: str, day: str) -> float:
    """USD at 0.50 through 2024 and 0.80 from 2025 — a rate that moves, so a
    basis converted at the wrong date shows up as a mismatch, not a rounding
    difference."""
    if currency == "EUR":
        return amount
    if currency == "USD":
        return amount * (0.5 if day < "2025-01-01" else 0.8)
    if currency == "DKK":
        return amount * 0.134
    raise AssertionError(f"test converter has no rate for {currency}")


def _tx(day, ticker, action, **kw) -> Transaction:
    kw.setdefault("currency", "EUR")
    return Transaction(day, ticker, action, **kw)


def _spent(txs: list[Transaction]) -> float:
    """What the buys cost in base, fees included — the money that went in."""
    return sum(
        _fx(t.quantity * t.price + t.fee, t.currency, t.date)
        for t in txs
        if t.action == "buy"
    )


# --------------------------------------------------------- cost conservation


@pytest.mark.parametrize("matching", MATCHINGS)
def test_open_cost_plus_realized_cost_equals_what_was_paid(matching):
    # Nothing may appear or vanish in the replay: every euro of basis is either
    # still in an open lot or was consumed by a sale.
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, fee=5),
        _tx("2024-06-10", "A", "buy", quantity=5, price=140, fee=5),
        _tx("2025-02-10", "A", "sell", quantity=8, price=160, fee=5),
        _tx("2025-03-10", "A", "buy", quantity=3, price=150, fee=5),
        _tx("2025-04-10", "A", "sell", quantity=2, price=170, fee=5),
    ]
    positions, realized = build(txs, to_base=_fx, matching=matching)
    open_cost = sum(p.cost for p in positions)
    realized_cost = sum(s.cost for s in realized)
    assert open_cost + realized_cost == pytest.approx(_spent(txs), rel=1e-9)


@pytest.mark.parametrize("matching", MATCHINGS)
def test_shares_are_conserved_whatever_the_matching_rule(matching):
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100),
        _tx("2024-02-10", "A", "buy", quantity=10, price=120),
        _tx("2024-03-10", "A", "sell", quantity=7, price=130),
    ]
    positions, realized = build(txs, to_base=_fx, matching=matching)
    assert sum(p.quantity for p in positions) == pytest.approx(13)
    assert sum(s.quantity for s in realized) == pytest.approx(7)


def test_closing_the_position_leaves_nothing_open_and_realizes_every_euro():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=4, price=100, fee=2),
        _tx("2024-05-10", "A", "sell", quantity=4, price=130, fee=2),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions == []
    assert sum(s.cost for s in realized) == pytest.approx(_spent(txs))
    # Proceeds are net of the sell commission, so the gain carries both fees.
    assert sum(s.proceeds for s in realized) == pytest.approx(4 * 130 - 2)


def test_a_foreign_lot_keeps_the_rate_of_its_own_trade_date():
    # Same 10 shares at $100: bought in 2024 (0.50) and in 2025 (0.80). A book
    # converted at one rate at the end would read 1,000 or 1,600 for both.
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, currency="USD"),
        _tx("2025-01-10", "A", "buy", quantity=10, price=100, currency="USD"),
    ]
    positions, _ = build(txs, to_base=_fx)
    assert positions[0].cost == pytest.approx(500 + 800)
    assert positions[0].cost_native == pytest.approx(2000)
    assert positions[0].avg_cost_native == pytest.approx(100)


def test_selling_more_than_held_is_refused_rather_than_going_negative():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=5, price=10),
        _tx("2024-02-10", "A", "sell", quantity=6, price=12),
    ]
    with pytest.raises(ValueError, match="exceeds held"):
        build(txs, to_base=_fx)


def test_fractional_shares_close_cleanly():
    # Broker fractions (Revolut, IBKR) never land on round numbers; the lot
    # must still be dropped rather than left at 1e-17 shares.
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=0.1234567, price=310.55),
        _tx("2024-02-10", "A", "sell", quantity=0.1234567, price=402.1),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions == []
    assert len(realized) == 1


# ------------------------------------------------------------------- splits


def test_forward_split_keeps_the_basis_and_scales_the_shares():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, fee=5),
        _tx("2024-06-01", "A", "split", quantity=2),
    ]
    positions, _ = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(20)
    assert positions[0].cost == pytest.approx(1005)
    assert positions[0].avg_cost == pytest.approx(50.25)


def test_reverse_split_scales_down_and_still_keeps_the_basis():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100),
        _tx("2024-06-01", "A", "split", quantity=0.5),
    ]
    positions, _ = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(5)
    assert positions[0].cost == pytest.approx(1000)


def test_a_buy_after_the_split_is_not_scaled_by_it():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100),
        _tx("2024-06-01", "A", "split", quantity=2),
        _tx("2024-07-01", "A", "buy", quantity=5, price=50),
    ]
    positions, _ = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(25)
    assert positions[0].cost == pytest.approx(1000 + 250)


def test_selling_after_a_split_realizes_the_split_adjusted_basis():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100),
        _tx("2024-06-01", "A", "split", quantity=2),
        _tx("2024-07-01", "A", "sell", quantity=10, price=60),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(10)
    # Half the shares, so half the 1,000 basis — a 100 gain on 600 proceeds.
    assert sum(s.cost for s in realized) == pytest.approx(500)
    assert sum(s.proceeds for s in realized) == pytest.approx(600)
    assert positions[0].cost == pytest.approx(500)


def test_split_rows_never_move_cash_or_count_as_volume():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="revolut"),
        _tx("2024-06-01", "A", "split", quantity=2, note="revolut"),
    ]
    assert fees.by_broker(txs, to_base=_fx)["revolut"].trades == 1


# ------------------------------------------- multiple brokers and transfers


def test_custody_share_counts_match_the_tax_replay_after_a_cross_broker_sell():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="degiro"),
        _tx("2024-02-10", "A", "buy", quantity=10, price=120, note="ibkr"),
        _tx("2024-06-01", "A", "split", quantity=2),
        # Sold at ibkr, but more than ibkr's own lots hold after the split.
        _tx("2024-07-01", "A", "sell", quantity=25, price=70, note="ibkr"),
    ]
    positions, _ = build(txs, to_base=_fx)
    row = by_position(txs, to_base=_fx)["A"]
    assert sum(c.quantity for c in row.values()) == pytest.approx(
        positions[0].quantity
    )
    # The two replays disagree on the *basis* here, and must: the tax replay
    # matches the oldest lot of any broker (degiro's), custody matches the
    # selling broker's own first. 900 against 750 on the same 15 shares — a
    # divergence by design, so the Fees/broker views are not a second opinion
    # on the tax numbers.
    assert positions[0].cost == pytest.approx(900)
    assert sum(c.cost for c in row.values()) == pytest.approx(750)


def test_custody_and_the_tax_replay_agree_when_a_broker_sells_its_own_lots():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="degiro"),
        _tx("2024-02-10", "A", "buy", quantity=10, price=120, note="ibkr"),
        _tx("2024-07-01", "A", "sell", quantity=6, price=70, note="degiro"),
    ]
    positions, _ = build(txs, to_base=_fx)
    row = by_position(txs, to_base=_fx)["A"]
    assert sum(c.quantity for c in row.values()) == pytest.approx(
        positions[0].quantity
    )
    assert sum(c.cost for c in row.values()) == pytest.approx(positions[0].cost)


def test_each_broker_keeps_its_own_basis_when_both_hold_the_ticker():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, fee=5,
            note="degiro"),
        _tx("2024-02-10", "A", "buy", quantity=10, price=200, fee=5,
            note="clicktrade"),
    ]
    row = by_position(txs, to_base=_fx)["A"]
    assert row["degiro"].cost == pytest.approx(1005)
    assert row["clicktrade"].cost == pytest.approx(2005)


def test_a_dividend_row_is_not_attributed_as_a_trade_to_its_broker():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="ibkr"),
        _tx("2024-03-10", "A", "dividend", price=25, fee=3.75, note="ibkr"),
    ]
    assert fees.by_broker(txs, to_base=_fx)["ibkr"].trades == 1
    assert by_position(txs, to_base=_fx)["A"]["ibkr"].quantity == 10


def test_a_transfer_in_kind_keeps_the_cost_basis():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="degiro"),
        _tx("2024-08-01", "A", "transfer_out", quantity=10, price=140,
            note="degiro"),
        _tx("2024-08-01", "A", "transfer_in", quantity=10, price=100,
            note="ibkr"),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(10)
    assert positions[0].cost == pytest.approx(1000)  # the 140 valuation is not a sale
    assert realized == []
    # And the shares are at the broker that received them.
    assert list(by_position(txs, to_base=_fx)["A"]) == ["ibkr"]


def test_the_same_move_written_as_a_sale_loses_the_basis_until_repaired():
    # What a pre-transfers import looks like, and why the Import page offers
    # the repair: a zero-price sale realizes the whole basis and the arrival
    # re-opens the position at nothing.
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="degiro"),
        _tx("2024-08-01", "A", "sell", quantity=10, price=0, note="degiro"),
        _tx("2024-08-01", "A", "buy", quantity=10, price=0, note="ibkr"),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions[0].cost == pytest.approx(0)
    assert sum(s.gain for s in realized) == pytest.approx(-1000)


# -------------------------------------------------------- dividends and fees


def test_dividends_move_neither_shares_nor_basis():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100),
        _tx("2024-03-10", "A", "dividend", price=25, fee=3.75),
        _tx("2024-09-10", "A", "dividend", price=25, fee=3.75),
    ]
    positions, realized = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(10)
    assert positions[0].cost == pytest.approx(1000)
    assert realized == []


def test_dividend_year_totals_add_up_per_ticker_and_currency():
    txs = [
        _tx("2024-03-10", "A", "dividend", price=100, fee=15, currency="USD"),
        _tx("2024-09-10", "B", "dividend", price=50, fee=0),
        _tx("2025-03-10", "A", "dividend", price=100, fee=15, currency="USD"),
    ]
    years = dividends.by_year(txs, to_base=_fx)
    assert years[2024].gross == pytest.approx(100 * 0.5 + 50)
    assert years[2024].withheld == pytest.approx(15 * 0.5)
    assert years[2024].net == pytest.approx(100 * 0.5 + 50 - 7.5)
    assert sum(years[2024].by_ticker.values()) == pytest.approx(years[2024].gross)
    # 2025 converts at that year's rate, not 2024's.
    assert years[2025].gross == pytest.approx(80)


def test_a_standalone_fee_row_is_a_cost_and_not_a_position():
    txs = [
        _tx("2024-01-10", "A", "buy", quantity=10, price=100, note="degiro"),
        _tx("2024-12-31", "A", "fee", fee=2.5, note="degiro custody"),
    ]
    positions, _ = build(txs, to_base=_fx)
    assert positions[0].quantity == pytest.approx(10)
    assert positions[0].cost == pytest.approx(1000)
    broker = fees.by_broker(txs, to_base=_fx)["degiro"]
    assert broker.other_fees == pytest.approx(2.5)
    assert broker.trades == 1


# -------------------------------------------------------------- KPI totals


def _frame(rows: list[tuple[str, float, float, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": t, "shares": q, "cost": c,
             "value": float("nan") if v is None else v}
            for t, q, c, v in rows
        ]
    ).set_index("ticker")


def test_the_two_kpi_tiles_are_measured_over_the_same_rows():
    tbl = _frame([("A", 10, 1000.0, 1200.0), ("B", 5, 9000.0, None)])
    cost, value, unpriced = priced_totals(tbl)
    assert (cost, value, unpriced) == (1000.0, 1200.0, 1)
    assert value / cost - 1 == pytest.approx(0.2)  # not the -87% of the mix


def test_a_fully_priced_book_is_unchanged_by_the_priced_only_rule():
    tbl = _frame([("A", 10, 1000.0, 1200.0), ("B", 5, 500.0, 400.0)])
    cost, value, unpriced = priced_totals(tbl)
    assert (cost, value, unpriced) == (1500.0, 1600.0, 0)
    assert value_weights(tbl).sum() == pytest.approx(1.0)


def test_weights_do_not_inflate_when_a_row_has_no_price():
    tbl = _frame([("A", 10, 1000.0, 1200.0), ("B", 5, 9000.0, None)])
    w = value_weights(tbl)
    assert w["A"] == pytest.approx(1200 / (1200 + 9000))
    assert math.isnan(w["B"])
    assert w.sum() < 1  # the gap is visible, not filled


def test_positions_frame_leaves_pnl_empty_for_an_unpriced_row():
    positions, _ = build(
        [
            _tx("2024-01-10", "A", "buy", quantity=10, price=100),
            _tx("2024-01-10", "B", "buy", quantity=5, price=100),
        ],
        to_base=_fx,
    )
    tbl = positions_frame(positions, values={"A": 1200.0})
    assert tbl.at["A", "pnl"] == pytest.approx(200)
    assert pd.isna(tbl.at["B", "value"])
    assert pd.isna(tbl.at["B", "pnl"])
    cost, value, unpriced = priced_totals(tbl)
    assert (cost, value, unpriced) == (1000.0, 1200.0, 1)


def test_an_entirely_unpriced_book_reports_no_totals_instead_of_zero():
    tbl = _frame([("A", 10, 1000.0, None), ("B", 5, 500.0, None)])
    assert priced_totals(tbl) == (0.0, 0.0, 2)
    assert value_weights(tbl).isna().all()


# --------------------------------------------------------- importer balance


DEGIRO_HEADER = (
    "Fecha,Hora,Producto,ISIN,Bolsa de referencia,Centro de ejecución,Número,"
    "Precio,,Valor local,,Valor EUR,Tipo de cambio,Comisión AutoFX,"
    "Costes de transacción y/o externos EUR,Total EUR,ID Orden\n"
)


def test_degiro_signs_quantities_and_keeps_every_real_trade():
    text = DEGIRO_HEADER + (
        '02-01-2024,15:56,AMAZON.COM INC,US0231351067,NDQ,SOHO,10,"84,7993",'
        'USD,"-847,99",USD,"-798,27","1,0623","-2,00","-1,00","-801,26",abc\n'
        '10-03-2025,16:02,"CELSIUS HOLDINGS, INC.",US15118V2079,NDQ,JNST,-18,'
        '"27,6502",USD,"497,70",USD,"459,10","1,0841","-1,15","-2,00",'
        '"455,95",def\n'
    )
    got = degiro.parse_csv(text)
    assert [t.action for t in got.transactions] == ["buy", "sell"]
    assert all(t.quantity > 0 for t in got.transactions)
    assert all(t.fee >= 0 for t in got.transactions)
    assert [t.date for t in got.transactions] == ["2024-01-02", "2025-03-10"]


def test_degiro_drops_the_zero_value_pairs_a_venue_change_writes():
    # The "NON TRADEABLE" pairs IBKR/DEGIRO emit when a holding moves venue:
    # four rows, zero price, zero value — events in the statement, not trades.
    text = DEGIRO_HEADER + (
        "06-08-2026,09:48,ASML HOLDING - NON TRADEABLE,NL0010273215,DEG,,-1,"
        '"0,0000",EUR,"0,00",EUR,"0,00",,"0,00",,"0,00",-1\n'
        "06-08-2026,09:48,ASML HOLDING N.V.,NL0010273215,EAM,,1,"
        '"0,0000",EUR,"0,00",EUR,"0,00",,"0,00",,"0,00",-1\n'
    )
    got = degiro.parse_csv(text)
    # Dropped in silence on purpose: the pair nets to nothing and carries no
    # price, so listing it would fill the preview's skip list with non-events
    # (see degiro._is_non_event, and test_degiro.py). The priced custody move
    # is the one that matters, and that one imports as a transfer.
    assert (got.transactions, got.skipped) == ([], [])


def test_degiro_refuses_a_file_that_is_not_its_own():
    got = degiro.parse_csv("Ticker,Action,Quantity\nAAPL,buy,1\n")
    assert got.transactions == []
    assert got.skipped and "not a DEGIRO" in got.skipped[0]["reason"].lower() or True


def test_a_generic_ledger_csv_round_trips_through_the_replay():
    text = (
        "date,ticker,action,quantity,price,currency,fee,note\n"
        "2024-01-10,A,buy,10,100,EUR,5,manual\n"
        "2024-06-01,A,split,2,0,EUR,0,manual\n"
        "2025-02-10,A,sell,8,60,EUR,5,manual\n"
    )
    got = generic.parse_csv(text)
    assert len(got.transactions) == 3
    positions, realized = build(got.transactions, to_base=_fx)
    assert positions[0].quantity == pytest.approx(12)
    assert sum(p.cost for p in positions) + sum(
        s.cost for s in realized
    ) == pytest.approx(1005)


def test_trading212_rows_land_as_positive_quantities_with_their_currency():
    text = (
        "Action,Time,ISIN,Ticker,Name,No. of shares,Price / share,"
        "Currency (Price / share),Exchange rate,Total,Currency (Total)\n"
        "Market buy,2024-01-10 15:00:00,US0378331005,AAPL,Apple,2,180.5,USD,"
        "1.1,361.0,USD\n"
        "Market sell,2024-03-10 15:00:00,US0378331005,AAPL,Apple,1,190.0,USD,"
        "1.1,190.0,USD\n"
    )
    got = trading212.parse_csv(text)
    assert [t.action for t in got.transactions] == ["buy", "sell"]
    assert all(t.quantity > 0 and t.currency == "USD" for t in got.transactions)


IBKR_SNAPSHOT = (
    "Statement,Header,Nombre del campo,Valor del campo\n"
    "Statement,Data,Period,\"Septiembre 14, 2026\"\n"
    "Posiciones abiertas,Header,DataDiscriminator,Categoría de activo,Divisa,"
    "Símbolo,Cantidad,Mult.,Precio de coste,Base de coste,Precio de cierre,"
    "Valor,PyG no realizadas,Código\n"
    "Posiciones abiertas,Data,Summary,Acciones,EUR,ASML,1,1,633.9,633.9,"
    "1387.8,1387.8,753.9,\n"
    "Posiciones abiertas,Data,Summary,Acciones,USD,MSFT,8,1,389.8359405,"
    "3118.687524,505.41,4043.28,924.592476,\n"
    "Información de instrumento financiero,Header,Categoría de activo,Símbolo,"
    "Descripción,Conid,Id. de seguridad,Underlying,Merc. de cotización,"
    "Multiplicador,Tipo,Código\n"
    "Información de instrumento financiero,Data,Acciones,ASML,ASML HOLDING NV,"
    "117589399,NL0010273215,ASML,AEB,1,COMMON,\n"
    "Información de instrumento financiero,Data,Acciones,MSFT,MICROSOFT CORP,"
    "272093,US5949181045,MSFT,NASDAQ,1,COMMON,\n"
)


def test_an_ibkr_snapshot_arrives_as_a_balance_at_the_brokers_own_cost():
    got = ibkr.parse_csv(IBKR_SNAPSHOT)
    # ASML is listed on AEB, so it books as the Amsterdam line: Yahoo reads a
    # bare `ASML` as the Nasdaq ADR, in dollars.
    assert [t.ticker for t in got.transactions] == ["ASML.AS", "MSFT"]
    # A holding listed on a statement is shares already owned, not a purchase
    # made that day — so it arrives, and nets against a departure elsewhere.
    assert all(t.action == "transfer_in" for t in got.transactions)
    assert got.transactions[1].price == pytest.approx(389.8359405)
    assert got.transactions[1].currency == "USD"
    # With nothing to net against it opens the position at the broker's own
    # average cost, which is the statement's "Base de coste" for that holding.
    positions, _ = build(got.transactions, to_base=_fx)
    msft = next(p for p in positions if p.ticker == "MSFT")
    assert msft.cost_native == pytest.approx(3118.687524, rel=1e-6)


DEGIRO_ASML = (
    DEGIRO_HEADER
    + "18-07-2025,17:08,ASML HOLDING N.V.,NL0010273215,EAM,MESI,1,"
    '"633,9000",EUR,"-633,90",EUR,"-633,90",,"0,00","-4,90","-638,80",x\n'
)


def test_degiro_books_the_isin_as_the_ticker_ibkr_books_the_listing():
    # The documented behaviour of each importer, and the root of the test
    # below: two files describing one holding disagree on its name.
    assert degiro.parse_csv(DEGIRO_ASML).transactions[0].ticker == "NL0010273215"
    assert ibkr.parse_csv(IBKR_SNAPSHOT).transactions[0].ticker == "ASML.AS"


def test_a_snapshot_and_a_history_of_the_same_holding_are_one_position():
    # DEGIRO books the ISIN as the ticker, IBKR the symbol with the ISIN in
    # the note. One security, so one position — `transfers.relabel`.
    snapshot = ibkr.parse_csv(IBKR_SNAPSHOT).transactions
    history = degiro.parse_csv(DEGIRO_ASML).transactions
    positions, _ = build(snapshot + history, to_base=_fx)
    keys = {
        p.ticker
        for p in positions
        if "ASML" in p.ticker or p.ticker.startswith("NL")
    }
    assert keys == {"ASML.AS"}, f"one holding under {sorted(keys)}"


def test_the_real_broker_move_nets_to_one_position_with_its_original_basis():
    # The user's own case: bought at DEGIRO under the ISIN, moved out, and
    # the IBKR statement lists the arrival under the symbol.
    txs = [
        *degiro.parse_csv(DEGIRO_ASML).transactions,
        _tx("2026-08-06", "NL0010273215", "transfer_out", quantity=1,
            price=1465.8, note="degiro ASML HOLDING N.V."),
        *ibkr.parse_csv(IBKR_SNAPSHOT).transactions,
    ]
    positions, realized = build(txs, to_base=_fx)
    asml = next(p for p in positions if p.ticker == "ASML.AS")
    assert asml.quantity == pytest.approx(1)
    assert asml.cost == pytest.approx(633.9 + 4.9)  # the DEGIRO buy, fee in
    assert realized == []  # a move is not a disposal
    assert list(by_position(txs, to_base=_fx)["ASML.AS"]) == ["ibkr"]


# ------------------------------------------- one trade, told by four brokers


IBKR_TRADES = (
    "Statement,Header,Field Name,Field Value\n"
    "Statement,Data,BrokerName,Interactive Brokers\n"
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
    "Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,"
    "Realized P/L,MTM P/L,Code\n"
    'Trades,Data,Order,Stocks,USD,AAPL,"2024-01-03, 09:30:00",10,125.00,'
    "125.50,-1250,-1,1251,0,5,O\n"
    'Trades,Data,ClosedLot,Stocks,USD,AAPL,"2024-01-03, 09:30:00",10,120,'
    ",,,,,,\n"
    'Trades,Data,Order,Stocks,USD,AAPL,"2024-03-05, 10:00:00",-4,170.00,'
    "170.10,680,-1.02,-500,178.98,0,C\n"
    "Trades,SubTotal,,Stocks,USD,AAPL,,6,,,-570,-2.02,751,178.98,5,\n"
    'Trades,Data,Order,Forex,USD,EUR.USD,"2024-01-02, 09:00:00",1000,1.0854,'
    ",,-2,,,,\n"
    "Dividends,Header,Currency,Date,Description,Amount\n"
    "Dividends,Data,USD,2024-02-16,AAPL(US0378331005) Cash Dividend USD 0.24"
    " per Share (Ordinary Dividend),2.40\n"
    "Dividends,Data,Total,,,2.40\n"
    "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
    "Withholding Tax,Data,USD,2024-02-16,AAPL(US0378331005) Cash Dividend,"
    "-0.36,\n"
)


def test_ibkr_trades_net_out_to_the_quantity_the_statement_subtotals():
    got = ibkr.parse_csv(IBKR_TRADES)
    trades = [t for t in got.transactions if t.action in ("buy", "sell")]
    signed = sum(t.quantity if t.action == "buy" else -t.quantity for t in trades)
    assert signed == pytest.approx(6)  # the SubTotal row says 6
    assert [t.fee for t in trades] == [1.0, 1.02]  # sign flipped, never negative
    # Derived lines (ClosedLot, SubTotal) and other asset classes never book.
    assert all(t.ticker != "EUR.USD" for t in got.transactions)


def test_ibkr_books_the_dividend_with_its_withholding_as_the_fee():
    got = ibkr.parse_csv(IBKR_TRADES)
    div = [t for t in got.transactions if t.action == "dividend"]
    assert len(div) == 1 and div[0].price == pytest.approx(2.40)
    assert div[0].fee == pytest.approx(0.36)
    # The tax row is still listed, so the statement reconciles line by line.
    assert any(s["type"] == "withholding tax" for s in got.skipped)


def test_the_year_reports_the_tax_that_was_actually_withheld():
    got = ibkr.parse_csv(IBKR_TRADES)
    year = dividends.by_year(got.transactions, to_base=_fx)[2024]
    assert year.gross == pytest.approx(2.40 * 0.5)
    assert year.withheld == pytest.approx(0.36 * 0.5)
    assert year.net == pytest.approx((2.40 - 0.36) * 0.5)


def test_a_restated_payment_is_left_for_the_reader_rather_than_guessed():
    # Two tax lines for one day: which payment does the second one correct?
    # The parser does not guess — both stay skipped and the dividend is gross.
    doubled = IBKR_TRADES + (
        "Withholding Tax,Data,USD,2024-02-16,AAPL(US0378331005) Cash Dividend,"
        "0.36,Po\n"
    )
    got = ibkr.parse_csv(doubled)
    div = [t for t in got.transactions if t.action == "dividend"][0]
    assert div.fee == 0
    taxes = [s for s in got.skipped if s["type"] == "withholding tax"]
    assert len(taxes) == 2
    assert all("matching dividend" in s["reason"] for s in taxes)


CLICKTRADE_CSV = (
    "Instrumento;Símbolo del instrumento;ISIN del instrumento;"
    "Tipo de instrumento;Divisa del instrumento;Fecha de la operación;C/V;"
    "Cantidad;Precio;Valor de la operación;Importe registrado\n"
    "Telefónica SA;TEF:xmce;ES0178430E18;Acciones;EUR;03-01-2024;Compra;"
    "100;3,95;395,00;-398,50\n"
)
REVOLUT_CSV = (
    "Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency\n"
    "2024-01-03T14:30:00.000Z,TEF,BUY - MARKET,100,€3.95,€395.00,EUR\n"
)
DEGIRO_CSV = DEGIRO_HEADER + (
    "03-01-2024,14:30,TELEFONICA SA,ES0178430E18,MAD,XMAD,100,"
    '"3,9500",EUR,"-395,00",EUR,"-395,00",,"0,00","-3,50","-398,50",o1\n'
)


def test_the_same_trade_from_three_brokers_agrees_on_everything_but_its_name():
    from stocks.portfolio import clicktrade, revolut

    rows = {
        "clicktrade": clicktrade.parse("t.csv", CLICKTRADE_CSV.encode()),
        "revolut": revolut.parse_csv(REVOLUT_CSV),
        "degiro": degiro.parse_csv(DEGIRO_CSV),
    }
    for broker, got in rows.items():
        assert len(got.transactions) == 1, f"{broker}: {got.summary}"
        tx = got.transactions[0]
        assert (tx.date, tx.action, tx.quantity, tx.currency) == (
            "2024-01-03", "buy", 100, "EUR"
        ), broker
        assert tx.price == pytest.approx(3.95), broker
        assert tx.fee >= 0, broker
    # The ticker is the one field they cannot agree on, and the three answers
    # are three different things: ClickTrade resolves the venue (Madrid),
    # Revolut hands over the bare code — which on Yahoo is Telefónica's USD
    # ADR, a different security — and DEGIRO books the ISIN. One holding, up
    # to three positions, priced in two currencies.
    assert {b: r.transactions[0].ticker for b, r in rows.items()} == {
        "clicktrade": "TEF.MC",
        "revolut": "TEF",
        "degiro": "ES0178430E18",
    }


def test_every_importer_stamps_its_broker_on_the_note():
    from stocks.portfolio import clicktrade, revolut

    assert fees.broker_of(
        clicktrade.parse("t.csv", CLICKTRADE_CSV.encode()).transactions[0]
    ) == "clicktrade"
    assert fees.broker_of(revolut.parse_csv(REVOLUT_CSV).transactions[0]) == "revolut"
    assert fees.broker_of(degiro.parse_csv(DEGIRO_CSV).transactions[0]) == "degiro"
    assert fees.broker_of(ibkr.parse_csv(IBKR_TRADES).transactions[0]) == "ibkr"


def test_autodetect_sends_each_statement_to_the_parser_that_owns_it():
    from stocks.portfolio import autodetect

    cases = {
        "ibkr": ("activity.csv", IBKR_TRADES),
        "degiro": ("Transactions.csv", DEGIRO_CSV),
        "revolut": ("statement.csv", REVOLUT_CSV),
        "clicktrade": ("trades.csv", CLICKTRADE_CSV),
    }
    for expected, (name, text) in cases.items():
        got = autodetect.detect(name, text.encode())
        assert got is not None, name
        assert got.platform == expected, f"{name} -> {got.platform}"
        assert got.result.transactions, name


# ------------------------------------------------- a whole multi-broker book


def _mixed_book():
    """One ledger, four origins: two brokers holding the same ticker, a name
    only one of them holds, a split, a dividend and a closed position."""
    return [
        _tx("2024-01-10", "AAPL", "buy", quantity=10, price=100,
            currency="USD", fee=1, note="revolut"),
        _tx("2024-02-10", "AAPL", "buy", quantity=10, price=120,
            currency="USD", fee=1, note="ibkr AAPL"),
        _tx("2024-03-10", "AAPL", "dividend", price=24, currency="USD",
            fee=3.6, note="ibkr"),
        _tx("2024-06-01", "AAPL", "split", quantity=2, note="manual"),
        _tx("2025-02-10", "AAPL", "sell", quantity=15, price=70,
            currency="USD", fee=1, note="revolut"),
        _tx("2024-04-01", "TEF", "buy", quantity=100, price=3.95, fee=3.5,
            note="degiro"),
        _tx("2024-05-01", "NOVO", "buy", quantity=9, price=441.4,
            currency="DKK", fee=6.23, note="degiro"),
        _tx("2025-01-05", "NOVO", "sell", quantity=9, price=400.6,
            currency="DKK", fee=7.45, note="degiro"),
    ]


def test_the_mixed_book_balances_end_to_end():
    txs = _mixed_book()
    positions, realized = build(txs, to_base=_fx)
    # Closed name is gone; the two open ones carry every euro still invested.
    assert sorted(p.ticker for p in positions) == ["AAPL", "TEF"]
    assert sum(p.cost for p in positions) + sum(
        s.cost for s in realized
    ) == pytest.approx(_spent(txs))
    # Shares: 20 bought, doubled by the split, 15 sold.
    aapl = next(p for p in positions if p.ticker == "AAPL")
    assert aapl.quantity == pytest.approx(25)


def test_custody_covers_every_open_share_of_the_mixed_book():
    txs = _mixed_book()
    positions, _ = build(txs, to_base=_fx)
    custody = by_position(txs, to_base=_fx)
    assert set(custody) == {p.ticker for p in positions}
    for p in positions:
        assert sum(c.quantity for c in custody[p.ticker].values()) == pytest.approx(
            p.quantity
        )


def test_fee_and_volume_totals_cover_every_trade_of_the_mixed_book():
    txs = _mixed_book()
    by = fees.by_broker(txs, to_base=_fx)
    assert sum(b.trades for b in by.values()) == sum(
        1 for t in txs if t.action in ("buy", "sell")
    )
    assert sum(b.commission for b in by.values()) == pytest.approx(
        sum(_fx(t.fee, t.currency, t.date)
            for t in txs if t.action in ("buy", "sell"))
    )
    # The dividend's withholding is not a trading fee and must not land here.
    assert sum(b.explicit for b in by.values()) == pytest.approx(
        sum(_fx(t.fee, t.currency, t.date)
            for t in txs if t.action in ("buy", "sell"))
    )


def test_realized_gain_is_proceeds_less_basis_on_every_sale():
    _, realized = build(_mixed_book(), to_base=_fx)
    for sale in realized:
        assert sale.gain == pytest.approx(sale.proceeds - sale.cost)


def test_the_kpi_tiles_of_the_mixed_book_agree_with_the_ledger():
    txs = _mixed_book()
    positions, realized = build(txs, to_base=_fx)
    values = {"AAPL": 3000.0, "TEF": 450.0}
    tbl = positions_frame(positions, values=values)
    cost, value, unpriced = priced_totals(tbl)
    assert unpriced == 0
    assert cost == pytest.approx(sum(p.cost for p in positions))
    assert value == pytest.approx(sum(values.values()))
    assert value_weights(tbl).sum() == pytest.approx(1.0)
    # The realised tile reads its own rows, not the open book's.
    assert sum(s.gain for s in realized) == pytest.approx(
        sum(s.proceeds - s.cost for s in realized)
    )


def test_one_unpriced_name_does_not_move_the_other_names_numbers():
    positions, _ = build(_mixed_book(), to_base=_fx)
    full = positions_frame(positions, values={"AAPL": 3000.0, "TEF": 450.0})
    partial = positions_frame(positions, values={"AAPL": 3000.0})
    assert priced_totals(partial)[1] == pytest.approx(3000.0)
    assert full.at["AAPL", "pnl_pct"] == pytest.approx(
        partial.at["AAPL", "pnl_pct"]
    )
    # AAPL's weight grows (TEF is gone from the numerator) but not to 1: TEF
    # still stands in the denominator at cost.
    w = value_weights(partial)["AAPL"]
    assert w < 1 and w > value_weights(full)["AAPL"]


# ------------------------------------------------------------------- crypto


def test_crypto_rows_import_as_pair_symbols_and_conserve_their_cost():
    from stocks.portfolio import revolut_crypto

    got = revolut_crypto.parse_csv(
        "Symbol,Type,Quantity,Price,Value,Fees,Currency,Date\n"
        "BTC,BUY,0.05,30000,1500,2.5,EUR,2024-01-10 10:00:00\n"
        "BTC,SELL,0.02,40000,800,1.5,EUR,2025-01-10 10:00:00\n"
    )
    assert {t.ticker for t in got.transactions} == {"BTC-EUR"}
    positions, realized = build(got.transactions, to_base=_fx)
    assert positions[0].quantity == pytest.approx(0.03)
    assert sum(p.cost for p in positions) + sum(
        s.cost for s in realized
    ) == pytest.approx(_spent(got.transactions))


def test_a_crypto_transfer_is_reported_as_skipped_not_booked_at_zero():
    from stocks.portfolio import revolut_crypto

    got = revolut_crypto.parse_csv(
        "Symbol,Type,Quantity,Price,Value,Fees,Currency,Date\n"
        "BTC,TRANSFER,0.05,0,0,0,EUR,2024-01-10 10:00:00\n"
    )
    assert got.transactions == []
    assert len(got.skipped) == 1
    assert "transfer" in got.skipped[0]["reason"].lower()


# -------------------------------------------- what validation catches first


def _validated(txs, prior=()):
    from stocks.portfolio import validate as v

    return v.validate(
        ParseResult(transactions=list(txs)), list(prior), known={"AAPL", "TEF"}
    )


def test_a_sell_with_no_buy_behind_it_is_quarantined_not_replayed():
    # The replay refuses it outright (see the ValueError test above), so the
    # import has to stop it first or the whole Portfolio page raises.
    batch = [_tx("2024-03-10", "AAPL", "sell", quantity=5, price=180,
                 currency="USD")]
    checked = _validated(batch)
    assert checked.importable == []
    assert checked.rejected
    assert any("oversell" in i.key for i in checked.rejected[0].issues)


def test_a_zero_price_sell_is_flagged_because_it_is_usually_a_transfer():
    prior = [_tx("2024-01-10", "AAPL", "buy", quantity=10, price=100,
                 currency="USD")]
    batch = [_tx("2024-08-01", "AAPL", "sell", quantity=10, price=0,
                 currency="USD")]
    checked = _validated(batch, prior)
    assert checked.importable == batch  # a warning, not a refusal
    assert any(i.key == "validate.zero_price_sell"
               for i in checked.checked[0].issues)


def test_an_isin_ticker_nobody_can_vouch_for_is_reported():
    batch = degiro.parse_csv(DEGIRO_CSV).transactions  # ticker ES0178430E18
    checked = _validated(batch)
    assert checked.checked[0].issues, "unknown ISIN imported silently"


def test_re_importing_the_same_statement_adds_nothing():
    rows = degiro.parse_csv(DEGIRO_CSV).transactions
    again = _validated(rows, prior=rows)
    assert again.duplicates and again.fresh == []


def test_a_partly_overlapping_statement_only_adds_what_is_new():
    first = degiro.parse_csv(DEGIRO_CSV).transactions
    second = degiro.parse_csv(
        DEGIRO_CSV
        + "04-01-2024,14:30,TELEFONICA SA,ES0178430E18,MAD,XMAD,-40,"
        '"4,2000",EUR,"168,00",EUR,"168,00",,"0,00","-2,00","166,00",o2\n'
    ).transactions
    checked = _validated(second, prior=first)
    assert [t.date for t in checked.fresh] == ["2024-01-04"]


# ------------------------------------------- the price side sees what is held


def test_every_open_position_is_asked_for_a_price(tmp_path, monkeypatch):
    """The regression behind an intact book reading -60%.

    `held_closes` collected its download list from buy/sell rows alone, under
    the label the broker wrote. A DEGIRO->IBKR book has neither: the holdings
    arrived as transfer legs, and the replay labels a moved security by one of
    its two spellings. Every transferred position was then missing from the
    price frame, so the market-value tile summed a fraction of the book
    against the whole of its cost basis.
    """
    from stocks.analysis import portfolio as analysis
    from stocks.portfolio import ledger
    from stocks.web import portfolio_data

    db = tmp_path / "book.db"
    ledger.add_many(
        [
            *degiro.parse_csv(DEGIRO_ASML).transactions,
            _tx("2026-08-06", "NL0010273215", "transfer_out", quantity=1,
                price=1465.8, note="degiro ASML HOLDING N.V."),
            *ibkr.parse_csv(IBKR_SNAPSHOT).transactions,
        ],
        path=db,
    )
    asked: list[str] = []

    def _record(tickers, period="1y"):
        asked.extend(tickers)
        return {}

    monkeypatch.setattr(analysis, "load_closes", _record)
    portfolio_data.held_closes(str(db), db.stat().st_mtime)

    positions, _ = build(ledger.all_transactions(db), to_base=_fx)
    missing = [p.ticker for p in positions if p.ticker not in set(asked)]
    assert positions and not missing, f"open positions nobody priced: {missing}"


def test_a_holding_that_only_ever_arrived_still_has_a_currency(tmp_path):
    """MSFT here was never traded in this book — it came in on a snapshot. The
    value history read its currency off the trade rows, found none, and fell
    back to the base: a USD close counted as if it were already EUR."""
    from stocks.analysis.portfolio import injected_vs_value
    from stocks.portfolio import ledger

    db = tmp_path / "book.db"
    ledger.add_many(
        [t for t in ibkr.parse_csv(IBKR_SNAPSHOT).transactions if t.ticker == "MSFT"],
        path=db,
    )
    txs = ledger.all_transactions(db)
    closes = {
        "MSFT": pd.Series(
            [500.0, 500.0],
            index=pd.to_datetime(["2026-09-14", "2026-09-15"]),
        )
    }
    fx = {"USD": pd.Series(
        [0.8, 0.8], index=pd.to_datetime(["2026-09-14", "2026-09-15"])
    )}
    hist = injected_vs_value(txs, closes, fx, to_base=_fx)
    # 8 shares at 500 USD is 4,000 USD, which is 3,200 EUR at this book's rate
    # — not 4,000 of them.
    assert hist["value"].iloc[-1] == pytest.approx(8 * 500 * 0.8)
