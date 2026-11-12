"""A broker statement becoming ledger rows, and undoing an import."""

from __future__ import annotations

from pydantic import BaseModel, Field

from stocks.schemas.book import Transaction

# ---------------------------------------------------------------- the importer
# A broker statement becoming ledger rows. The tiers are the safety property:
# a bad export must not be able to corrupt a cost basis quietly, so rows that
# failed validation are quarantined and reported rather than dropped or
# committed.


class ImportPlatform(BaseModel):
    key: str = Field(description="Stable id; what a preview or commit is asked for.")
    label: str
    file_types: list[str] = Field(description="Extensions this parser accepts.")
    hint: str = Field(description="Where to find the export on that platform.")
    domain: str | None = Field(default=None, description="Brand site, for a logo.")
    logo: str | None = Field(
        default=None,
        description=(
            "The brand mark, same-origin where this host could mirror it (the "
            "external URL otherwise) — what the Import page's picker draws "
            "beside each name. Null for a platform with no brand, and the client "
            "prints the name alone."
        ),
    )
    has_sample: bool = Field(
        default=False, description="Whether a shipped example export exists."
    )


class ImportPlatforms(BaseModel):
    platforms: list[ImportPlatform] = Field(default_factory=list)
    accepts: list[str] = Field(
        default_factory=list,
        description=(
            "Every extension a statement can arrive as, whichever platform is "
            "picked: the model reads first and every parser is its check, so a "
            "platform's own `file_types` is what it exports, not a limit."
        ),
    )


class ImportIssue(BaseModel):
    severity: str = Field(description="error | warning.")
    field: str
    key: str = Field(description="i18n key, e.g. `validate.oversell`.")
    params: dict = Field(default_factory=dict)
    message: str = Field(
        description="English rendering. A client with a catalog should use `key`."
    )


class ImportRow(BaseModel):
    date: str
    ticker: str
    action: str
    quantity: float
    price: float
    currency: str
    fee: float = 0.0
    note: str = ""
    issues: list[ImportIssue] = Field(default_factory=list)
    duplicate: bool = Field(
        default=False, description="Repeats a row the ledger already holds."
    )
    gain: float | None = Field(
        default=None,
        description=(
            "How the row has done, as a fraction, in its own currency: a buy "
            "against today's quote (its fee in the cost), a sell against the "
            "FIFO cost it realized from the book plus this batch. Null for "
            "every other action, and when there is no quote in the row's "
            "currency or the book cannot cover the sale."
        ),
    )


class ImportHolding(BaseModel):
    """One line of a holdings snapshot: held, but never dated."""

    row: int
    ticker: str = Field(
        description="The symbol, else the ISIN when no symbol was printed."
    )
    isin: str = ""
    quantity: float
    currency: str = Field(
        default="", description="As the file named it; empty when it did not."
    )
    cost: float | None = Field(
        default=None,
        description=(
            "Average price paid per share, when a column says so. Null when the "
            "file prints none: a bare price in a holdings report is today's."
        ),
    )


