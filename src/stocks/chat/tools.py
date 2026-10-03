"""App operations the assistant can perform — the chat's tool registry.

Same architecture as the skill router (web/chat_skills.py): a keyword gate
keeps overhead at zero for normal analysis questions; when it hits, one cheap
classifier-model call turns the message into a structured Action — favorite a
ticker, set price alerts, put it in a group, add it to the watchlist, record a
position — which is then executed through the same helpers the profile editor
uses. Anything the parser can't turn into a valid action degrades to None and
the message flows on to the normal LLM answer: tools add a fast path, they
never block chat.

Each tool is one TOOLS entry: the catalog line the router reads, a parser that
turns the reply's JSON into validated args (returning None to reject), a
runner that applies it to the account's watchlist, and the locale key of its
confirmation. Adding a tool means adding an entry — the system prompt, the
valid-action list and the dispatch all derive from the registry.

The router prompt is deliberately a JSON contract rather than provider-native
tool calling: the keyless free chain hops across OpenAI-compatible backends
whose tool support varies, and Provider only exposes a text stream. A native
adapter can be added per provider later without touching the tools themselves.

Streamlit-free (auth is imported lazily inside the runners) so parsing stays
trivially testable; all UI — confirmation bubbles, i18n — lives in the two
surfaces that dispatch here (web/chat_core.py and chat/engine.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ConfigDict

from stocks.chat import structured

if TYPE_CHECKING:
    from stocks.web.llm import Provider

# Symbols as the app knows them: Yahoo tickers, broker codes, crypto pairs
# (BTC-EUR), class shares (BRK.B).
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")

# Cheap gate so the extra classifier call only happens when the message could
# plausibly be an action (EN + ES vocabulary). False positives are fine — the
# parser returns null and chat proceeds; false negatives just mean no action.
_GATE_RE = re.compile(
    r"favou?rit|\bfav\b|alert|av[ií]s|notif|\btag\b|etiquet|group|grupo|"
    r"watchlist|seguimiento|a[ñn]ad|agreg|quita|elimin|\badd\b|\bremove\b|"
    r"\bdrop\b|shares|acciones|particip|position|posici[oó]n|"
    r"precio medio|coste medio|cost basis|"
    # The book: rows the reader wants shown, fixed, removed or undone.
    r"transacci|transaction|operaci[oó]n|movimiento|\btrades?\b|borra|"
    r"\bedit|corrig|correct|cambia|fusion|\bmerge\b|traspas|transfer|"
    r"deshaz|deshacer|\bundo\b|revert|renombr|rename|duplicad|duplicate|"
    r"\blibro\b|ledger|arregl|\bfix\b|apunta|registra|\brecord\b|"
    r"\bbroker\b|historial",
    re.IGNORECASE,
)


def maybe_action(text: str) -> bool:
    """Whether the message is worth one classifier call."""
    return bool(_GATE_RE.search(text))


# Importing is not one of the actions below, and never will be: it needs the
# statement itself, not a sentence about it. This gate catches the ask
# ("import my trades", "importa las compras del pdf") so each surface can
# answer it deterministically — a model left to answer is free to describe an
# import that never happened, and has. The lookbehinds keep two Spanish
# homographs out of it: "(no) me importa" ("I (don't) care") and the noun
# "el importe" ("the amount"), which a book full of trades says often.
_IMPORT_VERB = re.compile(
    r"(?<!me )(?<!te )(?<!le )(?<!nos )(?<!el )(?<!los )(?<!un )(?<!del )"
    r"(?<!su )(?<!sus )(?<!estos )"
    r"\bimport(?:a|ar|arme|ame|as|amos|o|e|es|en|ed|ing|s)?\b|"
    r"\bcarga(?:r|me)?\b|\bsube\b|\bsubir\b|\bupload\b",
    re.IGNORECASE,
)
_IMPORT_OBJECT = re.compile(
    r"transacc|transaction|operaci[oó]n|operaciones|movimiento|\btrades?\b|"
    r"\bcompras?\b|\bventas?\b|extracto|statement|\bpdf\b|\bcsv\b|"
    r"\bexcel\b|\bxlsx\b|fichero|archivo|\bfile\b|cartera|portfolio",
    re.IGNORECASE,
)


def wants_import(text: str) -> bool:
    """Whether the message is asking for a statement to be imported.

    Deliberately not a Tool: there is nothing to execute here. The surfaces
    use it to answer with the one thing that does work — attach the file —
    instead of spending a model call on a request the model cannot fulfil.
    """
    return bool(_IMPORT_VERB.search(text) and _IMPORT_OBJECT.search(text))


@dataclass(frozen=True)
class Action:
    """One parsed app operation: which tool, on which symbol, with what.

    Tool-specific values live in `args` rather than in a field per tool, so
    the registry can grow without the dataclass growing with it. `alerts` and
    `tags` are exposed as properties because both surfaces read them by name.
    """

    kind: str
    ticker: str
    args: dict = field(default_factory=dict)

    @property
    def alerts(self) -> list[dict]:
        return self.args.get("alerts", [])

    @property
    def tags(self) -> list[str]:
        return self.args.get("tags", [])


# ------------------------------------------------------------------ parsers
# Each takes the classifier's decoded JSON object and returns this tool's
# validated args — or None to reject the whole action, which sends the message
# down the normal answer path.


def _no_args(data: dict) -> dict:
    return {}


def _clean_tags(raw) -> list[str]:
    out: list[str] = []
    for t in raw or []:
        t = str(t).strip()
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def _parse_alerts(data: dict) -> dict | None:
    alerts: list[dict] = []
    for a in data.get("alerts") or []:
        if not isinstance(a, dict) or a.get("type") not in ("above", "below"):
            continue
        try:
            price = float(a.get("price"))
        except (TypeError, ValueError):
            continue
        rule = {"type": a["type"], "price": price}
        if price > 0 and rule not in alerts:
            alerts.append(rule)
    return {"alerts": alerts} if alerts else None


def _parse_tags(data: dict) -> dict | None:
    tags = _clean_tags(data.get("tags"))
    return {"tags": tags} if tags else None


def _parse_name(data: dict) -> dict:
    """add_ticker's optional company name — absent is fine, blank is nothing."""
    name = str(data.get("name") or "").strip()[:60]
    return {"name": name} if name else {}


