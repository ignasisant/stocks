"""Work out which parser an uploaded statement needs, without asking.

The Import page has the user pick their broker first; the assistant can't —
a file arrives in chat with nothing but its name. So every registered parser
whose extensions match is simply *tried*, and the first one that yields
transactions wins.

Order is by strictness, not by registry position. Most parsers key off exact
headers (Trading 212, DEGIRO, IBKR, ClickTrade) and decline anything they
don't own, so they go first in whatever order the registry lists them. Three
resolve their columns by *alias* and are permissive enough to claim each
other's files — generic.py, Revolut stocks and Revolut crypto — so they go
last, and only after their distinctive header has been sighted. That check is
not cosmetic: without it a Revolut *stock* statement is claimed by the crypto
parser, which imports NVO as the pair NVO-USD, and a ledger-format CSV is
claimed by the stock one, which drops its fees and notes.

That is the whole reason detection can't just reuse the registry order the
Import page shows: there the user has already said which broker it is.

Whatever no parser claims falls through to llm_map: one cheap call names the
columns, and the rows are converted in Python. That fallback is the reason an
arbitrary broker Excel or a hand-kept spreadsheet can be imported at all.

Detection is read-only — the caller still validates (validate.py) and previews
before anything reaches the ledger, exactly as the Import page does.

`read` is the order both HTTP surfaces use — the Import page and a file
attached to the chat: the model reads every statement first, and the parsers
read it too, as the check on the model. A parser that owns the file is exact
where the model is approximate (its fees, its split and sign rules, its broker
note), so it keeps the file whenever it found at least as many rows. The model
wins only when it found more — which is what a broker changing its layout
under a parser looks like — and that case is logged, because it is a parser
that needs fixing. `detect` is the older order (parsers, then the model for
what none owns).
"""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from stocks import obs
from stocks.portfolio import llm_map, platforms
from stocks.portfolio.statement import ParseResult

if TYPE_CHECKING:
    from stocks.web.llm import Provider

LLM_KEY = "llm"  # the "platform" recorded for a mapped import

# Parsers that accept a file on loose evidence, tried after every strict one.
# Anything not listed here is strict by assumption, which is the safe default:
# a new parser is tried early and simply declines files it doesn't own.
_LOOSE = ("generic", "revolut", "revolut_crypto")

# Header that must be present before a permissive parser is even tried — the
# one column that tells these three formats apart, since their alias resolvers
# won't. Checked on CSV headers only; the strict parsers need no fingerprint,
# and a file whose header can't be read is passed through rather than blocked.
_FINGERPRINT = {
    "generic": {"date", "ticker", "action"},
    "revolut": {"ticker", "price per share"},
    "revolut_crypto": {"symbol", "value"},
}


def _summarise(declined: dict[str, str]) -> str:
    """`degiro:KeyError, generic:no rows` — one flat log field, not a nesting."""
    return ", ".join(f"{k}:{v}" for k, v in declined.items())


@dataclass(frozen=True)
class Detected:
    """What the file turned out to be, and what came out of it."""

    result: ParseResult
    platform: str  # a platforms.py key, or LLM_KEY
    label: str  # display name for the preview ("Trading 212", "Column mapping")
    # What the document turned out to be (llm_map.KIND_*). "positions" is the
    # one worth telling the user about: a portfolio report holds no dated
    # movements, so "nothing to import" is the right answer, not a failure.
    kind: str = llm_map.KIND_NONE
    # True when the model was never reached, so the file was never judged.
    unavailable: bool = False
    # How a mapped export was read (`llm_map.Extraction`): the mapping, and
    # the file's columns by name. Empty for a dedicated parser and for a PDF.
    mapping: dict | None = None
    columns: tuple[str, ...] = ()

    @property
    def recognised(self) -> bool:
        return bool(self.result.transactions)


def _extension(filename: str) -> str:
    _, _, ext = filename.lower().rpartition(".")
    return ext


def _headers(filename: str, data: bytes) -> set[str]:
    """The CSV's header names, lowercased — empty for anything else."""
    if not filename.lower().endswith(".csv"):
        return set()
    grid = llm_map.read_grid(filename, data)
    return {c.strip().lower() for c in (grid[0] if grid else [])}


def _cascade() -> list:
    """Every platform, strict parsers first, the permissive ones last."""
    by_key = {p.key: p for p in platforms.PLATFORMS}
    strict = [p for p in platforms.PLATFORMS if p.key not in _LOOSE]
    return strict + [by_key[k] for k in _LOOSE if k in by_key]


def _order(prefer: str | None) -> list:
    """The cascade, with the platform the reader named tried first."""
    cascade = _cascade()
    if not prefer:
        return cascade
    return ([p for p in cascade if p.key == prefer]
            + [p for p in cascade if p.key != prefer])


