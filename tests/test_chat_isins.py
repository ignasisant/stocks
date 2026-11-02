"""ISINs in an answer are settled against OpenFIGI before it is stored.

The case is prod's bond-ETF answer of 2026-11-02: eight ISINs from memory,
three with a wrong check digit, one OpenFIGI had no record of, three that
named other funds. The reader saw twelve characters and no way to tell.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from stocks import identity
from stocks.chat import engine, guard, isins
from stocks.data import openfigi
from stocks.data.openfigi import Security
from stocks.web import auth

HY = "IE00B66F4759"  # iShares € High Yield Corp Bond, real
WORLD = "IE00B4L5Y983"  # iShares Core MSCI World, real
BTP = "IT0005566440"  # check digit fine, OpenFIGI: no such ISIN
BAD = "IE00B3VTM092"  # check digit wrong


def _sec(isin: str, name: str) -> Security:
    return Security(isin, name, "Mutual Fund", "BBG0", ())


@pytest.fixture
def registry(monkeypatch):
    """OpenFIGI as it answered: two securities, one miss. Records the asks."""
    asked: list[list[str]] = []
    answers = {HY: _sec(HY, "ISHARES EURO HY CORP"),
               WORLD: _sec(WORLD, "ISHARES CORE MSCI WORLD")}

    def securities(wanted):
        wanted = list(wanted)
        asked.append(wanted)
        return {isin: answers.get(isin) for isin in wanted}

    monkeypatch.setattr(openfigi, "securities", securities)
    monkeypatch.setattr(openfigi, "missed", lambda isin: isin == BTP)
    return asked


def test_the_check_digit_is_iso_6166():
    for real in (HY, WORLD, BTP, "US0378331005", "NL0010273215"):
        assert isins.check_digit_ok(real), real
    for made_up in (BAD, "IE00B3VTM216", "IE00B3VTM323", "US0378331006"):
        assert not isins.check_digit_ok(made_up), made_up


def test_a_made_up_isin_never_reaches_the_reader(registry):
    said = (f"- Esempi: `{BAD}` (1-3yr), **{HY}** (HY)\n"
            f"- BTP: {BTP}\n"
            f"- Euro agg: (`{BAD}`, `{WORLD}`)")
    out = isins.verify(said)
    assert BAD not in out and BTP not in out
    assert out.splitlines() == [
        f"- Esempi: (1-3yr), **{HY}** (HY)",
        "- BTP:",
        f"- Euro agg: (**{WORLD}**)",
    ]
    # Only what passed the check digit is asked about.
    assert sorted(registry[0]) == sorted([HY, BTP, WORLD])


def test_a_known_isin_is_bold_so_the_panel_names_it(registry):
    assert isins.verify(f"Buy `{HY}` for carry") == f"Buy **{HY}** for carry"
    assert isins.verify(f"{WORLD} is equity") == f"**{WORLD}** is equity"


def test_an_isin_the_reader_typed_stays_to_be_named(registry):
    said = f"`{BAD}` no es un ISIN válido; quizá buscas **{HY}**."
    out = isins.verify(said, asked=f"¿Qué ETF es el {BAD}?")
    assert out == f"`{BAD}` no es un ISIN válido; quizá buscas **{HY}**."
    assert isins.verify(said) == f"no es un ISIN válido; quizá buscas **{HY}**."


def test_an_isin_nobody_could_ask_about_stays_as_written(monkeypatch):
    monkeypatch.setattr(openfigi, "securities", lambda wanted: dict.fromkeys(wanted))
    monkeypatch.setattr(openfigi, "missed", lambda isin: False)
    said = f"The fund `{HY}`, indented:\n    - kept  as is"
    assert isins.verify(said) == said


def test_an_answer_without_isins_asks_nobody(monkeypatch):
    def boom(_):
        raise AssertionError("OpenFIGI asked for an answer with no ISIN")

    monkeypatch.setattr(openfigi, "securities", boom)
    said = "**ASML.AS** and NVDA; ISIN codes are 12 characters. USD1234567890X"
    assert isins.verify(said) == said


def test_an_isin_is_named_from_the_registry_when_nothing_else_knows_it(monkeypatch):
    monkeypatch.setattr(identity, "yahoo_symbol", lambda ticker: ticker)
    monkeypatch.setattr(identity, "load_watchlist", lambda path: [])
    monkeypatch.setattr(openfigi, "known", lambda isin: (
        _sec(BTP, "BUONI POLIENNALI DEL TES") if isin == BTP else None))
    assert identity.company_name(BTP, "unused.yaml") == "BUONI POLIENNALI DEL TES"
    assert identity.company_name("IE00B3VTMJ91", "unused.yaml") is None


def test_the_prompt_forbids_isins_from_memory():
    prompt = engine.system_prompt({}, "")
    assert "Never write an ISIN from memory" in prompt


@dataclass
class _Writes:
    reply: str
    id: str = "free"
    classifier_model: str = "cheap"
    default_model: str = "default-model"

    def available(self) -> bool:
        return True

    def complete(self, api_key, model, system, messages) -> str:
        return self.reply


def test_the_stored_answer_is_the_checked_one(registry, monkeypatch, tmp_path):
    from stocks.web import llm

    monkeypatch.setattr(guard, "mode", lambda: "off")
    monkeypatch.setattr(llm, "PROVIDERS", {"free": _Writes(
        f"Short duration: `{BAD}` (1-3yr). High yield: `{HY}`.")})
    monkeypatch.setattr(engine.market, "lookup_for", lambda *a, **k: [])
    (tmp_path / "watchlist.yaml").write_text("watchlist: []\n")
    paths = {"prefs_path": tmp_path / "prefs.json",
             "chat_path": tmp_path / "chat.json",
             "watchlist": tmp_path / "watchlist.yaml",
             "db": tmp_path / "portfolio.db"}
    reply = engine.answer(prefs={"chat_skills_mode": "off"},
                          message="¿ETFs de bonos en euros?", lang="es", **paths)
    expected = f"Short duration: (1-3yr). High yield: **{HY}**."
    assert reply.text == expected
    assert auth.load_chat(paths["chat_path"])[-1]["content"] == expected
