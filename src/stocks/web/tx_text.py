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
"""

from __future__ import annotations

from collections.abc import Iterable

from stocks.web.i18n import t


def action_label(action: str) -> str:
    """"buy" -> "compra". Unknown verbs pass through unchanged."""
    key = f"import.action_{action}"
    label = t(key)
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


def issue_text(issue) -> str:
    """One validation issue in the reader's language."""
    params = dict(issue.params)
    if "action" in params:
        params["action"] = action_label(params["action"])
    return t(issue.key, **params) if params else t(issue.key)


def issues_text(issues: Iterable) -> str:
    return "; ".join(issue_text(i) for i in issues)
