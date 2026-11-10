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
    # The verb with its pronoun, as a Spanish reader types it in a hurry.
    "grafícame NVDA",
    "gráficalo",
    "haz un grafico de la tendencia de apple",
])
def test_a_request_for_a_chart_is_heard(message):
    assert charts.wants(message)


def test_a_lower_case_name_behind_a_describing_word_is_still_looked_up():
    """"gráfico de la tendencia de apple": the first word after "de" says
    what to draw, not whom, and the name comes after it. Skipped, not
    searched — the one lookup is spent on the name."""
    asked: list[str] = []

    def lookup(name: str) -> str:
        asked.append(name)
        return "AAPL" if name.lower() == "apple" else ""

    assert charts.targets("haz un grafico de la tendencia de apple", {}, "",
                          lookup=lookup) == ["AAPL"]
    assert asked == ["apple"]
    # A prediction names nothing to draw: no lookup for "prediccion".
    asked.clear()
    assert charts.targets("haz un grafico de prediccion de valor de cartera",
                          {}, "", lookup=lookup) == []
    assert asked == []


def test_the_drawer_is_told_it_draws_and_what_it_cannot():
    """The sentence a drawing surface adds to the prompt: a small model asked
    for a chart otherwise says it cannot draw one, which is false there, and
    a projection is the one chart request that stays undrawn."""
    assert "never say you cannot draw or show charts" in charts.PROMPT
    assert "Projection tab" in charts.PROMPT


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


@pytest.mark.parametrize("message", [
    "create a chart of rentability",
    "chart of returns",
    "gráfico de rentabilidad",
    "hazme un gráfico del rendimiento",
])
def test_a_chart_of_returns_with_nothing_named_is_the_book_s(message):
    # Asked in the drawer with no ticker in focus, "returns" are the reader's:
    # read as a company name, the word found nothing and no chart was drawn.
    assert charts.wants(message)
    assert charts.targets(message, {}, "", lookup=_no_lookup) == [charts.BOOK]


def test_a_chart_of_returns_names_a_ticker_or_the_page_before_the_book():
    assert charts.targets("chart of AAPL returns", {}, "",
                          lookup=_no_lookup) == ["AAPL"]
    assert charts.targets("gráfico de rentabilidad", {}, "NVDA",
                          lookup=_no_lookup) == ["NVDA"]


@pytest.mark.parametrize("message", ["¿cómo voy?", "¿cómo va mi cartera?"])
def test_a_book_question_with_nothing_to_measure_it_by_draws_nothing(message):
    assert not charts.wants(message)


def _book(n: int = 1300, late: int = 1200, step: float = 0.0005):
    """A book that only ever held one index: ten units on its first day, ninety
    more on day `late`. Returns (book, the index's closes)."""
    days = pd.bdate_range("2021-01-04", periods=n)
    price = pd.Series([100 * (1 + step) ** i for i in range(n)], index=days)
    units = pd.Series([10.0 if i < late else 100.0 for i in range(n)], index=days)
    flows = pd.Series([10 * price.iloc[0], 90 * price.iloc[late]],
                      index=[days[0], days[late]])
    return charts.Book(units * price, flows), price


def test_the_book_s_days_open_on_the_close_before_the_window():
    book, _ = _book(n=400, late=300)
    days = charts.book_days(book.value, "ytd", today=date(2022, 6, 1))
    assert days[0] == pd.Timestamp("2021-12-31") and days[-1] == book.value.index[-1]
    six = charts.book_days(book.value, "6m")
    cut = book.value.index[-1] - pd.Timedelta(days=182)
    assert six[0] == book.value.index[book.value.index <= cut][-1]
    # Never before the first day anything was held.
    late = pd.concat([pd.Series(0.0, index=pd.bdate_range("2020-06-01", "2020-12-31")),
                      book.value])
    assert charts.book_days(late, "max")[0] == book.value.index[0]
    assert charts.book_days(pd.Series(dtype=float), "1y").empty


def test_against_an_index_the_book_reads_what_its_money_made_as_asignacion_does():
    """"Compárame con el S&P a 5 años": a book that held nothing but the index
    and put nine tenths of its money in near the end made a tenth of what the
    index's price did. The index fed the same buys reads the same as the book;
    rebased to the window's first day it read +91 %, all of today's money at
    work from five years back."""
    book, price = _book()
    chart = charts.build([charts.BOOK, "^GSPC"], "5y",
                         closes=lambda *_: price, currency=lambda _s: "EUR",
                         book=lambda: book, base="EUR")
    assert chart is not None
    mine, index = chart.lines
    assert mine.index and index.fed and not index.index
    invested = book.flows.sum()
    made = book.value.iloc[-1] / invested - 1
    assert mine.change == pytest.approx(made)
    assert index.change == pytest.approx(made)
    assert price.iloc[-1] / price.iloc[0] - 1 > made + 0.5
    text = chart.line()
    assert "the return on the money put in" in text
    assert "^GSPC fed the same buys and sales on the same days" in text
    assert "price only" in text and "time-weighted" not in text


def test_against_the_book_a_benchmark_is_in_its_currency_and_never_intraday():
    book, price = _book(n=400, late=300)
    converted: list[tuple[str, str]] = []

    def convert(closes, unit, base):
        converted.append((unit, base))
        return closes * 0.5

    def closes(symbol, window):
        assert window == "1m"  # a session of the book is one point: never 1d
        return price

    chart = charts.build([charts.BOOK, "^GSPC", "EURUSD=X"], "1d",
                         closes=closes, currency=lambda _s: "USD",
                         book=lambda: book, base="EUR", convert=convert)
    assert chart is not None and chart.window == "1m" and chart.rebased
    mine, index, pair = chart.lines
    assert mine.index and mine.currency == "EUR"
    # The index is drawn in euros; an exchange rate is left as it is.
    assert converted == [("USD", "EUR")]
    assert (index.currency, index.converted) == ("EUR", "USD")
    assert (pair.currency, pair.converted) == ("USD", "")
    assert index.first_on == mine.first_on == pair.first_on
    assert "converted from USD" in chart.line()


