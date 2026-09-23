"""Reference data: the answers that are the same for every caller.

Three routes, one shared property — none of them reads anybody's book, and all
three exist because a client that keeps its own copy of the list goes stale
silently. Nobody reports a country they cannot see; they just file under
somebody else's rules.

So the tests here are mostly the same test, asked three ways: does the API
report what the engine actually ships, right now, rather than a list somebody
typed out once? Which is why they compare against the registries themselves and
never against a literal — a test with its own hardcoded twelve countries in it
would pass on the day the thirteenth shipped, and that is the exact bug.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app
from stocks.portfolio import tax

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


# ------------------------------------------------------------- jurisdictions


def test_every_jurisdiction_the_engine_ships_is_offered(client):
    """Against the registry, not against a list written here: a test holding
    its own twelve countries passes on the day the thirteenth ships, which is
    the failure this route exists to prevent."""
    payload = client.get("/v1/jurisdictions", headers=AUTH).json()
    codes = [j["code"] for j in payload["jurisdictions"]]
    assert codes == list(tax.JURISDICTIONS)  # the registry's own order
    assert payload["default"] == tax.DEFAULT_CODE


def test_each_row_carries_what_the_selector_draws_it_with(client):
    """A flag to scan by and a key to translate the name with. The flag is not
    translated — it is the same glyph in every language, which is why it is
    built from the code rather than written into a catalog."""
    rows = {j["code"]: j for j in client.get("/v1/jurisdictions", headers=AUTH).json()[
        "jurisdictions"
    ]}
    assert rows["ES"]["flag"] == "🇪🇸"
    assert rows["ES"]["label_key"] == "profile.tax_residence_es"
    # "UK" is how everyone writes the tax code; the country code is GB, and
    # getting that wrong draws Ukraine's flag beside Britain's rules.
    assert rows["UK"]["flag"] == "🇬🇧"
    assert rows["UK"]["label_key"] == "profile.tax_residence_uk"


def test_the_label_keys_are_ones_the_catalogs_actually_ship(client):
    """The other half: a key nobody wrote copy for renders as a dotted key on
    screen, and the selector would read `profile.tax_residence_jp`."""
    from stocks.web.i18n import catalog

    for lang in ("en", "es"):
        strings = catalog(lang)
        missing = [
            j["label_key"]
            for j in client.get("/v1/jurisdictions", headers=AUTH).json()[
                "jurisdictions"
            ]
            if j["label_key"] not in strings
        ]
        assert not missing, f"{lang} has no copy for {missing}"


def test_the_replay_rules_are_the_registry_ones(client):
    """These are not decoration: the currency is what the cost basis is replayed
    in and the matching rule is which parcel a sale consumes. A client stating
    them from its own table tells a UK filer their gains are FIFO in EUR."""
    rows = {j["code"]: j for j in client.get("/v1/jurisdictions", headers=AUTH).json()[
        "jurisdictions"
    ]}
    for code, jurisdiction in tax.JURISDICTIONS.items():
        row = rows[code]
        assert row["currency"] == jurisdiction.currency
        assert row["matching"] == jurisdiction.matching
        assert tuple(row["year_start"]) == jurisdiction.year_start
        assert row["settings_fields"] == list(jurisdiction.settings_fields)
        assert row["filing_statuses"] == list(jurisdiction.filing_statuses)
        assert row["pools_shares"] == jurisdiction.pools_shares
    # Spot-check the three that are easy to get backwards.
    assert rows["UK"]["year_start"] == [4, 6]  # 6 April, not 4 June
    assert rows["UK"]["matching"] == "s104"
    assert rows["IT"]["matching"] == "lifo"


def test_a_country_with_no_repurchase_rule_says_null_not_empty(client):
    """The registry spells "no such rule" as an empty string; JSON spells it
    null, and a client rendering `"" ` would print an empty badge where there is
    no rule to print."""
    rows = {j["code"]: j for j in client.get("/v1/jurisdictions", headers=AUTH).json()[
        "jurisdictions"
    ]}
    assert rows["ES"]["repurchase_window"] == "2m"
    assert rows["US"]["repurchase_window"] == "30d"
    # The UK's 30-day rule lives inside the s.104 replay, so there is no
    # separate window to label.
    assert rows["UK"]["repurchase_window"] is None


def test_a_carryforward_that_never_expires_is_null_not_zero(client):
    """Null means indefinitely. Zero would mean a loss that cannot be carried at
    all, which is the opposite claim about somebody's tax bill."""
    rows = {j["code"]: j for j in client.get("/v1/jurisdictions", headers=AUTH).json()[
        "jurisdictions"
    ]}
    assert rows["US"]["carryforward_years"] is None  # IRC 1212(b)
    assert rows["ES"]["carryforward_years"] == tax.get("ES").carryforward_years


def test_the_codes_are_ones_the_prefs_patch_would_accept(client):
    """The round trip that matters: every jurisdiction offered here has to be
    one `PATCH /prefs` will store, or the selector offers a country that cannot
    be chosen."""
    from stocks.api.routes.prefs import PrefsPatch

    for row in client.get("/v1/jurisdictions", headers=AUTH).json()["jurisdictions"]:
        assert PrefsPatch(tax_residence=row["code"]).tax_residence == row["code"]


# ----------------------------------------------------------- profile options