def _parse_position(data: dict) -> dict | None:
    """shares / cost, either or both. Rejects when neither is a usable number
    — "record my position" with no numbers is a question, not an action."""
    out: dict = {}
    for key in ("shares", "cost"):
        if data.get(key) is None:
            continue
        try:
            value = float(data[key])
        except (TypeError, ValueError):
            continue
        if value >= 0:
            out[key] = value
    return out or None


# ------------------------------------------------------------------ runners
# Applied to the account's own watchlist. Alerts and tags are additive: the
# entry's existing values are read back and merged, because auth.set_* replace.


def _holding(ticker: str, path: Path):
    from stocks.config import load_watchlist

    return next(
        (h for h in load_watchlist(path) if h.ticker.upper() == ticker), None
    )


def _auth():
    from stocks.web import auth  # deferred: keeps this module streamlit-free

    return auth


def _run_favorite(act: Action, path: Path) -> None:
    _auth().set_favorite(act.ticker, True, path)


def _run_unfavorite(act: Action, path: Path) -> None:
    _auth().set_favorite(act.ticker, False, path)


def _run_set_alerts(act: Action, path: Path) -> None:
    from dataclasses import asdict

    holding = _holding(act.ticker, path)
    existing = [
        {k: v for k, v in asdict(a).items() if v is not None}
        for a in (holding.alerts if holding else [])
    ]
    new = [a for a in act.alerts if a not in existing]
    _auth().set_alerts(act.ticker, existing + new, path)


def _run_tag(act: Action, path: Path) -> None:
    holding = _holding(act.ticker, path)
    _auth().set_tags(act.ticker, (holding.tags if holding else []) + act.tags, path)


def _run_untag(act: Action, path: Path) -> None:
    holding = _holding(act.ticker, path)
    drop = {t.lower() for t in act.tags}
    kept = [t for t in (holding.tags if holding else []) if t.lower() not in drop]
    _auth().set_tags(act.ticker, kept, path)


