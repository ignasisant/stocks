"""Thumbs on chat answers, and the search fixes that came with them.

A rating names the answer by the id `_record` gave it, lands on the stored
turn (so a reload draws the thumb), and a vote — not a clear — copies the
question, the answer and what it was built from into the operator's feedback
store. The rest is what made the answer that prompted all this bad: a refused
key that kept leading the research, and a follow-up ("¿por qué ha subido
hoy?") that searched for its own words with no ticker in them.
"""

# The API fixtures are borrowed from test_api_chat, and a test naming one as
# a parameter reads to ruff as redefining the import.
# ruff: noqa: F811

from __future__ import annotations

import json

import pytest

from stocks.chat import engine
from stocks.web import auth, chat_web, feedback, llm

from .test_api_chat import (  # noqa: F401 — fixtures
    AUTH,
    EMAIL,
    FakeProvider,
    account,
    client,
    events,
    finished,
    run,
    served,
    signed_in,
    token,
)


@pytest.fixture
def sink(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(feedback.storage, "persist", lambda path: None)
    return tmp_path / "feedback"


@pytest.fixture(autouse=True)
def fresh_memo():
    llm._rejected.clear()
    yield
    llm._rejected.clear()


def _answered(signed_in) -> tuple[str, str]:
    """(thread id, answer id) of the one turn `served` answers."""
    stream = events(signed_in.post("/v1/chat/runs", json=run("hola")).text)
    tid = finished(stream)["result"]["id"]
    thread = signed_in.get("/v1/chat/conversations").json()["conversations"][0]
    return thread["id"], tid


# ------------------------------------------------------------------- storage


def test_rate_turn_sets_and_clears_without_touching_updated(tmp_path):
    path = tmp_path / "chat.json"
    book = {"conversations": [{
        "id": "c1", "title": "t", "updated": "2026-01-01T00:00:00",
        "messages": [{"role": "user", "content": "why up?"},
                     {"role": "assistant", "content": "because", "id": "a1"}],
    }], "active": "c1"}
    auth.save_book(book, path)

    found = auth.rate_turn("a1", "down", path)
    assert found["question"] == "why up?"
    assert found["answer"]["rating"] == "down"
    conv = auth.load_book(path)["conversations"][0]
    assert conv["messages"][1]["rating"] == "down"
    assert conv["updated"] == "2026-01-01T00:00:00"

    auth.rate_turn("a1", None, path)
    assert "rating" not in auth.load_book(path)["conversations"][0]["messages"][1]
    assert auth.rate_turn("nope", "up", path) is None
    assert auth.rate_turn("", "up", path) is None


def test_a_conversation_keeps_one_rating(tmp_path):
    path = tmp_path / "chat.json"
    book = {"conversations": [
        {"id": "c1", "title": "t", "updated": "2026-01-01T00:00:00", "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "one", "id": "a1"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "two", "id": "a2"},
        ]},
        {"id": "c2", "title": "u", "updated": "2026-01-01T00:00:00", "messages": [
            {"role": "user", "content": "other"},
            {"role": "assistant", "content": "three", "id": "b1", "rating": "up"},
        ]},
    ], "active": "c1"}
    auth.save_book(book, path)

    auth.rate_turn("a1", "up", path)
    found = auth.rate_turn("a2", "down", path)
    c1, c2 = auth.load_book(path)["conversations"]
    assert "rating" not in c1["messages"][1]
    assert c1["messages"][3]["rating"] == "down"
    # Another conversation's rating is its own.
    assert c2["messages"][1]["rating"] == "up"
    # What led up to the rated answer, without the question itself.
    assert found["thread"] == "c1" and found["question"] == "second"
    assert found["history"] == [{"role": "user", "content": "first"},
                                {"role": "assistant", "content": "one"}]


# ----------------------------------------------------------------------- API


def test_a_finished_turn_names_its_answer(client, account, signed_in, served):
    served()
    thread, tid = _answered(signed_in)
    assert tid
    turns = signed_in.get(f"/v1/chat/conversations/{thread}").json()["messages"]
    assert turns[1]["id"] == tid
    assert turns[1].get("rating") is None


