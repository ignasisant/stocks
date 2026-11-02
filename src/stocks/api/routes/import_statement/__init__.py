"""Turning a broker statement into ledger rows, over HTTP.

The flow the page has always had: upload, read (writing nothing), validate
against the ledger, look at the tiers, commit. Split here into a preview and a
commit, because the safety property is that a reader — or a client — sees what
a file will do before it does it.

**The model reads first, and the parsers check it.** Every statement goes to
the column mapper (`portfolio.llm_map`) and to every parser that takes its
extension, and `autodetect.read` keeps whichever read more of it — a parser on
a tie, because a parser that owns the layout is exact where a model is only
likely. The platform the page's picker names is tried first and trusted no
further: a Revolut PDF whose layout moved under its parser still imports, read
by the model, instead of arriving as "0 rows", and the preview says who read
it. The chat's attachment runs this same read and this same validation
(`chat_attach` takes both from here), so a file that imports on one surface
imports on the other.

**The file arrives as base64 in a JSON body, not as multipart.** That is a
deliberate choice and not an oversight: a cross-site HTML form *can* send
multipart, so accepting it would hand back the CSRF hole that every other write
here avoids by requiring `application/json`. The ~33% encoding overhead is
nothing against a statement.

**Commit re-validates the rows it was shown.** Reading the file again would
be a second model call, whose answer can differ from the one previewed, on
whichever instance the request lands on rather than the one that remembers the
first. So a client sends back the preview's rows — which it could always do by
uploading them as a generic CSV — and they are rebuilt through the ledger's
`Transaction` and validated again against the ledger as it is now: the ledger
moves, and a row that was importable ten seconds ago may be a duplicate of one
another client just committed. A commit that sends the file instead is read
again (the model's answer is remembered for a few minutes per account, so this
is usually the preview's own read); `expect` lets it assert the bytes are the
ones it previewed. Nothing lets either assert the ledger is. What the ledger
already holds is left out unless the commit asks for it (`keep_duplicates`),
the same default the chat's attachment card has: re-importing an overlapping
statement adds what is new and nothing twice.

**Replacing a ledger is a confirmation, not a flag.** The page offers a
"wipe first" checkbox, and the two halves of it have to travel together: a
client that emptied the book with `DELETE /v1/portfolio/transactions` and then
failed to commit has destroyed a book nobody can restore and put nothing in
its place. So `commit` takes `wipe` — and takes `wipe_confirm` with it, the
signed-in address typed back, which is the same confirmation that route
demands, because "name the book you are emptying" is not a rule worth having
two versions of. Nothing is deleted until the statement has parsed, validated
and produced rows worth writing.

**The demo rows are never the baseline.** A commit clears them (an invented
cost basis must not mix into a real one), so validating an incoming batch
against them would be checking it against lots that are about to stop
existing — `demo.without`.

**The two repairs sit beside the import**, because a statement cannot express
either: splits the book never heard about (`stocks.portfolio.corporate`, which
prices every holding against Yahoo) and shares that only changed broker but
read as a sale (`stocks.portfolio.transfers`, from the ledger alone). Each
scans and each applies, and an apply names what it accepts: the scan shows the
evidence first, and a client that could only say "yes to everything" would be
a worse offer than the page it replaces.
"""

from __future__ import annotations

from fastapi import APIRouter

from stocks.api.routes.import_statement import (
    book_checkup,
    buy_dates,
    example,
    moves,
    splits,
    statements,
    venue_lines,
)
from stocks.api.routes.import_statement.lookups import (
    LOOKUP_BUDGET_S,
    _charted,
    _exists_memo,
    _Lookup,
    _ticker_exists,
)
from stocks.api.routes.import_statement.splits import (
    ApplySplits,
    SplitPick,
    splits_apply,
    splits_scan,
)
from stocks.api.routes.import_statement.statements import last, undo
from stocks.api.routes.import_statement.upload import (
    MAX_BYTES,
    MAX_ROWS,
    _held,
    _provider,
    _read,
)
from stocks.api.routes.import_statement.validation import (
    QUOTES_BUDGET_S,
    _place_isins,
    _retag,
    _validated,
)

__all__ = [
    "_charted",
    "_exists_memo",
    "_held",
    "_Lookup",
    "_place_isins",
    "_provider",
    "_read",
    "_retag",
    "_ticker_exists",
    "_validated",
    "ApplySplits",
    "last",
    "LOOKUP_BUDGET_S",
    "MAX_BYTES",
    "MAX_ROWS",
    "QUOTES_BUDGET_S",
    "SplitPick",
    "splits_apply",
    "splits_scan",
    "undo",
]

# Each leaf carries the "/import" prefix itself: an included router is not
# flattened, and the guest gate reads the innermost route's path, which must
# still say "/import/...".
router = APIRouter()
for _leaf in (
    statements,
    splits,
    book_checkup,
    venue_lines,
    moves,
    example,
    buy_dates,
):
    router.include_router(_leaf.router)