def _run_add_ticker(act: Action, path: Path) -> None:
    _auth().add_entry(act.ticker, act.args.get("name", ""), path)


def _run_remove_ticker(act: Action, path: Path) -> None:
    _auth().remove_entry(act.ticker, path)


def _run_set_position(act: Action, path: Path) -> None:
    _auth().set_position(
        act.ticker, act.args.get("shares"), act.args.get("cost"), path
    )


# ----------------------------------------------------------------- registry


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str  # the catalog line the router reads, fields included
    parse: Callable[[dict], dict | None]
    run: Callable[[Action, Path], None]
    reply_key: str  # locale key of the confirmation bubble


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "favorite",
            "add the ticker to favorites (pins it to the top of the dashboard).",
            _no_args, _run_favorite, "chat.action_favorited",
        ),
        Tool(
            "unfavorite",
            "remove the ticker from favorites.",
            _no_args, _run_unfavorite, "chat.action_unfavorited",
        ),
        Tool(
            "set_alerts",
            'price thresholds. Fill "alerts": [{"type": "above"|"below", '
            '"price": <number>}]. Direction from wording (below/under/drops/'
            "falls/baja/cae -> below; above/over/rises/hits/sube/llega -> "
            "above). Two bare prices -> the lower one below, the higher one "
            "above. One bare price -> above.",
            _parse_alerts, _run_set_alerts, "chat.action_alerts_set",
        ),
        Tool(
            "tag",
            'add the ticker to one or more groups. Fill "tags": ["<group>"]. '
            "Reuse the exact spelling of an existing group from the context "
            "when the user means it.",
            _parse_tags, _run_tag, "chat.action_tagged",
        ),
        Tool(
            "untag",
            'remove the ticker from groups it is in. Fill "tags": ["<group>"].',
            _parse_tags, _run_untag, "chat.action_untagged",
        ),
        Tool(
            "add_ticker",
            'put a symbol on the watchlist so the app tracks it. Optionally '
            'fill "name" with the company name.',
            _parse_name, _run_add_ticker, "chat.action_added",
        ),
        Tool(
            "remove_ticker",
            "stop tracking a symbol — drops it from the watchlist entirely.",
            _no_args, _run_remove_ticker, "chat.action_removed",
        ),
        Tool(
            "set_position",
            'record how much of the ticker the user holds. Fill "shares" '
            'and/or "cost" (average buy price per share) with numbers; omit '
            "the one the user didn't state, and use 0 to clear it.",
            _parse_position, _run_set_position, "chat.action_position_set",
        ),
    )
}

# ------------------------------------------------------------------ the book
# Edits to the ledger itself. Unlike the tools above these never run from the
# classifier's answer: the model only names what the reader means — which
# rows, in words (ticker, broker, dates) — and `chat/book.py` finds the rows,
# builds the edit (`stocks.portfolio.edits`), plans it and puts its impact in
# front of the reader. Every one is a proposal, on every surface, whatever
# the account's confirm setting: a misread watchlist tag costs a click, a
# misread delete costs a tax year.

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_TRADES = frozenset({"buy", "sell", "dividend", "fee", "split", "capital",
                     "transfer_in", "transfer_out"})


def _number(raw) -> float | None:
    try:
        value = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _book_args(data: dict) -> dict:
    """Every ledger field the reply carried that reads as what it claims to be.

    Shared by all the ledger tools — which fields each one needs is
    `chat/book.py`'s call, made with the book in hand. A value that does not
    read (a date like "ayer", a currency like "euros") is dropped rather than
    guessed: the reader sees the rows it selects before anything happens.
    """
    out: dict = {}
    for key in ("broker", "to_broker"):
        text = str(data.get(key) or "").strip().lower()
        if text and re.fullmatch(r"[\w.\-]{1,30}", text):
            out[key] = text
    for key in ("date", "since", "until", "new_date"):
        text = str(data.get(key) or "").strip()
        if _ISO_DAY.match(text):
            out[key] = text
    trade = str(data.get("trade") or "").strip().lower()
    if trade in _TRADES:
        out["trade"] = trade
    for key in ("quantity", "price", "fee", "new_quantity", "new_price", "new_fee"):
        if data.get(key) is not None and (value := _number(data[key])) is not None:
            out[key] = value
    currency = str(data.get("currency") or "").strip().upper()
    if _CURRENCY_RE.match(currency):
        out["currency"] = currency
    to = str(data.get("to") or "").strip().upper()
    if _TICKER_RE.match(to):
        out["to"] = to
    ids = []
    for raw in data.get("ids") or []:
        try:
            ids.append(int(str(raw).lstrip("#")))
        except (TypeError, ValueError):
            continue
    if ids:
        out["ids"] = sorted(set(ids))[:50]
    return out


