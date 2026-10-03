"""The landing's number formatting and markup.

The page is built as a string, outside any request. See test_landing_static.py
for the document that wraps it and test_server.py for the routes that serve it.
"""

import re
from contextlib import ExitStack

import pytest

from stocks.web import landing

# ------------------------------------------------------------------ numbers


@pytest.fixture
def as_lang():
    """Enter landing.render_language(lang, jurisdiction) for the test.

    The jurisdiction defaults to the language's own — English pitches the US
    rules, Spanish the Spanish ones — so a test that cares about the country
    passes it explicitly.
    """
    with ExitStack() as stack:

        def _set(lang, jurisdiction=None):
            stack.enter_context(landing.render_language(lang, jurisdiction))

        yield _set


@pytest.mark.parametrize(
    ("lang", "amount", "signed", "expected"),
    [
        ("en", 48230, False, "€48,230"),
        ("es", 48230, False, "48.230 €"),
        ("en", 13254, True, "+€13,254"),
        ("es", 13254, True, "+13.254 €"),
        ("en", -612, True, "−€612"),
        ("es", -612, True, "−612 €"),
        ("en", 407, False, "€407"),
        ("es", 1234567, False, "1.234.567 €"),
    ],
)
def test_currency_follows_the_reader(as_lang, lang, amount, signed, expected):
    """Separators follow the language; the symbol follows the jurisdiction."""
    as_lang(lang, "ES")
    assert landing._money(amount, signed=signed) == expected


@pytest.mark.parametrize(
    ("lang", "amount", "signed", "expected"),
    [
        ("en", 48230, False, "$48,230"),
        ("es", 48230, False, "48.230 $"),
        ("en", -612, True, "−$612"),
    ],
)
def test_a_us_reader_gets_dollars(as_lang, lang, amount, signed, expected):
    as_lang(lang, "US")
    assert landing._money(amount, signed=signed) == expected


def test_english_pitches_the_us_rules_and_spanish_the_spanish_ones(as_lang):
    as_lang("en")
    assert landing.active_jurisdiction() == "US"
    assert landing._symbol() == "$"
    as_lang("es")
    assert landing.active_jurisdiction() == "ES"
    assert landing._symbol() == "€"


def test_jurisdiction_scoped_copy_falls_back_to_the_neutral_string(as_lang):
    as_lang("en", "US")
    # Overridden for the US pitch…
    assert landing.jur_key("landing.hero_title") == "landing.us_hero_title"
    # …but the shared strings have one version.
    assert landing.jur_key("landing.faq_q1") == "landing.faq_q1"
    assert landing.jur_key("common.sign_in_google") == "common.sign_in_google"


@pytest.mark.parametrize(
    ("lang", "value", "signed", "expected"),
    [
        ("en", 47.7, True, "+47.7%"),
        ("es", 47.7, True, "+47,7 %"),
        ("en", -22.6, True, "−22.6%"),
        ("es", -22.6, True, "−22,6 %"),
        ("en", 3.1, False, "3.1%"),
        ("es", 3.1, False, "3,1 %"),
    ],
)
def test_percent_follows_the_reader(as_lang, lang, value, signed, expected):
    as_lang(lang)
    assert landing._pct(value, signed=signed) == expected


def test_decimals_use_the_local_separator(as_lang):
    as_lang("en")
    assert landing._dec(1.0982, 4) == "1.0982"
    as_lang("es")
    assert landing._dec(1.0982, 4) == "1,0982"


def test_row_count_is_singular_or_plural(as_lang):
    as_lang("en")
    assert landing._rows(1) == "1 row"
    assert landing._rows(214) == "214 rows"


# ------------------------------------------------------------------- mobile


def _style_body(block: str) -> str:
    """The CSS text inside a <style> wrapper."""
    assert block.startswith("<style>") and block.endswith("</style>")
    return block[len("<style>") : -len("</style>")]


def test_stylesheet_is_one_block_with_the_breakpoints_in_order():
    css = _style_body(landing._CSS)
    assert css.count("{") == css.count("}")
    mobile = css.index("@media (max-width: 640px)")
    tiny = css.index("@media (max-width: 380px)")
    # base rules first, then the phone block, then the small-phone type tweaks —
    # each layer has to be able to override the one before it
    assert css.index(".ag-l-wrap {") < mobile < tiny


def test_mobile_rules_are_gated_by_width_in_the_stylesheet():
    css = _style_body(landing._CSS)
    after_breakpoint = css[css.index("@media (max-width: 640px)") :]
    assert ".ag-l-mbar {" in after_breakpoint
    # ...and the bar is hidden by default, outside any query
    assert ".ag-l-mbar { display: none; }" in landing._BASE_CSS


def test_user_agent_override_reapplies_the_same_rules_at_900():
    css = _style_body(landing._mobile_css())
    assert css.startswith("@media (max-width: 900px) {")
    assert landing._MOBILE_RULES in css
    # the small-phone block rides along, and stays last so it still wins
    assert css.index("@media (max-width: 380px)") > css.index(landing._MOBILE_RULES)


def test_mobile_bar_carries_the_sign_in_parameter():
    bar = landing._mobile_bar()
    assert bar.startswith('<div class="ag-l-mbar">')
    assert f"?{landing.PARAM_SIGNIN}=1" in bar


# -------------------------------------------------------------------- markup


@pytest.fixture
def body(as_lang):
    def _build(lang="en"):
        as_lang(lang)
        return landing.page_body()

    return _build


def test_the_english_page_argues_the_us_rules(body):
    """The pitch is a country's case, so the copy has to be that country's."""
    html = body("en")
    assert "IRS" in html and "IRC 1091" in html
    assert "Modelo 720" not in html and "LIRPF" not in html
    assert "$" in html


