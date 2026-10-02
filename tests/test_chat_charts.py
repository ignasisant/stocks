"""A price chart asked for in the chat, drawn by the app instead of the model.

Asked to chart something, a model with nothing to draw with types an ASCII
plot from figures it half-found. What is tested here is the replacement: the
message is read for what to chart and over which window, without a network
call where words will do; the closes are the Ticker page's download, thinned
for the drawer without losing the figures the prose quotes; and the surface
holds together as A2UI.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stocks.chat import a2ui, charts


def _no_lookup(name: str) -> str:
    raise AssertionError(f"looked {name!r} up when the message already said")


def _say(key: str, **slots) -> str:
    return key + "".join(f"|{k}={v}" for k, v in sorted(slots.items()))


@pytest.mark.parametrize("message", [
    "hazme un grafico evolucion euro dolar",
    "Gráfico del oro",
    "chart NVDA",
    "how has EUR/USD evolved this year?",
    "plot gold vs silver",
])
def test_a_request_for_a_chart_is_heard(message):
    assert charts.wants(message)


@pytest.mark.parametrize("message", [
    "¿qué opinas de Nvidia?",
    "vendo la mitad de AAPL",
    "add MSFT to my watchlist",
])
def test_a_message_that_asks_for_none_is_left_alone(message):
    assert not charts.wants(message)


@pytest.mark.parametrize(("message", "symbols"), [
    # The message that started this: two currencies in words, Spanish, no accents.
    ("hazme un grafico evolucion euro dolar", ["EURUSD=X"]),
    ("gráfico del EUR/USD", ["EURUSD=X"]),
    ("chart eurusd", ["EURUSD=X"]),
    ("evolución libra euro", ["GBPEUR=X"]),
    ("gráfico del oro y la plata", ["GC=F", "SI=F"]),
    ("compara AAPL vs MSFT en un gráfico", ["AAPL", "MSFT"]),
    ("gráfico de BTC-EUR esta semana", ["BTC-EUR"]),
    ("grafico del ibex 35", ["^IBEX"]),
])
def test_what_to_chart_is_read_off_the_words_first(message, symbols):
    assert charts.targets(message, {}, "", lookup=_no_lookup) == symbols


def test_a_single_currency_is_charted_against_the_reader_s_own():
    assert charts.targets("evolución del dólar", {}, "", base="EUR",
                          lookup=_no_lookup) == ["USDEUR=X"]
    assert charts.targets("chart the yen", {}, "", base="USD",
                          lookup=_no_lookup) == ["JPYUSD=X"]


def test_a_named_coin_is_priced_in_the_reader_s_currency():
    assert charts.targets("gráfico de bitcoin", {}, "", base="USD",
                          lookup=_no_lookup) == ["BTC-USD"]


def test_a_company_named_in_words_is_looked_up_once():
    asked: list[str] = []

    def lookup(name: str) -> str:
        asked.append(name)
        return "NVDA" if name.lower() == "nvidia" else ""

    assert charts.targets("Hazme un gráfico de Nvidia del último año", {}, "",
                          lookup=lookup) == ["NVDA"]
    # The request's own words are not a company: "Hazme" is never searched.
    assert asked == ["Nvidia"]
    asked.clear()
    assert charts.targets("grafico de nvidia", {}, "", lookup=lookup) == ["NVDA"]
    assert asked == ["nvidia"]


def test_the_page_in_focus_is_charted_when_the_message_names_nothing():
    assert charts.targets("muéstrame el gráfico", {}, "NVDA",
                          lookup=_no_lookup) == ["NVDA"]
    # ... and joins a comparison, but does not hijack another symbol's chart.
    assert charts.targets("gráfico comparado con el S&P 500", {}, "NVDA",
                          lookup=_no_lookup) == ["NVDA", "^GSPC"]
    assert charts.targets("gráfico de AAPL", {}, "NVDA",
                          lookup=_no_lookup) == ["AAPL"]


def test_nothing_to_chart_is_no_chart():
    assert charts.targets("gráfico de la nada", {}, "",
                          lookup=lambda _name: "") == []


@pytest.mark.parametrize(("message", "symbols"), [
    ("¿cómo voy contra el S&P?", [charts.BOOK, "^GSPC"]),
    ("Am I beating the market?", [charts.BOOK, "^GSPC"]),
    ("¿estoy batiendo al mercado este año?", [charts.BOOK, "^GSPC"]),
    ("compara mi cartera con el MSCI World", [charts.BOOK, "URTH"]),
    ("gráfico de mi rentabilidad frente al ibex", [charts.BOOK, "^IBEX"]),
    ("gráfico de mi cartera", [charts.BOOK]),
])
def test_the_reader_s_own_book_is_a_line_of_its_own(message, symbols):
    assert charts.wants(message)
    # The page in focus never joins: "how am I doing" is about the money.
    assert charts.targets(message, {}, "NVDA", lookup=_no_lookup) == symbols


@pytest.mark.parametrize("message", ["¿cómo voy?", "¿cómo va mi cartera?"])
def test_a_book_question_with_nothing_to_measure_it_by_draws_nothing(message):
    assert not charts.wants(message)


def _twr(n: int = 400, step: float = 0.001) -> tuple[pd.DataFrame, pd.Series]:
    days = pd.bdate_range("2025-01-01", periods=n)
    hist = pd.DataFrame({"value": range(n)}, index=days)
    twr = pd.Series(step, index=days[1:])  # no return on the book's first day
    return hist, twr


def test_the_book_s_line_compounds_to_the_figure_the_performance_tab_prints():
    hist, twr = _twr()
    level = charts.book_index(hist, twr, "6m")
    clipped = twr[twr.index >= twr.index.max() - pd.Timedelta(days=182)]
    assert level.iloc[0] == 100.0
    # Opened on the last day before the window's first return, so that
    # return is part of the line's change rather than its starting point.
    assert level.index[0] == hist.index[hist.index < clipped.index[0]][-1]
    assert level.iloc[-1] / level.iloc[0] - 1 == pytest.approx(
        float((1 + clipped).prod() - 1))
    whole = charts.book_index(hist, twr, "max")
    assert len(whole) == len(twr) + 1 and whole.index[0] == hist.index[0]
    assert charts.book_index(hist, pd.Series(dtype=float), "1y") is None


def test_against_the_book_a_benchmark_is_in_its_currency_and_from_its_first_day():
    hist, twr = _twr()
    converted: list[tuple[str, str]] = []

    def convert(closes, unit, base):
        converted.append((unit, base))
        return closes * 0.5

    def closes(symbol, window):
        assert window == "1m"  # a session of the book is one point: never 1d
        return pd.Series(range(1, len(hist) + 1), index=hist.index, dtype=float)

    chart = charts.build([charts.BOOK, "^GSPC", "EURUSD=X"], "1d",
                         closes=closes, currency=lambda _s: "USD",
                         book=lambda window: charts.book_index(hist, twr, window),
                         base="EUR", convert=convert)
    assert chart is not None and chart.window == "1m" and chart.rebased
    book, index, pair = chart.lines
    assert book.index and book.currency == "EUR"
    # The index is drawn in euros; an exchange rate is left as it is.
    assert converted == [("USD", "EUR")]
    assert (index.currency, index.converted) == ("EUR", "USD")
    assert (pair.currency, pair.converted) == ("USD", "")
    assert index.first_on >= book.first_on and pair.first_on >= book.first_on
    text = chart.line()
    assert "time-weighted return in EUR" in text
    assert "converted from USD" in text and "price only" in text


def test_without_a_ledger_the_book_drops_out_like_a_symbol_without_prices():
    chart = charts.build([charts.BOOK, "AAPL"], "1y", closes=lambda *_: _closes(),
                         currency=lambda _s: "USD")
    assert chart is not None and chart.symbols == ["AAPL"]
    assert charts.build([charts.BOOK], "1y", book=lambda _w: None) is None


def test_the_book_s_surface_names_it_and_draws_no_ticker_for_it():
    hist, twr = _twr()
    chart = charts.build([charts.BOOK, "^GSPC"], "1y",
                         closes=lambda *_: hist["value"].astype(float) + 1,
                         currency=lambda _s: "USD",
                         book=lambda window: charts.book_index(hist, twr, window),
                         base="EUR", convert=lambda c, *_: c)
    messages = charts.surface(chart, _say)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert [parts[i]["symbol"] for i in parts["head"]["children"][:-1]] == ["^GSPC"]
    assert parts["f0"]["label"] == "chat.chart_book"
    assert parts["plot"]["mode"] == "change"
    assert parts["note"]["text"].startswith("chat.chart_note_book")
    data = messages[2]["updateDataModel"]["value"]
    assert data["chart"][0]["index"] and data["chart"][0]["label"] == "chat.chart_book"
    assert "index" not in data["chart"][1]
    assert data["view"]["title"].startswith("chat.chart_title_book_vs")
    assert parts["windows"]["action"]["event"]["context"]["symbols"] == [
        charts.BOOK, "^GSPC"]


@pytest.mark.parametrize(("message", "window"), [
    ("gráfico del euro dólar", "1y"),
    ("grafico de NVDA de los últimos 5 años", "5y"),
    ("NVDA chart over the past 6 months", "6m"),
    ("gráfico de AAPL este año", "ytd"),
    ("chart of MSFT in 2026", "ytd"),
    ("grafico de SAN.MC del último mes", "1m"),
    ("gráfico de TSLA de hoy", "1d"),
    ("gráfico de AMZN desde su salida a bolsa", "max"),
])
def test_the_window_is_the_one_the_message_names(message, window):
    assert charts.window_asked(message, today=date(2026, 10, 2)) == window


def _closes(n: int = 600, start: float = 1.05) -> pd.Series:
    days = pd.bdate_range("2024-01-01", periods=n)
    values = [start + 0.0005 * i for i in range(n)]
    values[123] = 0.9  # the low, off the even spread of sampled points
    values[457] = 1.6  # the high
    return pd.Series(values, index=days)


def test_a_chart_keeps_the_figures_it_quotes_however_thin_its_line():
    chart = charts.build(["EURUSD=X"], "2y", closes=lambda *_: _closes(),
                         currency=lambda _s: "USD")
    assert chart is not None
    (line,) = chart.lines
    assert len(line.values) <= charts.MAX_POINTS + 2
    assert (line.low, line.high) == (0.9, 1.6)
    assert 0.9 in line.values and 1.6 in line.values
    assert line.dates[0] == line.first_on and line.dates[-1] == line.last_on
    assert line.sessions == 600


def test_the_prompt_carries_the_figures_and_forbids_a_drawn_chart():
    chart = charts.build(["EURUSD=X"], "1y", closes=lambda *_: _closes(),
                         currency=lambda _s: "USD")
    text = chart.line()
    assert "draws a price chart" in text
    assert "no ASCII art" in text
    assert "EURUSD=X: 1.0500 USD" in text
    assert "high 1.6000" in text and "low 0.9000" in text


def test_a_symbol_without_prices_drops_out_and_none_at_all_is_no_chart():
    def closes(symbol: str, _window: str):
        if symbol == "BAD":
            raise RuntimeError("Yahoo said no")
        return None if symbol == "EMPTY" else _closes()

    chart = charts.build(["AAPL", "BAD", "EMPTY"], "1y", closes=closes,
                         currency=lambda _s: "")
    assert chart is not None and chart.symbols == ["AAPL"]
    assert charts.build(["BAD"], "1y", closes=closes, currency=lambda _s: "") is None


def test_one_line_is_a_price_chart_and_several_a_change_chart():
    one = charts.build(["AAPL"], "1y", closes=lambda *_: _closes(),
                       currency=lambda _s: "")
    two = charts.build(["AAPL", "MSFT"], "1y", closes=lambda *_: _closes(),
                       currency=lambda _s: "")
    for chart, mode in ((one, "price"), (two, "change")):
        messages = charts.surface(chart, _say)
        a2ui.check(messages)
        parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
        assert parts["plot"]["mode"] == mode
        picker = parts["windows"]
        assert picker["variant"] == "chips"
        assert picker["action"]["event"]["name"] == charts.ACTION
        assert picker["action"]["event"]["context"]["symbols"] == chart.symbols
        data = messages[2]["updateDataModel"]["value"]
        assert data["window"] == "1y"
        assert [s["symbol"] for s in data["chart"]] == chart.symbols


def test_another_window_is_the_same_surface_s_data_again():
    chart = charts.build(["AAPL"], "5y", closes=lambda *_: _closes(),
                         currency=lambda _s: "USD")
    moved = charts.moved(chart, _say)
    assert {m["updateDataModel"]["path"] for m in moved} == {"/chart", "/view", "/window"}
    assert all(m["updateDataModel"]["surfaceId"] == charts.SURFACE_ID for m in moved)
    window = next(m for m in moved if m["updateDataModel"]["path"] == "/window")
    assert window["updateDataModel"]["value"] == "5y"


def test_every_window_a_chip_offers_is_one_the_server_fetches():
    assert set(charts.CHIPS) <= set(charts.WINDOWS)
    assert charts.DEFAULT in charts.CHIPS
