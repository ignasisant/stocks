"""What each daily routine needs fetched: its recipe.

A routine is the reader's own question, in their own words ("mírame los
indicadores principales de la bolsa", "avísame de los resultados que publiquen
las empresas"). Answering it on the daily card takes data, and most routines
name no ticker at all: the words have to be turned into fetches first. That
is the recipe, drawn from a closed catalog:

- `markets`: groups of market quotes (MARKETS) — the main indices, rates and
  currencies, commodities, crypto.
- `earnings`: company results, reported in the last few days and coming up,
  for a scope (SCOPES) — the reader's own names, the ones the routine names,
  or a fixed list of large caps.
- `symbols`: specific instruments the routine names in words ("el oro",
  "el Ibex", "Nvidia"), as Yahoo spells them.
- `topics`: the reader's own book seen from one more side (TOPICS) — what is
  coming up this week, what its insiders traded, the exit levels and
  criteria the reader set, the press's headlines, the companies' 8-Ks, and
  which way the big investors moved.

A model works the recipe out once per wording (`plan`, PlanRoutines in
baml_src/briefing.baml) and it is kept on the routine (`learnings.set_recipe`),
so the card's daily cost stays one call. When no model answers, keyword rules
(`rules`) stand in for that card and the model is asked again the next day.
Either way the recipe is only ever a list of fetches: the vocabulary is
checked here, and a symbol becomes a quote lookup, nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from stocks import obs
from stocks.chat import engine, learnings, structured

# The groups a routine can ask to be quoted, each a short fixed list so the
# card's fetch stays bounded. "core" is what "the market" means when the
# routine says nothing narrower.
MARKETS: dict[str, tuple[tuple[str, str], ...]] = {
    "core": (("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq Composite"),
             ("^STOXX50E", "Euro Stoxx 50"), ("^VIX", "VIX")),
    "us": (("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq Composite"),
           ("^DJI", "Dow Jones")),
    "europe": (("^STOXX50E", "Euro Stoxx 50"), ("^GDAXI", "DAX"),
               ("^FCHI", "CAC 40")),
    "spain": (("^IBEX", "IBEX 35"),),
    "asia": (("^N225", "Nikkei 225"), ("^HSI", "Hang Seng")),
    "rates": (("^TNX", "US 10-year yield"), ("EURUSD=X", "EUR/USD"),
              ("^VIX", "VIX")),
    "commodities": (("GC=F", "Gold"), ("BZ=F", "Brent crude")),
    "crypto": (("BTC-USD", "Bitcoin"), ("ETH-USD", "Ether")),
}
MAX_MARKET_QUOTES = 10

# Whose results: the reader's own (held and followed), the names the routine
# itself gives, or LARGE (and the reader's own besides) when it asks about
# "the companies" in general.
SCOPES = ("book", "named", "large")
LARGE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM",
    "V", "LLY", "WMT", "NFLX", "ORCL", "ASML.AS", "SAP.DE", "MC.PA",
    "NOVO-B.CO", "SAN.MC", "ITX.MC",
)

# The book from one more side each, fetched for the reader's own names only:
# events = the next week's results, ex-dividend dates, central-bank decisions
# and tax deadlines; insiders = open-market trades by each company's insiders
# (SEC Form 4, BaFin for German issuers); exits = the reader's price alerts and
# the decisions and goals they saved about their positions, the closest thing
# the app keeps to kill criteria; news = the last days' headlines naming the
# companies; filings = the 8-Ks they filed this week; holders = the big funds
# holding them and how much each added or cut last quarter (13F).
TOPICS = ("events", "insiders", "exits", "news", "filings", "holders")

MAX_SYMBOLS = 5
PLAN_TIMEOUT_S = 12.0
# Bumped when the vocabulary grows: a recipe a model planned under an older
# one is planned again once, so the new parts reach routines already saved.
RECIPE_VERSION = 3
_SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-]{0,11}(?:=[XF])?$")


@dataclass(frozen=True)
class Recipe:
    """What one routine's answer is fetched from. `by` is "model" or
    "rules"; an empty recipe still answers with the routine's own tickers
    and chart (`daily_routines`)."""

    markets: tuple[str, ...] = ()
    earnings: str = ""
    symbols: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    by: str = "rules"

    def market_quotes(self) -> list[tuple[str, str]]:
        """(symbol, name) for every group asked, each symbol once."""
        out: dict[str, str] = {}
        for group in self.markets:
            for symbol, name in MARKETS.get(group, ()):
                out.setdefault(symbol, name)
        return list(out.items())[:MAX_MARKET_QUOTES]

    def as_dict(self, wording: str) -> dict:
        return {"markets": list(self.markets), "earnings": self.earnings,
                "symbols": list(self.symbols), "topics": list(self.topics),
                "by": self.by, "wording": wording, "v": RECIPE_VERSION}

    def widened(self, other: Recipe) -> Recipe:
        """This recipe with whatever `other` asks for besides — never less."""
        return replace(
            self,
            markets=tuple(dict.fromkeys((*self.markets, *other.markets))),
            earnings=self.earnings or other.earnings,
            symbols=tuple(dict.fromkeys((*self.symbols, *other.symbols)))[:MAX_SYMBOLS],
            topics=tuple(t for t in TOPICS if t in (*self.topics, *other.topics)),
        )


def _groups(raw) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        g for g in (str(x).strip().lower() for x in raw or ()) if g in MARKETS))


def _symbols(raw) -> tuple[str, ...]:
    out = []
    for item in raw or ():
        symbol = str(item or "").strip().upper()
        if _SYMBOL_RE.match(symbol) and symbol not in out:
            out.append(symbol)
    return tuple(out[:MAX_SYMBOLS])


def _topics(raw) -> tuple[str, ...]:
    asked = {str(x).strip().lower() for x in raw or ()}
    return tuple(t for t in TOPICS if t in asked)


def _scope(raw) -> str:
    scope = str(raw or "").strip().lower()
    return scope if scope in SCOPES else ""


def _from_dict(raw: dict) -> Recipe:
    return Recipe(markets=_groups(raw.get("markets")),
                  earnings=_scope(raw.get("earnings")),
                  symbols=_symbols(raw.get("symbols")),
                  topics=_topics(raw.get("topics")),
                  by="model" if raw.get("by") == "model" else "rules")


# -------------------------------------------------------------------- rules
# Matched on folded text (`learnings._fold`: lower-case, no accents, no
# punctuation). Only the obvious: the model is what reads the rest.

_MARKET_RE = re.compile(
    r"\b(?:indices?|indicadores|bolsas?|mercados?|wall street|parqu[eé]|"
    r"markets?|stock market|indexes|benchmarks?)\b")
_REGION_RES = (
    ("us", re.compile(r"\b(?:eeuu|estados unidos|usa|americ\w*|wall street|"
                      r"nasdaq|dow jones|dow|s p 500|s p)\b")),
    ("europe", re.compile(r"\b(?:europ\w*|euro stoxx|eurostoxx|dax|cac)\b")),
    ("spain", re.compile(r"\b(?:espana|espanola?|spain|spanish|ibex)\b")),
    ("asia", re.compile(r"\b(?:asia\w*|japon|japan|nikkei|china|hong kong)\b")),
    ("rates", re.compile(r"\b(?:divisas?|dolar|tipos|bonos?|yields?|vix|"
                         r"volatilidad|volatility|currenc\w*|fx|rates|bonds?|"
                         r"treasur\w*)\b")),
    ("commodities", re.compile(r"\b(?:oro|gold|petroleo|brent|oil|crudo|"
                               r"materias primas|commodit\w*)\b")),
    ("crypto", re.compile(r"\b(?:bitcoin|btc|cripto\w*|crypto\w*|ether\w*)\b")),
)
_EARNINGS_RE = re.compile(
    r"\b(?:resultados|earnings|trimestrales|cuentas trimestrales|bpa|eps|"
    r"presenta\w* (?:sus )?(?:resultados|cuentas)|publica\w* (?:sus )?"
    r"(?:resultados|cuentas)|quarterly (?:results|reports?)|results|reports?|"
    r"reported)\b")
_MINE_RE = re.compile(
    r"\b(?:mis|mi cartera|mis acciones|que tengo|que sigo|mi watchlist|"
    r"my|portfolio|i hold|i follow|watchlist)\b")
_TOPIC_RES = (
    ("events", re.compile(
        r"\b(?:eventos?|proxim\w*|agenda|calendario|esta semana|"
        r"semana que viene|en una semana|upcoming|calendar|this week|"
        r"next week|coming up|dividendos?|dividends?|ex dividend\w*|fed|bce|"
        r"ecb|reserva federal|bancos? centrale?s?|central banks?|anuncios?|"
        r"announcements?|(?<!largo )(?<!medio )(?<!corto )plazos?|deadlines?|"
        r"hacienda)\b")),
    ("insiders", re.compile(
        r"\b(?:insiders?|directivos?|consejeros?|ejecutivos?|executives?|"
        r"form 4|informacion privilegiada)\b")),
    ("exits", re.compile(
        r"\b(?:kill|criterios? de (?:salida|venta)|stop ?loss|stops?|salida|"
        r"exit\w*|tesis|thesis|alertas?|alerts?)\b")),
    ("news", re.compile(
        r"\b(?:noticias?|news|titulares|headlines?|prensa|"
        r"yahoo(?: finance)?|que se dice|what s being said)\b")),
    ("filings", re.compile(
        r"\b(?:8 ?k|hechos? relevantes?|filings?|sec|edgar|comunicados?|"
        r"press releases?|registros? (?:en|ante) la sec)\b")),
    ("holders", re.compile(
        r"\b(?:grandes inversores|inversores institucionales|institucionales|"
        r"grandes (?:fondos|accionistas)|13 ?f|holders?|ballenas|big investors|"
        r"institutional\w*|institutions|whales|smart money|"
        r"(?:hacia )?donde (?:se mueve|va|fluye) el dinero|flujos? de dinero|"
        r"money (?:flows?|is going|is moving))\b")),
)
_LARGE_RE = re.compile(
    r"\b(?:grandes|principales|importantes|big|large|largest|major|"
    r"mega ?caps?|las empresas|companies)\b")


def rules(text: str, tickers=()) -> Recipe:
    """The recipe the words make obvious, with no model."""
    folded = learnings._fold(text)
    regions = tuple(code for code, pattern in _REGION_RES if pattern.search(folded))
    markets: tuple[str, ...] = ()
    # "La bolsa" with no region is the core indices; "el oro" alone is gold.
    broad = any(r in ("us", "europe", "spain", "asia") for r in regions)
    if _MARKET_RE.search(folded) and not broad:
        markets = ("core", *regions)
    elif regions:
        markets = regions
    earnings = ""
    if _EARNINGS_RE.search(folded):
        if tickers:
            earnings = "named"
        elif _MINE_RE.search(folded):
            earnings = "book"
        elif _LARGE_RE.search(folded):
            earnings = "large"
        else:
            earnings = "book"
    topics = tuple(code for code, pattern in _TOPIC_RES if pattern.search(folded))
    return Recipe(markets=markets, earnings=earnings, topics=topics, by="rules")


# ------------------------------------------------------------------ current


def current(routine: learnings.Learning) -> Recipe:
    """The recipe the card fetches for `routine` today: the model's when it
    was worked out for these very words, else the rules'. A model's recipe
    from before topics existed still gets the topics its words plainly ask
    for."""
    stored = routine.recipe or {}
    hint = rules(routine.text, routine.tickers)
    if stored.get("by") == "model" and stored.get("wording") == routine.text:
        planned = _from_dict(stored)
        return replace(planned, topics=planned.widened(hint).topics)
    return hint


def stale(routines: list[learnings.Learning], day: date) -> list[learnings.Learning]:
    """The routines a model should plan: no model recipe for their current
    wording under the current vocabulary, and not already tried today."""
    out = []
    for routine in routines:
        stored = routine.recipe or {}
        planned = stored.get("by") == "model" and stored.get("v") == RECIPE_VERSION
        if stored.get("wording") == routine.text and (
                planned or stored.get("tried") == day.isoformat()):
            continue
        out.append(routine)
    return out


# --------------------------------------------------------------------- plan

_PLAN_SYSTEM = (
    "You plan the data a stock-tracking app fetches each morning to answer "
    "its user's daily questions. For each routine below — a question the "
    "user asks every day, in their own words — decide what to fetch. Never "
    "answer the question; only plan the fetch.\n"
    "- markets: the market groups to quote, any of: "
    "core (S&P 500, Nasdaq, Euro Stoxx 50, VIX — for 'the market' or 'the "
    "main indices' with no region), us (S&P 500, Nasdaq, Dow Jones), europe "
    "(Euro Stoxx 50, DAX, CAC 40), spain (IBEX 35), asia (Nikkei, Hang "
    "Seng), rates (US 10-year yield, EUR/USD, VIX), commodities (gold, "
    "Brent), crypto (Bitcoin, Ether). Empty when the routine is not about "
    "markets.\n"
    "- earnings: company results (reported in the last days, and coming "
    "up). book = the user's own companies (held or followed), named = the "
    "companies the routine names, large = the largest listed companies "
    "(the user's own included), when it asks about companies in general. "
    "none when the routine is not about results.\n"
    "- symbols: at most five Yahoo Finance symbols for the specific "
    "instruments the routine names that the market groups do not already "
    "cover — a company by name (Nvidia -> NVDA, Inditex -> ITX.MC), an "
    "index, a currency (EURUSD=X), a commodity future (GC=F), a coin "
    "(BTC-EUR). Exchange suffix included for non-US listings. Leave a "
    "symbol out when you are not sure how Yahoo spells it.\n"
    "- topics: the user's own book seen from more sides, any of: events "
    "(what is coming up in the next week — results, ex-dividend dates, "
    "central-bank decisions, tax deadlines), insiders (shares the "
    "companies' own insiders bought or sold), exits (the user's price "
    "alerts and the exit or kill criteria and decisions they saved), news "
    "(the last days' press headlines about the companies), filings (the "
    "8-K current reports the companies filed with the SEC this week — "
    "deals, departures, results, restatements), holders (the big "
    "institutional investors in the companies and which of them added or "
    "cut their stake last quarter — 'where the money is going'). "
    "Empty when the routine asks for none of them.\n"
    "One plan per routine, its `id` copied exactly."
)


def plan_input(routines: list[learnings.Learning]) -> str:
    return "Routines:\n" + "\n".join(
        f"- {r.id}: {learnings.one_line(r.text)}" for r in routines)


def parse_plans(raw: str, ids: set[str]) -> dict[str, Recipe] | None:
    """{routine id: its recipe} from a PlanRoutines reply, None when it is
    not the JSON asked for. Unknown ids, groups and scopes are dropped."""
    try:
        body = structured.parse(raw, "PlanRoutines")
    except structured.OffContract:
        return None
    plans = body.get("plans")
    if not isinstance(plans, list):
        return None
    out: dict[str, Recipe] = {}
    for entry in plans:
        if not isinstance(entry, dict) or str(entry.get("id") or "") not in ids:
            continue
        out[str(entry["id"])] = Recipe(
            markets=_groups(entry.get("markets")),
            earnings=_scope(entry.get("earnings")),
            symbols=_symbols(entry.get("symbols")),
            topics=_topics(entry.get("topics")),
            by="model",
        )
    return out or None


def plan(prefs: dict, routines: list[learnings.Learning], *, spend_free,
         timeout_s: float = PLAN_TIMEOUT_S) -> dict[str, Recipe]:
    """Each routine's recipe from the first model that plans it, {} when none
    does. Never raises. The model's plan is widened by the rules' (a group or
    a scope it missed that the words plainly ask for), never narrowed."""
    if not routines:
        return {}
    try:
        system, messages = structured.render("PlanRoutines", _PLAN_SYSTEM,
                                             plan_input(routines))
    except Exception:  # noqa: BLE001 — a card with rules-only recipes
        return {}
    ids = {r.id for r in routines}
    got = engine.complete_attempts(
        prefs, system, messages, timeout_s, spend_free=spend_free,
        accept=lambda raw: parse_plans(raw, ids),
    ) or {}
    out = {}
    for routine in routines:
        if (planned := got.get(routine.id)) is None:
            continue
        out[routine.id] = planned.widened(rules(routine.text, routine.tickers))
    obs.event("daily_action.routines_planned", asked=len(routines), planned=len(out))
    return out


def ensure(prefs: dict, chat_path, routines: list[learnings.Learning], day: date,
           *, spend_free) -> list[learnings.Learning]:
    """`routines` with a model recipe for every one that needed planning and
    got it, each kept on the routine. One that got none is marked tried for
    `day`, so the model is asked once a day, not on every card. Never raises."""
    wanted = stale(routines, day)
    if not wanted or chat_path is None:
        return routines
    planned = plan(prefs, wanted, spend_free=spend_free)
    path = learnings.path_for(Path(chat_path))
    todo = {r.id for r in wanted}
    out = []
    for routine in routines:
        if routine.id in todo:
            recipe = (planned[routine.id].as_dict(routine.text)
                      if routine.id in planned
                      else {"by": "rules", "wording": routine.text,
                            "tried": day.isoformat()})
            try:
                learnings.set_recipe(path, routine.id, routine.text, recipe)
            except Exception as exc:  # noqa: BLE001 — used today, kept or not
                obs.warn("daily_action.recipe_unsaved", error_type=type(exc).__name__)
            routine = replace(routine, recipe=recipe)
        out.append(routine)
    return out
