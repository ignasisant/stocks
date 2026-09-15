"""Enable Banking client — token signing, request shaping, error contract.

No network: every test swaps the module's urlopen for a recorder. The RSA key
is generated once per session and handed to the client through the secrets
resolution env vars.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from stocks.bank import enablebanking as eb

APP_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture(scope="session")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return key.public_key(), pem


@pytest.fixture(autouse=True)
def credentials(monkeypatch, keypair):
    _, pem = keypair
    monkeypatch.setenv("EB_APPLICATION_ID", APP_ID)
    monkeypatch.setenv("EB_PRIVATE_KEY", pem)
    eb.reset_token()
    yield
    eb.reset_token()


class Response:
    def __init__(self, payload: dict, status: int = 200):
        self._body = json.dumps(payload).encode()
        self.status = status

    def read(self, *_):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Recorder:
    """Stands in for urlopen: records requests, replays queued responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        nxt = self.responses.pop(0) if self.responses else {}
        if isinstance(nxt, Exception):
            raise nxt
        return Response(nxt)

    @property
    def last(self):
        return self.requests[-1]

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].data)


def http_error(status: int, payload: dict | None = None):
    return urllib.error.HTTPError(
        "https://api.enablebanking.com/x",
        status,
        "err",
        {},
        io.BytesIO(json.dumps(payload or {}).encode()),
    )


@pytest.fixture
def calls(monkeypatch):
    def _install(*responses):
        rec = Recorder(*responses)
        monkeypatch.setattr(eb.urllib.request, "urlopen", rec)
        return rec

    return _install


def _segment(jwt: str, index: int) -> dict:
    raw = jwt.split(".")[index]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


# ------------------------------------------------------------------ token


def test_token_is_signed_by_the_registered_key(keypair):
    public, _ = keypair
    jwt = eb.token()
    header, claims = _segment(jwt, 0), _segment(jwt, 1)
    assert header == {"typ": "JWT", "alg": "RS256", "kid": APP_ID}
    assert claims["iss"] == "enablebanking.com"
    assert claims["aud"] == "api.enablebanking.com"
    assert claims["exp"] - claims["iat"] == eb.TOKEN_TTL
    signing_input, sig = jwt.rsplit(".", 1)
    public.verify(
        base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)),
        signing_input.encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises InvalidSignature on mismatch


def test_token_is_reused_until_it_nears_expiry():
    assert eb.token() == eb.token()


def test_escaped_newlines_in_the_env_pem_are_restored(monkeypatch, keypair):
    _, pem = keypair
    monkeypatch.setenv("EB_PRIVATE_KEY", pem.replace("\n", "\\n"))
    assert eb.private_key() == pem.strip()
    eb.token()  # would raise if the PEM were still escaped


def test_missing_credentials_raise_rather_than_sign_nothing(monkeypatch):
    monkeypatch.setenv("EB_APPLICATION_ID", "")
    monkeypatch.setenv("EB_PRIVATE_KEY", "")
    eb.reset_token()
    assert not eb.configured()
    with pytest.raises(eb.BankError):
        eb.token()


# ------------------------------------------------------------------ calls


def test_aspsps_passes_country_and_filters_psu_type(calls):
    rec = calls(
        {
            "aspsps": [
                {"name": "Bank A", "psu_types": ["personal", "business"]},
                {"name": "Bank B", "psu_types": ["business"]},
                {"name": "Bank C"},
            ]
        }
    )
    names = [a["name"] for a in eb.aspsps("es")]
    assert names == ["Bank A", "Bank C"]
    assert "country=ES" in rec.last.full_url
    assert rec.last.get_header("Authorization").startswith("Bearer ey")


def test_start_auth_sends_the_consent_body_and_returns_the_state(calls):
    rec = calls({"url": "https://bank.example/authorize?x=1"})
    url, state = eb.start_auth(
        name="Bank A", country="es", redirect_url="https://app.example/bank"
    )
    body = rec.body()
    assert url == "https://bank.example/authorize?x=1"
    assert body["state"] == state and len(state) >= 16
    assert body["aspsp"] == {"name": "Bank A", "country": "ES"}
    assert body["redirect_url"] == "https://app.example/bank"
    assert body["psu_type"] == "personal"
    assert body["access"]["valid_until"].endswith("Z")
    assert rec.last.method == "POST"


def test_transactions_follow_continuation_keys(calls):
    calls(
        {"transactions": [{"entry_reference": "1"}], "continuation_key": "k2"},
        {"transactions": [{"entry_reference": "2"}]},
    )
    got = eb.transactions("acc-uid", date_from="2026-01-01")
    assert [t["entry_reference"] for t in got] == ["1", "2"]


