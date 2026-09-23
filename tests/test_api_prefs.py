"""The account's settings over HTTP: what it may change, and who may change it.

The settings themselves are ordinary values in prefs.json. What is tested here
is everything the route decides on top of them:

* a write needs a session — a bearer token is refused, because it names nobody
  and any holder can name any account;
* only an allowlisted key is writable, and a key outside it is refused by name
  rather than dropped on the floor, so a client never believes it saved
  something it did not;
* a patch changes the keys it sent and nothing else, which is what keeps a
  concurrent Streamlit run's save from being wiped;
* null is a real value — "auto" — and is not the same as leaving a field out.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api import loaders
from stocks.api.app import app as fastapi_app

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHO = {"account": EMAIL}


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
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n")
    paths.prefs.write_text(
        json.dumps(
            {
                "currency": "EUR",
                "language": "es",
                "recent_searches": ["NVDA"],
                "first_seen": "2024-01-01T00:00:00Z",
                "telegram_chat_id": 12345,
            }
        )
    )
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr(loaders, "db_mtime", lambda db: 1.0)
    # Nothing in a test should reach the bucket.
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(client, sign_in):
    """A browser session for EMAIL — what a write needs, since a token cannot."""
    return sign_in(client, EMAIL)


# --------------------------------------------------------------------- reading


def test_the_view_is_the_settings_and_not_the_stored_file(client, account):
    """Signup accounting and the recent-search list are not settings anybody
    edits on a settings screen."""
    payload = client.get("/v1/prefs", params=WHO, headers=AUTH).json()
    assert payload["currency"] == "EUR"
    assert payload["language"] == "es"
    assert "first_seen" not in payload
    assert "recent_searches" not in payload


def test_the_chat_id_stays_on_the_server(client, account):
    """A caller needs to know notifications can be sent, not where they go."""
    payload = client.get("/v1/prefs", params=WHO, headers=AUTH).json()
    assert payload["telegram_linked"] is True
    assert "telegram_chat_id" not in payload


# --------------------------------------------------------------------- writing


def test_a_token_cannot_change_anybody_settings(client, account):
    response = client.patch(
        "/v1/prefs", params=WHO, headers=AUTH, json={"currency": "USD"}
    )
    assert response.status_code == 403
    assert json.loads(account.prefs.read_text())["currency"] == "EUR"


def test_a_session_changes_only_what_it_sent(client, account, signed_in):
    """The file is the unit the app stores: a patch that rewrote it whole would
    drop whatever a concurrent Streamlit run had just saved beside it."""
    response = signed_in.patch("/v1/prefs", json={"currency": "USD"})
    assert response.status_code == 200
    assert response.json()["currency"] == "USD"
    stored = json.loads(account.prefs.read_text())
    assert stored["currency"] == "USD"
    assert stored["language"] == "es"  # untouched
    assert stored["recent_searches"] == ["NVDA"]  # untouched
    assert stored["telegram_chat_id"] == 12345  # untouched


def test_a_key_outside_the_allowlist_is_refused_by_name(client, account, signed_in):
    """Dropping it silently would let a client believe it saved something it
    did not — and this particular key would forge a signup date."""
    response = signed_in.patch("/v1/prefs", json={"first_seen": "1999-01-01"})
    assert response.status_code == 422
    assert "first_seen" in response.text
    assert json.loads(account.prefs.read_text())["first_seen"] == "2024-01-01T00:00:00Z"


def test_the_chat_id_is_not_writable(client, account, signed_in):
    """It is proved by the linking handshake, not asserted by a client: a raw
    write would point this account's digest at a chat nobody verified."""
    response = signed_in.patch("/v1/prefs", json={"telegram_chat_id": 999})
    assert response.status_code == 422
    assert json.loads(account.prefs.read_text())["telegram_chat_id"] == 12345


def test_null_means_auto_and_is_not_the_same_as_omitting(client, account, signed_in):
    """Clearing a setting is a real edit; leaving the field out is not."""
    saved = signed_in.patch("/v1/prefs", json={"language": None}).json()
    assert saved["language"] is None
    assert json.loads(account.prefs.read_text())["language"] is None


def test_an_empty_patch_is_refused_rather_than_answered(client, account, signed_in):
    assert signed_in.patch("/v1/prefs", json={}).status_code == 422


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    "body",
    [
        {"currency": "XBT"},
        {"language": "fr"},  # no catalog ships for it
        {"tax_residence": "JP"},  # no rules are modelled for it
        {"tax_filing_status": "whatever"},
        {"tax_other_income": -1.0},
        {"tax_church_rate": 9.0},  # a percentage where a fraction belongs
        {"tax_subnational_rate": -0.1},
    ],
)
def test_a_value_the_app_cannot_honour_is_refused(client, account, signed_in, body):
    assert signed_in.patch("/v1/prefs", json=body).status_code == 422


def test_a_rate_is_read_as_a_fraction(client, account, signed_in):
    """0.09 is a church-tax rate; 9 would multiply a tax bill by a hundred."""
    assert signed_in.patch("/v1/prefs", json={"tax_church_rate": 0.09}).json()[
        "tax_church_rate"
    ] == pytest.approx(0.09)