def test_the_spanish_page_argues_the_spanish_ones(body):
    html = body("es")
    assert "Modelo 720" in html and "33.5.f" in html
    assert "IRC 1091" not in html


def test_the_page_is_one_element_with_every_section(body):
    html = body()
    assert html.startswith('<div class="ag-l">') and html.endswith("</div>")
    for marker in (
        "ag-l-bar",      # top bar
        "ag-l-hero",
        "ag-l-broker",   # broker list
        "ag-l-chat",     # the assistant section
        "ag-l-lensgrid", # its skill-library strip
        "ag-l-provcard", # provenance
        "ag-l-trustgrid",
        "ag-l-q",        # FAQ
        "ag-l-final",
        "ag-l-foot",
        "ag-l-mbar",     # the phone CTA bar ships on every request
    ):
        assert marker in html, f"section missing: {marker}"


def test_the_lens_strip_names_every_skill_the_assistant_actually_ships(as_lang):
    """The strip is a claim about the skill library, so it has to match it.

    `_LENSES` mirrors web/skills/*.md the way `_BROKERS` mirrors platforms.py.
    A new skill file with no landing entry would leave the page advertising a
    smaller library than the panel offers, and a stale id would render its own
    locale key as the label.
    """
    from stocks.web import chat_skills

    assert set(landing._LENSES) == chat_skills.valid_ids()
    as_lang("en")
    html = landing._assistant()
    assert f"{len(landing._LENSES)} analysis lenses" in html
    assert "chat.skill." not in html, "a lens id with no locale label"


def test_the_assistant_is_pitched_once(as_lang):
    """The bento's AI and Telegram tiles moved into the assistant section.

    Two pitches for one feature read as two weaker features, and the bento's
    summary was the weaker of the two once the section existed.
    """
    for lang in ("en", "es"):
        as_lang(lang)
        bento = landing._bento()
        for key in ("landing.ai_c1_h", "landing.ai_n1_h"):
            assert landing.tr(key) not in bento
        assert landing.tr("landing.ai_n1_h") in landing._assistant()


def test_every_cta_leaves_the_landing_for_the_app(body):
    """The CTAs must point at the app, not back at the page they are on.

    `server.py` routes `/` to the landing precisely when there is no query
    parameter, so a relative `?signin=1` from `/es/` would land on the Spanish
    landing again instead of the app.
    """
    # &amp; because the href is escaped for the attribute it sits in
    pairs = (("en", "/?signin=1"), ("es", "/?signin=1&amp;lang=es"))
    for lang, expected in pairs:
        html = body(lang)
        assert f'href="{expected}"' in html
        assert 'href="?signin=1"' not in html, "relative CTA would stay on the page"


def test_the_language_toggle_stays_inside_the_jurisdiction(as_lang):
    """A reader on the Spanish-tax page wants that page in English, not the
    US-tax one — so the switch keeps the country and changes the language."""
    as_lang("en", "US")
    en_us = landing.page_body()
    assert f'href="{landing.PATH_ES_US}"' in en_us
    assert '<span class="on">EN</span>' in en_us
    assert f'href="{landing.PATH_ES}"' not in en_us
    assert "?lang=" not in en_us.replace("&lang=es", ""), "no ?lang= toggle links"

    as_lang("en", "ES")
    assert f'href="{landing.PATH_ES}"' in landing.page_body()


def test_the_jurisdiction_toggle_keeps_the_language(as_lang):
    as_lang("es", "ES")
    es_es = landing.page_body()
    # The other country, same language — from the tax panel and the footer.
    assert f'class="ag-l-jurswitch" href="{landing.PATH_ES_US}"' in es_es
    assert es_es.count(f'href="{landing.PATH_ES_US}"') >= 2
    # …while the language switch on the same page keeps the Spanish rules.
    assert f'href="{landing.PATH_EN_ES}"' in es_es

    as_lang("en", "US")
    en_us = landing.page_body()
    assert f'class="ag-l-jurswitch" href="{landing.PATH_EN_ES}"' in en_us


def test_the_repository_url_has_exactly_one_definition():
    """A retyped owner slug is a 404 on the link the whole pitch rests on.

    The shipped URL had a hyphen the owner slug does not, in three separate
    modules, so every "read the source yourself" link, the structured data's
    codeRepository and the legal pages' contact address all 404. One
    definition, imported — and this test fails if a second literal shows up to
    drift from it.
    """
    from pathlib import Path

    web = Path(landing.__file__).parent
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(web.rglob("*.py"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "https://github.com/" in line and path.name != "landing.py"
    ]
    assert not offenders, f"second repository URL literal: {offenders}"
    assert landing.GITHUB_URL == "https://github.com/ignasisant/stocks"


def test_the_brand_mark_is_absolute(body):
    """/es/ is a directory deeper, so a relative asset URL would 404 there."""
    assert f'src="{landing.ASSET_BASE}topstocks-icon.svg"' in body()


def test_the_copy_actually_changes_language(body):
    assert "Your real return" in body("en")
    assert "Tu rentabilidad real" in body("es")


def test_the_faq_renders_every_question_the_structured_data_claims(body):
    assert body().count("<details class=\"ag-l-q\"") == landing.FAQ_COUNT


def test_no_grid_track_can_outgrow_its_container():
    """`minmax(Npx, 1fr)` does not shrink below N — it overflows and gets clipped.

    A 400px minimum track inside a 370px phone viewport cut the hero card off
    at the right edge rather than scrolling. Every auto-fit minimum is written
    min(Npx, 100%).
    """
    bare = re.findall(r"minmax\(\d+px", landing._CSS)
    assert not bare, f"unclamped grid minimums: {bare}"
