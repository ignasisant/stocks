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


def test_a_side_that_did_not_speak_is_recorded_as_failed_in_order():
    kept = debate.recorded([{"side": "bear", "text": "- debt"}])
    assert kept == [{"side": "bull", "text": "", "failed": True},
                    {"side": "bear", "text": "- debt"}]


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


class _Slow:
    """A provider whose sides land after set delays, recording what each read."""

    id = "fake"
    classifier_model = "cheap"
    default_model = "big"

    def __init__(self, delays: dict[str, float]):
        self.delays = delays
        self.read: dict[str, list[dict]] = {}

    def complete(self, api_key, model, system, messages):
        import time

        side = "bull" if "case FOR" in system else "bear"
        self.read[side] = messages
        time.sleep(self.delays[side])
        return f"- {side} point"


def test_a_side_that_lands_while_the_other_is_awaited_is_kept():
    # Prod 2026-11-18: the bull landed 2 s past its timeout, 10 s before the
    # bear did, and was stored as failed beside a lone bear case.
    told: list[dict] = []
    spoken = debate.run(_Slow({"bull": 0.4, "bear": 0.5}), "", [
        {"role": "user", "content": "q"}], "en", on_event=told.append,
        timeout=0.3)
    assert [s["side"] for s in spoken] == ["bull", "bear"]
    assert [e["kind"] for e in told if e["side"] == "bull"] == [
        "start", "text", "end"]


def test_nothing_is_told_after_the_debate_returns():
    import time

    told: list[dict] = []
    spoken = debate.run(_Slow({"bull": 0.05, "bear": 0.6}), "", [
        {"role": "user", "content": "q"}], "en", on_event=told.append,
        timeout=0.1)
    assert [s["side"] for s in spoken] == ["bull"]
    time.sleep(0.8)  # the bear lands now, on its orphaned thread
    assert not any(e["side"] == "bear" and e["kind"] == "text" for e in told)


def test_the_sides_do_not_read_the_answers_format():
    # A ticker page's brief asks the answer for seven sections; a free model
    # told that last wrote all seven under the bear's card.
    shape = "Answer in this structure, about 350 words in all:\n1. **Verdict**"
    fake = _Slow({"bull": 0, "bear": 0})
    history = [{"role": "assistant", "content": "earlier"},
               {"role": "user", "content": f"Analiza FICO\n\nfacts\n{shape}"}]
    debate.run(fake, "", history, "es", timeout=2, drop=shape)
    for side in debate.SIDES:
        last = fake.read[side][-1]["content"]
        assert "Verdict" not in last and "facts" in last
        assert fake.read[side][0] is history[0]
    assert shape in history[-1]["content"]  # the answer still gets it


def test_a_lone_case_is_not_weighed_as_the_whole_debate():
    text = debate.brief([{"side": "bear", "text": "- debt"}])
    assert "only one case arrived" in text and "the bull case did not" in text
    assert "build the bull case yourself" in text
    assert "has seen both" not in text
