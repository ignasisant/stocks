"""Instrument label -> ticker: what is answered locally, what the model answers,
and what is refused. No network: every test injects its own `ask`.
"""

from __future__ import annotations

import json

import pytest

from stocks.portfolio import instruments


@pytest.fixture(autouse=True)
def clear_memo():
    instruments._memo.clear()
    yield
    instruments._memo.clear()


def replying(answers, calls=None):
    """An `ask` that answers from `answers` and records what it was asked."""

    def ask(system, content):
        labels = json.loads(content)
        if calls is not None:
            calls.append(labels)
        return json.dumps({label: answers.get(label) for label in labels})

    return ask


def test_a_symbol_shaped_label_is_still_asked_about():
    """"AIRBUS" is six characters of a name column and "GOOGL" is a ticker;
    nothing in the strings tells them apart, so both are asked about."""
    calls = []
    out = instruments.resolve(
        ["AAPL", "AIRBUS"], None,
        ask=replying({"AAPL": "AAPL", "AIRBUS": "AIR.PA"}, calls))
    assert out == {"AAPL": "AAPL", "AIRBUS": "AIR.PA"}
    assert calls == [["AAPL", "AIRBUS"]]  # one call, both labels


def test_us_venue_codes_are_stripped_locally():
    """Upper-cased too: Transaction upper-cases every ticker before this runs."""
    calls = []
    labels = ["ZBRA:xnas", "S:xnys", "META:XNAS"]
    out = instruments.resolve(labels, None, ask=replying({}, calls))
    assert out == {"ZBRA:xnas": "ZBRA", "S:xnys": "S", "META:XNAS": "META"}
    assert calls == []


def test_a_foreign_venue_code_goes_to_the_model():
    """The Yahoo suffix for a venue is knowledge, not string surgery."""
    calls = []
    out = instruments.resolve(
        ["TEF:XMCE"], None, ask=replying({"TEF:XMCE": "TEF.MC"}, calls))
    assert out == {"TEF:XMCE": "TEF.MC"}
    assert calls == [["TEF:XMCE"]]


def test_a_broker_suffix_is_not_taken_for_a_yahoo_one():
    """XTB's PLTR.US and SHEL.UK look Yahoo-shaped and are not.

    Yahoo has no .US at all, and that London line is SHEL.L. Accepted
    verbatim they book a ticker that prices as nothing, so a dotted suffix is
    always the model's to judge.
    """
    calls = []
    labels = ["PLTR.US", "SHEL.UK"]
    out = instruments.resolve(
        labels, None, ask=replying({"PLTR.US": "PLTR", "SHEL.UK": "SHEL.L"},
                                   calls))
    assert out == {"PLTR.US": "PLTR", "SHEL.UK": "SHEL.L"}
    assert calls == [labels]


def test_a_yahoo_suffix_is_confirmed_rather_than_assumed():
    """Already correct, but only the model knows that — and it is free to
    confirm: unresolved labels travel in the one batch there already is."""
    calls = []
    out = instruments.resolve(
        ["MC.PA"], None, ask=replying({"MC.PA": "MC.PA"}, calls))
    assert out == {"MC.PA": "MC.PA"} and calls == [["MC.PA"]]


def test_a_suffix_the_model_declines_stays_unresolved():
    """A model that declines must not downgrade a symbol that was right:
    None leaves llm_map's row holding the label the document wrote."""
    out = instruments.resolve(["MC.PA"], None, ask=replying({}))
    assert out == {"MC.PA": None}


def test_names_isins_and_codes_are_resolved_by_the_model():
    answers = {
        "META PLATFORMS INC.": "META",
        "LVMH MOET HENNESSY LOUIS VUITTON": "MC.PA",
        "US0231351067": "AMZN",
        "PDD HOLDINGS INC - ADR": "PDD",
    }
    out = instruments.resolve(list(answers), None, ask=replying(answers))
    assert out == answers


def test_an_unnameable_label_stays_unresolved():
    """An id is nobody's ticker. A bare currency code is symbol-shaped and
    passes through here — llm_map drops it where the row's currency is known."""
    out = instruments.resolve(
        ["6057847232"], None, ask=replying({"6057847232": None}))
    assert out == {"6057847232": None}


def test_a_reply_that_is_not_a_ticker_is_discarded():
    """A model that answers with prose, a name or an ISIN is not believed."""
    out = instruments.resolve(
        ["Tesla Inc.", "InMode Ltd"], None,
        ask=replying({"Tesla Inc.": "I think it is TSLA",
                      "InMode Ltd": "IL0011595993"}))
    assert out == {"Tesla Inc.": None, "InMode Ltd": None}


def test_junk_and_unasked_keys_are_ignored():
    assert instruments.resolve(["Tesla Inc."], None, ask=lambda s, c: "no idea") == {
        "Tesla Inc.": None}
    assert instruments.resolve(
        ["Tesla Inc."], None, ask=lambda s, c: '{"Ford Motor Co": "F"}'
    ) == {"Tesla Inc.": None}


def test_one_call_for_repeated_labels_and_then_memoised():
    calls = []
    ask = replying({"Tesla Inc.": "TSLA"}, calls)
    labels = ["Tesla Inc."] * 9
    assert instruments.resolve(labels, None, ask=ask) == {"Tesla Inc.": "TSLA"}
    assert calls == [["Tesla Inc."]]  # asked once for nine rows
    instruments.resolve(["Tesla Inc."], None, ask=ask)
    assert len(calls) == 1  # and not again


def test_case_differences_in_the_reply_still_match():
    out = instruments.resolve(
        ["Tesla Inc."], None, ask=lambda s, c: '{"TESLA INC.": "tsla"}')
    assert out == {"Tesla Inc.": "TSLA"}


def test_more_labels_than_one_call_carries_are_left_unresolved(monkeypatch):
    """A cap is never a silent truncation: the excess resolves to nothing."""
    monkeypatch.setattr(instruments, "MAX_LABELS", 2)
    calls = []
    labels = ["Name A", "Name B", "Name C"]
    out = instruments.resolve(
        labels, None, ask=replying({"Name A": "AAA", "Name B": "BBB"}, calls))
    assert out == {"Name A": "AAA", "Name B": "BBB", "Name C": None}
    assert calls == [["Name A", "Name B"]]


def test_without_a_model_only_the_obvious_resolves():
    """Only the US venue form; everything else keeps the document's label."""
    out = instruments.resolve(["ZBRA:xnas", "AAPL", "Tesla Inc."], None,
                              ask=None)
    assert out == {"ZBRA:xnas": "ZBRA"}
