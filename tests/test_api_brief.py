"""The daily card's brief editor over HTTP (`api/routes/brief.py`).

What is tested is what the editor promises a reader:

* a brief saved comes back with what the card will fetch for it, worked out
  from the words there and then — or by the keyword rules when no model
  answers — so "mírame la bolsa" reads back as the main indices before the
  first card;
* a reworded brief is planned again, and the plan is kept on it;
* the routines an account kept before the brief read as one text, a line
  each, and the first save folds them into one;
* the editor touches the brief only, and dropping it leaves other memories;
* writes are a session's, never a token's.

No network: the planning model is a stub that answers from a fixed reply.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from stocks import accounts
from stocks.api.app import app as fastapi_app
from stocks.chat import learnings, routine_plan

TOKEN = "s3cret-token"
EMAIL = "holder@example.com"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
URL = "/v1/daily/brief"


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


@pytest.fixture
def account(monkeypatch, tmp_path):
    users = tmp_path / "users"
    paths = accounts.paths_for(EMAIL, None, users_dir=users)
    paths.root.mkdir(parents=True)
    paths.watchlist.write_text("watchlist:\n  - ticker: NVDA\n    name: Nvidia\n")
    paths.prefs.write_text(json.dumps({"currency": "EUR"}))
    monkeypatch.setattr(accounts, "configured_owner", lambda: None)
    monkeypatch.setattr(
        accounts, "paths_for", lambda email, owner=None, users_dir=users: paths
    )
    monkeypatch.setattr(accounts, "restore_account", lambda *a, **k: False)
    monkeypatch.setattr("stocks.storage.persist", lambda path: None)
    return paths


@pytest.fixture
def signed_in(sign_in, account):
    return sign_in(TestClient(fastapi_app), EMAIL)


@pytest.fixture
def planner(monkeypatch):
    """The model that plans: answers each routine asked with `plan`, or
    nothing at all when `plan` is None. Records how often it was asked."""
    asked: list[str] = []
    reply: dict = {"plan": None}

    def complete(prefs, system, messages, timeout_s, *, spend_free, accept):
        asked.append(messages[-1]["content"])
        if reply["plan"] is None:
            return None
        ids = [line.split(":")[0].lstrip("- ")
               for line in messages[-1]["content"].splitlines()[1:]]
        return accept(json.dumps({"plans": [{"id": i, **reply["plan"]} for i in ids]}))

    monkeypatch.setattr(routine_plan.engine, "complete_attempts", complete)
    reply["asked"] = asked
    return reply


def test_a_brief_reads_back_with_what_the_card_will_fetch(signed_in, planner):
    assert signed_in.get(URL).json() == {
        "text": "", "plan": None, "enabled": True,
        "max_chars": learnings.MAX_ROUTINE_CHARS,
        "max_lines": learnings.MAX_ROUTINE_LINES,
    }
    planner["plan"] = {"markets": ["core"], "earnings": "none",
                       "topics": ["events"]}
    made = signed_in.put(
        URL, json={"text": "Cada día mírame los indicadores de la bolsa"})
    assert made.status_code == 200
    body = made.json()
    assert body["text"] == "Cada día mírame los indicadores de la bolsa"
    assert body["plan"] == {"markets": ["core"], "earnings": None, "symbols": [],
                            "topics": ["events"], "by": "model"}
    assert signed_in.get(URL).json() == body


def test_no_model_and_the_words_still_say_the_obvious(signed_in, planner):
    made = signed_in.put(URL, json={
        "text": "Resultados de las grandes empresas\nLos insiders"})
    assert made.json()["plan"] == {"markets": [], "earnings": "large", "symbols": [],
                                   "topics": ["insiders"], "by": "rules"}


def test_a_brief_naming_a_followed_company_quotes_it(signed_in, planner):
    planner["plan"] = {"earnings": "named", "symbols": ["GC=F"]}
    body = signed_in.put(URL, json={"text": "Cada día cómo van NVDA y el oro"}).json()
    assert body["plan"]["symbols"] == ["NVDA", "GC=F"]
    assert body["plan"]["earnings"] == "named"


def test_rewording_plans_again_and_keeps_the_plan(signed_in, planner, account):
    planner["plan"] = {"symbols": ["GC=F"]}
    signed_in.put(URL, json={"text": "Cada día cómo va el oro"})
    planner["plan"] = {"markets": ["spain"]}
    edited = signed_in.put(URL, json={"text": "Cada día cómo va el Ibex"})
    assert edited.status_code == 200
    assert edited.json()["plan"]["markets"] == ["spain"]
    assert len(planner["asked"]) == 2
    [kept] = learnings.load(account.learnings)
    assert kept.recipe["wording"] == "Cada día cómo va el Ibex"
    # Read back from the stored plan: no model on a GET.
    assert signed_in.get(URL).json()["plan"]["markets"] == ["spain"]
    assert len(planner["asked"]) == 2


def test_routines_kept_before_the_brief_read_as_one_and_fold_on_save(
        signed_in, planner, account):
    learnings.add(account.learnings, "Cada día cómo va el oro", kind="routine")
    learnings.add(account.learnings, "Cada día los resultados de mis empresas",
                  kind="routine")
    goal, _ = learnings.add(account.learnings, "Mi horizonte es de veinte años",
                            kind="goal")
    read = signed_in.get(URL).json()
    assert read["text"] == ("Cada día cómo va el oro\n"
                            "Cada día los resultados de mis empresas")
    assert read["plan"]["earnings"] == "book" and read["plan"]["by"] == "rules"
    signed_in.put(URL, json={"text": read["text"] + "\nMis insiders"})
    kept = learnings.load(account.learnings)
    assert sorted(i.kind for i in kept) == ["goal", "routine"]
    assert next(i for i in kept if i.kind == "routine").text.endswith("Mis insiders")
    assert signed_in.delete(URL).status_code == 204
    assert [i.id for i in learnings.load(account.learnings)] == [goal.id]
    assert signed_in.get(URL).json()["text"] == ""


def test_the_same_words_kept_as_a_memory_become_the_brief(signed_in, planner, account):
    learnings.add(account.learnings, "Cada día dime cómo va el oro", kind="goal")
    signed_in.put(URL, json={"text": "Cada día dime cómo va el oro"})
    [kept] = learnings.load(account.learnings)
    assert kept.kind == "routine"


def test_a_token_reads_but_never_writes(account, planner):
    client = TestClient(fastapi_app)
    who = {"account": EMAIL}
    assert client.get(URL, headers=AUTH, params=who).status_code == 200
    refused = client.put(URL, headers=AUTH, params=who,
                         json={"text": "Cada día cómo va el oro"})
    assert refused.status_code in (401, 403)
    assert client.delete(URL, headers=AUTH, params=who).status_code in (401, 403)
    assert planner["asked"] == []


def test_a_brief_may_run_to_a_paragraph(signed_in, planner):
    brief = "Cada día resume lo que mueve mi cartera, " + "con noticias y eventos " * 40
    assert len(brief) > learnings.MAX_CHARS
    made = signed_in.put(URL, json={"text": brief})
    assert made.status_code == 200 and made.json()["text"] == brief.strip()
    too_long = signed_in.put(URL, json={"text": "x" * (learnings.MAX_ROUTINE_CHARS + 1)})
    assert too_long.status_code == 422


def test_a_brief_keeps_its_lines_and_no_lone_capital_becomes_a_ticker(
        signed_in, planner):
    brief = ("Haz un resumen de lo que afecta a mi cartera\n"
             "- Grandes variaciones y noticias (SEC, Yahoo)\n\n"
             "- Propón una acción: venta de X, compra Y, reforzar NVDA")
    body = signed_in.put(URL, json={"text": brief}).json()
    assert body["text"].splitlines() == [line for line in brief.splitlines() if line]
    assert body["plan"]["symbols"] == ["NVDA"]
    # The planner reads the brief on one line all the same.
    assert "\n- Grandes" not in planner["asked"][-1]
    # A reworded brief is read for symbols again.
    edited = signed_in.put(URL, json={"text": "Cada día resume mi cartera y AMD"})
    assert edited.json()["plan"]["symbols"] == ["AMD"]


def test_a_lone_capital_saved_before_is_not_read_back_as_a_ticker(
        signed_in, planner, account):
    learnings.add(account.learnings, "Propón una acción: venta de X o compra NVDA",
                  kind="routine", tickers=["X", "NVDA"])
    assert signed_in.get(URL).json()["plan"]["symbols"] == ["NVDA"]