class ImportPreview(BaseModel):
    """What a statement would do, having changed nothing.

    Three tiers, and they are not a presentation detail: `rejected` rows failed
    validation and are never committed, so a client that shows only a count has
    hidden the part the reader has to act on.
    """

    platform: str = Field(
        description=(
            "What read the file: a key from `/import/platforms`, or `llm` for "
            "the model. Not always the platform the request named — that one "
            "is only tried first."
        )
    )
    label: str = Field(
        default="",
        description="The parser's display name. Empty when the model read it.",
    )
    kind: str = Field(
        default="none",
        description=(
            "What the document turned out to be: `trades`, `positions` (a "
            "holdings report, with no dated movement to import) or `none`."
        ),
    )
    unavailable: bool = Field(
        default=False,
        description=(
            "The model was never reached, so only the parsers judged the file. "
            "Not the same as a file with nothing in it."
        ),
    )
    filename: str
    digest: str = Field(
        description=(
            "SHA-256 of the uploaded bytes. Pass it back as `expect` on commit "
            "to be told, rather than guess, whether you are committing the file "
            "you previewed."
        )
    )
    importable: list[ImportRow] = Field(
        default_factory=list,
        description=(
            "Clean and warned rows. A commit writes those not flagged "
            "`duplicate`, and the duplicates too only with `keep_duplicates`."
        ),
    )
    rejected: list[ImportRow] = Field(
        default_factory=list,
        description="Failed validation: quarantined, never committed.",
    )
    duplicates: int = Field(
        default=0, description="Importable rows the ledger already holds."
    )
    skipped: list[dict] = Field(
        default_factory=list,
        description=(
            "Rows the parser leaves out by design: cash, fees, tax lines. Each "
            "keeps the parser's own fields, plus `reason_key` — the catalog "
            "stem naming its `reason` (`<stem>` the kind of row, `<stem>_note` "
            "why), null for a reason no catalog names yet — and `manual`, "
            "whether it leaves the reader a step to take by hand."
        ),
    )
    broker: str = Field(
        default="",
        description=(
            "Origin detected from the rows' own notes. Empty means the parser "
            "stamped none — a generic CSV can come from anywhere — and a commit "
            "has to be told which broker, or the batch lands unattributed in the "
            "fees and custody views."
        ),
    )
    needs_broker: bool = Field(
        default=False, description="Whether a commit must supply `broker`."
    )
    holdings: list[ImportHolding] = Field(
        default_factory=list,
        description=(
            "With `kind` `positions`, what the report says is held. Nothing to "
            "commit as it is: each becomes a buy once dated, and "
            "`/import/buy-dates` offers the days its price was on the board."
        ),
    )
    unlisted: list[str] = Field(
        default_factory=list,
        description=(
            "Tickers of importable rows Yahoo positively said it does not list "
            "— a bare broker code, usually. They import, but hold at cost with "
            "no price until the code is mapped to a Yahoo symbol. A lookup that "
            "could not be asked (throttled, out of time) puts nothing here."
        ),
    )
    doubted: list[str] = Field(
        default_factory=list,
        description=(
            "Tickers the model gave importable rows whose prices sit far from "
            "that name's closes on the days they traded: possibly another "
            "company. Their rows carry `validate.ticker_doubt`; the reader "
            "confirms or corrects each through `/import/ticker`. Only on a "
            "statement the model read, and only where the closes could be asked."
        ),
    )


class ImportResult(BaseModel):
    platform: str
    filename: str
    imported: int = Field(description="Rows written to the ledger.")
    duplicates: int = Field(
        default=0,
        description=(
            "Rows left out because the ledger already held them. Zero when "
            "the commit asked for `keep_duplicates`."
        ),
    )
    tx_ids: list[int] = Field(
        default_factory=list, description="Ledger ids, which is what an undo needs."
    )
    broker: str
    imported_at: str
    rejected: list[ImportRow] = Field(
        default_factory=list,
        description=(
            "Re-validated at commit time and refused. Reported rather than "
            "silently dropped: the ledger moved since the preview, and a row "
            "that passed then can fail now."
        ),
    )


class LastImport(BaseModel):
    """The most recent committed batch, or nothing.

    Kept so an import can be undone exactly — those ids and no others — rather
    than by guessing which rows a file put there.
    """

    filename: str | None = None
    imported_at: str | None = None
    imported_on: str | None = Field(
        default=None,
        description="The UTC day of `imported_at` (YYYY-MM-DD), shared by every page.",
    )
    platform: str | None = None
    rows: int = 0
    still_here: int = Field(
        default=0,
        description=(
            "How many of those rows are still in the ledger. Rows can leave "
            "after a commit — deleted one by one, or taken by another undo — "
            "and an offer to undo a batch has to be an offer to undo what is "
            "actually there."
        ),
    )
    transactions: list[Transaction] = Field(
        default_factory=list,
        description=(
            "Those surviving rows themselves, so the reader can see what an "
            "undo would take rather than trust a count."
        ),
    )
    wiped: bool = Field(
        default=False, description="Whether the ledger was cleared just before it."
    )


class LedgerCleared(BaseModel):
    """What a wipe destroyed, said in numbers because nothing else is left."""

    removed: int = Field(description="Transactions deleted.")
