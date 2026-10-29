"""The prod eval's catalog and the parts of it that run without a model."""

from __future__ import annotations

import json

import pytest

from stocks.chat import navigate, prod_eval


@pytest.fixture(scope="module")
def catalog() -> list[prod_eval.Question]:
    return prod_eval.load()


def test_the_catalog_loads_and_every_page_has_a_question(catalog):
    pages = {q.page for q in catalog}
    missing = set(navigate.PAGES) - pages
    assert not missing, f"pages with no question: {sorted(missing)}"
    assert {"assistant", "concept", "abstain"} <= pages


def test_every_kind_is_asked(catalog):
    assert {q.kind for q in catalog} == set(prod_eval.KINDS)


def test_numeric_truths_say_which_field(catalog):
    for q in catalog:
        for t in q.truth:
            assert t.get.startswith("/"), q.id
            assert 0 < t.tol < 1, q.id


def test_the_catalog_refuses_an_unknown_area(tmp_path):
    bad = tmp_path / "q.yaml"
    bad.write_text("- {id: x, area: nowhere, kind: howto, message: hi}\n")
    with pytest.raises(ValueError, match="unknown area"):
        prod_eval.load(bad)


def test_pick_walks_dicts_and_keyed_lists():
    data = {
        "kpis": [{"key": "pe_fwd", "value": 25.1}, {"key": "pe_ttm", "value": 31.4}],
        "value": 9,
    }
    assert prod_eval.pick(data, "kpis[key=pe_ttm].value") == 31.4
    assert prod_eval.pick(data, "value") == 9
    assert prod_eval.pick(data, "kpis[key=peg].value") is None
    assert prod_eval.pick(data, "") is data


@pytest.mark.parametrize(
    "text, want",
    [
        ("El PER es 31,4 veces", [31.4]),
        ("cotiza a 182.35 USD", [182.35]),
        ("vale 12.345,67 €", [12345.67]),
        ("worth 12,345.67 USD", [12345.67]),
        ("1.234 acciones", [1234.0]),
        ("un 0,123 %", [0.123]),
        ("de 10 a 20", [10.0, 20.0]),
    ],
)
def test_numbers_read_spanish_and_english_formats(text, want):
    assert prod_eval.numbers(text) == want


def test_a_figure_is_a_hit_off_or_absent():
    assert prod_eval.figure("El PER es 31,4", 31.0, 0.1) == "hit"
    assert prod_eval.figure("El PER es 45", 31.0, 0.1) == "off"
    assert prod_eval.figure("Compraste en 2024", 31.0, 0.1) == "absent"
    assert prod_eval.figure("No tengo el dato", 31.0, 0.1) == "absent"


def _sse(*events: dict) -> list[str]:
    lines = [": open", ""]
    for ev in events:
        lines += [f"data: {json.dumps(ev)}", ""]
    return lines


def test_a_run_stream_folds_into_the_answer():
    lines = _sse(
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "ticker_data"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"symbol": "AAPL"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {
            "type": "TOOL_CALL_RESULT",
            "toolCallId": "c1",
            "messageId": "m",
            "content": "P/E 31.4",
        },
        {
            "type": "CUSTOM",
            "name": "chat.meta",
            "value": {"provider": "free", "model": "gpt-oss-120b"},
        },
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "El PER "},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "es 31,4"},
        {"type": "TOOL_CALL_START", "toolCallId": "n1", "toolCallName": "navigate"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "n1", "delta": '{"page": "ticker"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "n1"},
        {
            "type": "RUN_FINISHED",
            "threadId": "t",
            "runId": "r",
            "result": {"text": "El PER es 31,4.", "provider": "free", "sources": []},
        },
    )
    ans = prod_eval.read_run(prod_eval.frames(lines))
    assert ans.text == "El PER es 31,4."
    assert ans.model == "gpt-oss-120b"
    assert [(c.name, c.args, c.result) for c in ans.calls] == [
        ("ticker_data", {"symbol": "AAPL"}, "P/E 31.4")
    ]
    assert ans.nav == [{"page": "ticker"}]
    assert ans.first_s is not None


def test_a_dead_run_keeps_its_error_and_partial_words():
    lines = _sse(
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "Hola"},
        {"type": "RUN_ERROR", "message": "chat.free_cap", "code": "chat.free_cap"},
    )
    ans = prod_eval.read_run(prod_eval.frames(lines))
    assert ans.error == "chat.free_cap"
    assert ans.text == "Hola"


