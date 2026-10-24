"""The ticker page's "Analyse with AI", as a brief rather than a sentence.

The button used to send one line — "Analyse Centrus Energy (LEU): business,
fundamentals, valuation…" — the same for a uranium enricher, a chip designer
and a regional bank. The router then picked a lens from those words alone and
read "Energy" as oil and gas; the answer had no structure to fill, did not
know whether the reader held the name, and missed the quarter reported four
days earlier.

So the button names an *angle* (`ANGLES`) and the server writes the rest, from
what it already knows about the company and the reader:

* **The lens is the company's, not the router's.** `chat_skills.lens_for` maps
  Yahoo's sector and industry to a skill; the angle adds its own (bear case,
  earnings review, portfolio risk) and so does the company's stage (an income
  payer gets the dividend lens). No classifier call, no guess.
* **The facts that change the question.** Held or not (opening a position is
  not adding to one), a report in the last ten days (start from it), the next
  one within a month (a catalyst), a large move today (say why first).
* **A structure per angle**, short enough to read in the drawer.
* **A dossier per company** (`Dossier`): what it sells and the two or three
  questions its bulls and bears actually argue about — for LEU the HALEU
  contract and the Russian supply waiver, not "competition". A cheap model
  drafts it from Yahoo's profile once a month; it is framed as questions to
  verify, never as facts, and an item carrying a figure is dropped.

Everything rides on the outgoing copy of the user turn. The thread keeps the
reader's own short question, so the brief is never shown back to them.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, SupportsFloat

from pydantic import field_validator

from stocks import atomic, obs, storage
from stocks.chat import structured
from stocks.config import DATA_DIR
from stocks.web import chat_skills

if TYPE_CHECKING:
    from stocks.web.llm import Provider

ANGLES = ("full", "bear", "earnings", "fit")

# The lens each angle brings besides the company's own.
ANGLE_SKILL = {
    "bear": "bear-case",
    "earnings": "earnings-review",
    "fit": "portfolio-risk",
}

# Yahoo's quoteType for what is not a company: the wrapper's lens replaces the
# industry's, and the angles past "full" do not apply (`structure`).
KIND_SKILL = {
    "ETF": "etfs",
    "MUTUALFUND": "etfs",
    "MONEYMARKET": "etfs",
    "CRYPTOCURRENCY": "crypto",
}

# A report this recent is what the analysis starts from; one this close ahead
# is a catalyst to name.
RECENT_DAYS = 10
AHEAD_DAYS = 30
# A day move worth explaining before anything else.
BIG_MOVE = 0.05

# How long a drafted dossier is read before it is drafted again. A business
# changes slower than this; the debates around it, about this fast.
DOSSIER_DAYS = 30
DOSSIER_DIR = DATA_DIR / "dossiers"
# What the draft is given of Yahoo's business summary, and what it may say.
SUMMARY_CHARS = 1500
BUSINESS_CHARS = 240
ITEM_CHARS = 160
MAX_ITEMS = 3

# A dossier is the model's general knowledge, so it may ask but not assert: an
# item with a figure in it ("backlog of $3.8bn", "Q3", "40%") is the kind of
# claim nobody checked, and goes.
_FIGURE = re.compile(r"\d|%|\$|€|£")


# ----------------------------------------------------------------- facts


@dataclass(frozen=True)
class Facts:
    """What Yahoo's profile says about the company, read best-effort."""

    ticker: str
    name: str = ""
    quote_type: str = ""
    sector: str = ""
    industry: str = ""
    summary: str = ""
    revenue: float | None = None
    growth: float | None = None
    margin: float | None = None
    dividend_yield: float | None = None
    day_move: float | None = None


def _num(value: object) -> float | None:
    try:
        out = float(value) if isinstance(value, (SupportsFloat, str)) else None
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN -> None