@dataclass(frozen=True)
class BookTool:
    name: str
    summary: str  # the catalog line the router reads
    needs_ticker: bool = False


BOOK: dict[str, BookTool] = {
    t.name: t
    for t in (
        BookTool(
            "show_transactions",
            "list the recorded trades the user asks about. Narrow with "
            '"ticker", "broker", "trade", "since"/"until".',
        ),
        BookTool(
            "edit_transaction",
            "change a recorded trade. Say which with \"ticker\" plus any of "
            '"broker", "date", "trade", "ids"; put the corrected values in '
            '"new_date", "new_quantity", "new_price", "new_fee".',
        ),
        BookTool(
            "delete_transactions",
            "remove recorded trades. Say which with \"ticker\", \"broker\", "
            '"date" or "since"/"until", "trade", "quantity", "ids".',
        ),
        BookTool(
            "add_transaction",
            'record a trade the book is missing: "ticker", "trade" (buy, '
            'sell, dividend…), "quantity", "price", optional "date", '
            '"currency", "fee", "broker".',
            needs_ticker=True,
        ),
        BookTool(
            "rename_security",
            'book a company\'s rows under another symbol: "ticker" is the label '
            'now, "to" the one to use; "broker" to rename only that broker\'s.',
            needs_ticker=True,
        ),
        BookTool(
            "mark_transfer",
            "the user moved shares between brokers and the book shows a sale "
            'and a purchase instead: "ticker", optional "broker" (where they '
            'left) and "to_broker".',
            needs_ticker=True,
        ),
        BookTool(
            "move_position",
            "the user moved a holding to another broker and nothing was "
            'recorded: "ticker", "broker" (from), "to_broker", optional '
            '"date" and "quantity".',
            needs_ticker=True,
        ),
        BookTool(
            "check_book",
            "look for mistakes in the recorded trades (duplicates, transfers "
            "read as sales, one company under two symbols). Optional "
            '"ticker".',
        ),
        BookTool(
            "undo_change",
            "undo the last change made to the recorded trades.",
        ),
    )
}

KINDS = (*TOOLS, *BOOK)


def is_book(kind: str) -> bool:
    """Whether `kind` edits the ledger rather than the watchlist."""
    return kind in BOOK


def _catalog() -> str:
    lines = [f'- "{t.name}": {t.summary}' for t in TOOLS.values()]
    lines += [f'- "{t.name}": {t.summary}' for t in BOOK.values()]
    return "\n".join(lines)


# The reply's shape is BAML's (DetectAction in baml_src/chat.baml), appended
# after this by structured.render.
_SYSTEM = f"""You turn requests from a stock-tracker chat into ONE app action.

Actions:
{_catalog()}

Rules:
- "action" is null when the message is a question, opinion or analysis
  request rather than a request to change the app. When in doubt, null.
- "ticker": the symbol the action targets. Resolve "this"/"it" ("esto") from
  the context's ticker in focus; resolve company names against the watchlist
  listing and reuse the symbol exactly as listed there.
- Fill only the fields the chosen action names; leave the rest null.
- The recorded-trade actions ("show_transactions" … "undo_change") are for
  the user's trades as the app has them. Dates are YYYY-MM-DD; resolve
  "yesterday"/"in August" against the context's date. "broker" is a single
  lowercase word (degiro, ibkr, revolut). A row number the user quotes
  ("#123") goes in "ids".
"""


