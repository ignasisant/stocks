"""Editing the watchlist over HTTP.

What an edit means to the file — which keys survive it, how tags de-duplicate,
that a group is only the tag repeated on its members — is `stocks.watchlist`'s
job and is tested with the pages that have always made these edits. What is
tested here is the HTTP shape put on top:

* POST is an upsert, because naming a ticker is enough to follow it;
* PATCH and DELETE 404 instead, because a client naming a string is as likely
  to have typed it wrong as to have meant it;
* only the fields actually sent are applied, so `shares: 0` clears a holding
  without touching its cost basis;
* an edit preserves what it did not name — alert rules and the alias map ride
  through untouched, which is the whole reason these go through the seam and
  not through a model of the file.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.config import load_watchlist, yaml_load

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}

WATCHLIST = """\
aliases:
  BRK.B: BRK-B
watchlist:
  - ticker: AAPL
    name: Apple
    favorite: true
    tags: [Tech, Core]
    alerts:
      - type: above
        price: 250
  - ticker: MSFT
    tags: [Tech]
"""


@pytest.fixture
def client() -> TestClient:
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text(WATCHLIST)
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


def tickers(path) -> list[str]:
    return [h.ticker for h in load_watchlist(path)]


# ---------------------------------------------------------------------- adding


def test_posting_a_new_ticker_lists_it(client, account, signed_in):
    response = signed_in.post("/v1/watchlist", json={"ticker": "nvda", "name": "Nvidia"})
    assert response.status_code == 200
    assert response.json()["ticker"] == "NVDA"
    assert response.json()["name"] == "Nvidia"
    assert "NVDA" in tickers(account.watchlist)


def test_posting_one_already_listed_updates_it_instead_of_refusing(
    client, account, signed_in
):
    """"Follow this symbol" is the request; a client that cannot know whether
    the app already listed it should not have to ask first."""
    response = signed_in.post("/v1/watchlist", json={"ticker": "MSFT", "favorite": True})
    assert response.status_code == 200
    assert response.json()["favorite"] is True
    assert tickers(account.watchlist).count("MSFT") == 1


def test_a_coin_says_so_without_the_client_parsing_the_symbol(
    client, account, signed_in
):
    payload = signed_in.post("/v1/watchlist", json={"ticker": "BTC-EUR"}).json()
    assert payload["is_crypto"] is True


# --------------------------------------------------------------------- editing


def test_only_the_fields_sent_are_applied(client, account, signed_in):
    payload = signed_in.patch("/v1/watchlist/AAPL", json={"favorite": False}).json()
    assert payload["favorite"] is False
    assert payload["name"] == "Apple"  # untouched
    assert payload["tags"] == ["Tech", "Core"]  # untouched


def test_an_edit_leaves_the_rules_nobody_named_alone(client, account, signed_in):
    """Alert rules and the alias map are not in this endpoint's model at all,
    which is exactly why they have to survive an edit that never mentions them."""
    signed_in.patch("/v1/watchlist/AAPL", json={"tags": ["Growth"]})
    raw = yaml_load(account.watchlist.read_text())
    entry = next(i for i in raw["watchlist"] if i["ticker"] == "AAPL")
    assert entry["alerts"] == [{"type": "above", "price": 250}]
    assert raw["aliases"] == {"BRK.B": "BRK-B"}


def test_clearing_shares_does_not_touch_the_cost_basis(client, account, signed_in):
    """0 clears a field and omitting it leaves it alone — two different requests
    that a model built on nulls alone could not tell apart."""
    signed_in.patch("/v1/watchlist/MSFT", json={"shares": 12, "cost": 300.0})
    signed_in.patch("/v1/watchlist/MSFT", json={"shares": 0})
    entry = next(
        i for i in yaml_load(account.watchlist.read_text())["watchlist"]
        if i["ticker"] == "MSFT"
    )
    assert "shares" not in entry
    assert entry["cost"] == 300.0


def test_an_empty_tag_list_removes_them_all(client, account, signed_in):
    assert signed_in.patch("/v1/watchlist/AAPL", json={"tags": []}).json()["tags"] == []


def test_patching_an_unlisted_ticker_is_a_404_not_a_new_entry(
    client, account, signed_in
):
    """In the app, tagging an unlisted symbol adds it — that is a person
    pointing at something on screen. A PATCH is a client naming a string, and
    the string is as likely to be a mistake as an intention."""
    response = signed_in.patch("/v1/watchlist/APPL", json={"favorite": True})
    assert response.status_code == 404
    assert tickers(account.watchlist) == ["AAPL", "MSFT"]


def test_a_ticker_is_matched_without_regard_to_case(client, account, signed_in):
    """Symbols are case-insensitive everywhere else in this app; a URL is not
    where that should stop being true."""
    response = signed_in.patch("/v1/watchlist/aapl", json={"favorite": False})
    assert response.status_code == 200
    assert tickers(account.watchlist) == ["AAPL", "MSFT"]


def test_a_field_outside_the_model_is_refused_by_name(client, account, signed_in):
    response = signed_in.patch("/v1/watchlist/AAPL", json={"alerts": []})
    assert response.status_code == 422
    assert "alerts" in response.text


# -------------------------------------------------------------------- removing


def test_deleting_drops_the_entry(client, account, signed_in):
    assert signed_in.delete("/v1/watchlist/MSFT").status_code == 204
    assert tickers(account.watchlist) == ["AAPL"]


def test_deleting_something_never_listed_is_a_404(client, account, signed_in):
    """A silent 204 and a real removal look identical to a client, and one of
    them means the request did nothing it was meant to."""
    assert signed_in.delete("/v1/watchlist/TSLA").status_code == 404


# ------------------------------------------------------------------ tag groups


def test_the_tags_in_use_are_listed(client, account):
    assert client.get("/v1/watchlist/tags", params=WHO, headers=AUTH).json()["tags"] == [
        "Core",
        "Tech",
    ]


def test_renaming_a_group_rewrites_every_member(client, account, signed_in):
    response = signed_in.patch("/v1/watchlist/tags/Tech", json={"name": "Software"})
    assert response.status_code == 200
    assert response.json() == {"tag": "Software", "holdings": 2}
    tags = client.get("/v1/watchlist/tags", params=WHO, headers=AUTH).json()["tags"]
    assert tags == ["Core", "Software"]


def test_renaming_onto_an_existing_group_merges_rather_than_duplicating(
    client, account, signed_in
):
    signed_in.patch("/v1/watchlist/tags/Core", json={"name": "tech"})
    entry = next(
        i for i in yaml_load(account.watchlist.read_text())["watchlist"]
        if i["ticker"] == "AAPL"
    )
    assert entry["tags"] == ["Tech"]  # de-duplicated, first spelling wins


def test_ungrouping_keeps_the_tickers(client, account, signed_in):
    """Ungrouping is not un-following."""
    response = signed_in.delete("/v1/watchlist/tags/Tech")
    assert response.json() == {"tag": "Tech", "holdings": 2}
    assert tickers(account.watchlist) == ["AAPL", "MSFT"]


def test_a_group_nobody_carries_touches_nothing(client, account, signed_in):
    assert signed_in.delete("/v1/watchlist/tags/Nonexistent").json()["holdings"] == 0


# ----------------------------------------------------------------------- gate


def test_a_token_cannot_edit_anybody_watchlist(client, account):
    for call, url, body in (
        (client.post, "/v1/watchlist", {"ticker": "NVDA"}),
        (client.patch, "/v1/watchlist/AAPL", {"favorite": False}),
        (client.delete, "/v1/watchlist/AAPL", None),
    ):
        kwargs = {"params": WHO, "headers": AUTH}
        if body is not None:
            kwargs["json"] = body
        assert call(url, **kwargs).status_code == 403
    assert tickers(account.watchlist) == ["AAPL", "MSFT"]


# --------------------------------------------------------------------- alerts


def test_the_rules_come_back_as_the_yaml_holds_them(client, account):
    payload = client.get("/v1/watchlist/AAPL/alerts", params=WHO, headers=AUTH).json()
    assert payload["ticker"] == "AAPL"
    assert payload["alerts"] == [
        {"type": "above", "price": 250.0, "pct": None, "level": None, "window": None}
    ]


def test_a_field_this_rule_does_not_use_is_null_not_zero(client, account, signed_in):
    """A drawdown alert has no price, and a price of 0 would be a threshold
    nothing can ever be below."""
    payload = signed_in.put(
        "/v1/watchlist/MSFT/alerts",
        json={"alerts": [{"type": "drawdown", "pct": 15}]},
    ).json()
    rule = payload["alerts"][0]
    assert rule["pct"] == 15.0
    assert rule["price"] is None and rule["level"] is None


def test_putting_replaces_the_whole_set(client, account, signed_in):
    """The rules carry no identity of their own, so "change the second one" is
    not a request anything here could honour."""
    payload = signed_in.put(
        "/v1/watchlist/AAPL/alerts",
        json={"alerts": [{"type": "below", "price": 150}]},
    ).json()
    assert [rule["type"] for rule in payload["alerts"]] == ["below"]


def test_an_empty_set_clears_the_rules(client, account, signed_in):
    assert signed_in.put("/v1/watchlist/AAPL/alerts", json={"alerts": []}).json()[
        "alerts"
    ] == []
    entry = next(
        i for i in yaml_load(account.watchlist.read_text())["watchlist"]
        if i["ticker"] == "AAPL"
    )
    assert "alerts" not in entry


def test_an_alert_type_nobody_evaluates_is_refused(client, account, signed_in):
    """Written straight to the YAML it would make the watchlist unreadable:
    `config.Alert` raises on an unknown type, and every page parses it."""
    response = signed_in.put(
        "/v1/watchlist/AAPL/alerts",
        json={"alerts": [{"type": "vibes_below", "level": 3}]},
    )
    assert response.status_code == 422
    assert load_watchlist(account.watchlist)  # still parses


def test_alerts_on_an_unlisted_ticker_are_a_404(client, account, signed_in):
    assert signed_in.get("/v1/watchlist/TSLA/alerts").status_code == 404
    assert signed_in.put(
        "/v1/watchlist/TSLA/alerts", json={"alerts": []}
    ).status_code == 404


def test_an_entry_edit_leaves_the_alert_rules_alone(client, account, signed_in):
    """The two are separate resources precisely so that renaming a ticker does
    not silently drop the rules a client never sent."""
    signed_in.patch("/v1/watchlist/AAPL", json={"name": "Apple Inc"})
    payload = client.get("/v1/watchlist/AAPL/alerts", params=WHO, headers=AUTH).json()
    assert payload["alerts"][0]["price"] == 250.0


# ------------------------------------------------------------- focus examples


def test_no_declared_focus_is_no_suggestions(client, account, signed_in):
    """Empty, not a default set: a reader who skipped the investor profile has
    not asked for anything, and guessing would be the page recommending."""
    assert signed_in.get("/v1/watchlist/suggestions").json()["suggestions"] == []


def test_the_examples_follow_the_areas_the_profile_declares(
    client, account, signed_in
):
    accounts.update_prefs(
        account.prefs, {"investor_profile": {"set": True, "focus": ["crypto"]}}
    )
    rows = signed_in.get("/v1/watchlist/suggestions").json()["suggestions"]
    assert rows, "crypto is one of the catalog's areas"
    assert all(row["tags"] for row in rows), "each example arrives grouped"


def test_the_offer_shrinks_as_it_is_taken_up(client, account, signed_in):
    accounts.update_prefs(
        account.prefs, {"investor_profile": {"set": True, "focus": ["tech"]}}
    )
    before = signed_in.get("/v1/watchlist/suggestions").json()["suggestions"]
    signed_in.post("/v1/watchlist", json={"ticker": before[0]["ticker"]})
    after = signed_in.get("/v1/watchlist/suggestions").json()["suggestions"]
    assert len(after) == len(before) - 1
    assert before[0]["ticker"] not in [row["ticker"] for row in after]


def test_a_suggestion_route_is_not_a_ticker_called_suggestions(
    client, account, signed_in
):
    """It sits ahead of `/{ticker}`, which would otherwise swallow the word."""
    assert signed_in.get("/v1/watchlist/suggestions").status_code == 200
