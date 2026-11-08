"""The Friday email: what it says, when it is sent, and how it is stopped."""

from __future__ import annotations

from datetime import date

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from stocks import accounts
from stocks.data.earnings import EarningsEvent
from stocks.notify import mail
from stocks.notify import weekly as wk
from stocks.notify import weekly_email as we
from stocks.web import unsubscribe
from stocks.web.onboarding import Gap

D = date(2026, 11, 6)  # a Friday
START = date(2022, 4, 6)
SINCE = (D - START).days
YTD = (D - date(2026, 1, 1)).days
BASE = "https://topstocks.example"


def data(**over) -> wk.WeeklyData:
    base = dict(
        date=D,
        total=133_199.0,
        week=(-2_546.0, -0.0188),
        month=(-13_294.0, -0.0893),
        ytd=(5_978.0, 0.0393),
        since=(22_109.0, 0.1245),
        start=START,
        benchmark={SINCE: 0.1348, 7: -0.0346, 30: -0.0544, YTD: 0.1093},
        benchmark_gain={SINCE: 23_947.0, 7: -4_692.0, 30: -8_094.0, YTD: 16_652.0},
        best=[("DUOL", 670.0, 0.193)],
        worst=[("NVDA", -678.0, -0.113)],
        earnings=[EarningsEvent("TTD", date(2026, 11, 9), 3)],
        top_weight=0.27,
        effective_names=30.3,
        largest=("NVDA", 0.091),
        currency="EUR",
        as_of=date(2026, 11, 5),
    )
    base.update(over)
    return wk.WeeklyData(**base)


def view(lang: str = "en", **over) -> we._View:
    gaps = over.pop("gaps", [])
    v = we._View(data(**over), lang, BASE)
    v.gaps = gaps
    v.unsubscribe = f"{BASE}/email/unsubscribe?t=tok"
    return v


# ---------------------------------------------------------------- rendering


def test_returns_open_on_the_books_first_day():
    text = we.render_text(view())
    returns = text.split("You against the S&P 500")[1].splitlines()[1:5]
    assert returns[0].startswith("- Since start")
    assert "6 Apr 2022" in returns[0]
    assert "+€23,947" in returns[0]  # the index on the same money, beside it
    assert [r.split(":")[0].split(" (")[0] for r in returns[1:]] == [
        "- Week", "- Month", "- Year to date"]


def test_a_window_the_index_cannot_cover_shows_a_dash_not_a_figure():
    v = view(benchmark={SINCE: 0.1348, 7: None, 30: -0.0544, YTD: 0.1093})
    html = we.render_html(v)
    week_row = html.split(">Week<")[1].split("</tr>")[0]
    assert "—" in week_row
    assert "S&P 500 -" not in we.render_text(v).split("- Week")[1].splitlines()[0]


def test_figures_are_written_the_way_the_reader_writes_them():
    en = we.subject(view("en"))
    es = we.subject(view("es"))
    assert "€133,199" in en and "-1.88%" in en
    assert "133.199 €" in es and "-1,88%" in es


def test_empty_sections_are_left_out_not_drawn_empty():
    v = view(best=[], worst=[], earnings=[], top_weight=None, largest=None,
             effective_names=None)
    text = we.render_text(v)
    for title in ("What moved", "Your activity", "Your rules",
                  "Next week", "Concentration", "Finish setting up"):
        assert title not in text, title


def test_setup_gaps_carry_their_real_counts_and_a_link_each():
    v = view(gaps=[Gap("rules", "portfolio", {"tab": "positions"},
                       {"n": "7", "total": "12"})])
    text = we.render_text(v)
    assert "7 of 12" in text
    assert f"{BASE}/portfolio?tab=positions" in text
    assert f'href="{BASE}/portfolio?tab=positions"' in we.render_html(v)


def test_names_held_at_cost_are_disclosed_once():
    v = view(missing=["ORGN", "SLP"])
    assert we.render_text(v).count("ORGN, SLP") == 1
    v.gaps = [Gap("unpriced", "ticker", {"ticker": "ORGN"}, {"names": "ORGN, SLP"})]
    assert we.render_text(v).count("ORGN, SLP") == 1


def test_the_html_carries_the_preheader_and_the_unsubscribe_link():
    v = view()
    html = we.render_html(v, "hidden preview line")
    assert "hidden preview line" in html
    assert v.unsubscribe in html


