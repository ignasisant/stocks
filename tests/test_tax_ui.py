"""Jurisdiction resolution and wording for the web layer."""

import pytest

from stocks.portfolio import tax
from stocks.web import tax_ui


@pytest.fixture
def locale(monkeypatch):
    """Pretend the browser reports `code` as its locale."""

    class _Ctx:
        locale = None

    ctx = _Ctx()
    monkeypatch.setattr(tax_ui.st, "context", ctx)

    def _set(code):
        ctx.locale = code

    return _set


# --- resolution ---

def test_explicit_preference_wins(locale):
    locale("es-ES")
    assert tax_ui.resolve_code({"tax_residence": "US"}) == "US"


def test_auto_reads_the_browser_region(locale):
    locale("en-US")
    assert tax_ui.resolve_code({}) == "US"
    assert tax_ui.resolve_code({"tax_residence": "auto"}) == "US"


def test_a_supported_region_resolves_to_its_jurisdiction(locale):
    locale("de-DE")
    assert tax_ui.resolve_code({}) == "DE"


def test_an_emirati_browser_locale_resolves_to_the_uae(locale):
    locale("ar-AE")
    assert tax_ui.resolve_code({}) == "AE"


# --- where the jurisdiction came from ---

def test_a_stored_preference_is_reported_as_chosen(locale):
    locale("de-CH")
    assert tax_ui.resolve({"tax_residence": "US"}) == ("US", tax_ui.CHOSEN)


def test_a_modelled_region_is_reported_as_such(locale):
    locale("de-DE")
    assert tax_ui.resolve({}) == ("DE", tax_ui.REGION)


def test_a_region_we_do_not_model_is_flagged_not_silently_spanish(locale):
    """The whole point: a Japanese filer must not read IRPF as if it were his."""
    locale("ja-JP")
    code, how = tax_ui.resolve({})
    assert (code, how) == ("ES", tax_ui.UNMODELLED)


def test_a_locale_with_no_region_is_not_warned_about(locale):
    # "es" names no country. Spain is very likely right, and a warning here
    # would be noise on the app's own home jurisdiction.
    locale("es")
    assert tax_ui.resolve({}) == ("ES", tax_ui.UNKNOWN)


def test_resolve_code_still_answers_the_code_alone(locale):
    locale("ja-JP")
    assert tax_ui.resolve_code({}) == "ES"


def test_active_hands_back_the_jurisdiction_and_the_provenance(locale):
    locale("de-CH")
    jur, how = tax_ui.active({})
    assert (jur.code, how) == ("CH", tax_ui.REGION)


# --- flags ---

def test_every_jurisdiction_gets_a_flag_from_its_own_code():
    # Built from the code, so a new country needs no table entry.
    assert tax_ui.flag_emoji("ES") == "\U0001F1EA\U0001F1F8"
    assert tax_ui.flag_emoji("ae") == "\U0001F1E6\U0001F1EA"
    assert all(tax_ui.flag_emoji(c) for c in tax.codes())


def test_the_uk_flies_gb_because_its_tax_code_is_not_its_country_code():
    assert tax_ui.flag_emoji("UK") == tax_ui.flag_emoji("GB")


def test_something_that_is_not_a_country_code_gets_no_flag():
    # `label` concatenates unconditionally, so this must be empty, not junk.
    assert tax_ui.flag_emoji("auto") == ""
    assert tax_ui.flag_emoji("") == ""


def test_the_selector_label_is_the_flag_then_the_name():
    assert tax_ui.label("ES").startswith("\U0001F1EA\U0001F1F8 ")
    assert "Spain" in tax_ui.label("ES") or "España" in tax_ui.label("ES")


def test_unknown_region_falls_back_to_spain(locale):
    """A book has to be taxed under some rules; this app's home is Spain."""
    locale("ja-JP")
    assert tax_ui.resolve_code({}) == tax.DEFAULT_CODE == "ES"


def test_a_language_region_is_read_as_the_region_not_the_language(locale):
    """"pt-BR" is a Brazilian speaking Portuguese, not a Portuguese filer."""
    locale("pt-BR")
    assert tax_ui.resolve_code({}) == "ES"
    locale("pt-PT")
    assert tax_ui.resolve_code({}) == "PT"


def test_a_language_without_a_region_falls_back(locale):
    locale("en")
    assert tax_ui.resolve_code({}) == "ES"


def test_region_of_needs_a_two_letter_subtag():
    assert tax_ui.region_of("en_US") == "US"
    assert tax_ui.region_of("es-419") is None
    assert tax_ui.region_of(None) is None


# --- settings ---

def test_settings_come_from_prefs():
    s = tax_ui.settings(
        {"tax_filing_status": "mfj", "tax_other_income": "90000", "tax_niit": True}
    )
    assert (s.filing_status, s.other_income, s.include_niit) == ("mfj", 90_000.0, True)


def test_a_junk_income_preference_does_not_break_the_tab():
    assert tax_ui.settings({"tax_other_income": "lots"}).other_income == 0.0


# --- wording ---

def test_key_prefers_the_jurisdictions_own_copy():
    assert tax_ui.key("US", "estimated_tax_help") == "portfolio.us_estimated_tax_help"
    # No US override for the shared label: the neutral key answers.
    assert tax_ui.key("US", "net_taxable") == "portfolio.net_taxable"
    assert tax_ui.key("ES", "tax_header") == "portfolio.es_tax_header"


def test_money_puts_the_right_symbol_on():
    assert tax_ui.money(1_240, "EUR") == "€1,240"
    assert tax_ui.money(-3_000, "USD") == "$-3,000"
    assert tax_ui.money(1_240, "USD", signed=True) == "$+1,240"


def test_flag_caption_is_localized_per_flag(monkeypatch):
    monkeypatch.setattr(tax_ui.i18n, "active_language", lambda: "en")
    es_flag = tax.get("ES").reporting_flags(60_000)[0]
    caption = tax_ui.flag_caption("ES", es_flag, "EUR")
    assert "Modelo 720" in caption and "€60,000" in caption
    fbar = tax.get("US").reporting_flags(5_000)[0]
    assert "FBAR" in tax_ui.flag_caption("US", fbar, "USD")


def test_an_unworded_flag_still_renders(monkeypatch):
    monkeypatch.setattr(tax_ui.i18n, "active_language", lambda: "en")
    odd = tax.ReportingFlag("form_9999", 12_000, 10_000, True)
    caption = tax_ui.flag_caption("US", odd, "USD")
    assert "$12,000" in caption and "portfolio." not in caption