def facts(ticker: str) -> Facts:
    """The company's profile: `fetch.info` (memoized — the page the button is
    on has just read it), else the on-disk profile memo, else the symbol."""
    from stocks.data import fetch, profiles

    blob: dict = {}
    try:
        blob = fetch.info(ticker) or {}
    except Exception as exc:  # noqa: BLE001 — a throttled profile is no brief, not an error
        obs.warn("chat.brief_info_failed", ticker=ticker,
                 error_type=type(exc).__name__, error=str(exc)[:200])
    if not blob:
        blob = dict(profiles.known(ticker) or {})
    move = _num(blob.get("regularMarketChangePercent"))
    return Facts(
        ticker=ticker,
        name=str(blob.get("longName") or blob.get("shortName")
                 or blob.get("name") or ""),
        quote_type=str(blob.get("quoteType") or "").upper(),
        sector=str(blob.get("sector") or ""),
        industry=str(blob.get("industry") or ""),
        summary=str(blob.get("longBusinessSummary") or "")[:SUMMARY_CHARS],
        revenue=_num(blob.get("totalRevenue")),
        growth=_num(blob.get("revenueGrowth")),
        margin=_num(blob.get("profitMargins")),
        dividend_yield=_num(blob.get("dividendYield")),
        # Yahoo gives this one in percent points, the rest as fractions.
        day_move=move / 100 if move is not None else None,
    )


def about(ticker: str) -> str:
    """"Energy · Uranium" for the prompt's current view, from the on-disk
    profile memo only — this runs on every question asked on a ticker page,
    and a network read for a label is not worth its wait."""
    if not ticker:
        return ""
    from stocks.data import profiles

    known = profiles.known(ticker) or {}
    return " · ".join(p for p in (known.get("sector"), known.get("industry")) if p)


# Yahoo's dividend yield arrives in percent on some listings and as a fraction
# on others; anything above this is read as percent points.
_YIELD_AS_PERCENT = 1.0

_CYCLICAL = {"Energy", "Basic Materials"}


def stage(f: Facts) -> tuple[str, str]:
    """(a line saying where the company is in its life, the style lens it
    calls for or "")."""
    dy = f.dividend_yield
    if dy is not None and dy > _YIELD_AS_PERCENT:
        dy /= 100
    if f.revenue is not None and f.revenue < 50e6:
        return ("Stage: early or pre-revenue — value it on the odds of what it is "
                "building and on its cash runway, not on earnings.",
                "growth-momentum")
    if f.margin is not None and f.margin < 0:
        return ("Stage: growing but not yet profitable — judge the path to "
                "profit and the dilution on the way.", "growth-momentum")
    if f.sector in _CYCLICAL:
        return ("Stage: cyclical — judge it on mid-cycle earnings, not on the "
                "current ones.", "")
    if f.growth is not None and f.growth > 0.2:
        return ("Stage: profitable and growing fast — the question is what "
                "growth the price already assumes.", "growth-momentum")
    if dy is not None and dy >= 0.03:
        return ("Stage: mature income payer — the dividend's cover and growth "
                "are the thesis.", "dividend")
    if f.revenue is None and f.margin is None:
        return "", ""
    return "Stage: mature — returns on capital and the price paid decide it.", ""


# ------------------------------------------------------------- the reader


def holding_line(ticker: str, watchlist: Path, db: Path, currency: str) -> str:
    """Whether the reader holds the name, and how much of the book it is."""
    from stocks.chat import engine

    tbl = engine.enriched_frame(db, currency) if db.exists() else None
    if tbl is not None and ticker in tbl.index:
        row = tbl.loc[ticker]
        wt, pnl = _num(row.get("weight")), _num(row.get("pnl_pct"))
        bits = [f"weight {wt:.1%}" if wt is not None else "",
                f"P/L {pnl:+.1%}" if pnl is not None else ""]
        said = ", ".join(b for b in bits if b)
        return ("The user holds it" + (f" ({said})" if said else "")
                + " — the question is hold, add or trim.")
    try:
        from stocks.config import positions

        if any(p.ticker == ticker for p in positions(watchlist)):
            return "The user holds it — the question is hold, add or trim."
    except Exception:  # noqa: BLE001 — a missing watchlist reads as "not held"
        pass
    return ("The user does not hold it — the question is whether to open a "
            "position, and at what size.")


