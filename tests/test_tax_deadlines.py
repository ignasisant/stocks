"""The filing calendar each jurisdiction imposes, and the 30-day reminder.

What is pinned here is the arithmetic a reader would be hurt by getting wrong:
which tax year a deadline belongs to (the UK's return lands two calendar years
after its year opens), the weekend roll where the law rolls and not where it
doesn't, and that every rule has copy in both catalogs.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from stocks.notify import state as notify_state
from stocks.portfolio import tax
from stocks.portfolio.tax import deadlines

LOCALES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "locales"


def _on(code: str, today: date) -> dict[str, date]:
    return {f"{d.key}:{d.tax_year}": d.date for d in deadlines.calendar(code, today)}


def test_every_jurisdiction_has_a_rule_set():
    assert set(deadlines.RULES) == set(tax.codes())


def test_spain_files_the_720_and_the_renta_the_year_after():
    got = _on("ES", date(2026, 9, 23))
    assert got["es_modelo_720:2026"] == date(2027, 3, 31)
    assert got["es_renta:2026"] == date(2027, 6, 30)
    assert got["es_renta_second:2025"] == date(2026, 11, 5)


def test_a_weekend_deadline_rolls_where_the_law_rolls_it():
    # 30 June 2024 was a Sunday; the campaign closed Monday 1 July.
    assert _on("ES", date(2024, 6, 1))["es_renta:2023"] == date(2024, 7, 1)


def test_hmrc_does_not_roll_31_january():
    # 31 January 2027 is a Sunday, and it is still the deadline.
    got = _on("UK", date(2026, 9, 23))
    assert got["uk_self_assessment:2025"] == date(2027, 1, 31)


def test_the_uk_year_is_written_its_own_way():
    labels = {d.year_label for d in deadlines.calendar("UK", date(2026, 9, 23))}
    assert "2025/26" in labels


def test_no_personal_return_means_no_deadlines():
    assert deadlines.calendar("AE", date(2026, 9, 23)) == []


def test_an_unset_residence_is_spain():
    assert deadlines.calendar(None, date(2026, 9, 23))[0].code == "ES"


def test_due_soon_is_the_next_thirty_days_today_included():
    soon = deadlines.due_soon("ES", date(2027, 3, 1))
    assert {d.key for d in soon} == {"es_modelo_720", "es_modelo_721"}
    assert deadlines.due_soon("ES", date(2027, 2, 28)) == []
    assert {d.key for d in deadlines.due_soon("ES", date(2027, 3, 31))} == {
        "es_modelo_720",
        "es_modelo_721",
    }
    assert deadlines.due_soon("ES", date(2027, 4, 1)) == []


def test_a_reminder_goes_once():
    state: dict = {}
    today = date(2027, 3, 5)
    due = notify_state.tax_reminders_due(state, "ES", today)
    assert len(due) == 2
    notify_state.remember_tax_reminders(state, due)
    assert notify_state.tax_reminders_due(state, "ES", today) == []
    # Next year's 720 is a different deadline and is reminded afresh.
    assert notify_state.tax_reminders_due(state, "ES", date(2028, 3, 5))


@pytest.mark.parametrize("lang", ["en", "es"])
def test_every_rule_has_a_title_and_a_body(lang):
    catalog = json.loads((LOCALES / lang / "earnings.json").read_text("utf-8"))
    for code, rules in deadlines.RULES.items():
        for rule in rules:
            stem = f"earnings.tax_{code.lower()}_{rule.key}"
            assert "{year}" in catalog[stem]
            assert f"{stem}_body" in catalog