def test_a_converted_benchmark_carries_its_own_currency_s_change_and_the_fx_effect():
    """"¿Bato al S&P?" from Spain: the index is drawn in euros, and the
    currency's part of its move is worked out here, not guessed by the model
    (it once said 5.3 % for a 5.6 % dollar slide)."""
    book, price = _book(n=400, late=300)
    n = len(price)
    rate = pd.Series([1.0 - 0.1 * i / (n - 1) for i in range(n)], index=price.index)

    chart = charts.build(
        [charts.BOOK, "^GSPC"], "max", closes=lambda *_: price,
        currency=lambda _s: "USD", book=lambda: book,
        base="EUR", convert=lambda closes, unit, base: closes * rate)
    _mine, index = chart.lines
    assert index.converted == "USD"
    # In dollars it is the book's own race, the book having held it.
    assert index.own_change == pytest.approx(book.value.iloc[-1] / book.flows.sum() - 1)
    assert index.change < index.own_change
    effect = (1 + index.change) / (1 + index.own_change) - 1
    assert f"the currency effect is {effect:+.2%}" in chart.line()
    assert f"{index.own_change:+.2%} in USD" in chart.line()


def test_a_benchmark_that_opens_late_races_from_its_own_first_day():
    book, price = _book(n=400, late=300)
    young = price[price.index >= price.index[200]]
    chart = charts.build([charts.BOOK, "BTC-EUR"], "max",
                         closes=lambda *_: young, currency=lambda _s: "EUR",
                         book=lambda: book, base="EUR")
    mine, coin = chart.lines
    assert coin.first_on == str(young.index[0].date()) > mine.first_on
    assert coin.first == pytest.approx(100.0)


def test_without_a_ledger_the_book_drops_out_like_a_symbol_without_prices():
    chart = charts.build([charts.BOOK, "AAPL"], "1y", closes=lambda *_: _closes(),
                         currency=lambda _s: "USD")
    assert chart is not None and chart.symbols == ["AAPL"]
    assert charts.build([charts.BOOK], "1y", book=lambda: None) is None


def test_the_book_s_surface_names_it_and_draws_no_ticker_for_it():
    book, price = _book(n=400, late=300)
    chart = charts.build([charts.BOOK, "^GSPC"], "1y",
                         closes=lambda *_: price, currency=lambda _s: "USD",
                         book=lambda: book, base="EUR", convert=lambda c, *_: c)
    messages = charts.surface(chart, _say)
    a2ui.check(messages)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert [parts[i]["symbol"] for i in parts["head"]["children"][:-1]] == ["^GSPC"]
    assert parts["f0"]["label"] == "chat.chart_book"
    assert parts["plot"]["mode"] == "change"
    assert parts["note"]["text"].startswith("chat.chart_note_book")
    data = messages[2]["updateDataModel"]["value"]
    assert data["chart"][0]["index"] and data["chart"][0]["label"] == "chat.chart_book"
    # Raced against the book, the index is an index too: no price to print.
    assert data["chart"][1]["index"] and data["chart"][1]["label"] == "S&P 500"
    assert data["view"]["m1"]["last"].startswith("chat.chart_fed_hint")
    assert data["view"]["title"].startswith("chat.chart_title_book_vs")
    assert parts["windows"]["action"]["event"]["context"]["symbols"] == [
        charts.BOOK, "^GSPC"]


def test_an_index_is_drawn_by_its_name_and_a_share_by_its_ticker():
    chart = charts.build(["^GSPC", "^IXIC", "AAPL"], "1y",
                         closes=lambda *_: _closes(), currency=lambda _s: "USD")
    messages = charts.surface(chart, _say)
    parts = {c["id"]: c for c in messages[1]["updateComponents"]["components"]}
    assert [parts[f"f{i}"]["label"] for i in range(3)] == [
        "S&P 500", "Nasdaq Composite", "AAPL"]
    lines = messages[2]["updateDataModel"]["value"]["chart"]
    assert [ln.get("label") for ln in lines] == ["S&P 500", "Nasdaq Composite", None]
    # The header keeps the symbols: the Ticker cell prints the name beside it.
    assert [parts[i]["symbol"] for i in parts["head"]["children"][:-1]] == [
        "^GSPC", "^IXIC", "AAPL"]


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


def test_the_figures_over_the_line_read_in_the_reader_s_language():
    values = pd.Series([6_607.0, 6_923.48],
                       index=pd.bdate_range("2026-10-01", periods=2))
    chart = charts.build(["^GSPC"], "1m", closes=lambda *_: values,
                         currency=lambda _s: "EUR")
    es = charts.view(chart, _say, "es")["m0"]
    assert es["last"] == "6.923,48 EUR"
    assert es["change"] == "+4,79%"
    assert es["range"] == "6.607,00 – 6.923,48"
    en = charts.view(chart, _say)["m0"]
    assert (en["last"], en["change"]) == ("6,923.48 EUR", "+4.79%")
    moved = charts.moved(chart, _say, "es")
    view = next(m for m in moved if m["updateDataModel"]["path"] == "/view")
    assert view["updateDataModel"]["value"]["m0"]["change"] == "+4,79%"