def test_the_profile_vocabulary_is_the_forms_own(client):
    """Same claim as the jurisdictions: against `web.auth`'s tuples, which are
    the ones `chat.engine.persona` has English wording for."""
    from stocks.web.auth import (
        PROFILE_CONSTRAINTS,
        PROFILE_FOCUS,
        PROFILE_HORIZON,
        PROFILE_RISK,
    )

    payload = client.get("/v1/profile-options", headers=AUTH).json()
    assert payload["risk"] == list(PROFILE_RISK)
    assert payload["horizon"] == list(PROFILE_HORIZON)
    assert payload["focus"] == list(PROFILE_FOCUS)
    assert payload["constraints"] == list(PROFILE_CONSTRAINTS)


def test_the_scales_are_offered_low_to_high(client):
    """A row of chips only reads as a scale when both halves agree on which end
    is "more"; reversing one is a silent change of meaning, not a layout bug."""
    payload = client.get("/v1/profile-options", headers=AUTH).json()
    assert payload["risk"][0] == "conservative"
    assert payload["risk"][-1] == "very_aggressive"
    assert payload["horizon"][0] == "under_1y"
    assert payload["horizon"][-1] == "5y_plus"


def test_every_option_has_copy_in_both_catalogs(client):
    """`profile.iv_<group>_<option>` is the key a client builds. An option with
    no copy renders as a dotted key inside a chip."""
    from stocks.web.i18n import catalog

    payload = client.get("/v1/profile-options", headers=AUTH).json()
    for lang in ("en", "es"):
        strings = catalog(lang)
        missing = [
            f"profile.iv_{group}_{option}"
            for group, options in payload.items()
            for option in options
            if f"profile.iv_{group}_{option}" not in strings
        ]
        assert not missing, f"{lang} has no copy for {missing}"


# ------------------------------------------------------------- market status


def test_the_market_state_is_a_clock_not_a_fetch(client):
    payload = client.get("/v1/market/status", headers=AUTH).json()
    assert isinstance(payload["us_open"], bool)
    assert payload["us_extended"] in (None, "pre", "post")
    # Parseable, and actually now rather than a formatted guess.
    stamp = datetime.fromisoformat(payload["as_of"])
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 60
    assert payload["tickers"] == []  # none were asked for


def test_an_open_session_needs_no_caveat_and_a_shut_one_does(client, monkeypatch):
    """`note` is what the page prints under a day-change figure. While the
    session is open there is nothing to warn about, and printing "market
    closed" over live numbers is worse than printing nothing."""
    import stocks.api.routes.market as route

    monkeypatch.setattr(route, "us_market_open", lambda: True)
    assert client.get("/v1/market/status", headers=AUTH).json()["note"] is None

    monkeypatch.setattr(route, "us_market_open", lambda: False)
    monkeypatch.setattr(route, "us_extended_session", lambda: None)
    payload = client.get("/v1/market/status", headers=AUTH).json()
    assert payload["note"] == "market_closed"
    assert payload["us_extended"] is None


@pytest.mark.parametrize(
    ("window", "note"), [("pre", "premarket"), ("post", "postmarket")]
)
def test_an_extended_window_gets_its_own_wording(client, monkeypatch, window, note):
    """A premarket quote is live data with a different meaning, not a stale
    close — and the app has separate copy for each, in both languages."""
    import stocks.api.routes.market as route

    monkeypatch.setattr(route, "us_market_open", lambda: False)
    monkeypatch.setattr(route, "us_extended_session", lambda: window)
    payload = client.get("/v1/market/status", headers=AUTH).json()
    assert payload["us_extended"] == window
    assert payload["note"] == note


def test_the_note_stems_are_ones_both_catalogs_word(client):
    """The stem is a catalog key with the page's own prefix in front of it, so
    `home.premarket_note` and `portfolio.market_closed_note` both have to
    exist — otherwise the client prints the key."""
    from stocks.web.i18n import catalog

    for lang in ("en", "es"):
        strings = catalog(lang)
        for stem in ("premarket", "postmarket", "market_closed"):
            for page in ("home", "portfolio"):
                assert f"{page}.{stem}_note" in strings, f"{lang} {page}.{stem}_note"


def test_a_ticker_is_reported_on_its_own_exchange(client, monkeypatch):
    """The per-ticker rows routinely disagree with the US block, and that is the
    point: a Paris name is live at 10:00 CET while New York is hours from
    opening, and crypto never shuts."""
    import stocks.api.routes.market as route

    monkeypatch.setattr(route, "us_market_open", lambda: False)
    monkeypatch.setattr(route, "us_extended_session", lambda: None)
    monkeypatch.setattr(route, "market_live", lambda t: t.endswith(".PA"))
    monkeypatch.setattr(route, "market_active", lambda t: t != "AAPL")

    rows = client.get(
        "/v1/market/status",
        params={"tickers": "aapl,mc.pa,BTC-EUR,AAPL"},
        headers=AUTH,
    ).json()["tickers"]
    # Ordered as asked, uppercased and deduplicated — a caller drawing a table
    # wants its own order back.
    assert [r["ticker"] for r in rows] == ["AAPL", "MC.PA", "BTC-EUR"]
    assert rows[0] == {"ticker": "AAPL", "live": False, "active": False}
    assert rows[1]["live"] is True
    assert rows[2] == {"ticker": "BTC-EUR", "live": False, "active": True}


def test_the_batch_is_bounded(client):
    response = client.get(
        "/v1/market/status",
        params={"tickers": ",".join(f"T{i}" for i in range(51))},
        headers=AUTH,
    )
    assert response.status_code == 422
