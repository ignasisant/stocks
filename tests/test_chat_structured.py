"""structured: BAML-shaped replies, Python-judged contracts, one repair turn.

PlanQueries (baml_src/chat.baml) stands in for every BAML function here: the
plumbing is the same for all of them, and its one-list shape is the one most
prone to the parser's stringifying fallback.
"""

import pytest
from pydantic import field_validator

from stocks.chat import structured
from stocks.chat.structured import OffContract

FN = "PlanQueries"


class _Plan(structured.Contract):
    queries: list[str]


class _Loose(structured.Contract):
    """A contract that cleans instead of rejecting, like the real ones."""

    queries: list[str]

    @field_validator("queries", mode="before")
    @classmethod
    def _clean(cls, v):
        return [x for x in v if x.strip()] if isinstance(v, list) else v


class _Provider:
    """Stand-in for llm.Provider: hands back scripted replies, counts calls."""

    id = "fake"
    classifier_model = "cheap-model"

    def __init__(self, *replies, exc=None):
        self.replies, self.exc = list(replies), exc
        self.calls = []

    def complete(self, api_key, model, system, messages):
        self.calls.append((api_key, model, system, messages))
        if self.exc:
            raise self.exc
        return self.replies.pop(0) if self.replies else ""


@pytest.fixture
def warned(monkeypatch):
    """Every llm.off_contract logged, with the context bound at the time."""
    out = []

    def warn(name, **fields):
        out.append({"event": name, **structured.obs._fields(), **fields})

    monkeypatch.setattr(structured.obs, "warn", warn)
    return out


# ------------------------------------------------------------------ render


def test_render_puts_the_instructions_and_the_schema_in_the_system_prompt():
    system, messages = structured.render(FN, "Plan the searches.", "NVDA today?")
    assert system.startswith("Plan the searches.")
    assert "queries" in system  # the shape, spelled out by BAML
    assert messages == [{"role": "user", "content": "NVDA today?"}]


# ------------------------------------------------------------------ decode


def test_decode_reads_the_object_out_of_prose_and_fences():
    got = structured.decode(
        'Sure! ```json\n{"queries": ["ASML news"]}\n```', FN, _Plan
    )
    assert got.queries == ["ASML news"]


def test_decode_ignores_fields_the_contract_does_not_name():
    got = structured.decode(
        '{"queries": [], "reasoning": "nothing recent"}', FN, _Plan
    )
    assert got.queries == []


@pytest.mark.parametrize(
    "raw",
    [
        '{"queries": ["ASML news",],}',  # trailing commas
        "{queries: ['ASML news']}",  # unquoted keys, single quotes
        '{"queries": "ASML news"}',  # a lone string where a list was asked
        '["ASML news"]',  # the bare list
    ],
)
def test_decode_reads_the_near_misses_that_used_to_cost_a_repair(raw):
    assert structured.decode(raw, FN, _Plan).queries == ["ASML news"]


@pytest.mark.parametrize(
    "raw, why",
    [
        ("I cannot help with that", "no JSON object"),
        ("", "no JSON object"),
        ('{"nope": 1}', "do not match the requested shape"),
        ("{broken json", "cut off"),  # an object that never closes
        ('{"queries": null}', "queries"),
    ],
)
def test_decode_rejects_off_contract_replies_with_a_reason(raw, why):
    with pytest.raises(OffContract) as err:
        structured.decode(raw, FN, _Plan)
    assert why in str(err.value)
    assert err.value.raw == raw  # the caller may still read the text itself


def test_a_rejection_never_quotes_the_reply(warned):
    # A statement read back by the model is the user's data: the reason goes
    # to the log and to the repair turn, so it describes, it does not quote.
    with pytest.raises(OffContract) as err:
        structured.decode("Bought 12 NVDA at 101.5", FN, _Plan)
    assert "NVDA" not in str(err.value)
    assert "NVDA" not in warned[0]["reason"]


def test_decode_keeps_a_before_validators_cleaning():
    got = structured.decode('{"queries": ["a", "  ", "b"]}', FN, _Loose)
    assert got.queries == ["a", "b"]


def test_parse_hands_back_only_the_fields_the_model_filled():
    assert structured.parse('{"queries": null}', FN) == {}


def test_each_rejection_is_logged_against_the_function(warned):
    with pytest.raises(OffContract):
        structured.decode("prose", FN, _Plan)
    (entry,) = warned
    assert entry["event"] == "llm.off_contract"
    assert entry["fn"] == FN and entry["parser"] == "baml"


# --------------------------------------------------------------------- ask


def test_ask_spends_one_call_on_a_good_reply():
    p = _Provider('{"queries": ["NVDA news"]}')
    assert structured.ask(p, "k", FN, "sys", "usr", _Plan).queries == ["NVDA news"]
    ((api_key, model, system, messages),) = p.calls
    assert (api_key, model) == ("k", "cheap-model")
    assert system.startswith("sys") and "queries" in system
    assert messages == [{"role": "user", "content": "usr"}]


def test_ask_repairs_an_off_contract_reply(warned):
    p = _Provider("I think NVDA news", '{"queries": ["NVDA news"]}')
    assert structured.ask(p, "k", FN, "sys", "usr", _Plan).queries == ["NVDA news"]
    assert len(p.calls) == 2
    first, repair = (c[3] for c in p.calls)
    assert repair[:1] == first  # the question is asked again, not paraphrased
    assert repair[1] == {"role": "assistant", "content": "I think NVDA news"}
    assert "rejected" in repair[2]["content"]
    assert "no JSON object" in repair[2]["content"]  # says what was wrong
    assert p.calls[1][2] == p.calls[0][2]  # same system prompt, same contract
    (entry,) = warned  # the miss is logged against the attempt that missed
    assert (entry["provider"], entry["model"], entry["attempt"]) == (
        "fake", "cheap-model", 1
    )


def test_ask_shows_an_empty_reply_back_as_something_the_model_can_read():
    p = _Provider("", '{"queries": []}')
    structured.ask(p, "k", FN, "sys", "usr", _Plan)
    assert p.calls[1][3][1]["content"] == "(empty)"


def test_ask_trims_a_rambling_reply_before_quoting_it_back():
    p = _Provider("x" * 5000, '{"queries": []}')
    structured.ask(p, "k", FN, "sys", "usr", _Plan)
    assert len(p.calls[1][3][1]["content"]) == 500


def test_ask_gives_up_after_the_repair(warned):
    p = _Provider("nope", "still nope")
    with pytest.raises(OffContract) as err:
        structured.ask(p, "k", FN, "sys", "usr", _Plan)
    assert err.value.raw == "still nope"  # the reply the caller may re-read
    assert len(p.calls) == 2
    assert [w["attempt"] for w in warned] == [1, 2]


def test_ask_can_be_told_not_to_repair():
    p = _Provider("nope", '{"queries": []}')
    with pytest.raises(OffContract):
        structured.ask(p, "k", FN, "sys", "usr", _Plan, repair=False)
    assert len(p.calls) == 1


def test_ask_lets_provider_errors_through_untouched():
    # A rate limit is not a contract problem: retrying it here would spend a
    # second doomed call and hide the reason from the caller.
    p = _Provider(exc=RuntimeError("rate limited"))
    with pytest.raises(RuntimeError, match="rate limited"):
        structured.ask(p, "k", FN, "sys", "usr", _Plan)
    assert len(p.calls) == 1


def test_ask_honours_an_explicit_model_over_the_cheapest_one():
    p = _Provider('{"queries": []}')
    structured.ask(p, "k", FN, "sys", "usr", _Plan, model="big-model")
    assert p.calls[0][1] == "big-model"