class ActionCall(structured.Contract):
    """The router's contract: which tool, on which symbol.

    ``extra="allow"`` because the tool-specific fields ("alerts", "tags",
    "shares"…) are the registry's business, not this model's — exactly like
    Action.args. The model only sees the ones DetectAction's reply class in
    baml_src/chat.baml declares, so a tool with a new field adds it there.
    Both keys are optional at this level so a shapeless answer still decodes
    and gets rejected by _action_from with a reason, instead of burning a
    repair call on a model that correctly answered "no action"
    ({"action": null}).
    """

    model_config = ConfigDict(extra="allow")

    action: str | None = None
    ticker: str | None = None


def _action_from(data: dict) -> Action | None:
    """An Action out of the router's decoded object, or None to reject it.

    None covers the whole "not an app operation" family — action null, an
    unknown tool, an unusable ticker, missing required fields — and sends the
    message down the normal answer path."""
    ticker = str(data.get("ticker") or "").strip().upper()
    book = BOOK.get(data.get("action"))
    if book is not None:
        if ticker and not _TICKER_RE.match(ticker):
            return None
        if book.needs_ticker and not ticker:
            return None
        return Action(book.name, ticker, _book_args(data))

    tool = TOOLS.get(data.get("action"))
    if tool is None:
        return None

    if not _TICKER_RE.match(ticker):
        return None

    args = tool.parse(data)
    if args is None:
        return None
    return Action(tool.name, ticker, args)


def parse_action(raw: str) -> Action | None:
    """An Action out of a classifier reply, defensively.

    The tolerant reading, for callers holding a reply and no provider:
    anything missing, unknown or malformed yields None."""
    try:
        call = structured.decode(raw, "DetectAction", ActionCall)
    except structured.OffContract:
        return None
    return _action_from(call.model_dump())


def detect(
    provider: Provider, api_key: str, message: str, context: str = ""
) -> Action | None:
    """Parse a message into an Action via the provider's cheapest model.

    None on any failure — network, bad JSON, no action — and the caller
    proceeds with the normal answer. Same BYOK key as the conversation.

    A reply that is not the requested object at all gets one repair turn
    (chat/structured.py); a reply that *is* the object and says "no action"
    does not, so the common case (a question, not a command) stays one call."""
    user = (context + "\n\n" if context else "") + f"User message: {message}"
    try:
        call = structured.ask(provider, api_key, "DetectAction", _SYSTEM, user,
                              ActionCall)
    except Exception:
        return None
    return _action_from(call.model_dump())


def execute(action: Action, path: Path | None = None) -> None:
    """Apply an Action to the account's watchlist."""
    p = path or _auth().watchlist_path()
    TOOLS[action.kind].run(action, p)


def _slots(action: Action, translate: Callable[..., str]) -> dict[str, str]:
    """The placeholders a tool's confirmation and proposal lines both fill."""
    if action.kind == "set_alerts":
        rules = ", ".join(
            translate(f"chat.action_alert_{a['type']}", price=f"{a['price']:g}")
            for a in action.alerts
        )
        return {"ticker": action.ticker, "rules": rules}
    if action.kind in ("tag", "untag"):
        return {"ticker": action.ticker, "groups": ", ".join(action.tags)}
    if action.kind == "set_position":
        parts = [
            translate(f"chat.action_position_{f}", value=f"{action.args[f]:g}")
            for f in ("shares", "cost")
            if f in action.args
        ]
        return {"ticker": action.ticker, "details": " · ".join(parts)}
    return {"ticker": action.ticker}


def reply(action: Action, translate: Callable[..., str]) -> str:
    """The confirmation bubble for an executed action.

    `translate(key, **kwargs) -> str` is the caller's own translator — the web
    panel passes its session-language `tr`, the Telegram bot one bound to the
    recipient's language — so this stays the single place that knows which
    locale key and which slots each tool's confirmation needs.
    """
    return translate(TOOLS[action.kind].reply_key, **_slots(action, translate))


