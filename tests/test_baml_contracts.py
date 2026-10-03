"""The BAML layer itself (baml_src/ -> stocks.baml_client), offline.

Pins what the callers' Python rules lean on: how the parser reads the replies
small free models really send, the traps it was configured around (comma
decimals, one bad list item), that every prompt is rendered without a network
or a key, and that the functions the code names exist in the generated client.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from stocks.baml_client import b
from stocks.baml_client import types as baml_types
from stocks.chat import structured, tools

SRC = Path(__file__).resolve().parent.parent / "src" / "stocks"
FUNCTIONS = sorted(n for n in dir(b.parse) if not n.startswith("_"))
SHAPE = "Reply with ONLY a JSON object in this shape"


# ------------------------------------------------------------------ render


@pytest.mark.parametrize("fn", FUNCTIONS)
def test_every_function_renders_offline_with_its_shape_once(fn):
    system, messages = structured.render(fn, "THE RULES", "THE INPUT")
    assert system.startswith("THE RULES")
    assert system.count(SHAPE) == 1
    assert messages == [{"role": "user", "content": "THE INPUT"}]


def test_the_input_is_sent_verbatim_never_templated():
    # Statement text and chat messages are user data: braces in them are
    # characters, not template syntax.
    text = '{"a": "{{ ctx.output_format }}"} {% if x %}'
    _, messages = structured.render("PlanQueries", "rules", text)
    assert messages[0]["content"] == text


def test_the_callers_no_longer_spell_out_the_shape_themselves():
    """One description of the reply per prompt: BAML's. A second, hand-kept
    copy in the instructions is how the two drift apart."""
    from stocks.chat import daily, daily_analysis, learnings, sector_ai
    from stocks.portfolio import instruments, llm_map
    from stocks.web import chat_skills, chat_web

    prompts = {
        "chat_skills": chat_skills._CLASSIFIER_SYSTEM,
        "chat_web": chat_web._PLANNER_SYSTEM,
        "tools": tools._SYSTEM,
        "sector_ai": sector_ai._PEERS_SYSTEM,
        "llm_map": llm_map._SYSTEM,
        "llm_map.pdf": llm_map._PDF_SYSTEM,
        "instruments": instruments._SYSTEM,
        "daily": daily._SHAPE,
        "daily_analysis": daily_analysis._SHAPE,
        "learnings": learnings.lesson_prompt([]),
    }
    for where, text in prompts.items():
        assert "ONLY a JSON object" not in text, where
        assert "single JSON object" not in text, where
        assert "JSON only" not in text, where


def _named_functions() -> set[tuple[str, str]]:
    """(file, name) for every BAML function the code passes by name."""
    calls = {"ask", "_ask", "decode", "parse", "render"}
    out = set()
    for path in SRC.rglob("*.py"):
        if "baml_client" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else ""
            )
            if name not in calls:
                continue
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value[:1].isupper()
                    and arg.value.isidentifier()
                ):
                    out.add((path.name, arg.value))
    return out


def test_every_function_the_code_names_exists():
    named = _named_functions()
    assert {n for _, n in named} >= {
        "PickSkills", "PlanQueries", "DetectAction", "ProposePeers",
        "MapColumns", "ExtractStatement", "ResolveSymbols",
        "WriteDailyCard", "WriteAnalysis",
    }
    missing = sorted(f"{f}: {n}" for f, n in named if n not in FUNCTIONS)
    assert not missing


def test_detect_action_declares_every_field_a_tool_reads():
    """A tool's parser can only read what DetectAction's reply class lets the
    model send — a field added to tools.py alone would never arrive."""

    class Reads(dict):
        def __init__(self):
            super().__init__()
            self.read = set()

        def get(self, key, default=None):
            self.read.add(key)
            return super().get(key, default)

        def __getitem__(self, key):
            self.read.add(key)
            return super().__getitem__(key)

    declared = set(baml_types.ActionCall.model_fields)
    for tool in tools.TOOLS.values():
        data = Reads()
        tool.parse(data)
        assert data.read <= declared, (tool.name, data.read - declared)


# ------------------------------------------------------------------- parse


def test_a_comma_decimal_reaches_python_as_written():
    """A float field would read "1,5" as 15 — a position ten times too big.
    The figures stay text, and the callers' own float() decides."""
    data = structured.parse(
        '{"action": "set_position", "ticker": "NVDA", "shares": "1,5", "cost": 0.25}',
        "DetectAction",
    )
    assert data["shares"] == "1,5"
    assert data["cost"] == 0.25
    assert tools.parse_action(
        '{"action": "set_position", "ticker": "NVDA", "shares": "1,5", "cost": 2}'
    ).args == {"cost": 2.0}


