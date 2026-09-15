"""Ledger words on their way to a preview table (stocks.web.tx_text)."""

import pytest

from stocks.portfolio.validate import Issue
from stocks.web import i18n, tx_text


@pytest.fixture
def spanish(monkeypatch):
    monkeypatch.setattr(i18n, "active_language", lambda: "es")


def test_action_labels_translate_and_unknown_verbs_pass_through(spanish):
    assert tx_text.action_label("sell") == "venta"
    assert tx_text.action_label("transfer") == "transfer"


def test_column_labels_skip_columns_nobody_named(spanish):
    labels = tx_text.labels("date", "why", "isin")
    assert labels == {"date": "fecha", "why": "motivo"}


def test_issue_text_translates_key_and_parameters(spanish):
    issue = Issue(
        "error", "quantity", "validate.oversell",
        {"quantity": "20", "held": "1.0000", "date": "2024-12-31"},
    )
    text = tx_text.issue_text(issue)
    assert text.startswith("venta de 20 sobre 1.0000")
    assert "2024-12-31" in text
    # The English rendering is untouched — the CLI still prints that one.
    assert "exceeds" in issue.message


def test_issue_text_translates_the_action_inside_a_message(spanish):
    issue = Issue(
        "warning", "near_duplicate", "validate.near_duplicate",
        {"action": "buy", "quantity": "5", "ticker": "AAPL",
         "date": "2025-01-03"},
    )
    assert "una compra de 5 AAPL" in tx_text.issue_text(issue)


def test_english_is_the_source_language(monkeypatch):
    monkeypatch.setattr(i18n, "active_language", lambda: "en")
    assert tx_text.action_label("sell") == "sell"
    assert tx_text.labels("why") == {"why": "why"}
