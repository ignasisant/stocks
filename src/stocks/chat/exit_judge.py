"""The model's reading of an event exit rule: did the CEO go, was guidance cut?

The reader writes "I sell if the CEO leaves" with the chat's help, and the
journal keeps it as an ``ceo_change`` criterion (`chat/journal.py`). Whether
it happened is in the company's 8-Ks and the news, in words no keyword match
can be trusted to read — "Jensen Huang named chairman" is not a departure,
"the board thanks outgoing CEO …" is. So `journal.check_slow` sieves the
passages for the rule's words and, only when one gets through, asks a model
one closed question about them (`JudgeExitEvent`): met or not, which passage,
and the words that say so.

The answer is held to what the model was shown — a passage that exists, a
quote that passage holds (`journal._judged`) — so a hit on the reader's card
always carries the sentence it was read off, and a model that imagines one
is a miss, not a false alarm.

A thesis rule asks the open question instead (`JudgeThesis`): the pillars
the reader holds the company for, against the day's business news, each
passage sorted into noise, a fact to watch, or one that damages a pillar
(`journal.check_theses`). Noise is the default and most of what it reads:
the price, the ratings, the opinions and the good news never break a
thesis.
"""

from __future__ import annotations

from collections.abc import Callable

from stocks import obs
from stocks.chat import engine, structured

JUDGE_TIMEOUT_S = 20.0
PASSAGE_CHARS = 2000  # `journal.EXCERPT_CHARS` already cut it to this

# What each event rule asks, in the terms a filing or a headline uses.
QUESTIONS = {
    "ceo_change": (
        "Does a passage say that the company's chief executive officer (CEO) "
        "is leaving, has left, was dismissed, or is being replaced, including "
        "a named successor or an interim CEO? A new chair, a CFO, a director "
        "or a CEO of a subsidiary does not count; neither does speculation."
    ),
    "guidance_cut": (
        "Does a passage say that the company itself lowered, cut or withdrew "
        "its own financial guidance or outlook (revenue, earnings, margin or "
        "cash flow)? Analysts cutting their estimates does not count; "
        "neither does guidance below expectations that was not lowered."
    ),
    "dividend_cut": (
        "Does a passage say that the company cut, suspended, or eliminated "
        "its regular dividend? A special dividend not repeated, a share "
        "buyback change or a dividend kept the same does not count."
    ),
}

_SYSTEM = (
    "You check one of an investor's exit rules against the company's own "
    "filings and recent headlines. Answer only from the numbered passages. "
    "Set met to true only when a passage plainly states that the event "
    "happened to {ticker}; rumours, analysts' views and other companies do "
    "not count. When met is true, give the passage's number in item and copy "
    "the words that say so into quote exactly as written, at most 30 words. "
    "When unsure, met is false.\n\nThe question: {question}"
)


def judge_input(passages: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {p.get('source') or ''} {p.get('day') or ''}\n"
        f"{str(p.get('text') or '')[:PASSAGE_CHARS]}"
        for i, p in enumerate(passages)
    )


def parse(raw: str) -> dict | None:
    """A JudgeExitEvent reply as {met, item, quote}, None off contract."""
    try:
        body = structured.parse(raw, "JudgeExitEvent")
    except structured.OffContract:
        return None
    item = body.get("item")
    return {"met": bool(body.get("met")),
            "item": item if isinstance(item, int) else None,
            "quote": str(body.get("quote") or "")}


def make_judge(prefs: dict, *, spend_free: Callable[[dict], bool],
               timeout_s: float = JUDGE_TIMEOUT_S):
    """`journal.Judge` on the reader's own models (their key, or the free
    chain within their allowance). None comes back when no model answered."""

    def judge(rule: str, ticker: str, passages: list[dict]) -> dict | None:
        question = QUESTIONS.get(rule)
        if not question or not passages:
            return None
        try:
            system, messages = structured.render(
                "JudgeExitEvent",
                _SYSTEM.format(ticker=ticker, question=question),
                judge_input(passages))
            got = engine.complete_attempts(
                prefs, system, messages, timeout_s, spend_free=spend_free,
                accept=parse)
        except Exception as exc:  # noqa: BLE001 — judged on the next check
            obs.warn("journal.judge_failed", rule=rule, error_type=type(exc).__name__)
            return None
        obs.event("journal.event_judged", rule=rule, asked=len(passages),
                  met=bool(got and got.get("met")))
        return got

    return judge


THESIS_TIMEOUT_S = 45.0

_THESIS_SYSTEM = (
    "An investor holds {ticker} for the reasons below, its pillars. Read the "
    "numbered passages (the company's filings and today's headlines) and "
    "decide, for each pillar a passage touches, whether the business itself "
    "is affected or it is only noise.\n\n{pillars}\n\n"
    "noise: price moves, analyst ratings and targets, opinion and "
    "'stocks to buy' pieces, rumours, general market or macro news, other "
    "companies, and any news that supports the pillar. Most passages are "
    "noise.\n"
    "watch: a concrete fact about {ticker} that goes against a pillar but "
    "is partial, early or one-off: one customer lost, one product delayed, a "
    "probe opened, one weak segment.\n"
    "damaged: a concrete fact, from the company, a regulator, a court or a "
    "major customer, that plainly contradicts a pillar: the result or event "
    "the pillar depends on did not happen or reversed.\n\n"
    "List only pillars that are watch or damaged, each with the passage's "
    "number in item and its words copied exactly into quote, at most 30 "
    "words. When unsure, it is noise: leave it out. An empty list is the "
    "usual answer."
)


def thesis_system(ticker: str, pillars: list[str]) -> str:
    from stocks.chat import journal

    lines = "\n".join(f"{journal.PILLAR_LETTERS[i]}. {p}"
                      for i, p in enumerate(pillars))
    return _THESIS_SYSTEM.format(ticker=ticker, pillars=lines)


def parse_thesis(raw: str) -> dict | None:
    """A JudgeThesis reply as {verdicts: [{pillar, verdict, item, quote}]},
    None off contract (an empty list is an answer: all noise)."""
    try:
        body = structured.parse(raw, "JudgeThesis")
    except structured.OffContract:
        return None
    out = []
    for v in body.get("verdicts") or ():
        if not isinstance(v, dict):
            continue
        item = v.get("item")
        out.append({"pillar": str(v.get("pillar") or ""),
                    "verdict": str(v.get("verdict") or ""),
                    "item": item if isinstance(item, int) else None,
                    "quote": str(v.get("quote") or "")})
    return {"verdicts": out}


def make_thesis_judge(prefs: dict, *, spend_free: Callable[[dict], bool],
                      timeout_s: float = THESIS_TIMEOUT_S):
    """`journal.ThesisJudge` on the reader's own models, as `make_judge`."""

    def judge(ticker: str, pillars: list[str], passages: list[dict]) -> dict | None:
        if not pillars or not passages:
            return None
        try:
            system, messages = structured.render(
                "JudgeThesis", thesis_system(ticker, pillars),
                judge_input(passages))
            return engine.complete_attempts(
                prefs, system, messages, timeout_s, spend_free=spend_free,
                accept=parse_thesis)
        except Exception as exc:  # noqa: BLE001 — judged on the next round
            obs.warn("journal.thesis_judge_failed", error_type=type(exc).__name__)
            return None

    return judge
