"""The assistant's two jobs on the sector screen: widen the cohort, read it.

Both are the same shape as `chat.daily` — a model is asked for judgement over
figures it did not compute, and every figure it prints back is checked against
the ones it was given before anything reaches a page.

**Widening** (`propose_peers`). A sector ETF holds large American companies, so
the cohort it produces answers "the best of the S&P's technology names", which
is not the question. The model is asked for listed companies in the same sector
outside the US. It is the only step here that is allowed to name something
nobody asked about, and it is also the step most able to invent — so its output
is text, not symbols, and `analysis.sectors.validate_symbols` is what turns one
into the other.

**Reading** (`generate`). The podium is already decided by `comp_scores`
before the model sees it; the model is not ranking anything. It explains what
the three have in common, what separates them, and how they sit against what
the reader already owns — and `audit` rejects the answer outright if it prints
a percentage that is not in the facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import field_validator

from stocks import obs
from stocks.chat import engine
from stocks.chat.daily import audit
from stocks.chat.structured import Contract, decode

# The verdict is read on a page that is already waiting on Yahoo; the daily
# card's budget is the right one, for the same reason.
TIMEOUT_S = 25.0

# Widening gets far longer, because nobody is watching it: it runs in the
# nightly cron. Measured against the real free chain, one proposal costs ~38s
# — two dead backends before a 550B model that is itself slow — so the page's
# budget rejected every answer it ever got and every sector silently stayed at
# its ETF basket. A cron may wait; a reader may not.
PEERS_TIMEOUT_S = 120.0

# Bullets in a verdict. Three podium places, three things to say about them.
MAX_BULLETS = 3

# Bullet furniture the model adds however it is told not to.
_BULLET_RE = re.compile(r"^\s*(?:[-*•–—]|\d+[.)])\s*")


# --------------------------------------------------------------- widening


class PeerPicks(Contract):
    """Symbols only. Names and rationales are noise we would throw away."""

    symbols: list[str] = []

    @field_validator("symbols")
    @classmethod
    def _clean(cls, raw: list[str]) -> list[str]:
        out: list[str] = []
        for item in raw:
            symbol = str(item or "").strip().upper()
            if symbol and symbol not in out:
                out.append(symbol)
        return out[:12]


_PEERS_SYSTEM = (
    "You list stock ticker symbols. Reply with JSON only: "
    '{"symbols": ["ASML.AS", "7203.T"]}.\n'
    "Rules:\n"
    "- Symbols must be spelled as Yahoo Finance spells them, including the "
    "exchange suffix for non-US listings (.AS, .PA, .DE, .L, .T, .HK, .SW).\n"
    "- Every company must be listed, currently trading, and operate mainly in "
    "the named sector.\n"
    "- Exclude anything listed in the United States, and exclude ETFs, funds "
    "and holding vehicles.\n"
    "- Prefer large, liquid companies over small ones.\n"
    "- If you are unsure a symbol is spelled correctly, leave it out. A short "
    "list is correct; a wrong symbol is not."
)


def peers_prompt(sector: str, known: tuple[str, ...], count: int) -> str:
    return (
        f"Sector: {sector}\n"
        f"Already covered (do not repeat): {', '.join(known) or 'none'}\n"
        f"List up to {count} listed companies in this sector outside the "
        f"United States."
    )


def propose_peers(
    prefs: dict,
    sector: str,
    known: tuple[str, ...],
    count: int,
    *,
    spend_free,
    timeout_s: float = PEERS_TIMEOUT_S,
) -> list[str]:
    """Candidate symbols for `sector`, unvalidated. Empty when no model answers.

    Never raises: a sector whose widening failed is a sector with its ETF
    cohort, which is a worse screen but a working one. The caller must still
    run these through `analysis.sectors.validate_symbols` — nothing here has
    asked Yahoo whether any of them exist.
    """
    seen = {s.upper() for s in known}

    def accept(raw: str):
        try:
            picks = decode(raw, PeerPicks)
        except ValueError:
            return None
        fresh = [s for s in picks.symbols if s not in seen][:count]
        return fresh or None

    out = engine.complete_attempts(
        prefs,
        _PEERS_SYSTEM,
        [{"role": "user", "content": peers_prompt(sector, known, count)}],
        timeout_s,
        spend_free=spend_free,
        accept=accept,
    )
    obs.event("sector.peers_proposed", sector=sector, n=len(out or []))
    return list(out or [])


# ----------------------------------------------------------------- reading


@dataclass(frozen=True)
class Verdict:
    """One sector's written read. `source` is "llm" or "computed"."""

    sector: str
    as_of: str
    lang: str
    headline: str
    bullets: tuple[str, ...]
    source: str
    generated: str = ""

    def to_dict(self) -> dict:
        return {
            "sector": self.sector, "as_of": self.as_of, "lang": self.lang,
            "headline": self.headline, "bullets": list(self.bullets),
            "source": self.source, "generated": self.generated,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> Verdict:
        return cls(
            sector=str(raw.get("sector") or ""),
            as_of=str(raw.get("as_of") or ""),
            lang=str(raw.get("lang") or "en"),
            headline=str(raw.get("headline") or ""),
            bullets=tuple(str(b) for b in raw.get("bullets") or ()),
            source=str(raw.get("source") or "computed"),
            generated=str(raw.get("generated") or ""),
        )


def _pct(value) -> float | None:
    """A stored fraction as the percentage a reader will see.

    The KPIs are fractions here (ROIC 0.15 == 15%) but a verdict says "15%",
    and `audit` compares what was printed against what was given — so the facts
    must carry the printed scale or every true sentence looks invented.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number * 100, 1) if number == number else None


def _plain(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if number == number else None


def build_facts(scan, held: tuple[str, ...] = ()) -> dict:
    """The podium's figures, in the units a verdict prints them in.

    No fetching: everything comes off a scan the cron already paid for, plus
    the reader's own position list.
    """
    rows = {str(m.get("ticker") or "").upper(): m for m in scan.metrics}
    owned = {t.upper() for t in held}
    podium = []
    for rank, ticker in enumerate(scan.podium, start=1):
        row = rows.get(ticker.upper(), {})
        podium.append({
            "ticker": ticker.upper(),
            "rank": rank,
            "score_pct": _pct(scan.scores.get(ticker)),
            "pe_ttm": _plain(row.get("pe_ttm")),
            "ev_ebitda": _plain(row.get("ev_ebitda")),
            "roic_pct": _pct(row.get("roic")),
            "fcf_yield_pct": _pct(row.get("fcf_yield")),
            "net_margin_pct": _pct(row.get("net_margin")),
            "revenue_cagr_pct": _pct(row.get("revenue_cagr")),
            "held": ticker.upper() in owned,
        })
    return {
        "sector": scan.sector,
        "as_of": scan.as_of,
        "cohort": len(scan.tickers),
        "podium": podium,
        "held_in_cohort": sorted(owned & {t.upper() for t in scan.tickers}),
    }


_VERDICT_SYSTEM = (
    "You explain a stock screen's result to the investor who ran it.\n"
    "The ranking is already decided — you are not re-ordering anything.\n"
    "Rules:\n"
    "- Write the headline on the first line, then up to {bullets} lines, one "
    "per company. No markdown, no bullet characters, no numbering.\n"
    "- Use ONLY the figures given. Never state a percentage that is not in "
    "them, and never estimate one.\n"
    "- Never name a company that is not in the podium.\n"
    "- Say what the score rests on (cheap, profitable, growing) and what the "
    "reader gives up by picking one over another.\n"
    "- Where the reader already holds one, say so and say what the other two "
    "would add that it does not.\n"
    "- Write the composite score as NN/100, never as a percentage — that is "
    "how the card above your answer prints it.\n"
    "- The score is relative to this cohort of {cohort} companies and measures "
    "valuation and quality only. Do not call anything a buy, a target or an "
    "opportunity of the year.\n"
    "- Write in {language}. Be concrete and short; no preamble."
)

_LANGUAGES = {"en": "English", "es": "Spanish"}


def prompt(facts: dict, lang: str) -> tuple[str, list[dict]]:
    import json

    system = _VERDICT_SYSTEM.format(
        bullets=MAX_BULLETS,
        cohort=facts.get("cohort") or 0,
        language=_LANGUAGES.get(lang, "English"),
    )
    return system, [{"role": "user", "content": json.dumps(facts, sort_keys=True)}]


def parse(raw: str, *, facts: dict, lang: str) -> Verdict | None:
    """A reply as a Verdict, or None when it broke a rule.

    Rejects rather than repairs: a rejected reply falls through to the next
    provider and, if they all fail, to `computed()`. A verdict that quietly
    dropped an invented figure would be worse than no verdict, because the
    reader cannot tell which sentences were edited.
    """
    lines = [
        _BULLET_RE.sub("", line).strip()
        for line in (raw or "").splitlines()
        if line.strip()
    ]
    if not lines:
        return None
    # Two gates, and deliberately not a third. `audit` is the one that matters:
    # an invented company arrives with invented figures, and those it catches.
    # Policing prose for ticker-shaped words was tried and dropped — it cannot
    # tell NVDA from a Spanish abbreviation, and rejecting a true verdict is
    # the worse error when the fallback below is strictly less useful.
    top = str((facts.get("podium") or [{}])[0].get("ticker") or "")
    if top and not any(top in line for line in lines):
        # Wholesale drift: a reply about companies other than the ones ranked.
        obs.event("sector.verdict_off_cohort", sector=facts.get("sector"))
        return None
    bad = audit(lines, facts)
    if bad:
        obs.event("sector.verdict_audit_failed",
                  sector=facts.get("sector"), figure=bad)
        return None
    return Verdict(
        sector=str(facts.get("sector") or ""),
        as_of=str(facts.get("as_of") or ""),
        lang=lang,
        headline=lines[0],
        bullets=tuple(lines[1:1 + MAX_BULLETS]),
        source="llm",
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def computed(facts: dict, lang: str) -> Verdict:
    """The verdict without a model: what the podium cannot say for itself.

    Shown whenever generation is unavailable — no provider, allowance spent,
    every candidate down, or nobody signed in. It deliberately does NOT restate
    the three places: the card directly above it already prints each one's rank,
    score and figures, and repeating them was the whole content of this block
    on a phone, where you scrolled the same numbers twice.

    What is left is what the podium has no room for — which of the three the
    reader already owns — plus the honest admission that nothing was written.
    """
    from stocks.web.i18n import translate

    def tr(key: str, **kw) -> str:
        return translate(f"sector.fb_{key}", lang, **kw)

    podium = facts.get("podium") or []
    sector = str(facts.get("sector") or "")
    if not podium:
        return Verdict(sector=sector, as_of=str(facts.get("as_of") or ""),
                       lang=lang, headline=tr("empty", sector=sector),
                       bullets=(), source="computed")

    held = [p["ticker"] for p in podium if p.get("held")]
    bullets = [tr("held", tickers=", ".join(held))] if held else []
    return Verdict(
        sector=sector,
        as_of=str(facts.get("as_of") or ""),
        lang=lang,
        headline=tr("headline", sector=sector,
                    top=podium[0].get("ticker") or "",
                    cohort=facts.get("cohort") or 0),
        bullets=tuple(bullets),
        source="computed",
    )


def generate(
    prefs: dict,
    facts: dict,
    lang: str,
    *,
    timeout_s: float = TIMEOUT_S,
    spend_free=None,
) -> Verdict | None:
    """One verdict from the first provider that answers usefully, or None.

    Never raises — the caller falls through to `computed()`. `spend_free`
    defaults to the per-account counter: a verdict is generated from a user
    session looking at a page, so it is that account's to pay for.
    """
    if not (facts.get("podium") or []):
        return None
    try:
        system, messages = prompt(facts, lang)
    except Exception:
        return None
    return engine.complete_attempts(
        prefs,
        system,
        messages,
        timeout_s,
        spend_free=spend_free or engine.spend_free_quota,
        accept=lambda raw: parse(raw, facts=facts, lang=lang),
    )
