"""Which questions get argued by a bull and a bear before they are answered.

Two more model calls, often on the operator's keys, so the gate is the thing
worth pinning: an explicit ask for a decision or for both sides — and not a
question that merely mentions buying or selling.
"""

from __future__ import annotations

import pytest

from stocks.chat import debate


@pytest.mark.parametrize(("said", "argued"), [
    ("¿Debería comprar NVDA?", True),
    ("deberia vender mis AAPL ahora", True),
    ("Should I buy more MSFT?", True),
    ("give me the bull and bear case for ASML", True),
    ("pros y contras de Inditex", True),
    ("¿Es buena compra Iberdrola?", True),
    ("¿cuándo compré AAPL?", False),
    ("how is NVDA doing today?", False),
    ("sell my TSLA at 300", False),
    ("the bear market of 2022", False),
])
def test_only_an_ask_for_a_decision_is_argued(said, argued):
    assert debate.wants(said) is argued


def test_the_brief_carries_both_cases_and_the_rule():
    text = debate.brief([{"side": "bull", "text": "- cash"},
                         {"side": "bear", "text": "- debt"}])
    assert "BULL ANALYST:\n- cash" in text and "BEAR ANALYST:\n- debt" in text
    assert "Weigh them" in text
    assert debate.brief([]) == ""


def test_each_side_is_told_to_argue_only_its_own_case():
    bull, bear = debate._system("bull", "es"), debate._system("bear", "es")
    assert "case FOR" in bull and "case AGAINST" in bear
    assert "Spanish" in bull and "Never invent a number" in bear


def test_a_side_argues_a_thesis_and_does_not_advise_the_reader():
    # Both sides, since the rules are shared: the first real run had the bull
    # telling the reader to buy more of a stock their book did not hold, off a
    # blog's forecast quoted as fact.
    for side in debate.SIDES:
        told = debate._system(side, "en")
        assert "you do not advise the reader" in told
        assert "Do not assume they own the security" in told
        assert "that site's claim" in told


def test_the_brief_asks_the_answer_to_correct_the_analysts():
    text = debate.brief([{"side": "bull", "text": "- cash"}])
    assert "correct any figure" in text
    assert "not among the reader's holdings" in text
