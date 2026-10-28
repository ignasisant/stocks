"""Design tokens and translated strings, served to the front end.

Both are shipped files rather than anybody's data, so both are open — and that
is the thing worth testing, because "open" is a decision and not an oversight.
The rest guards the property that makes serving them worthwhile at all: the
shell reads the same colours and strings the server renders with, from the
same source, so the two cannot drift apart while both still look right in
isolation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stocks.api.app import app as fastapi_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    """No API token anywhere: these routes must answer without one."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr("stocks.api.security.configured_token", lambda: "")


# ------------------------------------------------------------------- the tokens


def test_the_tokens_are_the_ones_the_app_paints_with(client):
    """Same dict `ds_vars_css` renders into `--ag-*`, so a chart drawn in
    JavaScript cannot pick a colour the stylesheet never heard of."""
    from stocks.web.ds import BRAND_CTA, tokens

    served = client.get("/v1/design/tokens").json()["tokens"]
    assert served == tokens()
    assert served["brand-cta"] == BRAND_CTA


def test_every_token_reaches_the_stylesheet_under_the_same_name(client):
    """The name is the contract: `tokens.border` and `var(--ag-border)` have to
    be the same thing, or a client styles against tokens that do not exist."""
    from stocks.web.ds import ds_vars_css

    css = ds_vars_css()
    for name in client.get("/v1/design/tokens").json()["tokens"]:
        assert f"--ag-{name}:" in css


def test_the_tokens_need_no_credentials(client):
    assert client.get("/v1/design/tokens").status_code == 200


# ------------------------------------------------------------------- the strings


def test_a_catalog_comes_back_flat_and_dotted(client):
    strings = client.get("/v1/i18n/es").json()["strings"]
    assert strings["ticker.price"] == "Precio"
    assert all("." in key for key in list(strings)[:50])


def test_an_untranslated_key_reads_in_english_not_as_a_key(client):
    """Mirrors i18n.translate's per-key fallback. Without it a missing
    translation renders as `ticker.price` on somebody's screen."""
    from stocks.web.i18n import catalog

    english, spanish = catalog("en"), catalog("es")
    served = client.get("/v1/i18n/es").json()["strings"]
    missing = [k for k in english if k not in spanish]
    assert set(english) <= set(served), "every source key is answerable"
    for key in missing[:20]:
        assert served[key] == english[key]


def test_a_prefix_filter_cuts_the_catalog_down(client):
    """The whole catalog is ~2300 keys; one page needs a fraction of it."""
    whole = client.get("/v1/i18n/es").json()["strings"]
    part = client.get("/v1/i18n/es", params={"prefix": "ticker,common"}).json()["strings"]
    assert 0 < len(part) < len(whole)
    assert all(k.startswith(("ticker.", "common.")) for k in part)
    assert part["ticker.price"] == whole["ticker.price"]


def test_a_language_nobody_ships_reads_in_english(client):
    """A browser set to Italian asks for `it`. A 404 left the app with no
    strings and every label on screen as its dotted key."""
    served = client.get("/v1/i18n/it")
    assert served.status_code == 200
    assert served.json() == client.get("/v1/i18n/en").json()


def test_the_catalog_needs_no_credentials(client):
    """The sign-in screen has to be translated before anyone is signed in."""
    assert client.get("/v1/i18n/en").status_code == 200


# ------------------------------------------------------------- the caching


def test_a_catalog_carries_an_etag_and_answers_304_to_it(client):
    first = client.get("/v1/i18n/es")
    tag = first.headers["etag"]
    assert tag.startswith('"') and first.headers["cache-control"] == "public, no-cache"
    again = client.get("/v1/i18n/es", headers={"If-None-Match": tag})
    assert again.status_code == 304
    assert again.headers["etag"] == tag and not again.content
    # A weak tag, and a list, both name it.
    assert (
        client.get("/v1/i18n/es", headers={"If-None-Match": f"W/{tag}"}).status_code
        == 304
    )
    assert (
        client.get(
            "/v1/i18n/es", headers={"If-None-Match": f'"other", {tag}'}
        ).status_code
        == 304
    )
    assert (
        client.get("/v1/i18n/es", headers={"If-None-Match": '"other"'}).status_code == 200
    )


def test_a_catalog_under_the_current_stamp_is_immutable(client):
    from stocks.web.i18n import version

    stamp = version()
    assert len(stamp) == 12 and stamp == version()
    current = client.get("/v1/i18n/es", params={"v": stamp})
    assert current.headers["cache-control"] == "public, max-age=31536000, immutable"
    stale = client.get("/v1/i18n/es", params={"v": "0" * 12})
    assert stale.headers["cache-control"] == "public, no-cache"
    assert stale.json() == current.json()


def test_the_etag_tells_languages_and_filters_apart(client):
    tags = {
        client.get("/v1/i18n/es").headers["etag"],
        client.get("/v1/i18n/en").headers["etag"],
        client.get("/v1/i18n/es", params={"prefix": "ticker"}).headers["etag"],
    }
    assert len(tags) == 3