def earnings_lines(ticker: str, today: date | None = None) -> tuple[str, bool]:
    """(the report lines, whether one landed in the last `RECENT_DAYS`)."""
    from stocks.api import loaders

    today = today or date.today()
    try:
        dates, _results = loaders.earnings(ticker)
    except Exception:  # noqa: BLE001 — loaders.earnings never raises; belt and braces
        return "", False
    past = [d for d in dates if d <= today]
    ahead = [d for d in dates if d > today]
    lines: list[str] = []
    recent = bool(past) and (today - max(past)).days <= RECENT_DAYS
    if recent:
        last = max(past)
        lines.append(f"It reported on {last.isoformat()} "
                     f"({(today - last).days} days ago): start from that quarter.")
    if ahead and (min(ahead) - today).days <= AHEAD_DAYS:
        nxt = min(ahead)
        lines.append(f"Next report {nxt.isoformat()} (in {(nxt - today).days} "
                     "days): name it as a catalyst.")
    return "\n".join(lines), recent


# ------------------------------------------------------------- structure

_SECTIONS = {
    "full": (
        "1. **Verdict** — one line: accumulate, hold, trim, avoid or no clear "
        "edge, and why now.\n"
        "2. **Business** — what it sells, to whom, what drives the numbers.\n"
        "3. **Numbers that matter here** — the KPIs the industry framework "
        "names, newest period.\n"
        "4. **Valuation** — against its own history and two or three peers, by "
        "the method the framework names; bear / base / bull with a rough "
        "probability each.\n"
        "5. **Risks and kill criteria** — what would prove the thesis wrong, as "
        "a price level or an event.\n"
        "6. **Catalysts** — dated where the research has the date.\n"
        "7. **In your book** — {book}",
        350,
    ),
    "bear": (
        "1. **The strongest bear case** — its single best pillar, in one line.\n"
        "2. **What the price assumes** — the growth and margins the valuation "
        "needs, and how plausible they are.\n"
        "3. **Red flags** — accounting, dilution, insider selling, balance "
        "sheet: only those the research supports.\n"
        "4. **Pre-mortem** — the likeliest way this loses a third from here.\n"
        "5. **What would change my mind** — the evidence that kills the bear "
        "case.\n"
        "6. **Kill criteria** — {kill}",
        300,
    ),
    "earnings": (
        "1. **The quarter** — revenue, EPS and the industry's KPIs against "
        "consensus and a year ago.\n"
        "2. **Guidance** — new against prior and against consensus.\n"
        "3. **What moved** — margins, mix, the topic analysts pressed hardest.\n"
        "4. **Market reaction** — the move, and whether the numbers explain it.\n"
        "5. **Thesis check** — stronger, unchanged or weaker, and why.\n"
        "6. **Next** — the next report's date and what to watch in it.",
        300,
    ),
    "fit": (
        "1. **What it adds** — the exposure (sector, factor, currency, region) "
        "it brings that the book lacks, or doubles.\n"
        "2. **Overlap** — holdings that move with it (same driver, not same "
        "label) and their combined weight.\n"
        "3. **Size** — a weight range and why; what would fund it.\n"
        "4. **Risk to the book** — what a 30 % fall in it does to the whole "
        "book.\n"
        "5. **Verdict** — fits, fits smaller, or does not fit.",
        250,
    ),
}

_BOOK_HELD = ("its weight now, whether to add or trim, and what else in the "
              "book moves with it.")
_BOOK_NEW = ("a starting size as a share of the book, how to enter (all at "
             "once or in steps), and what else in the book moves with it.")
_KILL_HELD = ("say whether the user's saved exit rule for it covers this; "
              "propose one when there is none.")
_KILL_NEW = "the level or event that would make this a no."

_RULES = (
    "Label every figure: reported (with its period), consensus, or your "
    "estimate. A figure the research did not find is \"not found\", never a "
    "guess. \"No clear edge\" is a valid verdict. Use the section headers "
    "above, two or three lines each, no padding."
)


# ---------------------------------------------------------------- dossier


