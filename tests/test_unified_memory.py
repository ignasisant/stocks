"""One memory everywhere (engine.user_memory).

What the user told the chat steers every other surface that writes to them —
the daily card, the analysis behind one of its lines, the Telegram digest,
weekly and alerts lines, and the walkthrough — under the same switches as the
chat. Pinned here:

* each surface's prompt carries the saved memories and the clause on how to
  read them (`engine.MEMORY_USE`), and leaves the prompt as it was without;
* the card also quotes the earlier conversations about today's tickers, on
  the user turn and after the data, so the facts the audit reads are the
  same bytes with or without them;
* nothing here can stop a line from being written: a memory that cannot be
  read is a line written without it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from stocks.chat import daily, daily_analysis, engine, guide_ai, learnings, memory
from stocks.notify import narrative
from stocks.notify.alerts import AlertHit
from stocks.notify.digest import DigestData
from stocks.notify.fanout import NotifyUser

DAY = date(2026, 10, 3)
SAID = "Mantengo NVDA a largo plazo, no la quiero vender"

FACTS = {
    "date": DAY.isoformat(),
    "currency": "EUR",
    "actions": [
        {"kind": "drawdown", "ticker": "NVDA", "pnl_pct": -21.4, "pnl": -830.0,
         "currency": "EUR", "key": "drawdown:NVDA"},
        {"kind": "drawdown", "ticker": "nvda", "pnl_pct": -21.4, "pnl": -830.0,
         "currency": "EUR", "key": "drawdown:NVDA-dup"},
        {"kind": "vs_benchmark", "ticker": "", "index": "S&P 500",
         "book_month_pct": -1.2, "index_month_pct": 2.4, "gap_pp": -3.6,
         "currency": "EUR", "key": "vs_benchmark:"},
    ],
}


@dataclass
class Recorder:
    id: str = "free"
    reply: str = ""
    is_available: bool = True
    systems: list = field(default_factory=list)
    contents: list = field(default_factory=list)

    def available(self) -> bool:
        return self.is_available

    def complete(self, api_key, model, system, messages) -> str:
        self.systems.append(system)
        self.contents.append(messages[-1]["content"])
        return self.reply


@pytest.fixture(autouse=True)
def free_pot(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "GLOBAL_FREE_FILE", tmp_path / "free_llm_global.json")
    monkeypatch.setattr(engine, "_global_free", {"day": "", "used": 0})
    monkeypatch.setattr(engine, "_global_free_loaded", True)


@pytest.fixture
def provider(monkeypatch) -> Recorder:
    from stocks.web import llm

    fake = Recorder()
    monkeypatch.setattr(llm, "PROVIDERS", {"free": fake})
    return fake


@pytest.fixture
def chat(tmp_path) -> Path:
    """An account's chat.json path, with one saved memory beside it."""
    path = tmp_path / "chat.json"
    learnings.add(learnings.path_for(path), SAID, kind="decision")
    return path


def recalled(text: str = "NVDA: la mantengo pase lo que pase") -> memory.Memory:
    return memory.Memory(thread="t1", role="user", when="2026-09-30",
                         text=text, rank=1)


def card() -> daily.DailyAction:
    written = daily.computed(FACTS, "en", DAY)
    return daily.DailyAction.from_dict(daily.to_store(None, written, FACTS))


# ------------------------------------------------------------- the helper


def test_no_chat_is_no_memory():
    assert engine.user_memory({}, None, ["NVDA"]) == ("", [])


def test_the_helper_reads_the_saved_memories(chat):
    block, talk = engine.user_memory({}, chat, ["NVDA"])
    assert SAID in block and talk == []


def test_memory_switched_off_is_read_nowhere(chat):
    assert engine.user_memory({"chat_memory": False}, chat, ["NVDA"])[0] == ""


def test_recall_switched_off_quotes_no_conversation(chat, monkeypatch):
    monkeypatch.setattr(memory, "about", lambda *a, **k: [recalled()])
    chat.write_text("[]")
    assert engine.talk_about({"chat_recall": False}, chat, ["NVDA"]) == []


