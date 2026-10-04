"""A routine's recipe (stocks.chat.routine_plan) and the data it fetches
(stocks.chat.daily_routines).

What is tested is what a recipe promises:

* the words alone already say the obvious ("la bolsa" is the main indices,
  "resultados" is company results), so a card with no model still fetches
  for them;
* a model works the recipe out once per wording and it is kept on the
  routine; its vocabulary is checked, and the rules widen it, never narrow;
* a routine reworded since is planned again, and a model that did not answer
  is asked again the next day, not on every card;
* the brief's facts carry the market quotes, the results and the sources
  (events, insiders, exits) the recipe asks for, and a model line quoting
  them passes the audit.

Pure: no network, no clock.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pytest

from stocks.chat import daily, daily_routines, learnings, market, routine_plan
from stocks.data.earnings import EarningsEvent, EarningsResult

TODAY = date(2026, 10, 5)  # a Monday


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setattr("stocks.storage.persist", lambda p: None)
    return tmp_path / "chat.json"


def routine(text: str, rid: str = "r1", tickers=(), recipe=None) -> learnings.Learning:
    return learnings.Learning(rid, text, kind="routine", tickers=tuple(tickers),
                              recipe=recipe or {})


# ------------------------------------------------------------------ rules


@pytest.mark.parametrize(("text", "markets", "earnings"), [
    ("Cada día mírame los indicadores principales de la bolsa", ("core",), ""),
    ("Every morning tell me how the stock market closed", ("core",), ""),
    ("Dime cada mañana cómo ha ido el Ibex", ("spain",), ""),
    ("Cada día dime cómo van la bolsa y el dólar", ("core", "rates"), ""),
    ("Cada mañana cómo van el oro y el bitcoin", ("commodities", "crypto"), ""),
    ("Avísame cada día de los resultados publicados por las empresas", (), "large"),
    ("Cada día dime los resultados de mis empresas", (), "book"),
    ("Every day, who reported earnings", (), "book"),
    ("Cada día dime cómo va mi cartera", (), ""),
])
def test_the_words_say_the_obvious(text, markets, earnings):
    recipe = routine_plan.rules(text)
    assert (recipe.markets, recipe.earnings, recipe.by) == (markets, earnings, "rules")


@pytest.mark.parametrize(("text", "topics"), [
    ("Eventos importantes de la próxima semana", ("events",)),
    ("Qué hacen los insiders de mis empresas", ("insiders",)),
    ("Revisa mis criterios de salida y kill criteria", ("exits",)),
    ("Agenda de la semana, directivos y mis alertas", ("events", "insiders", "exits")),
    ("Cada día dime cómo va mi cartera", ()),
    # A horizon, not a deadline.
    ("Una propuesta a largo plazo: vender o reforzar", ()),
    ("Los plazos de Hacienda de este mes", ("events",)),
    ("Las noticias de Yahoo Finance sobre mis empresas", ("news",)),
    ("Los 8-K y hechos relevantes en la SEC", ("filings",)),
    ("Hacia dónde se mueve el dinero de los grandes inversores", ("holders",)),
    ("News, 8-K filings and what the big investors did", ("news", "filings", "holders")),
    # Owning funds is not asking who holds the companies.
    ("Cómo van mis fondos indexados", ()),
    # Share prices, not shareholders.
    ("Los precios medios de mis acciones", ()),
])
def test_the_words_name_the_sources(text, topics):
    assert routine_plan.rules(text).topics == topics


def test_results_of_named_companies_are_theirs():
    recipe = routine_plan.rules("cada día resultados de NVDA", ("NVDA",))
    assert recipe.earnings == "named"


def test_the_groups_are_quoted_once_each():
    recipe = routine_plan.Recipe(markets=("core", "us", "rates"))
    symbols = [s for s, _ in recipe.market_quotes()]
    assert symbols[:3] == ["^GSPC", "^IXIC", "^STOXX50E"]
    assert len(symbols) == len(set(symbols)) <= routine_plan.MAX_MARKET_QUOTES


# ---------------------------------------------------------------- current


def test_a_model_recipe_is_used_for_the_words_it_was_planned_for():
    text = "Cada día cómo va el oro"
    kept = routine_plan.Recipe(symbols=("GC=F",), by="model").as_dict(text)
    assert routine_plan.current(routine(text, recipe=kept)).symbols == ("GC=F",)
    reworded = routine("Cada día cómo va la plata", recipe=kept)
    assert routine_plan.current(reworded).by == "rules"


def test_a_routine_is_planned_until_a_model_has_planned_it_or_tried_today():
    text = "Cada día cómo va el oro"
    v = routine_plan.RECIPE_VERSION
    model = routine(text, recipe={"by": "model", "wording": text, "v": v})
    tried_today = routine(text, "r2", recipe={"by": "rules", "wording": text,
                                              "tried": TODAY.isoformat()})
    tried_before = routine(text, "r3", recipe={"by": "rules", "wording": text,
                                               "tried": "2026-10-04"})
    reworded = routine("Cada día cómo va la plata", "r4",
                       recipe={"by": "model", "wording": text, "v": v})
    fresh = routine(text, "r5")
    # Planned before the recipe knew about topics: planned again.
    older = routine(text, "r6", recipe={"by": "model", "wording": text})
    every = [model, tried_today, tried_before, reworded, fresh, older]
    wanted = routine_plan.stale(every, TODAY)
    assert [r.id for r in wanted] == ["r3", "r4", "r5", "r6"]


# ------------------------------------------------------------------- plan


def test_a_plan_keeps_only_the_vocabulary():
    raw = json.dumps({"plans": [
        {"id": "r1", "markets": ["core", "mars"], "earnings": "everything",
         "symbols": ["gc=f", "not a symbol", "^IBEX", "GC=F"],
         "topics": ["exits", "gossip", "events"]},
        {"id": "ghost", "markets": ["us"]},
    ]})
    got = routine_plan.parse_plans(raw, {"r1"})
    assert got == {"r1": routine_plan.Recipe(
        markets=("core",), earnings="", symbols=("GC=F", "^IBEX"),
        topics=("events", "exits"), by="model")}
    assert routine_plan.parse_plans("no idea", {"r1"}) is None


def test_the_rules_widen_the_model_s_plan(monkeypatch):
    reply = json.dumps(
        {"plans": [{"id": "r1", "markets": ["spain"], "earnings": "none"}]})
    monkeypatch.setattr(routine_plan.engine, "complete_attempts",
                        lambda *a, accept, **k: accept(reply))
    got = routine_plan.plan(
        {}, [routine("Cada día el Ibex, los resultados de mis empresas y los insiders")],
        spend_free=lambda p: True)
    assert got["r1"] == routine_plan.Recipe(markets=("spain",), earnings="book",
                                            topics=("insiders",), by="model")


def test_ensure_keeps_the_recipe_on_the_routine(chat, monkeypatch):
    path = learnings.path_for(chat)
    item, _ = learnings.add(path, "Cada día cómo va el oro", kind="routine")
    reply = json.dumps({"plans": [{"id": item.id, "symbols": ["GC=F"]}]})
    monkeypatch.setattr(routine_plan.engine, "complete_attempts",
                        lambda *a, accept, **k: accept(reply))
    got = routine_plan.ensure({}, chat, learnings.load(path), TODAY,
                              spend_free=lambda p: True)
    assert routine_plan.current(got[0]).symbols == ("GC=F",)
    kept = learnings.load(path)[0]
    assert kept.recipe["by"] == "model" and kept.recipe["wording"] == item.text
    # Planned once: the next card asks no model.
    monkeypatch.setattr(routine_plan.engine, "complete_attempts",
                        lambda *a, **k: pytest.fail("planned twice"))
    routine_plan.ensure({}, chat, learnings.load(path), TODAY, spend_free=lambda p: True)


def test_no_model_marks_the_day_tried_and_the_rules_stand_in(chat, monkeypatch):
    path = learnings.path_for(chat)
    learnings.add(path, "Cada día los indicadores de la bolsa", kind="routine")
    monkeypatch.setattr(routine_plan.engine, "complete_attempts", lambda *a, **k: None)
    got = routine_plan.ensure({}, chat, learnings.load(path), TODAY,
                              spend_free=lambda p: True)
    assert routine_plan.current(got[0]).markets == ("core",)
    assert learnings.load(path)[0].recipe["tried"] == TODAY.isoformat()
    assert routine_plan.stale(learnings.load(path), TODAY) == []


def test_a_recipe_for_words_since_changed_is_not_kept(chat):
    path = learnings.path_for(chat)
    item, _ = learnings.add(path, "Cada día cómo va el oro", kind="routine")
    learnings.edit(path, item.id, text="Cada día cómo va la plata")
    assert not learnings.set_recipe(path, item.id, item.text, {"by": "model"})
    assert learnings.load(path)[0].recipe == {}


def test_a_routine_without_a_recipe_is_stored_as_before(chat):
    path = learnings.path_for(chat)
    learnings.add(path, "Cada día cómo va el oro", kind="routine")
    assert "recipe" not in json.loads(path.read_text())["items"][0]


# ------------------------------------------------------------------ fetch


def _quotes(names, **_):
    return [market.Quote(n, price=100.0, currency="USD", prev_close=98.0) for n in names]


def test_a_market_routine_fetches_the_indices_by_name(monkeypatch):
    monkeypatch.setattr(market, "quotes", _quotes)
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None:
                        [t for t in [lookup("Bolsa")] if t])
    fact, _ = daily_routines.gather(
        [routine("Cada día los indicadores principales de la Bolsa")],
        watchlist=None, db=None, base="EUR", lookup=lambda name: "BOLSA.MX", day=TODAY)
    assert "quotes" not in fact  # "Bolsa" was not looked up as a company
    assert [m["name"] for m in fact["markets"]] == [
        "S&P 500", "Nasdaq Composite", "Euro Stoxx 50", "VIX"]
    assert fact["markets"][0]["change_pct"] == 2.04


def _calendar(names):
    upcoming = [EarningsEvent("NVDA", date(2026, 10, 8), 3),
                EarningsEvent("AAPL", date(2026, 10, 30), 25)]
    printed = [EarningsResult("ASML.AS", date(2026, 10, 2), eps_estimate=5.0,
                              reported_eps=5.5, surprise_pct=10.0),
               EarningsResult("MSFT", date(2026, 9, 20), reported_eps=3.0)]
    return upcoming, printed


def test_a_results_routine_carries_the_week_s_prints(monkeypatch):
    monkeypatch.setattr(market, "quotes", _quotes)
    asked = []

    def calendar(names):
        asked.append(names)
        return _calendar(names)

    got = daily_routines.earnings_fact(
        "book", ["NVDA", "ASML.AS"], ("NVDA", "ASML.AS"), day=TODAY, calendar=calendar)
    assert asked == [("ASML.AS", "NVDA")]
    assert got["reported"] == [{
        "ticker": "ASML.AS", "date": "2026-10-02", "days_ago": 3, "mine": True,
        "reported_eps": 5.5, "eps_estimate": 5.0, "surprise_pct": 10.0,
        "beat": True, "change_pct": 2.04,
    }]
    assert got["upcoming"] == [
        {"ticker": "NVDA", "date": "2026-10-08", "in_days": 3, "mine": True}]


def test_results_in_general_take_the_large_caps_and_the_reader_s_own():
    names = daily_routines._scope_names("large", [], ("SAN.MC",))
    assert names[0] == "SAN.MC" and "NVDA" in names
    assert daily_routines._scope_names("book", [], ()) == list(routine_plan.LARGE)
    assert daily_routines._scope_names("named", ["NVDA"], ("SAN.MC",)) == ["NVDA"]


def test_gather_reads_the_kept_recipe(monkeypatch):
    monkeypatch.setattr(market, "quotes", _quotes)
    monkeypatch.setattr(market, "mentioned", lambda text, known, lookup=None: [])
    text = "Cada día dime cómo va el oro"
    kept = routine_plan.Recipe(symbols=("GC=F",), by="model").as_dict(text)
    facts, _ = daily_routines.gather([routine(text, recipe=kept)], watchlist=None,
                                     db=None, base="EUR", lookup=lambda n: "", day=TODAY)
    assert [q["ticker"] for q in facts["quotes"]] == ["GC=F"]
    assert "markets" not in facts  # the kept plan stands: widened when made


# ----------------------------------------------------------------- answer


def test_a_model_line_quoting_an_index_and_a_print_passes_the_audit():
    brief = {
        "asks": [{"n": 1, "ask": "how did the market and my results go"}],
        "markets": [{"ticker": "^GSPC", "name": "S&P 500", "price": 5800.25,
                     "currency": "USD", "change_pct": 0.5}],
        "earnings": {"scope": "book", "reported": [
            {"ticker": "ASML.AS", "date": "2026-10-02", "reported_eps": 5.5,
             "eps_estimate": 5.0, "surprise_pct": 10.0}], "upcoming": []},
    }
    facts = {"date": TODAY.isoformat(), "currency": "EUR", "brief": brief}
    good = "S&P 500 up 0.5% at 5,800.25; ASML beat with EPS 5.50 vs 5.00 (+10%)."
    bad = "S&P 500 up 0.9% at 5,812.00."

    def card(line):
        raw = json.dumps({"headline": "Markets up", "sections": [
            {"asks": [1], "title": "Markets", "lines": [{"line": line}]}]})
        return daily.parse(raw, day=TODAY, lang="en", facts=facts)

    assert card(good).sections[0]["lines"][0]["line"] == good
    assert card(bad) is None  # its one line went, and with it the only section


def test_recipes_do_not_change_what_a_learning_is():
    a = routine("Cada día cómo va el oro")
    assert a == replace(a, recipe={"by": "model"})


# -------------------------------------------------------------- templates

_TEMPLATES = {
    "moves": ((), "", ()),
    "events": ((), "", ("events",)),
    "results": ((), "book", ()),
    "insiders": ((), "", ("insiders",)),
    "news": ((), "", ("news",)),
    "filings": ((), "", ("filings",)),
    "holders": ((), "", ("holders",)),
    "exits": ((), "", ("exits",)),
    "proposal": ((), "", ()),
    "indices": (("core",), "", ()),
    "macro": (("rates", "commodities"), "", ()),
}


@pytest.mark.parametrize("lang", ["en", "es"])
@pytest.mark.parametrize(("tpl", "want"), list(_TEMPLATES.items()))
def test_every_template_asks_for_what_its_chip_says_with_no_model(lang, tpl, want):
    from pathlib import Path

    catalog = json.loads((Path(__file__).resolve().parents[1] / "src" / "stocks" / "web"
                          / "locales" / lang / "home.json").read_text(encoding="utf-8"))
    recipe = routine_plan.rules(catalog[f"home.routine_tpl_{tpl}_text"])
    assert (recipe.markets, recipe.earnings, recipe.topics) == want