def proposal(action: Action, translate: Callable[..., str]) -> str:
    """The question put to the reader before an action runs.

    The confirmation line asked in the future tense — "Add AAPL to
    favorites?" — under the same slots, so what is proposed and what is
    confirmed afterwards can never describe two different changes. Its key is
    the reply key with `action_` turned into `propose_`.
    """
    key = TOOLS[action.kind].reply_key.replace("chat.action_", "chat.propose_", 1)
    return translate(key, **_slots(action, translate))


def revise(action: Action, ticker: str | None, args: dict | None) -> Action | None:
    """The action as the reader edited it before approving, or None if unusable.

    Only the symbol and the tool's own fields can change, never the tool: an
    edit that turned "favorite" into "remove_ticker" would be a second action
    nobody was asked about. The edit goes back through the same parser the
    classifier's answer did, so a price of -5 or a symbol with a space in it is
    refused here exactly as it would have been refused there.
    """
    data = {**action.args, **(args or {}), "action": action.kind,
            "ticker": ticker if ticker is not None else action.ticker}
    return _action_from(data)


# ------------------------------------------------------------------- forms
# What a proposal card lets the reader change before approving, per tool:
# the symbol always, and these. Strings in the form (it is what an input
# holds), turned back into the tool's arguments by `args_from_form` and then
# parsed like any detection. `chat/a2ui.py` lays the fields out.

FORMS: dict[str, tuple[str, ...]] = {
    "set_position": ("shares", "cost"),
    "set_alerts": ("above", "below"),
    "tag": ("tags",),
    "untag": ("tags",),
    "add_ticker": ("name",),
}
NUMERIC_FIELDS = frozenset({"shares", "cost", "above", "below"})


def _figure(value) -> str:
    return format(value, ".12g") if isinstance(value, (int, float)) else ""


def form_of(action: Action) -> dict[str, str]:
    """The proposal as its card's fields hold it."""
    form = {"ticker": action.ticker}
    for name in FORMS.get(action.kind, ()):
        if name in ("above", "below"):
            rule = next((a for a in action.alerts if a["type"] == name), None)
            form[name] = _figure(rule["price"]) if rule else ""
        elif name == "tags":
            form[name] = ", ".join(action.tags)
        elif name in NUMERIC_FIELDS:
            form[name] = _figure(action.args.get(name))
        else:
            form[name] = str(action.args.get(name) or "")
    return form


def args_from_form(kind: str, form: dict) -> dict:
    """The card's fields as the tool's arguments, for `revise` to parse.

    A blank number is left out rather than read as zero: "0 shares" clears a
    position, and an emptied box is not the reader asking for that.
    """
    def text(name: str) -> str:
        return str(form.get(name) or "").strip()

    def figure(name: str):
        raw = text(name).replace(",", ".")
        return raw if raw else None

    if kind == "set_position":
        return {k: v for k in ("shares", "cost") if (v := figure(k)) is not None}
    if kind == "set_alerts":
        return {"alerts": [{"type": k, "price": v} for k in ("above", "below")
                           if (v := figure(k)) is not None]}
    if kind in ("tag", "untag"):
        return {"tags": [t.strip() for t in text("tags").split(",") if t.strip()]}
    if kind == "add_ticker":
        return {"name": text("name")}
    return {}


# A whole message that answers a pending proposal. Short on purpose: "sí, pero
# a 150" is a new instruction and goes to the classifier, not a yes.
_YES = frozenset({
    "si", "sí", "yes", "ok", "okay", "vale", "dale", "hazlo", "confirmo",
    "confirmar", "confirm", "adelante", "claro", "perfecto", "go", "do it",
    "go ahead", "yes please", "si por favor", "sí por favor", "sí hazlo",
    "si hazlo", "venga",
})
_NO = frozenset({
    "no", "nope", "cancel", "cancela", "cancelar", "cancelalo", "cancélalo",
    "mejor no", "dejalo", "déjalo", "olvidalo", "olvídalo", "no gracias",
    "no thanks", "never mind", "nevermind",
})


def verdict(text: str) -> bool | None:
    """True for a typed yes, False for a typed no, None for anything else."""
    said = re.sub(r"[^\w\sáéíóúüñ]", "", str(text or "").lower()).strip()
    said = re.sub(r"\s+", " ", said)
    if said in _YES:
        return True
    if said in _NO:
        return False
    return None
