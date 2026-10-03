"""Ledger words on their way to a preview table (stocks.web.tx_text)."""

import pytest

from stocks.portfolio.validate import Issue
from stocks.web import i18n, tx_text


def test_action_labels_translate_and_unknown_verbs_pass_through():
    assert tx_text.action_label("sell", "es") == "venta"
    assert tx_text.action_label("transfer", "es") == "transfer"


def test_issue_text_translates_key_and_parameters():
    issue = Issue(
        "error", "quantity", "validate.oversell",
        {"quantity": "20", "held": "1.0000", "date": "2024-12-31"},
    )
    text = tx_text.issue_text(issue, "es")
    assert text.startswith("vende 20 pero")
    assert "2024-12-31" in text
    # The English rendering is untouched — the CLI still prints that one.
    assert "only 1.0000 were held" in issue.message


def test_issue_text_translates_the_action_inside_a_message():
    issue = Issue(
        "warning", "near_duplicate", "validate.near_duplicate",
        {"action": "buy", "quantity": "5", "ticker": "AAPL",
         "date": "2025-01-03"},
    )
    assert "una compra de 5 AAPL" in tx_text.issue_text(issue, "es")


def test_english_is_the_source_language():
    assert tx_text.action_label("sell") == "sell"
    assert tx_text.action_label("sell", "en") == "sell"


# Every branch of each parser's `_skip_reason`, by a type that reaches it.
_SKIP_TYPES = {
    "revolut": [
        "STOCK SPLIT", "DIVIDEND TAX (CORRECTION)",
        "REWARD", "CUSTODY FEE", "CASH TOP-UP", "CASH WITHDRAWAL", "SOMETHING NEW",
    ],
    "trading212": [
        "Stock split open", "Deposit", "Withdrawal", "Interest on cash",
        "Currency conversion", "Result adjustment", "Something new",
    ],
    "revolut_crypto": ["Reward", "Staking", "Exchange", "Send", "Something new"],
}


@pytest.mark.parametrize("parser", sorted(_SKIP_TYPES))
def test_every_reason_a_parser_skips_with_is_named(parser):
    """A reason that drifts from the table prints in English on a Spanish
    page, and nothing else would notice."""
    import importlib

    module = importlib.import_module(f"stocks.portfolio.{parser}")
    for rtype in _SKIP_TYPES[parser]:
        reason = module._skip_reason(rtype)
        assert reason in tx_text.SKIP_REASONS, (rtype, reason)


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_named_reason_ships_a_name_and_a_why(lang):
    import json
    from pathlib import Path

    catalog = json.loads(
        (Path(i18n.__file__).parent / "locales" / lang / "import.json").read_text(
            encoding="utf-8"
        )
    )
    for stem, _ in tx_text.SKIP_REASONS.values():
        assert stem in catalog and f"{stem}_note" in catalog, stem


def test_a_skip_reads_in_the_reader_language_and_an_unnamed_one_as_written():
    cash = "cash movement — not position-affecting"
    assert tx_text.skip_text(cash, "es").startswith("Movimientos de efectivo — ")
    assert tx_text.skip_reason(cash) == ("import.skip_cash", False)
    assert tx_text.skip_reason(
        "dividend tax correction — arrives in +/- pairs, review manually"
    ) == ("import.skip_div_tax", True)
    assert tx_text.skip_text("no symbol", "es") == "no symbol"
    assert tx_text.skip_reason("no symbol") == (None, False)
