"""PSD2 bank accounts: balances, connections and the consent dance."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ bank
# PSD2 account information: balances read from the user's own bank, which the
# ledger cannot see. Shaped for a card per connection, an account per row.


class BankAccount(BaseModel):
    """One account inside a consent, with its last read balance."""

    uid: str = Field(description="Opaque handle; the only id the bank hands out.")
    name: str = ""
    masked_id: str = Field(
        default="",
        description="IBAN down to what identifies it to its owner: ES12 ···· 3456.",
    )
    currency: str = ""
    product: str = ""
    balance: float | None = Field(
        default=None,
        description=(
            "The balance a person means by 'how much is in the account' — "
            "booked or available, whatever else the bank also reports. Null "
            "until the account has been read once, and null again when the "
            "bank's figure would not parse: a zero is a claim about somebody's "
            "money and 'unreadable' is not that claim."
        ),
    )
    balance_currency: str = ""
    fetched_at: str | None = Field(
        default=None,
        description=(
            "When that balance was read, ISO UTC. Banks cap fetches (commonly "
            "four a day), so the page shows a stored figure and says how old "
            "it is rather than refetching on every load."
        ),
    )


class BankConnection(BaseModel):
    """One bank, consented to once, until `valid_until`."""

    session_id: str
    name: str
    country: str
    valid_until: str = Field(
        default="", description="When the consent runs out, ISO. '' when unstated."
    )
    connected_at: str = ""
    expired: bool = Field(
        default=False,
        description=(
            "Whether that date has passed. Computed here because the same date "
            "is backdated when the bank refuses a fetch early, which is how a "
            "revoked consent becomes a reconnect offer instead of a dead button."
        ),
    )
    accounts: list[BankAccount] = Field(default_factory=list)


class BankState(BaseModel):
    """Everything the bank page draws."""

    available: bool = Field(
        description=(
            "Whether this account may use the feature. False is the ordinary "
            "answer and not a failure: the application runs in Enable Banking's "
            "restricted mode, so the gate is an allowlist that fails closed."
        )
    )
    redirect_url: str = Field(
        default="",
        description=(
            "Where the bank will send the user back to. '' when this host "
            "cannot offer one — banks only redirect to https, which is what "
            "makes a plain local dev server unable to start a consent."
        ),
    )
    connections: list[BankConnection] = Field(default_factory=list)


class BankChoice(BaseModel):
    """One bank that can be connected, from Enable Banking's own list."""

    name: str
    country: str
    logo: str | None = None


class BankAuth(BaseModel):
    """Where to send the user, and the round trip it belongs to."""

    url: str = Field(description="The bank's own authentication page.")
    bank: str
    state: str = Field(
        description=(
            "Echoed by the bank on the way back. Stored server-side too — this "
            "copy is for a client that wants to recognise its own round trip, "
            "never for proving one: the stored entry is the authority."
        )
    )