def test_a_thumb_lands_on_the_turn_and_a_reload_draws_it(
    client, account, signed_in, served, sink
):
    served()
    thread, tid = _answered(signed_in)
    response = signed_in.put(f"/v1/chat/turns/{tid}/rating", json={"vote": "up"})
    assert response.status_code == 200 and response.json() == {"vote": "up"}
    turns = signed_in.get(f"/v1/chat/conversations/{thread}").json()["messages"]
    assert turns[1]["rating"] == "up"

    cleared = signed_in.put(f"/v1/chat/turns/{tid}/rating", json={"vote": None})
    assert cleared.json() == {"vote": None}
    turns = signed_in.get(f"/v1/chat/conversations/{thread}").json()["messages"]
    assert turns[1].get("rating") is None
    # One copy for the vote, none for the clear.
    assert len(list(sink.glob("*.json"))) == 1


def test_a_thumbs_down_tells_the_operator_what_missed(
    client, account, signed_in, served, sink
):
    served()
    _thread, tid = _answered(signed_in)
    signed_in.put(f"/v1/chat/turns/{tid}/rating",
                  json={"vote": "down", "reason": "made_up", "note": "search it"})
    (copy,) = sink.glob("*.json")
    data = json.loads(copy.read_text())
    assert data["kind"] == "rating" and data["vote"] == "down"
    assert data["reason"] == "made_up" and data["text"] == "search it"
    assert data["question"] == "hola" and data["answer"] == "Hola mundo"
    assert data["provider"] == "fake" and data["turn"] == tid
    assert data["thread"] and data["history"] == []


def test_rating_an_unknown_answer_is_a_404(client, account, signed_in, sink):
    response = signed_in.put("/v1/chat/turns/abc123/rating", json={"vote": "up"})
    assert response.status_code == 404


def test_a_rating_refuses_what_it_does_not_know(client, account, signed_in, sink):
    for body in ({"vote": "meh"}, {"vote": "down", "reason": "boring"},
                 {"vote": "up", "extra": 1}):
        assert signed_in.put("/v1/chat/turns/x/rating", json=body).status_code == 422


def test_a_token_cannot_rate(client, account, sink):
    response = client.put("/v1/chat/turns/x/rating", json={"vote": "up"},
                          headers=AUTH, params={"account": EMAIL})
    assert response.status_code == 403
    assert not sink.exists()


# ------------------------------------------------------- refused-key memo


class Keyed:
    needs_key = True

    def __init__(self, pid):
        self.id = pid

    def error_key(self, exc):
        return "chat.invalid_key" if "401" in str(exc) else None


def test_a_refused_key_goes_to_the_back_of_the_research_order():
    byok, free = Keyed("openai"), Keyed("groq")
    atts = [(byok, "sk-bad", "m"), (free, "gk", "m")]
    llm.note_failure(byok, "sk-bad", RuntimeError("Error code: 401"))
    assert llm.rejected(byok, "sk-bad")
    assert not llm.rejected(byok, "sk-other")
    assert [p.id for p, _k, _m in engine.answerable({}, atts)] == ["groq", "openai"]


def test_a_failure_that_is_not_a_refusal_keeps_the_key_in_front():
    byok = Keyed("openai")
    llm.note_failure(byok, "sk-ok", RuntimeError("timeout"))
    assert not llm.rejected(byok, "sk-ok")


def test_a_refusal_is_forgotten_after_its_ttl(monkeypatch):
    byok = Keyed("openai")
    llm.note_failure(byok, "sk-bad", RuntimeError("401"))
    real = llm.time.monotonic
    monkeypatch.setattr(llm.time, "monotonic", lambda: real() + llm.REJECTED_TTL_S + 1)
    assert not llm.rejected(byok, "sk-bad")


# ------------------------------------------------------------- follow-ups


def test_topic_ticker_reads_the_last_answer_s_page_link():
    history = [
        {"role": "user", "content": "¿por qué ha subido Shopify hoy?"},
        {"role": "assistant", "content": "...", "nav": {"ticker": "shop"}},
        {"role": "user", "content": "¿venderías?"},
        {"role": "assistant", "content": "..."},
    ]
    assert engine.topic_ticker(history) == "SHOP"
    assert engine.topic_ticker(history[2:]) == ""