# ---------------------------------------------------------------- sending


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(mail, "configured", lambda: True)

    def send(to, subject, html, text, **kw):
        sent.append({"to": to, "subject": subject, **kw})
        return mail.Sent(True, id="re_1")

    monkeypatch.setattr(mail, "send", send)
    monkeypatch.setattr(we, "compose", lambda *a, **k: we.Email(
        "s", "p", "<p>h</p>", "t", to="a@example.com", unsubscribe="u"))
    return sent


class _Paths:
    prefs = "prefs.json"


def test_a_send_is_keyed_so_a_retried_run_sends_once(outbox):
    assert we.send_for("slug", _Paths, {}, D) == "sent re_1"
    assert outbox[0]["idempotency_key"] == f"weekly_email-slug-{D}"
    assert outbox[0]["unsubscribe"] == "u"


@pytest.mark.parametrize(
    ("prefs", "configured", "why"),
    [({"notify_weekly_email": False}, True, "off"),
     ({}, False, "email not configured")],
)
def test_skips(outbox, monkeypatch, prefs, configured, why):
    monkeypatch.setattr(mail, "configured", lambda: configured)
    assert we.send_for("slug", _Paths, prefs, D) == f"skipped: {why}"
    assert outbox == []


def test_an_account_with_no_book_or_no_address_is_skipped(outbox, monkeypatch):
    monkeypatch.setattr(we, "compose", lambda *a, **k: "no book")
    assert we.send_for("slug", _Paths, {}, D) == "skipped: no book"
    monkeypatch.setattr(we, "compose", lambda *a, **k: we.Email("s", "p", "h", "t"))
    assert we.send_for("slug", _Paths, {}, D) == "skipped: no address"
    assert outbox == []


def test_a_test_copy_goes_out_even_when_switched_off_and_is_not_keyed(outbox):
    out = we.send_for("slug", _Paths, {"notify_weekly_email": False}, D,
                      to="me@example.com")
    assert out == "sent re_1"
    assert outbox[0]["to"] == "me@example.com"
    assert outbox[0]["idempotency_key"] is None


def test_an_undeliverable_address_switches_the_email_off(outbox, monkeypatch):
    stored: list[tuple] = []
    monkeypatch.setattr(mail, "send", lambda *a, **k: mail.Sent(False, status=422))
    monkeypatch.setattr(accounts, "update_prefs", lambda *a, **k: stored.append(a))
    assert we.send_for("slug", _Paths, {}, D) == "not sent: 422"
    assert stored == [("prefs.json", {"notify_weekly_email": False})]


# ---------------------------------------------------------------- unsubscribe


@pytest.fixture
def users(tmp_path, monkeypatch, cookie_secret):
    (tmp_path / "ana").mkdir()
    monkeypatch.setattr(accounts, "USERS_DIR", tmp_path)
    stored: list[tuple] = []
    monkeypatch.setattr(accounts, "update_prefs", lambda path, changes: stored.append(
        (path.parent.name, changes)))
    return stored


@pytest.fixture
def client():
    return TestClient(Starlette(routes=unsubscribe.routes()), base_url=BASE)


def test_a_token_opens_only_for_its_own_account(cookie_secret):
    token = we.unsubscribe_token("ana")
    assert we.unsubscribe_label(token) == "ana"
    assert we.unsubscribe_label(token + "x") is None
    from stocks import session

    other = session.seal("other", {"s": "ana", "j": "weekly_email"})
    assert we.unsubscribe_label(other) is None


def test_opening_the_link_asks_and_changes_nothing(client, users):
    r = client.get("/email/unsubscribe", params={"t": we.unsubscribe_token("ana")})
    assert r.status_code == 200
    assert '<form method="post"' in r.text
    assert users == []


def test_the_button_stops_the_email(client, users):
    r = client.post("/email/unsubscribe", data={"t": we.unsubscribe_token("ana")})
    assert r.status_code == 200
    assert users == [("ana", {"notify_weekly_email": False})]


def test_the_mail_clients_one_click_post_stops_it_too(client, users):
    r = client.post(
        "/email/unsubscribe",
        params={"t": we.unsubscribe_token("ana")},
        data={"List-Unsubscribe": "One-Click"},
    )
    assert r.status_code == 200
    assert users == [("ana", {"notify_weekly_email": False})]


@pytest.mark.parametrize("label", ["../ana", ".hidden", "nobody"])
def test_a_token_for_no_real_account_changes_nothing(client, users, label):
    r = client.post("/email/unsubscribe", data={"t": we.unsubscribe_token(label)})
    assert r.status_code == 400
    assert users == []


def test_a_forged_token_is_refused(client, users):
    r = client.post("/email/unsubscribe", data={"t": "forged"})
    assert r.status_code == 400
    assert users == []