def test_transactions_stop_on_a_repeated_continuation_key(calls):
    rec = calls(*[{"transactions": [{"x": 1}], "continuation_key": "same"}] * 5)
    eb.transactions("acc-uid")
    assert len(rec.requests) == 2  # first page, then the repeat breaks the loop


def test_transactions_omit_empty_query_parameters(calls):
    rec = calls({"transactions": []})
    eb.transactions("acc-uid")
    assert "?" not in rec.last.full_url


# ----------------------------------------------------------------- errors


def test_a_401_on_an_account_call_is_a_consent_error(calls):
    calls(http_error(401, {"error_code": "SESSION_EXPIRED", "error_description": "gone"}))
    with pytest.raises(eb.ConsentError) as exc:
        eb.balances("acc-uid")
    assert exc.value.code == "SESSION_EXPIRED"
    assert exc.value.status == 401


def test_a_401_on_authorisation_is_a_plain_bank_error(calls):
    # Not session-scoped: there is no consent yet, so this is our own key.
    calls(http_error(401, {"error_code": "invalid_token"}))
    with pytest.raises(eb.BankError) as exc:
        eb.start_auth(name="A", country="ES", redirect_url="https://x/bank")
    assert not isinstance(exc.value, eb.ConsentError)


@pytest.mark.parametrize(
    "status,code",
    [(429, "ASPSP_RATE_LIMIT_EXCEEDED"), (403, "ASPSP_RATE_LIMIT_EXCEEDED")],
)
def test_a_spent_fetch_budget_is_its_own_error(calls, status, code):
    # Not a consent problem and not ours: the bank allows ~4 background
    # fetches a day, and the only answer is to come back later.
    calls(http_error(status, {"error_code": code, "error_description": "slow down"}))
    with pytest.raises(eb.RateLimited):
        eb.balances("acc-uid")


def test_the_consent_asked_for_is_the_180_day_maximum(calls):
    from datetime import UTC, datetime

    rec = calls({"url": "https://bank.example/authorize"})
    eb.start_auth(name="A", country="ES", redirect_url="https://x/bank")
    asked = rec.body()["access"]["valid_until"]
    days = (
        datetime.fromisoformat(asked.replace("Z", "+00:00")) - datetime.now(UTC)
    ).days
    assert eb.DEFAULT_CONSENT_DAYS == 180
    assert 178 <= days <= 180


def test_delete_session_tolerates_an_already_closed_session(calls):
    calls(http_error(404, {"error_code": "NOT_FOUND"}))
    eb.delete_session("gone")  # no raise


def test_delete_session_reraises_real_failures(calls):
    calls(http_error(500, {"error_code": "SERVER_ERROR"}))
    with pytest.raises(eb.BankError):
        eb.delete_session("sid")


def test_network_failure_is_reported_as_a_bank_error(calls, monkeypatch):
    monkeypatch.setattr(
        eb.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    with pytest.raises(eb.BankError) as exc:
        eb.aspsps("ES")
    assert exc.value.status == 0


# ---------------------------------------------------------------- shaping


@pytest.mark.parametrize(
    "indicator,expected",
    [("CRDT", 250.0), ("DBIT", -250.0), ("", 250.0)],
)
def test_amount_takes_its_sign_from_the_indicator(indicator, expected):
    tx = {
        "transaction_amount": {"amount": "250.00", "currency": "EUR"},
        "credit_debit_indicator": indicator,
    }
    assert eb.amount(tx) == expected


def test_counterparty_prefers_the_far_side_of_the_transfer():
    debit = {
        "transaction_amount": {"amount": "100"},
        "credit_debit_indicator": "DBIT",
        "creditor": {"name": "Saxo Bank"},
        "debtor": {"name": "Me"},
    }
    credit = dict(debit, credit_debit_indicator="CRDT")
    assert eb.counterparty(debit) == "Saxo Bank"
    assert eb.counterparty(credit) == "Me"


def test_counterparty_falls_back_to_remittance_information():
    tx = {
        "transaction_amount": {"amount": "10"},
        "remittance_information": ["TRANSFER", "CLICKTRADE"],
    }
    assert eb.counterparty(tx) == "TRANSFER CLICKTRADE"


def test_tx_date_prefers_booking_then_value_then_transaction():
    assert eb.tx_date({"booking_date": "2026-03-01", "value_date": "2026-03-02"}) == (
        "2026-03-01"
    )
    assert eb.tx_date({"value_date": "2026-03-02"}) == "2026-03-02"
    assert eb.tx_date({"transaction_date": "2026-03-03T10:00:00Z"}) == "2026-03-03"
    assert eb.tx_date({}) == ""
