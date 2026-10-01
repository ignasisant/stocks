"""Ledger vocabulary in the reader's language.

A transaction is stored in one vocabulary and one only: English column names
(`quantity`, `fee`) and canonical action verbs (`buy`, `split`). The ledger,
the parsers, the CLI and every test agree on those words, and nothing here
changes that — the import previews are simply the one screen where a reader
meets them, so they are translated on the way to the table and nowhere else.

That means the frames keep their English column names (`fmt`, `title` and the
mobile specs all key on them) and only the rendered header text changes, via
the `labels` argument the table widgets already take. Validation issues work
the same way: `validate.Issue` carries a catalog key and its parameters, and
`issue_text` renders it here instead of the English fallback the CLI prints.

`lang` is for callers outside a Streamlit run (the HTTP API), where `t` has no
session to read a language from and every string came out in English.
"""

from __future__ import annotations

from collections.abc import Iterable

from stocks.web.i18n import t, translate


def _t(key: str, lang: str | None, **kwargs) -> str:
    return translate(key, lang, **kwargs) if lang else t(key, **kwargs)


def action_label(action: str, lang: str | None = None) -> str:
    """"buy" -> "compra". Unknown verbs pass through unchanged."""
    key = f"import.action_{action}"
    label = _t(key, lang)
    return action if label == key else label


def labels(*columns: str) -> dict[str, str]:
    """column -> header text, for the tables' `labels` argument.

    Columns with no catalog entry are left out, so the widget falls back to
    the raw name — a statement column nobody has named yet still renders.
    """
    out: dict[str, str] = {}
    for c in columns:
        label = t(f"import.col_{c}")
        if label != f"import.col_{c}":
            out[c] = label
    return out


def issue_text(issue, lang: str | None = None) -> str:
    """One validation issue in the reader's language."""
    params = dict(issue.params)
    if "action" in params:
        params["action"] = action_label(params["action"], lang)
    return _t(issue.key, lang, **params)


def issues_text(issues: Iterable, lang: str | None = None) -> str:
    return "; ".join(issue_text(i, lang) for i in issues)


# A skipped row's reason, as the parsers word it, to the catalog stem that says
# it in the reader's language — `<stem>` names the kind of row, `<stem>_note`
# why it stayed out — and whether it leaves the reader a step to take by hand.
# Matched whole, never by prefix: Revolut's "reward —" is a cash credit and
# Revolut crypto's is an acquisition. A reason missing here still shows, in the
# parser's English.
SKIP_REASONS: dict[str, tuple[str, bool]] = {
    "cash movement — not position-affecting": ("import.skip_cash", False),
    "reward — cash credit, not position-affecting": ("import.skip_reward", False),
    "interest — cash credit, not position-affecting": ("import.skip_interest", False),
    "currency conversion — not position-affecting": ("import.skip_fx", False),
    "fee row — add manually if you want it in cost basis": ("import.skip_fee", False),
    "unrecognised type — not imported": ("import.skip_unknown", False),
    "not a stock/ETF trade": ("import.skip_not_stock", False),
    "moved in or out of staking — the same coins, no acquisition and no "
    "disposal; nothing to import": ("import.skip_staking", False),
    "accrued dividend — not cash yet; it imports from the Dividends section "
    "of the statement covering its pay date": ("import.skip_accrued", False),
    "stock split — ratio derived at validation, or add manually": (
        "import.skip_split",
        True,
    ),
    "dividend tax correction — arrives in +/- pairs, review manually": (
        "import.skip_div_tax",
        True,
    ),
    "return of capital — reduces cost basis, adjust manually": (
        "import.skip_capital",
        True,
    ),
    "result adjustment — review manually": ("import.skip_adjustment", True),
    "reward — an acquisition at market value (taxable income in Spain); add "
    "manually as a buy at the reward-day price": ("import.skip_coin_reward", True),
    "coin-to-coin exchange — fiscally a sell plus a buy; add both legs "
    "manually at the exchange-day prices": ("import.skip_coin_swap", True),
    "transfer — moves coins without a price; adjust manually if it was a "
    "disposal": ("import.skip_coin_transfer", True),
    "withholding tax — set it as the fee on the matching dividend row for the "
    "double-tax credit": ("import.skip_withholding", True),
}


def skip_reason(reason: str) -> tuple[str | None, bool]:
    """(catalog stem, needs a step by hand) for a skip's reason; no stem for
    one nobody has named yet."""
    return SKIP_REASONS.get(reason, (None, False))


def skip_text(reason: str, lang: str | None = None) -> str:
    """A skip's reason in the reader's language, the parser's own when unnamed."""
    stem, _ = skip_reason(reason)
    if stem is None:
        return reason
    return f"{_t(stem, lang)} — {_t(f'{stem}_note', lang)}"