def test_residence_and_status_can_move_together(client, account, signed_in):
    """Validating the status against the new country alone would refuse a filer
    moving from Spain — which distinguishes none — to the US, which does."""
    response = signed_in.patch(
        "/v1/prefs", json={"tax_residence": "us", "tax_filing_status": "mfj"}
    )
    assert response.status_code == 200
    assert response.json()["tax_residence"] == "US"
    assert response.json()["tax_filing_status"] == "mfj"


def test_auto_residence_is_stored_as_nothing_chosen(client, account, signed_in):
    """"auto" is how the UI spells it; None is how the resolver reads it, and
    storing the string would make `tax.normalize("auto")` the country."""
    assert signed_in.patch("/v1/prefs", json={"tax_residence": "auto"}).json()[
        "tax_residence"
    ] is None


def test_a_form_post_cannot_masquerade_as_a_patch(client, account, signed_in):
    """The CSRF argument in one line: a cross-site form cannot send JSON, and a
    cross-site fetch that does gets preflighted against nothing."""
    response = signed_in.patch(
        "/v1/prefs",
        data={"currency": "USD"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422
    assert json.loads(account.prefs.read_text())["currency"] == "EUR"


def test_the_written_settings_are_what_the_tax_engine_then_reads(
    client, account, signed_in
):
    """The round trip that matters: a setting saved here has to change the rules
    the tax endpoint applies, not just a field in a JSON file."""
    from stocks.portfolio.tax import prefs as tax_prefs

    signed_in.patch("/v1/prefs", json={"tax_residence": "UK"})
    code, how = tax_prefs.resolve(tax_prefs.load(account.prefs))
    assert (code, how) == ("UK", "chosen")


# ------------------------------------------------------------ the weekly review


def test_the_weekly_review_toggle_is_readable(client, account):
    """It was writable on the Profile page and missing from this API, so a
    client could see two of the three deliveries and never the third."""
    payload = client.get("/v1/prefs", params=WHO, headers=AUTH).json()
    assert payload["notify_weekly"] is True


def test_an_untouched_weekly_toggle_reads_on_because_it_is_on(client, account):
    """The one that would ship a lie quietly. Unlike its two neighbours this key
    is absent from `accounts.DEFAULT_PREFS`, so a plain `.get()` returns None —
    and a client would draw the switch off beside a review the cron
    (`notify.fanout.iter_notify_users`, which defaults it True) is delivering
    every Sunday."""
    stored = json.loads(account.prefs.read_text())
    assert "notify_weekly" not in stored  # nothing has ever written it
    assert client.get("/v1/prefs", params=WHO, headers=AUTH).json()[
        "notify_weekly"
    ] is True


def test_the_weekly_review_can_be_turned_off(client, account, signed_in):
    """And the write has to land in the file the cron reads, not just in the
    response — the two are different machines."""
    assert signed_in.patch("/v1/prefs", json={"notify_weekly": False}).json()[
        "notify_weekly"
    ] is False
    assert json.loads(account.prefs.read_text())["notify_weekly"] is False


def test_every_delivery_the_profile_page_writes_is_writable_here(
    client, account, signed_in
):
    """The sweep, pinned. The Profile page writes exactly these three keys from
    its notification card; a fourth added there and not here would save on one
    surface and 422 on the other."""
    for key in ("notify_digest", "notify_weekly", "notify_alerts"):
        response = signed_in.patch("/v1/prefs", json={key: False})
        assert response.status_code == 200, key
        assert response.json()[key] is False, key


# ---------------------------------------------------------- the investor profile


def test_an_account_that_never_filled_the_form_gets_the_apps_own_defaults(
    client, account
):
    """Not an empty object and not a 404: the middle of the risk scale rather
    than one end, because this is a guess about somebody we know nothing about.
    `set` is how a client tells that guess from an answer."""
    payload = client.get("/v1/profile", params=WHO, headers=AUTH).json()
    assert payload["set"] is False
    assert payload["risk"] == "balanced"
    assert payload["horizon"] == "5y_plus"
    assert payload["focus"] == [] and payload["constraints"] == []


def test_a_token_cannot_change_who_the_assistant_thinks_it_is_advising(
    client, account
):
    """This is the text that goes into the model's system prompt. A token names
    nobody and any holder can name any account."""
    response = client.put(
        "/v1/profile",
        params=WHO,
        headers=AUTH,
        json={"risk": "aggressive", "horizon": "5y_plus"},
    )
    assert response.status_code == 403
    assert "investor_profile" not in json.loads(account.prefs.read_text())


def test_saving_it_marks_it_set_and_leaves_the_settings_alone(
    client, account, signed_in
):
    """`set` is the server's to stamp — a client asserting it would let an
    untouched form claim to be an answer. And the profile is one key in
    prefs.json: writing it must not drop what sits beside it."""
    response = signed_in.put(
        "/v1/profile",
        json={
            "risk": "very_aggressive",
            "horizon": "3_5y",
            "focus": ["crypto", "tech"],
            "constraints": ["eur"],
            "notes": "  no airlines  ",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["set"] is True
    assert body["risk"] == "very_aggressive"
    assert body["notes"] == "no airlines"  # stripped

    stored = json.loads(account.prefs.read_text())
    assert stored["investor_profile"]["set"] is True
    assert stored["language"] == "es"  # untouched
    assert stored["telegram_chat_id"] == 12345  # untouched


def test_the_lists_come_back_in_the_order_the_form_offers_them(
    client, account, signed_in
):
    """Normalised, exactly as `auth.render_profile_form` normalises the page's
    click order. The Profile page autosaves on a field-by-field difference
    against what is stored, so a list stored in click order would read as an
    edit on every rerun and toast "saved" at a reader who touched nothing."""
    from stocks.web.auth import PROFILE_CONSTRAINTS, PROFILE_FOCUS

    saved = signed_in.put(
        "/v1/profile",
        json={
            "risk": "balanced",
            "horizon": "5y_plus",
            # Clicked back to front, and one of them twice.
            "focus": ["dividends_value", "tech", "tech"],
            "constraints": ["esg", "spain_tax"],
        },
    ).json()
    assert saved["focus"] == [f for f in PROFILE_FOCUS if f in saved["focus"]]
    assert saved["focus"] == ["tech", "dividends_value"]
    assert saved["constraints"] == [
        c for c in PROFILE_CONSTRAINTS if c in saved["constraints"]
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"risk": "reckless", "horizon": "5y_plus"},
        {"risk": "balanced", "horizon": "40y"},
        {"risk": "balanced", "horizon": "5y_plus", "focus": ["gold"]},
        {"risk": "balanced", "horizon": "5y_plus", "constraints": ["no_mondays"]},
        {"horizon": "5y_plus"},  # the scale is not optional
        {"risk": "balanced", "horizon": "5y_plus", "notes": "x" * 2001},
    ],
)
def test_a_profile_the_persona_could_not_describe_is_refused(
    client, account, signed_in, body
):
    """Every option is an enum key `chat.engine.persona` has English wording
    for. A value outside them stores fine and then describes nobody — the
    sentence simply loses a clause, silently."""
    assert signed_in.put("/v1/profile", json=body).status_code == 422


def test_the_profile_carries_the_sentence_it_produces(client, account, signed_in):
    """What the form says and what the model is told, side by side.

    The Profile page hides this behind a popover so a reader can check the
    second follows from the first. A client could not draw it at all until the
    API said it — the persona is built in Python from an enum table, and a
    front end reassembling it would be a second place for that wording to
    drift.
    """
    signed_in.put(
        "/v1/profile",
        json={
            "risk": "conservative",
            "horizon": "1_3y",
            "focus": ["dividends_value"],
            "constraints": ["esg"],
            "notes": "no airlines",
        },
    )
    profile = signed_in.get("/v1/profile").json()
    assert profile["risk"] == "conservative"
    assert "no airlines" in profile["persona"]
    assert "conservative" in profile["persona"]
    # And the write hands it straight back, so the popover updates with the form.
    saved = signed_in.put(
        "/v1/profile", json={"risk": "aggressive", "horizon": "5y_plus"}
    ).json()
    assert "aggressive" in saved["persona"]
    assert "no airlines" not in saved["persona"]


def test_a_profile_nobody_filled_still_describes_somebody(client, account, signed_in):
    """`set: false` is a profile of defaults, and the persona says the app's
    historical one rather than an empty string — the assistant is always told
    something, and this is what."""
    profile = signed_in.get("/v1/profile").json()
    assert profile["set"] is False
    assert profile["persona"]


def test_an_unknown_field_is_refused_by_name(client, account, signed_in):
    """Dropping it silently would let a client believe it saved something it
    did not."""
    response = signed_in.put(
        "/v1/profile",
        json={"risk": "balanced", "horizon": "5y_plus", "leverage": 3},
    )
    assert response.status_code == 422
    assert "leverage" in response.text


def test_what_is_saved_is_what_the_assistant_is_actually_told(
    client, account, signed_in
):
    """The round trip that matters: a profile saved here has to change the
    persona sentence the chat engine builds, not just a field in a JSON file.
    Which is also why the field names are the stored ones — a rename here is a
    persona that quietly loses a clause."""
    from stocks.chat.engine import persona
    from stocks.web.auth import load_profile

    signed_in.put(
        "/v1/profile",
        json={
            "risk": "very_aggressive",
            "horizon": "5y_plus",
            "focus": ["em"],
            "constraints": ["eur"],
            "notes": "no airlines",
        },
    )
    sentence = persona(load_profile(accounts.load_prefs(account.prefs)))
    assert "no airlines" in sentence
    assert "emerging" in sentence.lower()
    # And not the unfilled-form fallback, which is what a profile that never
    # reached prefs.json would still produce.
    assert "The signed-in user describes themselves as" in sentence
