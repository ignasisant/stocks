"""Skill library loading, classifier-output parsing and prompt assembly — pure,
no network."""

import pytest

from stocks.web import chat_skills

EXPECTED_IDS = {
    "tech", "energy", "value", "financials", "healthcare", "crypto",
    "emerging-markets", "dividend", "growth-momentum", "technical", "macro",
    "earnings-review", "portfolio-risk", "spain-tax", "us-tax", "bear-case",
    "etfs", "tax",
}
INDUSTRY_IDS = {
    "semiconductors", "internet-platforms", "hardware-devices",
    "nuclear-uranium", "utilities", "insurance", "reits", "biotech-clinical",
    "pharma", "medtech", "payments", "retail-restaurants", "consumer-staples",
    "autos-ev", "mining-metals", "aerospace-defense",
    "industrials-capital-goods", "telecom", "asset-managers-exchanges",
}


def test_catalog_loads_all_skills():
    skills = chat_skills.catalog()
    assert {s.id for s in skills} == EXPECTED_IDS | INDUSTRY_IDS
    for s in skills:
        assert s.name and s.description and s.body, s.id


def test_industry_skills_stay_out_of_the_picker():
    assert {s.id for s in chat_skills.pickable()} == EXPECTED_IDS
    for s in chat_skills.catalog():
        if s.id in INDUSTRY_IDS:
            assert s.kind == "industry" and s.industries, s.id


@pytest.mark.parametrize(("sector", "industry", "expected"), [
    # The bug this exists for: Yahoo files Centrus under Energy, and the
    # oil-and-gas lens is the wrong one.
    ("Energy", "Uranium", "nuclear-uranium"),
    ("Energy", "Oil & Gas E&P", "energy"),
    ("Technology", "Semiconductors", "semiconductors"),
    ("Technology", "Software - Infrastructure", "tech"),
    ("Financial Services", "Banks - Regional", "financials"),
    ("Financial Services", "Insurance - Property & Casualty", "insurance"),
    ("Real Estate", "REIT - Industrial", "reits"),
    ("Healthcare", "Biotechnology", "biotech-clinical"),
    ("Healthcare", "Drug Manufacturers - General", "pharma"),
    # No industry match: the sector's broad lens.
    ("Utilities", "", "utilities"),
    ("Healthcare", "Something New", "healthcare"),
    ("", "", ""),
    ("Nowhere", "Nothing", ""),
])
def test_lens_for(sector, industry, expected):
    assert chat_skills.lens_for(sector, industry) == expected


def test_fits_is_case_insensitive_with_prefixes():
    s = chat_skills.Skill("x", "X", "d", "b", kind="industry",
                         industries=("Banks*", "Solar"))
    assert s.fits("banks - regional") and s.fits("Solar")
    assert not s.fits("Solar Inverters") and not s.fits("") and not s.fits("Bank")


def test_every_lens_for_target_exists():
    assert set(chat_skills.SECTOR_LENS.values()) <= chat_skills.valid_ids()


def test_skills_block_empty_without_ids():
    assert chat_skills.skills_block([]) == ""
    assert chat_skills.skills_block(["not-a-skill"]) == ""


def test_skills_block_contains_name_and_body():
    block = chat_skills.skills_block(["tech"])
    tech = next(s for s in chat_skills.catalog() if s.id == "tech")
    assert f"## {tech.name}" in block
    assert tech.body in block


def test_skills_block_order_is_stable():
    """Same set in any order -> byte-identical text (prompt-cache friendly)."""
    assert chat_skills.skills_block(["value", "tech"]) == chat_skills.skills_block(
        ["tech", "value"]
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"skills": ["tech", "value"]}', ["tech", "value"]),
        ('```json\n{"skills": ["energy"]}\n```', ["energy"]),
        ('Sure! {"skills": ["macro"]} fits best.', ["macro"]),
        ('{"skills": []}', []),
        ('{"skills": ["nope", "tech"]}', ["tech"]),  # unknown ids dropped
        ('{"skills": [42, "tech"]}', ["tech"]),  # non-strings dropped
        ("I would pick tech and spain-tax here", ["tech", "spain-tax"]),  # fallback
        ("total garbage", []),
        ("", []),
        ('{"skills": ["tech", "tech", "value"]}', ["tech", "value"]),  # dedupe
    ],
)
def test_parse_skill_ids(raw, expected):
    assert chat_skills.parse_skill_ids(raw) == expected


def test_parse_skill_ids_caps_at_limit():
    raw = '{"skills": ["tech", "value", "macro", "energy"]}'
    assert len(chat_skills.parse_skill_ids(raw)) == chat_skills.MAX_AUTO
    assert chat_skills.parse_skill_ids(raw, limit=3) == ["tech", "value", "macro"]


class _FakeProvider:
    classifier_model = "cheap-model"

    def __init__(self, reply=None, exc=None, replies=None):
        self.reply, self.exc = reply, exc
        self.replies = list(replies) if replies else None
        self.calls = []

    def complete(self, api_key, model, system, messages):
        self.calls.append((api_key, model, system, messages))
        if self.exc:
            raise self.exc
        return self.replies.pop(0) if self.replies else self.reply


def test_classify_returns_parsed_ids():
    p = _FakeProvider(reply='{"skills": ["earnings-review"]}')
    assert chat_skills.classify(p, "k", "how was the NVDA quarter?") == [
        "earnings-review"
    ]
    api_key, model, system, messages = p.calls[0]
    assert (api_key, model) == ("k", "cheap-model")
    assert "- earnings-review:" in system  # catalog rides in the system prompt
    assert "NVDA" in messages[0]["content"]


def test_classify_none_on_provider_error():
    p = _FakeProvider(exc=RuntimeError("boom"))
    assert chat_skills.classify(p, "k", "anything") is None


def test_classify_repairs_an_off_contract_reply():
    p = _FakeProvider(replies=["I think tech fits!", '{"skills": ["tech"]}'])
    assert chat_skills.classify(p, "k", "chips?") == ["tech"]
    assert len(p.calls) == 2
    repair = p.calls[1][3]
    assert repair[0]["role"] == "user"  # the original question rides along
    assert repair[1]["content"] == "I think tech fits!"
    assert "ONLY the JSON object" in repair[2]["content"]


def test_classify_does_not_spend_a_repair_call_on_a_good_reply():
    p = _FakeProvider(reply='{"skills": []}')
    assert chat_skills.classify(p, "k", "hola") == []  # an explicit "none" is obeyed
    assert len(p.calls) == 1


def test_classify_reads_prose_when_the_repair_fails_too():
    p = _FakeProvider(reply="the tech lens is the one I would use here")
    assert chat_skills.classify(p, "k", "chips?") == ["tech"]


def test_classify_none_when_both_tries_are_unreadable():
    # Two junk replies mean the router is broken, not that no skill applies:
    # None lets the caller keep the previous turn's lens (and its warm cache).
    p = _FakeProvider(reply="no json here")
    assert chat_skills.classify(p, "k", "hello") is None
    assert len(p.calls) == 2


def test_an_earnings_review_reads_the_reaction_where_it_trades():
    """A report after the bell moves the stock in after-hours and the next
    premarket; the session before it is not the reaction (ServiceNow's -3 %
    was called the guidance's verdict when the print had it 18 % lower)."""
    body = {s.id: s.body for s in chat_skills.catalog()}["earnings-review"]
    assert "after-hours" in body and "premarket" in body
    assert "before the report" in body