def test_a_memory_that_cannot_be_read_is_a_line_without_it(chat, monkeypatch):
    def broken(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr(engine, "memory_block", broken)
    monkeypatch.setattr(engine, "talk_about", broken)
    assert engine.user_memory({}, chat, ["NVDA"]) == ("", [])


# ------------------------------------------------------------ the card


def test_the_card_heads_where_the_chat_did(provider, chat):
    daily.generate({}, {}, FACTS, "en", DAY, chat_path=chat)
    system = provider.systems[0]
    assert SAID in system and engine.MEMORY_USE in system
    assert system.index(SAID) < system.index(engine.MEMORY_USE)
    # Context, never data: the facts the audit reads do not carry it.
    assert SAID not in provider.contents[0]
    assert json.loads(provider.contents[0]) == FACTS


def test_the_card_quotes_what_was_said_about_todays_tickers(
    provider, chat, monkeypatch
):
    asked = []
    monkeypatch.setattr(
        engine, "talk_about",
        lambda prefs, path, names, **k: asked.append(names) or [recalled()],
    )
    daily.generate({}, {}, FACTS, "en", DAY, chat_path=chat)
    assert asked == [["NVDA"]]  # the actions' tickers, once each, no blanks
    content = provider.contents[0]
    data, quoted = content.split("\n\n---\n", 1)
    assert json.loads(data) == FACTS
    assert quoted.startswith(memory.QUOTE_HEADER)
    assert "la mantengo pase lo que pase" in quoted


def test_without_memories_the_card_prompt_is_what_it_was():
    plain = daily.prompt(FACTS, {}, "en")
    assert daily.prompt(FACTS, {}, "en", memories="", talk=[]) == plain
    assert engine.MEMORY_USE not in plain[0]


def test_a_card_without_a_chat_path_reads_nothing(provider):
    daily.generate({}, {}, FACTS, "en", DAY)
    assert engine.MEMORY_USE not in provider.systems[0]


# ---------------------------------------------------- one line's analysis


def test_the_analysis_reads_the_memory_about_its_line(provider, chat, monkeypatch):
    asked = []
    monkeypatch.setattr(
        engine, "talk_about",
        lambda prefs, path, names, **k: asked.append(names) or [recalled()],
    )
    daily_analysis.generate({}, {}, card(), "drawdown:NVDA", {}, "en",
                            chat_path=chat)
    assert asked == [["NVDA"]]
    system = provider.systems[0]
    assert SAID in system and engine.MEMORY_USE in system
    assert system.endswith(daily._HOUSE_RULES)  # the rules still close it
    assert "la mantengo pase lo que pase" in provider.contents[0]


def test_a_line_without_a_ticker_looks_up_no_conversation(provider, chat, monkeypatch):
    asked = []
    monkeypatch.setattr(
        engine, "talk_about", lambda prefs, path, names, **k: asked.append(names) or []
    )
    daily_analysis.generate({}, {}, card(), "vs_benchmark:", {}, "en", chat_path=chat)
    assert asked == [[]]
    assert SAID in provider.systems[0]


# ------------------------------------------------------------- Telegram


def digest_data() -> DigestData:
    return DigestData(date=DAY, total=1000.0, day=(10.0, 0.01), movers=[("NVDA", 0.03)])


def test_every_telegram_line_reads_the_memory(provider, chat):
    block = engine.memory_block({}, chat)
    narrative.highlight(digest_data(), {}, "en", memories=block)
    narrative.alerts_line([AlertHit("NVDA", "above", "closed above 190", value=192.0)],
                          {}, "en", memories=block)
    for system in provider.systems:
        assert SAID in system and system.endswith(engine.MEMORY_USE)


def test_telegram_lines_speak_to_the_profiled_investor(provider):
    prefs = {"investor_profile": {"set": True, "risk": "conservative",
                                  "horizon": "5y_plus"}}
    narrative.highlight(digest_data(), prefs, "en")
    assert engine.persona({"set": True, "risk": "conservative",
                           "horizon": "5y_plus"}) in provider.systems[0]
    assert engine.MEMORY_USE not in provider.systems[0]


def test_the_account_memory_is_read_beside_its_prefs(tmp_path, chat):
    root = chat.parent
    user = NotifyUser(label="jane", prefs={}, watchlist=root / "watchlist.yaml",
                      db=root / "portfolio.db", prefs_path=root / "prefs.json",
                      state_path=root / "alerts_state.json")
    assert SAID in user.memories()
    off = NotifyUser(label="jane", prefs={"chat_memory": False},
                     watchlist=root / "watchlist.yaml", db=root / "portfolio.db",
                     prefs_path=root / "prefs.json",
                     state_path=root / "alerts_state.json")
    assert off.memories() == ""


# ---------------------------------------------------------- walkthrough


def test_the_walkthrough_reads_the_memory(provider, chat):
    from stocks.web import onboarding

    guide_ai.generate({}, onboarding.STEPS[0], "en", save=lambda p: None,
                      account_facts="{}", memories=engine.memory_block({}, chat))
    assert SAID in provider.systems[0]
    assert provider.systems[0].endswith(engine.MEMORY_USE)