def _parsers(filename: str, data: bytes, prefer: str | None = None,
             ) -> tuple[Detected | None, Detected | None, dict[str, str]]:
    """The first parser that yields transactions, if any.

    Also returns what the `prefer` platform made of the file when it found
    nothing to import — its skipped lines, or the error it raised, say why,
    which beats "nothing recognised" when the model found nothing either — and
    why each parser passed on it.

    `prefer` only reorders: the permissive parsers still need their
    fingerprint, because on the Import page the platform is preselected and
    naming it is not proof the file is from it. A named parser whose
    fingerprint is missing still runs, for its reason only: "missing column
    date" is what the reader who picked it needs to hear.
    """
    ext = _extension(filename)
    head = _headers(filename, data)
    # Why each parser passed on the file. A decline is ordinary — that is how
    # the cascade works — but when *every* parser declines, this is the only
    # record of what they each objected to, and the file itself is never kept.
    declined: dict[str, str] = {}
    quiet: Detected | None = None
    for platform in _order(prefer):
        if ext not in platform.file_types:
            continue
        need = _FINGERPRINT.get(platform.key)
        foreign = bool(need and head and not need <= head)
        if foreign and platform.key != prefer:
            continue
        try:
            result = platform.parse(filename, data)
        except Exception as exc:  # noqa: BLE001 — a choking parser has declined
            declined[platform.key] = type(exc).__name__
            if platform.key == prefer:
                quiet = Detected(ParseResult(skipped=[{
                    "row": 0, "type": "file",
                    "reason": f"{platform.label} could not read this file: {exc}"[:300],
                }]), platform.key, platform.label)
            continue
        if foreign:
            # The named parser, on a file without its headers: run for its own
            # account of what is missing ("no date column"), never for rows.
            if result.skipped:
                quiet = Detected(ParseResult(skipped=result.skipped),
                                 platform.key, platform.label)
            declined[platform.key] = "no fingerprint"
            continue
        if result.transactions:
            return (Detected(result, platform.key, platform.label,
                             llm_map.KIND_TRADES), quiet, declined)
        if platform.key == prefer:
            # Not even a skipped line is a file from another platform or the
            # wrong export, and saying so beats "nothing recognised".
            quiet = Detected(result if result.skipped else ParseResult(skipped=[{
                "row": 0, "type": "file",
                "reason": f"{platform.label} found no transactions in this file",
            }]), platform.key, platform.label)
        declined[platform.key] = "no rows"
    return None, quiet, declined


def _mapped(found: llm_map.Extraction) -> Detected:
    return Detected(found.result, LLM_KEY, "", found.kind, found.unavailable,
                    found.mapping, found.columns)


def _nothing() -> Detected:
    return Detected(
        ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": "no parser recognised this file",
        }]),
        LLM_KEY, "",
    )


def detect(filename: str, data: bytes, provider: Provider | None = None,
           api_key: str = "", mapping: dict | None = None) -> Detected:
    """Parse an uploaded statement with whichever parser understands it.

    `provider` enables the column-mapping fallback; without one, an
    unrecognised file comes back empty with a skip reason, never guessed at.
    `mapping` is a reader's correction of how the fallback read this same file:
    the parsers already declined it, so it goes straight to being applied.
    """
    if mapping is not None:
        return _mapped(llm_map.extract(filename, data, provider, api_key,
                                       mapping=mapping))
    ext = _extension(filename)
    parsed, _quiet, declined = _parsers(filename, data)
    if parsed is not None:
        obs.event("import.detect", winner=parsed.platform, ext=ext,
                  declined=_summarise(declined))
        return parsed

    obs.warn("import.detect", winner=None, ext=ext, declined=_summarise(declined),
             fallback="llm" if provider is not None else "none")

    if provider is None:
        return _nothing()
    return _mapped(llm_map.extract(filename, data, provider, api_key))


# ---------------------------------------------------------------- model first
# A statement is read twice by the model if nothing remembers the first read:
# the page previews again when the wipe box is ticked or the ledger moves, and
# a PDF costs up to MAX_PDF_CALLS calls a read. The rows, not the bytes, are
# kept — in memory, for minutes, under the account that uploaded them — and a
# read the model never answered is not kept at all, so an outage does not
# outlive itself.

MODEL_TTL_S = 600.0
MODEL_MAX = 32

_model_memo: OrderedDict[tuple, tuple[float, llm_map.Extraction]] = OrderedDict()
_model_lock = threading.Lock()


def forget() -> None:
    """Drop every remembered model read (tests; nothing else needs it)."""
    with _model_lock:
        _model_memo.clear()


