"""Answers worth a second look, found without anyone voting.

Few readers press a thumbs, so most wrong answers never say so. Two signals
say it for them, both read at the moment the data is in hand and logged as
`chat.review` — counts and ids only, never the words or the figures, which
can be the reader's own amounts:

- `figures`: an answer whose figures nothing the model was shown states. The
  pool is the prompt itself (`Turn.system` + `Turn.messages`): the book, the
  quotes, the tool results and the pages are stapled onto it before the model
  speaks, and none of that is stored on the turn, so this is the one place the
  check can run. It reuses the prod eval's checker (`prod_eval.unsourced`).
  A figure the model worked out — a sum, a difference, a share of an amount —
  reads as unsourced too, so the count is a lead, not a verdict: the
  threshold is to be set from what prod logs.
- `complaint` / `rephrase`: the reader's next message says the answer above
  was wrong, or asks the same question again. Logged against that answer's
  id (`answer`), since the ambient `turn` is already the new question's.
- `judged`: a model reads the question, what the answering model was shown
  and the answer, and scores it (`agent_judge.SCORES`, 1-5). Scores only,
  never its reasons: they quote the answer. Off unless the deploy says
  `[review] judge = "on"`, and narrow on purpose:
  - only answers the free chain wrote, judged by the same chain, so the
    reader's words reach no one they had not already reached — a reader on
    their own key is never sent to the operator's providers;
  - never for an account that switched review off in Profile (`PREF`),
    which stops the counts above as well: a lead is what gets an answer read;
  - a small sample plus every `figures` lead, under a daily cap per
    process, and none for the rest of the day once the chain is out of
    quota: the free chain is one pot every reader's answers come from.
  It runs after the answer is stored, on its own thread; the run's hold
  stays open until it is done (`judging`, api/routes/chat/turns.py).
  A judged answer is read back by its id from the account's chat.json
  (`stocks review-answer`), which keeps it KEEP_DAYS.

Best-effort throughout: a check that fails costs a missed lead, never an
answer.
"""

from __future__ import annotations

import random
import re
import threading
import time
import unicodedata
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor

from stocks import cache, llm, obs
from stocks.chat import agent_judge, prod_eval
from stocks.secrets_env import secret

EVENT = "chat.review"

# Figures an answer may state that nothing shown to the model does before it
# is logged. One is noise (a total the model added up); the eval calls three a
# hallucination on catalog questions, where every figure has a truth to match.
FLAG_AT = 2

# A prompt can carry thousands of numbers (page extracts, a long book), and
# the checker compares every figure of the answer against every one of them:
# deduped at this precision first.
_POOL_DIGITS = 6

# Words of three letters or more, folded, that a rephrase has to share with
# the question before it: this share of the two together (Jaccard).
REPHRASE_AT = 0.6
# Fewer words than this on either side and a "rephrase" is only a short
# follow-up ("¿y AMD?", "más detalle").
REPHRASE_MIN_WORDS = 4

# The reader saying the answer above was wrong, in the app's three languages.
# Narrow on purpose: "error" alone is a tracking error, "mal" alone a bad
# quarter. Matched on folded text (no accents, lower case).
_COMPLAINT = re.compile(
    r"\b(?:"
    # es
    r"(?:eso|esto|esa|ese|la respuesta|el dato|la cifra)\s+(?:esta|es)\s+mal"
    r"|(?:esta|estas)\s+mal\s+(?:calculad|hech)"
    r"|no\s+es\s+(?:correct[oa]|cierto|verdad|asi)"
    r"|te\s+(?:has\s+)?equivoca"
    r"|(?:es|eso es|esta)\s+(?:incorrect[oa]|falso)"
    r"|no\s+(?:cuadra|tiene\s+sentido)"
    r"|(?:te\s+)?(?:lo\s+)?has\s+inventado|te\s+lo\s+inventas"
    r"|no\s+es\s+lo\s+que\s+(?:te\s+)?(?:he\s+)?pregunt"
    # en
    r"|(?:that|this|it)(?:'s|\s+is)\s+(?:wrong|incorrect|not\s+right|not\s+true)"
    r"|you(?:'re|\s+are)\s+wrong"
    r"|you\s+made\s+(?:that|it|this)\s+up"
    r"|(?:doesn't|does\s+not)\s+add\s+up"
    r"|not\s+what\s+i\s+asked"
    # it
    r"|(?:e|questo\s+e|e\s+tutto)\s+sbagliat"
    r"|non\s+e\s+(?:corrett|vero|giust)"
    r"|ti\s+sbagli"
    r"|non\s+torna"
    r"|(?:l'hai|hai)\s+inventat"
    r"|non\s+e\s+quello\s+che\s+ho\s+chiesto"
    r")"
)