class Dossier(structured.Contract):
    """A month's notes on one company. Every field may come back empty; an
    item carrying a figure is dropped (`_FIGURE`), a lens outside the
    industry catalog is "" (the company's own industry decides anyway)."""

    business: str = ""
    lens: str = ""
    debates: list[str] = []
    watch: list[str] = []

    @field_validator("business", mode="before")
    @classmethod
    def _business(cls, v):
        return _clip(v, BUSINESS_CHARS) if isinstance(v, str) else ""

    @field_validator("lens", mode="before")
    @classmethod
    def _lens(cls, v):
        ids = {s.id for s in chat_skills.catalog()}
        got = v.strip().lower() if isinstance(v, str) else ""
        return got if got in ids else ""

    @field_validator("debates", "watch", mode="before")
    @classmethod
    def _items(cls, v):
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            text = _clip(item.strip().lstrip("-•* ").strip(), ITEM_CHARS)
            if text and not _FIGURE.search(text) and text not in out:
                out.append(text)
        return out[:MAX_ITEMS]


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_DOSSIER_SYSTEM = (
    "You prepare an analyst's notes on one listed company before a full "
    "analysis is written. From the profile below, give: the business in one "
    "sentence; the one industry skill id from the catalog that fits it best "
    "(empty if none does); two or three questions that bulls and bears "
    "genuinely disagree on for THIS company — specific to its products, "
    "contracts, regulators and competitors, not generic ('competition', "
    "'macro'); and two or three company-specific metrics or events to watch. "
    "Write questions and names, never figures, dates or percentages: they "
    "will be checked against fresh research, and a number from memory is the "
    "one thing that cannot be.\n\nIndustry skill catalog:\n"
)

_lock = threading.Lock()
_restored: set[str] = set()


def _path(ticker: str) -> Path:
    safe = re.sub(r"[^A-Z0-9._-]", "_", ticker.upper())
    return DOSSIER_DIR / f"{safe}.json"