def _model_read(filename: str, data: bytes, provider: Provider | None,
                api_key: str, scope: str) -> llm_map.Extraction | None:
    """The model's reading of the file, or None when there is no model.

    A model read that raises is a model that could not read: it comes back
    `unavailable`, never as an exception, because the parsers can still read
    the file without it.
    """
    if provider is None:
        return None
    key = (scope, hashlib.sha256(data).hexdigest(), _extension(filename),
           getattr(provider, "id", ""))
    now = time.monotonic()
    if scope:
        with _model_lock:
            hit = _model_memo.get(key)
            if hit is not None and now - hit[0] < MODEL_TTL_S:
                _model_memo.move_to_end(key)
                return copy.deepcopy(hit[1])
    try:
        found = llm_map.extract(filename, data, provider, api_key)
    except Exception as exc:  # noqa: BLE001 — the parsers still get their turn
        obs.warn("import.read.model_failed", error_type=type(exc).__name__,
                 ext=_extension(filename))
        return llm_map.Extraction(ParseResult(skipped=[{
            "row": 0, "type": "file",
            "reason": f"the assistant could not read this file: {exc}"[:300],
        }]), unavailable=True)
    if scope and not found.unavailable:
        with _model_lock:
            _model_memo[key] = (now, copy.deepcopy(found))
            _model_memo.move_to_end(key)
            while len(_model_memo) > MODEL_MAX:
                _model_memo.popitem(last=False)
    return found


def read(filename: str, data: bytes, provider: Provider | None = None,
         api_key: str = "", *, prefer: str | None = None,
         mapping: dict | None = None, scope: str = "") -> Detected:
    """Read a statement with the model first and the parsers as its check.

    Both read it; the reconciling rule is in the module docstring. When the
    model wins over a parser that also read the file, the rows take that
    parser's broker, because the parser recognising the layout is evidence of
    where it came from that the model's rows do not carry.

    `prefer` is the platform the reader named, tried before the cascade.
    `mapping` is a reader's correction of the model's column mapping: applied
    as given, with no model call and no second opinion. `scope` names whose
    read this is (the account's directory), which is what lets a repeat read
    of the same bytes reuse the model's answer; empty, nothing is remembered.
    Without a provider this is the parsers alone.
    """
    if mapping is not None:
        return _mapped(llm_map.extract(filename, data, provider, api_key,
                                       mapping=mapping))
    model = _model_read(filename, data, provider, api_key, scope)
    parsed, quiet, declined = _parsers(filename, data, prefer)
    by_model = len(model.result.transactions) if model is not None else 0
    by_parser = len(parsed.result.transactions) if parsed is not None else 0

    if parsed is not None and by_parser >= by_model:
        winner = parsed
    elif model is not None and by_model:
        winner = _mapped(model)
        origin = platforms.detected_broker(parsed.result.transactions) if parsed else ""
        if origin:
            winner = replace(winner, result=ParseResult(
                transactions=platforms.stamp_broker(model.result.transactions, origin),
                skipped=model.result.skipped,
            ))
    elif model is not None and model.kind == llm_map.KIND_POSITIONS:
        winner = _mapped(model)
    elif quiet is not None:
        # The parser's own account of every line it left out, and whether the
        # model was ever asked — "the assistant is down" is not "this file
        # holds nothing".
        winner = replace(quiet, unavailable=model is not None and model.unavailable)
    elif model is not None:
        winner = _mapped(model)
    else:
        winner = _nothing()
    if parsed is not None and winner is not parsed and parsed.result.isins:
        # The parser's read of the holdings table rides along whoever won: an
        # ISIN beside a code is the statement naming the security outright,
        # and the model's rows do not carry it.
        winner = replace(winner, result=replace(
            winner.result, isins={**parsed.result.isins, **winner.result.isins},
        ))

    fields: dict[str, Any] = {
        "winner": winner.platform if winner.recognised else None,
        "ext": _extension(filename),
        "model": by_model,
        "parser": by_parser,
        "parser_key": parsed.platform if parsed is not None else "",
        "unavailable": bool(model is not None and model.unavailable),
        "declined": _summarise(declined),
    }
    if winner.recognised:
        obs.event("import.read", **fields)
    else:
        obs.warn("import.read", **fields)
    if by_parser and winner.platform == LLM_KEY:
        # A parser read the file and read less of it than the model did: the
        # layout has moved under it, and the rows it missed are the evidence.
        obs.warn("import.read.parser_behind", **fields)
    return winner


def supported_types() -> tuple[str, ...]:
    """Every extension any parser accepts — what the uploader should allow."""
    seen = {t for p in platforms.PLATFORMS for t in p.file_types}
    seen.update({"xlsx", "pdf", "csv"})  # llm_map reads these even unrecognised
    return tuple(sorted(seen))
