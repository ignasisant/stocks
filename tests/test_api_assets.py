"""Design tokens and translated strings, served to a front end that is not
Streamlit.

Both are shipped files rather than anybody's data, so both are open — and that
is the thing worth testing, because "open" is a decision and not an oversight.
The rest guards the property that makes serving them worthwhile at all: the two
front ends read the same colours and the same strings, from the same source, so
they cannot drift apart while both still look right in isolation.
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


def test_a_language_nobody_ships_is_a_404(client):
    assert client.get("/v1/i18n/xx").status_code == 404


def test_the_catalog_needs_no_credentials(client):
    """The sign-in screen has to be translated before anyone is signed in."""
    assert client.get("/v1/i18n/en").status_code == 200