def _q(**kw) -> prod_eval.Question:
    base = {"id": "x", "area": "ticker", "kind": "data", "message": "?"}
    return prod_eval.Question(**{**base, **kw})


def test_checks_name_what_broke():
    q = _q(
        truth=(prod_eval.Truth("/t", "AAPL P/E", "kpis[key=pe_ttm].value", 0.1),),
        opens="portfolio/tax",
        mentions=("per",),
        forbids=("seguro",),
    )
    ans = prod_eval.Answer(text="Sube seguro, PER de 50", nav=[{"page": "portfolio"}])
    got = prod_eval.checks(q, ans, {"AAPL P/E": 31.0})
    assert got["figures"] == {"AAPL P/E": "off"}
    assert got["opens"] is False
    assert got["forbids"] == ["seguro"]
    assert len(got["failed"]) == 3


def test_verdict_puts_a_figure_off_above_a_missed_goal():
    row = {"checks": {"failed": ["x"], "figures": {"a": "off"}}, "judged": None}
    assert prod_eval.verdict(row) == "halluc"
    row = {
        "checks": {"failed": []},
        "judged": {"goals": {"g": "not_met"}, "scores": {"grounded": 4}},
    }
    assert prod_eval.verdict(row) == "fail"
    row = {
        "checks": {"failed": []},
        "judged": {"goals": {"g": "met"}, "scores": {"grounded": 2}},
    }
    assert prod_eval.verdict(row) == "halluc"


def test_the_run_body_is_what_the_drawer_sends():
    q = _q(view="ticker", focus="ASML", lang="en", depth="deep")
    body = prod_eval.run_body(q, "thr")
    assert body["threadId"] == "thr"
    assert body["state"] == {"view": "ticker", "focus": "ASML"}
    assert body["forwardedProps"] == {"lang": "en", "depth": "deep"}
    assert body["tools"][0]["name"] == navigate.TOOL_NAME
    from stocks.api.routes.chat import Run

    Run.model_validate(body)


def test_references_cover_the_named_tickers_and_the_book():
    q = _q(
        kind="book",
        focus="ASML",
        truth=(prod_eval.Truth("/ticker/AAPL/metrics", "P/E", "pe"),),
        refs=("/ticker/TSLA/quote",),
    )
    paths = prod_eval.reference_paths(q)
    assert paths[:2] == ["/ticker/AAPL/metrics", "/ticker/TSLA/quote"]
    for p in (
        "/ticker/AAPL/quote",
        "/ticker/TSLA/metrics",
        "/ticker/ASML/quote",
        "/portfolio/summary",
        "/portfolio/positions",
    ):
        assert p in paths
    assert len(paths) == len(set(paths))


def test_harvest_reads_values_and_figures_in_text():
    data = {"price": 22.11, "ok": True, "rows": [{"w": 0.27}, {"note": "rango 17,39"}]}
    assert sorted(prod_eval.harvest(data)) == [0.27, 17.39, 22.11]


def test_invented_technicals_are_unsourced_but_the_quote_is_not():
    pool = [404.22, 0.48, 297.38, 498.83]
    text = (
        "Cotiza 404,22 USD, rango de 52 semanas 297,38 – 498,83. Media de 200 días "
        "~380, RSI ~62, resistencia 425, un 27 % de la cartera, 3 pasos, en 2026."
    )
    assert prod_eval.unsourced(text, pool + [0.27]) == [380.0, 62.0, 425.0]
    assert prod_eval.unsourced("vendí a 26,51", pool, "he vendido a 26,51") == []


def test_three_unsourced_figures_are_a_hallucination():
    q = _q(kind="abstain")
    ans = prod_eval.Answer(text="Mañana 425, soporte 395, RSI 62")
    got = prod_eval.checks(q, ans, {}, pool=[404.22])
    assert got["unsourced"] == [425.0, 395.0, 62.0]
    assert prod_eval.verdict({"checks": got, "judged": None}) == "halluc"
    assert "unsourced" not in prod_eval.checks(q, ans, {})


def test_a_saved_answer_reads_back():
    ans = prod_eval.Answer(
        text="hola", model="m", calls=[prod_eval.Call("t", {"a": 1}, "r")], seconds=3.0
    )
    back = prod_eval.Answer.from_dict(ans.as_dict())
    assert back.as_dict() == ans.as_dict()