_WORD = re.compile(r"[a-z0-9]{3,}")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def text(content: object) -> str:
    """A message's words: a string, or the text parts of a multimodal list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") for p in content
                         if isinstance(p, dict))
    return ""


def pool(system: str, messages: Iterable[dict]) -> list[float]:
    """Every distinct number in what the model was shown."""
    seen: set[float] = set()
    for chunk in (system, *(text(m.get("content")) for m in messages)):
        seen.update(round(n, _POOL_DIGITS) for n in prod_eval.numbers(chunk))
    return list(seen)


def figures(answer: str, shown: list[float]) -> tuple[int, int]:
    """(figures the answer states, those nothing shown states) — the same
    skips as the eval: years, small counts, windows, links."""
    stated = prod_eval.unsourced(answer, [])
    if not stated:
        return 0, 0
    return len(stated), len(prod_eval.unsourced(answer, shown))


def check_answer(answer: str, *, system: str, messages: Iterable[dict],
                 provider: str, model: str, skills: Iterable[str],
                 route: str = "", profile: str = "", answer_id: str = "") -> bool:
    """Log the stored answer as `figures` when FLAG_AT or more of its figures
    come from nowhere the model was shown. True when it was."""
    try:
        stated, loose = figures(answer, pool(system, messages))
        if loose >= FLAG_AT:
            obs.event(EVENT, kind="figures", answer=answer_id, figures=stated,
                      unsourced=loose, provider=provider, model=model,
                      skills=list(skills), route=route, profile=profile)
            return True
    except Exception as exc:  # a lead lost, never an answer
        obs.warn("chat.review_failed", step="figures",
                 error_type=type(exc).__name__)
    return False


def _words(text: str) -> set[str]:
    return set(_WORD.findall(_fold(text)))


def check_question(history: list[dict]) -> None:
    """Read the newest question (`history[-1]`) as a verdict on the answer
    right above it: `complaint` when it says that answer was wrong,
    `rephrase` when it asks the question before it again. Only an answer a
    model wrote is judged — it is the one with an `id`."""
    try:
        if len(history) < 3:
            return
        new, above, before = history[-1], history[-2], history[-3]
        if (new.get("role") != "user" or above.get("role") != "assistant"
                or before.get("role") != "user"):
            return
        answer = str(above.get("id") or "")
        if not answer:
            return
        said = text(new.get("content"))

        def flag(kind: str) -> None:
            obs.event(EVENT, kind=kind, answer=answer,
                      provider=str(above.get("provider") or ""),
                      skills=[str(s) for s in above.get("skills") or []])

        if _COMPLAINT.search(_fold(said)):
            flag("complaint")
            return
        now, then = _words(said), _words(text(before.get("content")))
        if min(len(now), len(then)) < REPHRASE_MIN_WORDS:
            return
        if len(now & then) / len(now | then) >= REPHRASE_AT:
            flag("rephrase")
    except Exception as exc:
        obs.warn("chat.review_failed", step="question",
                 error_type=type(exc).__name__)


# --------------------------------------------------------------------- judge

#: The Profile setting that keeps an account's answers from the judge.
PREF = "review_answers"

# Share of the free chain's answers judged when nothing flagged them.
SAMPLE = 0.05
# Answers judged per process per day, flagged ones included. A judgment is
# one call of a few thousand tokens on the pot every reader answers from.
DAILY_CAP = 40
# What of the prompt the judge reads, by part: the question as sent (the
# reader's words with the evidence stapled on), the book, the tools called.
_ASKED_CHARS = 4000
_BOOK_CHARS = 2500
_STEPS_CHARS = 1500
# The question and the answer themselves, so one long answer cannot push the
# judge's prompt past what the free chain's small models take.
_QUESTION_CHARS = 1500
_ANSWER_CHARS = 6000

_lock = threading.Lock()
_spent: dict[str, int] = {}
_resting: set[str] = set()
_pending: set[Future] = set()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-review")


def wanted(prefs: dict) -> bool:
    """The account leaves its answers to be reviewed — every check here, the
    counts as much as the judge: a lead is what gets an answer read."""
    return prefs.get(PREF) is not False


def judge_mode() -> str:
    """`on` only when the deploy says so; anything else is `off`."""
    said = secret("CHAT_REVIEW_JUDGE", "review", "judge", "off").lower()
    return "on" if said == "on" else "off"


def material(system: str, messages: list[dict], steps: Iterable[dict]) -> str:
    """What the answering model was shown, cut to what a judge can read: the
    newest message as sent, the book's part of the system prompt
    (`llm.Prompt.blocks`: persona, book, the turn's part) and the tools it
    called with their short results — the full results are not kept, so an
    answer from a tool loop is judged on less than its model saw."""
    parts = []
    if messages:
        parts.append("Question as sent, with what was fetched for it:\n"
                     + text(messages[-1].get("content"))[:_ASKED_CHARS])
    blocks = getattr(system, "blocks", ())
    if len(blocks) >= 3:
        parts.append("The reader's book:\n" + blocks[1][:_BOOK_CHARS])
    called = "\n".join(f"- {s.get('tool')}({s.get('arg') or ''}): {s.get('out') or ''}"
                       for s in steps if isinstance(s, dict))
    if called:
        parts.append("Tools called:\n" + called[:_STEPS_CHARS])
    return "\n\n".join(parts)


def _take() -> bool:
    """A judgment out of today's budget, if there is one left."""
    day = time.strftime("%Y-%m-%d")
    with _lock:
        if day in _resting or _spent.get(day, 0) >= DAILY_CAP:
            return False
        if day not in _spent:
            _spent.clear()  # yesterday's count
            _spent[day] = 0
        _spent[day] += 1
        return True


def judge_answer(answer_id: str, question: str, answer: str, *,
                 system: str, messages: list[dict], steps: Iterable[dict],
                 provider: str, skills: Iterable[str], prefs: dict,
                 flagged: bool) -> Future | None:
    """Queue the stored answer for the judge, when it is due one (see the
    module). Returns the queued judgment, None when there is none."""
    try:
        if provider != "free" or not wanted(prefs) or judge_mode() != "on":
            return None
        reason = "figures" if flagged else "sample" if random.random() < SAMPLE else ""
        if not reason or not _take():
            return None
        shown = material(system, messages, steps)
        tools = sum(1 for s in steps if isinstance(s, dict))
        # The worker starts with an empty context: who and which turn only.
        where = {k: v for k, v in obs.current().items() if k in ("user", "turn")}
        future = _pool.submit(_judge, where, answer_id, question, answer,
                              shown, list(skills), reason, tools)
    except Exception as exc:
        obs.warn("chat.review_failed", step="queue",
                 error_type=type(exc).__name__)
        return None
    done = threading.Event()
    with _lock:
        _pending.add(future)

    def settle(f: Future) -> None:
        with _lock:
            _pending.discard(f)
        done.set()

    future.add_done_callback(settle)
    # A plain request's answer: held while it is judged, like a background
    # refresh (`api.holds.keep`). A detached run's is held by its own hold.
    if cache.on_background is not None:
        cache.on_background(done)
    return future


def judging() -> bool:
    """A judgment is queued or running in this process."""
    with _lock:
        return bool(_pending)


def _judge(where: dict, answer_id: str, question: str, answer: str,
           shown: str, skills: list[str], reason: str, tools: int) -> None:
    with obs.context(**where):
        try:
            said = agent_judge.judge(
                llm.PROVIDERS["free"], "", (), question[:_QUESTION_CHARS], [],
                answer[:_ANSWER_CHARS], material=shown)
        except llm.FreeTierExhausted as exc:
            # The pot is empty for readers too: no more judging today.
            with _lock:
                _resting.add(time.strftime("%Y-%m-%d"))
            obs.warn("chat.review_failed", step="judge",
                     error_type=type(exc).__name__)
            return
        except Exception as exc:
            obs.warn("chat.review_failed", step="judge",
                     error_type=type(exc).__name__)
            return
        scores = said.scores
        obs.event(EVENT, kind="judged", answer=answer_id, provider="free",
                  skills=skills, reason=reason, tools=tools,
                  answer_quality=scores.get("answer_quality"),
                  grounded=scores.get("grounded"), tone=scores.get("tone"))


def find(book: dict, answer_id: str) -> tuple[str, dict] | None:
    """The question and the stored answer a `chat.review` line names by its
    `answer` id, from an account's chat book (`conversations.load_book`)."""
    for conv in book.get("conversations") or []:
        asked = ""
        for m in conv.get("messages") or []:
            if m.get("role") == "user":
                asked = text(m.get("content"))
            elif m.get("role") == "assistant" and m.get("id") == answer_id:
                return asked, m
    return None


def _reset() -> None:
    """Forget today's budget and pause. Tests only."""
    with _lock:
        _spent.clear()
        _resting.clear()