def test_a_follow_up_searches_for_the_conversation_s_ticker():
    queries = chat_web.heuristic_queries(
        "porque ha subido hoy",
        "Today is 2026-10-05.\nThe conversation is about SHOP.",
    )
    assert queries and queries[0].startswith("SHOP")


def test_asking_for_the_internet_is_a_reason_to_search():
    ctx = "Today is 2026-10-05.\nThe conversation is about SHOP."
    for ask in ("busca en internet el motivo real",
                "can you look it up",
                "dime la razón"):
        assert chat_web.heuristic_queries(ask, ctx), ask


# ------------------------------------------------------ searching by default


def test_the_heuristic_searches_unless_the_message_needs_nothing_outside():
    ctx = "Today is 2026-10-05.\nThe conversation is about SHOP."
    for ask in ("¿venderías?", "qué opinas de Shopify", "is it a buy?"):
        assert chat_web.heuristic_queries(ask, ctx), ask
    for quiet in ("gracias", "hola!", "¿qué es un PER?", "what is an ETF?",
                  "cuánto llevo ganado en mi cartera", "how do I import my trades"):
        assert chat_web.heuristic_queries(quiet) == [], quiet


class _Researcher(FakeProvider):
    """A provider whose own lookup ran and fetched a quote, but no page."""

    classifier_model = "fake-1"

    def supports_tools(self):
        return True

    def run_tools(self, api_key, model, system, messages, tools, execute):
        from stocks.web.llm import ToolCall, ToolRun

        out = execute("get_quotes", {"tickers": "SHOP"})
        return ToolRun("DONE", [ToolCall("get_quotes", {"tickers": "SHOP"}, out)])


def _searched(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def collect(queries, message=""):
        seen.append(list(queries))
        return [chat_web.Result("Why SHOP rose", "https://news.example/shop", "beat")]

    from stocks.chat import toolbox

    spec = toolbox.TOOLS["get_quotes"][0]
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes",
                        (spec, lambda args, ctx: "SHOP 120.5 USD +4.1%"))
    monkeypatch.setattr(chat_web, "available", lambda: True)
    monkeypatch.setattr(chat_web, "collect", collect)
    monkeypatch.setattr(chat_web, "plan", lambda *a, **k: pytest.fail("planner ran"))
    return seen


def test_a_lookup_that_skipped_the_web_still_searches(
    client, account, signed_in, served, monkeypatch
):
    seen = _searched(monkeypatch)
    served(_Researcher())
    stream = events(signed_in.post(
        "/v1/chat/runs", json=run("¿por qué ha subido Shopify hoy?")).text)
    assert seen and "Shopify" in seen[0][0]
    steps = [e["stepName"] for e in stream if e["type"] == "STEP_STARTED"]
    assert "searching" in steps
    assert finished(stream)["result"]["sources"][0]["url"] == "https://news.example/shop"


def test_small_talk_is_still_not_searched(
    client, account, signed_in, served, monkeypatch
):
    seen = _searched(monkeypatch)
    served(_Researcher())
    signed_in.post("/v1/chat/runs", json=run("gracias"))
    assert seen == []


def test_the_search_plan_skips_a_key_refused_minutes_ago(
    client, account, signed_in, monkeypatch
):
    bad, good = FakeProvider(pid="bad"), FakeProvider(pid="good")
    monkeypatch.setattr(engine, "attempts",
                        lambda prefs: [(bad, "k-bad", "fake-1"), (good, "k", "fake-1")])
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    monkeypatch.setattr(chat_web, "available", lambda: True)
    llm._rejected[llm._fingerprint("bad", "k-bad")] = llm.time.monotonic()
    planned: list[str] = []
    monkeypatch.setattr(chat_web, "plan",
                        lambda provider, *a, **k: planned.append(provider.id) or [])
    signed_in.post("/v1/chat/runs", json=run("¿qué tal SHOP?"))
    assert planned == ["good"]