def cached_dossier(ticker: str, today: date | None = None) -> Dossier | None:
    """The stored dossier for `ticker` while it is younger than DOSSIER_DAYS.

    A cold container asks the bucket once per ticker, then trusts its disk."""
    path = _path(ticker)
    with _lock:
        first = ticker not in _restored
        _restored.add(ticker)
    if first and not path.exists() and storage.enabled():
        with obs.swallow("chat.dossier_restore"):
            storage.restore(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        made = date.fromisoformat(str(raw.get("made")))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if ((today or date.today()) - made) > timedelta(days=DOSSIER_DAYS):
        return None
    try:
        return Dossier.model_validate(raw)
    except ValueError:
        return None


def _save(ticker: str, dossier: Dossier, today: date | None = None) -> None:
    path = _path(ticker)
    payload = {"made": (today or date.today()).isoformat(), "ticker": ticker,
               **dossier.model_dump()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(path, payload, indent=1, sort_keys=True)
    except OSError:
        return
    if storage.enabled():
        with obs.swallow("chat.dossier_persist"):
            storage.persist(path)


def draft_dossier(provider: Provider, api_key: str, f: Facts) -> Dossier | None:
    """A new dossier for the company, stored for the month. None when the model
    fails or there is nothing to draft from (no profile, no summary)."""
    if not f.summary:
        return None
    cat = "\n".join(f"- {s.id}: {s.description}" for s in chat_skills.catalog()
                    if s.kind == "industry")
    user = (f"{f.name or f.ticker} ({f.ticker}) — {f.sector or '?'} · "
            f"{f.industry or '?'}\n\nProfile: {f.summary}")
    try:
        got = structured.ask(provider, api_key, "DraftDossier",
                             _DOSSIER_SYSTEM + cat, user, Dossier)
    except Exception as exc:  # noqa: BLE001 — notes are garnish; the answer goes on
        obs.warn("chat.dossier_failed", ticker=f.ticker,
                 error_type=type(exc).__name__, error=str(exc)[:200])
        return None
    if not (got.business or got.debates or got.watch):
        return None
    _save(f.ticker, got)
    obs.event("chat.dossier_drafted", ticker=f.ticker, lens=got.lens or "-",
              debates=len(got.debates))
    return got


def dossier_block(d: Dossier | None) -> str:
    """The dossier as it rides on the turn — "" when there is none."""
    if d is None or not (d.business or d.debates or d.watch):
        return ""
    lines = ["\n\nCompany notes (drafted earlier from the company's profile — "
             "background, not facts: settle each question against the research "
             "above, and drop any the research does not support):"]
    if d.business:
        lines.append(f"Business: {d.business}")
    if d.debates:
        lines.append("Questions to settle:")
        lines.extend(f"- {q}" for q in d.debates)
    if d.watch:
        lines.append("Watch: " + "; ".join(d.watch) + ".")
    return "\n".join(lines)


# ------------------------------------------------------------------ brief


@dataclass(frozen=True)
class Brief:
    """One button press, resolved: the lenses, the instructions for the turn,
    and what the engine should run beside it."""

    angle: str
    ticker: str
    facts: Facts
    skills: list[str] = field(default_factory=list)
    text: str = ""
    # Both sides argued before the answer (`chat.debate`): a verdict and a
    # bear case are the questions a debate exists for.
    debate: bool = False
    # The research reads further: a full analysis is "in depth" by definition.
    deep: bool = False
    dossier: Dossier | None = None
    # The dossier is missing or stale and the profile has enough to draft one.
    needs_dossier: bool = False


def pick_skills(angle: str, f: Facts, style: str, recent: bool,
                dossier: Dossier | None) -> list[str]:
    """The company's lens first, then the angle's, then the stage's — capped
    at the manual limit, known ids only."""
    kind = KIND_SKILL.get(f.quote_type, "")
    lens = kind or chat_skills.lens_for(f.sector, f.industry)
    if dossier is not None and dossier.lens and not kind:
        # The draft read the business; Yahoo's industry is a label, and
        # sometimes the wrong one (a reactor developer filed as machinery).
        industry_hit = any(s.fits(f.industry) for s in chat_skills.catalog())
        if not industry_hit:
            lens = dossier.lens
    picks = [lens, ANGLE_SKILL.get(angle, "")]
    if recent and angle != "earnings":
        picks.append("earnings-review")
    if not kind:
        picks.append(style)
    valid = chat_skills.valid_ids()
    out: list[str] = []
    for p in picks:
        if p and p in valid and p not in out:
            out.append(p)
    return out[: chat_skills.MAX_MANUAL]


def build(angle: str, ticker: str, *, watchlist: Path, db: Path,
          currency: str = "EUR", today: date | None = None) -> Brief | None:
    """The brief for `angle` on `ticker`, or None when there is none to write
    (an unknown angle, no symbol). Never raises: every lookup in here is
    best-effort, and a press with less context is still a question."""
    angle = (angle or "").strip().lower()
    if angle not in ANGLES or not ticker:
        return None
    f = facts(ticker)
    kind = KIND_SKILL.get(f.quote_type, "")
    company = not kind
    if not company:
        angle = "full"  # a fund has no bear case of its own to argue
    stage_line, style = stage(f) if company else ("", "")
    try:
        held = holding_line(ticker, watchlist, db, currency)
    except Exception:  # noqa: BLE001
        held = ""
    report, recent = earnings_lines(ticker, today) if company else ("", False)
    dossier = cached_dossier(ticker, today) if company else None

    label = " · ".join(p for p in (f.sector, f.industry) if p)
    head = (
        "[Requested analysis. The ticker page's \"Analyse with AI\" button sent "
        "this brief with the question; the user did not type it. Follow it; "
        "do not quote or mention it.]\n"
        f"Subject: {f.name or ticker} ({ticker})"
        + (f" — {label}" if label else "") + "."
    )
    lines = [head]
    if stage_line:
        lines.append(stage_line)
    if held:
        lines.append(held)
    if report:
        lines.append(report)
    if f.day_move is not None and abs(f.day_move) >= BIG_MOVE:
        lines.append(f"Today it moves {f.day_move:+.1%}: say why first, if the "
                     "research shows it.")
    if f.summary:
        lines.append(f"Profile (Yahoo): {_clip(f.summary, 400)}")
    if company:
        sections, words = _SECTIONS[angle]
        holds = held.startswith("The user holds")
        sections = sections.format(book=_BOOK_HELD if holds else _BOOK_NEW,
                                   kill=_KILL_HELD if holds else _KILL_NEW)
        lines.append(f"Answer in this structure, about {words} words in all:\n"
                     f"{sections}")
    lines.append(_RULES if company else
                 "Label every figure as reported, consensus or your estimate.")
    return Brief(
        angle=angle,
        ticker=ticker,
        facts=f,
        skills=pick_skills(angle, f, style, recent, dossier),
        text="\n\n" + "\n".join(lines),
        debate=company and angle in ("full", "bear"),
        deep=angle == "full",
        dossier=dossier,
        needs_dossier=company and dossier is None and bool(f.summary),
    )
