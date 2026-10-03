"""Which jurisdiction a filer is taxed under, and the flag it is shown with."""

from stocks.api.routes.reference import flag_emoji
from stocks.portfolio import tax
from stocks.portfolio.tax import prefs as tax_prefs


def _resolve(locale, prefs):
    """Resolve as a request carrying `locale` as its browser locale would."""
    return tax_prefs.resolve(prefs, tax_prefs.region_of(locale))


def _code(locale, prefs):
    return _resolve(locale, prefs)[0]


# --- resolution ---

def test_explicit_preference_wins():
    assert _code("es-ES", {"tax_residence": "US"}) == "US"


def test_auto_reads_the_browser_region():
    assert _code("en-US", {}) == "US"
    assert _code("en-US", {"tax_residence": "auto"}) == "US"


def test_a_supported_region_resolves_to_its_jurisdiction():
    assert _code("de-DE", {}) == "DE"


def test_an_emirati_browser_locale_resolves_to_the_uae():
    assert _code("ar-AE", {}) == "AE"


# --- where the jurisdiction came from ---

def test_a_stored_preference_is_reported_as_chosen():
    assert _resolve("de-CH", {"tax_residence": "US"}) == ("US", tax_prefs.CHOSEN)


def test_a_modelled_region_is_reported_as_such():
    assert _resolve("de-DE", {}) == ("DE", tax_prefs.REGION)


def test_a_region_we_do_not_model_is_flagged_not_silently_spanish():
    """The whole point: a Japanese filer must not read IRPF as if it were his."""
    assert _resolve("ja-JP", {}) == ("ES", tax_prefs.UNMODELLED)


def test_a_locale_with_no_region_is_not_warned_about():
    # "es" names no country. Spain is very likely right, and a warning here
    # would be noise on the app's own home jurisdiction.
    assert _resolve("es", {}) == ("ES", tax_prefs.UNKNOWN)


def test_unknown_region_falls_back_to_spain():
    """A book has to be taxed under some rules; this app's home is Spain."""
    assert _code("ja-JP", {}) == tax.DEFAULT_CODE == "ES"


def test_a_language_region_is_read_as_the_region_not_the_language():
    """"pt-BR" is a Brazilian speaking Portuguese, not a Portuguese filer."""
    assert _code("pt-BR", {}) == "ES"
    assert _code("pt-PT", {}) == "PT"


def test_a_language_without_a_region_falls_back():
    assert _code("en", {}) == "ES"


def test_region_of_needs_a_two_letter_subtag():
    assert tax_prefs.region_of("en_US") == "US"
    assert tax_prefs.region_of("es-419") is None
    assert tax_prefs.region_of(None) is None


# --- settings ---

def test_settings_come_from_prefs():
    s = tax_prefs.settings(
        {"tax_filing_status": "mfj", "tax_other_income": "90000", "tax_niit": True}
    )
    assert (s.filing_status, s.other_income, s.include_niit) == ("mfj", 90_000.0, True)


def test_a_junk_income_preference_does_not_break_the_tab():
    assert tax_prefs.settings({"tax_other_income": "lots"}).other_income == 0.0


# --- flags ---

def test_every_jurisdiction_gets_a_flag_from_its_own_code():
    # Built from the code, so a new country needs no table entry.
    assert flag_emoji("ES") == "\U0001F1EA\U0001F1F8"
    assert flag_emoji("ae") == "\U0001F1E6\U0001F1EA"
    assert all(flag_emoji(c) for c in tax.codes())


def test_the_uk_flies_gb_because_its_tax_code_is_not_its_country_code():
    assert flag_emoji("UK") == flag_emoji("GB")


def test_something_that_is_not_a_country_code_gets_no_flag():
    # The selector concatenates unconditionally, so this must be empty, not junk.
    assert flag_emoji("auto") == ""
    assert flag_emoji("") == ""