def test_one_bad_alert_does_not_drop_the_good_one():
    raw = (
        '{"action": "set_alerts", "ticker": "AAPL", "alerts": ['
        '{"type": "sideways", "price": 1}, {"type": "below", "price": 150}]}'
    )
    assert len(structured.parse(raw, "DetectAction")["alerts"]) == 2
    assert tools.parse_action(raw).args == {
        "alerts": [{"type": "below", "price": 150.0}]
    }


def test_one_bad_statement_row_does_not_drop_the_page():
    raw = (
        '{"kind": "trades", "transactions": ['
        '{"date": "2026-01-02", "ticker": "NVDA", "action": "buy", '
        '"quantity": "n/a", "price": 100},'
        '{"date": "2026-01-03", "ticker": "ASML", "action": "sell", '
        '"quantity": 2, "price": "612,40"}]}'
    )
    data = structured.parse(raw, "ExtractStatement")
    assert data["kind"] == "trades"
    rows = data["transactions"]
    assert [r["ticker"] for r in rows] == ["NVDA", "ASML"]
    assert rows[1]["price"] == "612,40"


def test_the_enums_come_back_in_their_wire_spelling():
    assert structured.parse(
        '{"header_row": 0, "columns": {"date": 0}, "asset_class": "Crypto"}',
        "MapColumns",
    )["asset_class"] == "crypto"
    # "none" is a reserved word in the generated Python; the value is read
    # as Neither and llm_map files anything but trades/positions as none.
    assert structured.parse(
        '{"kind": "none", "transactions": []}', "ExtractStatement"
    )["kind"] == "neither"


def test_an_unresolved_label_stays_an_explicit_null():
    assert structured.parse(
        '{"Apple Inc": "AAPL", "Mystery Fund": null}', "ResolveSymbols"
    ) == {"Apple Inc": "AAPL", "Mystery Fund": None}


@pytest.mark.parametrize(
    "fn, raw, want",
    [
        # Left to the parser, each of these keeps its comma: "null,", "10,".
        ("ResolveSymbols", '{"A": "AAPL", "B": null,}', {"A": "AAPL", "B": None}),
        ("WriteDailyCard", '{"focus": [], "headline": null,}', {"focus": []}),
        (
            "DetectAction",
            '{"action": "set_position", "ticker": "X", "shares": 10,}',
            {"action": "set_position", "ticker": "X", "shares": 10.0},
        ),
        (
            "ExtractStatement",
            '{"transactions": [{"ticker": "X", "price": 12.5 ,},]}',
            {"transactions": [{"ticker": "X", "price": 12.5}]},
        ),
        # A quoted value was never affected, and stays as written.
        ("WriteDailyCard", '{"headline": "Up 1,5%,",}', {"headline": "Up 1,5%,"}),
    ],
)
def test_a_bare_value_before_a_trailing_comma_keeps_its_meaning(fn, raw, want):
    assert structured.parse(raw, fn) == want


def test_a_card_in_a_fence_with_trailing_commas_still_reads():
    raw = (
        "Here is today's card:\n```json\n"
        '{"headline": "Quiet day", "items": [{"key": "day", "line": "Flat",},],'
        ' "focus": ["NVDA",],}\n```'
    )
    assert structured.parse(raw, "WriteDailyCard") == {
        "headline": "Quiet day",
        "items": [{"key": "day", "line": "Flat"}],
        "focus": ["NVDA"],
    }


@pytest.mark.parametrize(
    ("fn", "raw"),
    [
        # Out of tokens mid-string: the parser would save "retire at 5".
        ("ExtractLessons", '{"ops": [{"op": "add", "text": "Me jubilo a los 5'),
        ("ExtractLessons", '{"ops": ['),
        ("WriteDailyCard", '```json\n{"headline": "Quiet", "items": [{"key": "day"'),
        ("ResolveSymbols", '{"Apple": "AAPL", "Tesla": "TS'),
    ],
)
def test_a_reply_cut_off_before_its_json_closes_is_off_contract(fn, raw):
    with pytest.raises(structured.OffContract):
        structured.parse(raw, fn)


def test_a_closed_reply_is_read_whatever_follows_it():
    # Quotes and brackets inside strings, and prose after the object, are not
    # an unclosed reply.
    raw = '{"ops": [{"op": "add", "text": "Digo \\"[no {"}]} Hope it helps {'
    assert structured.parse(raw, "ExtractLessons")["ops"][0]["text"] == 'Digo "[no {'


def test_the_parser_is_safe_to_share_between_threads():
    # The Home card, the sector scan and chat turns parse concurrently on
    # one process-wide client.
    raw = '{"action": "tag", "ticker": "NVDA", "tags": ["ai", "chips"]}'

    def one(_):
        return structured.parse(raw, "DetectAction")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(200)))
    assert all(r == results[0] for r in results)
    assert results[0]["tags"] == ["ai", "chips"]
