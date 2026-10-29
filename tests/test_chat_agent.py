"""agent: the model-directed gather step and what it hands the answer."""

from pathlib import Path

from stocks.chat import agent, toolbox
from stocks.chat.agent import Evidence
from stocks.web.llm import ToolCall, ToolRun


class _Provider:
    """Stand-in for a tool-capable llm.Provider."""

    id = "stub"
    classifier_model = "cheap-model"

    def __init__(self, run=None, exc=None, tools=True):
        self.run, self.exc, self._tools = run, exc, tools
        self.calls = []

    def supports_tools(self):
        return self._tools

    def run_tools(self, api_key, model, system, messages, tools, execute,
                  max_rounds=3, stop=None):
        self.calls.append((api_key, model, system, messages, tools))
        self.stop, self.rounds = stop, max_rounds
        if self.exc:
            raise self.exc
        return self.run(execute) if callable(self.run) else self.run


_MSGS = [{"role": "user", "content": "why did ASML drop?"}]


# ---------------------------------------------------------------- Evidence


def test_empty_evidence_leaves_the_message_alone():
    assert Evidence().augment("hola") == "hola"
    assert not Evidence()


def test_evidence_appends_what_was_fetched_with_its_arguments():
    ev = Evidence([ToolCall("get_quotes", {"tickers": ["NVDA"]}, "NVDA 226.68")])
    got = ev.augment("is NVDA up?")
    assert got.startswith("is NVDA up?")  # the user's own words stay first
    assert "get_quotes(tickers=['NVDA'])" in got
    assert "NVDA 226.68" in got
    assert "prefer these figures over anything you remember" in got


def test_ok_separates_no_lookup_needed_from_no_lookup_possible():
    assert Evidence().ok  # ran, decided nothing was needed
    assert not Evidence(ok=False).ok  # never ran


def test_sources_are_the_pages_the_gather_read():
    ev = Evidence([
        ToolCall("read_page", {"url": "https://ex.com/a"}, "body"),
        ToolCall("search_web", {"query": "asml"},
                 "[1] T\nhttps://ex.com/b\ntext\n\n[2] U\nhttps://ex.com/b\ntext"),
        ToolCall("get_quotes", {"tickers": ["NVDA"]}, "NVDA 1"),
    ])
    urls = [s["url"] for s in ev.sources()]
    assert urls == ["https://ex.com/a", "https://ex.com/b"]  # deduped, no quotes


# ------------------------------------------------------------------ gather


def test_gather_returns_what_the_model_fetched():
    p = _Provider(ToolRun("DONE", [ToolCall("get_quotes", {}, "NVDA 226")]))
    ev = agent.gather(p, "k", _MSGS, toolbox.Context())
    assert ev.ok and ev.tools_used == ["get_quotes"]


def test_gather_runs_the_tools_the_toolbox_offers():
    p = _Provider(ToolRun("DONE", []))
    agent.gather(p, "k", _MSGS, toolbox.Context())
    (_, model, system, messages, tools) = p.calls[0]
    assert model == "cheap-model"  # the gather is not what the big model is for
    assert [t.name for t in tools] == [s.name for s in toolbox.specs()]
    assert "recall" not in [t.name for t in tools]  # no index on this Context
    assert messages == _MSGS
    assert "Do NOT answer the user's question" in system


def test_gather_that_fetched_nothing_still_counts_as_having_run():
    # The model looked at the question and decided it needed nothing. Falling
    # back to the fixed pre-flight here would undo that decision.
    ev = agent.gather(_Provider(ToolRun("DONE", [])), "k", _MSGS,
                      toolbox.Context())
    assert ev.ok and not ev


def test_gather_drops_a_call_that_produced_nothing():
    p = _Provider(ToolRun("DONE", [ToolCall("search_web", {}, "")]))
    assert not agent.gather(p, "k", _MSGS, toolbox.Context())


def test_a_provider_without_tools_never_gathers():
    p = _Provider(ToolRun("x", []), tools=False)
    ev = agent.gather(p, "k", _MSGS, toolbox.Context())
    assert not ev.ok and p.calls == []


def test_a_dead_provider_falls_back_instead_of_raising():
    ev = agent.gather(_Provider(exc=RuntimeError("rate limited")), "k", _MSGS,
                      toolbox.Context())
    assert not ev.ok


def test_a_gather_that_overruns_is_abandoned():
    import time

    p = _Provider(lambda execute: time.sleep(5) or ToolRun("x", []))
    ev = agent.gather(p, "k", _MSGS, toolbox.Context(), timeout=0.05)
    assert not ev.ok


def test_an_abandoned_gather_stops_at_its_next_call():
    """The timeout stops waiting, and the loop it left running stops too:
    it no longer spends rounds on the free chain until the turn ends."""
    import threading
    import time

    ran, seen, done = [], [], threading.Event()
    real = toolbox.TOOLS["get_quotes"]

    def run(execute):
        time.sleep(0.2)
        seen.extend([p.stop(), execute("get_quotes", {"tickers": ["NVDA"]})])
        done.set()
        return ToolRun("x", [])

    toolbox.TOOLS["get_quotes"] = (real[0], lambda a, c: ran.append(a) or "1")
    try:
        p = _Provider(run)
        ev = agent.gather(p, "k", _MSGS, toolbox.Context(), timeout=0.05)
        assert not ev.ok
        assert done.wait(1)
    finally:
        toolbox.TOOLS["get_quotes"] = real
    assert seen == [True, agent.HALTED] and ran == []


def test_an_abandoned_budget_halts():
    budget = agent._Budget(lambda name, args: "ran", limit=5)
    assert not budget.halted and budget("get_quotes", {}) == "ran"
    budget.abandoned.set()
    assert budget.halted and budget("get_quotes", {}) == agent.HALTED


def _alerting(tools=True):
    return toolbox.Context(watchlist=Path("/nope/watchlist.yaml"),
                           proposes=tools)


def test_an_alert_ask_reminds_the_gather_to_draft_it():
    p = _Provider(ToolRun("DONE", []))
    asked = [{"role": "user", "content": "avísame si NVDA cae a 150"}]
    agent.gather(p, "k", asked, _alerting())
    sent = p.calls[0][3]
    assert sent[-1]["content"].endswith(agent.ALERT_NUDGE)
    assert p.rounds == agent.FAST.rounds + 1
    assert asked == [{"role": "user", "content": "avísame si NVDA cae a 150"}]


def test_no_reminder_without_the_ask_or_the_tool():
    for msgs, ctx in ((_MSGS, _alerting()),
                      ([{"role": "user", "content": "avísame si NVDA cae"}],
                       _alerting(tools=False))):
        p = _Provider(ToolRun("DONE", []))
        agent.gather(p, "k", msgs, ctx)
        assert p.calls[0][3] == msgs and p.rounds == agent.FAST.rounds


def test_gather_of_an_empty_thread_does_nothing():
    p = _Provider(ToolRun("x", []))
    assert not agent.gather(p, "k", [], toolbox.Context()).ok
    assert p.calls == []


def test_the_executor_handed_over_dispatches_the_real_tools():
    seen = {}

    def run(execute):
        seen["out"] = execute("nope_not_a_tool", {})
        return ToolRun("DONE", [])

    agent.gather(_Provider(run), "k", _MSGS, toolbox.Context())
    assert "no tool called" in seen["out"].lower()


# ---------------------------------------------------------------- profiles


def test_a_lookup_gets_the_fast_gather():
    assert agent.profile_for("is NVDA above 200 yet?") is agent.FAST
    assert agent.profile_for("¿cuál es mi mayor posición?") is agent.FAST


def test_research_gets_the_deep_gather():
    for asked in ("analiza ASML a fondo", "compara NVDA y AMD",
                  "NVDA vs AMD", "an in-depth look at Adyen",
                  "¿cómo está MELI frente a sus competidores?"):
        assert agent.profile_for(asked) is agent.DEEP, asked


def test_the_readers_choice_beats_the_wording():
    assert agent.profile_for("compara NVDA y AMD", "fast") is agent.FAST
    assert agent.profile_for("hola", "deep") is agent.DEEP
    assert agent.profile_for("hola", "nonsense") is agent.FAST


def test_a_deep_gather_researches_on_the_answering_model_with_the_engines(tmp_path):
    db = tmp_path / "prices.db"
    db.write_text("")
    ctx = toolbox.Context(db=db, prefs_path=tmp_path / "prefs.json")
    p = _Provider(ToolRun("DONE", []))
    agent.gather(p, "k", _MSGS, ctx, model="big-model", profile=agent.DEEP)
    (_, model, system, _, tools) = p.calls[0]
    assert model == "big-model"
    assert "research in depth" in system and "up to 16 calls" in system
    assert toolbox.ENGINES <= {t.name for t in tools}


def test_a_fast_gather_stays_on_the_cheap_model_without_the_engines(tmp_path):
    db = tmp_path / "prices.db"
    db.write_text("")
    ctx = toolbox.Context(db=db, prefs_path=tmp_path / "prefs.json")
    p = _Provider(ToolRun("DONE", []))
    agent.gather(p, "k", _MSGS, ctx, model="big-model")
    (_, model, system, _, tools) = p.calls[0]
    assert model == "cheap-model"
    assert "research in depth" not in system
    assert not toolbox.ENGINES & {t.name for t in tools}


def test_calls_past_the_budget_are_refused_and_not_kept(monkeypatch):
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes",
                        (toolbox.TOOLS["get_quotes"][0], lambda a, c: "NVDA 1"))

    def greedy(execute):
        outs = [execute("get_quotes", {"tickers": [str(n)]}) for n in range(9)]
        return ToolRun("DONE", [ToolCall("get_quotes", {"tickers": [str(n)]}, o)
                                for n, o in enumerate(outs)])

    ev = agent.gather(_Provider(greedy), "k", _MSGS, toolbox.Context())
    assert len(ev.calls) == agent.FAST.max_calls


def test_a_gather_cut_short_keeps_what_it_fetched(monkeypatch):
    # A rate limit on a late round: the pages already read are real material,
    # and the fixed pre-flight's guess would be the worse answer.
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes",
                        (toolbox.TOOLS["get_quotes"][0], lambda a, c: "NVDA 1"))

    def dies(execute):
        execute("get_quotes", {"tickers": ["NVDA"]})
        execute("get_quotes", {"tickers": ["NVDA"]})  # a replay on the next backend
        raise RuntimeError("rate limited")

    ev = agent.gather(_Provider(dies), "k", _MSGS, toolbox.Context())
    assert ev.ok and ev.tools_used == ["get_quotes"]


def test_a_repeated_call_is_answered_from_memory(monkeypatch):
    # A model asking for the same page again is looping, and the free chain
    # replays a failed round on its next backend: neither fetches twice, and
    # neither spends the budget.
    fetched = []
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes", (
        toolbox.TOOLS["get_quotes"][0],
        lambda a, c: fetched.append(a) or "NVDA 1"))

    def loops(execute):
        outs = [execute("get_quotes", {"tickers": ["NVDA"]}) for _ in range(10)]
        assert set(outs) == {"NVDA 1"}
        return ToolRun("DONE", [])

    ev = agent.gather(_Provider(loops), "k", _MSGS, toolbox.Context())
    assert len(fetched) == 1 and ev.tools_used == ["get_quotes"]


def test_the_loop_is_told_to_stop_once_the_budget_is_spent(monkeypatch):
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes",
                        (toolbox.TOOLS["get_quotes"][0], lambda a, c: "NVDA 1"))
    p = _Provider()
    seen = []

    def run(execute):
        for n in range(agent.FAST.max_calls):
            seen.append(p.stop())
            execute("get_quotes", {"tickers": [str(n)]})
        seen.append(p.stop())
        return ToolRun("", [])

    p.run = run
    agent.gather(p, "k", _MSGS, toolbox.Context())
    assert seen == [False] * agent.FAST.max_calls + [True]


def test_a_deep_gather_stops_once_its_tokens_are_spent(monkeypatch):
    from stocks.web import metering

    p = _Provider()
    seen = []

    def run(execute):
        seen.append(p.stop())
        metering.note("m", input=agent.DEEP.max_tokens)
        seen.append(p.stop())
        return ToolRun("", [])

    p.run = run
    with metering.metered() as m:
        agent.gather(p, "k", _MSGS, toolbox.Context(), model="big-model",
                     profile=agent.DEEP)
    assert seen == [False, True]
    assert m.by_step() == {"gather": agent.DEEP.max_tokens}


def test_a_fast_gather_has_no_token_cap():
    from stocks.web import metering

    p = _Provider()
    seen = []

    def run(execute):
        metering.note("m", input=10**7)
        seen.append(p.stop())
        return ToolRun("", [])

    p.run = run
    with metering.metered():
        agent.gather(p, "k", _MSGS, toolbox.Context())
    assert seen == [False]


# -------------------------------------------------------------------- stop


def _stopped_context(event):
    """A context whose turn's stop is `event`, the way the stream arms one."""
    import contextvars

    from stocks.chat import stopping

    ctx = contextvars.copy_context()
    ctx.run(stopping.arm, event)
    return ctx


def test_a_stopped_turn_starts_no_more_lookups(monkeypatch):
    # Stop is pressed between two calls: the second is refused without
    # running, and the loop is told to end at the round.
    import threading

    fetched = []
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes", (
        toolbox.TOOLS["get_quotes"][0],
        lambda a, c: fetched.append(a) or "NVDA 1"))
    halt = threading.Event()
    p = _Provider()
    said = []

    def run(execute):
        said.append(execute("get_quotes", {"tickers": ["NVDA"]}))
        halt.set()
        said.append(execute("get_quotes", {"tickers": ["AMD"]}))
        said.append(p.stop())
        return ToolRun("DONE", [])

    p.run = run
    from stocks.chat import stopping

    try:
        _stopped_context(halt).run(agent.gather, p, "k", _MSGS, toolbox.Context())
    except stopping.Stopped:
        pass
    assert fetched == [{"tickers": ["NVDA"]}]
    assert said[1] == agent.HALTED and said[2] is True


def test_a_stop_ends_the_wait_on_a_round_still_running():
    # A deep round can take a minute; the reader's Stop must not.
    import threading
    import time

    from stocks.chat import stopping

    halt = threading.Event()
    release = threading.Event()

    def slow(_execute):
        release.wait(10)
        return ToolRun("DONE", [])

    threading.Timer(0.2, halt.set).start()
    t0 = time.monotonic()
    try:
        _stopped_context(halt).run(
            agent.gather, _Provider(slow), "k", _MSGS, toolbox.Context(),
            model="big-model", profile=agent.DEEP)
        raised = False
    except stopping.Stopped:
        raised = True
    finally:
        release.set()
    assert raised and time.monotonic() - t0 < 2


def test_a_reason_does_not_make_the_same_call_a_new_one(monkeypatch):
    fetched = []
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes", (
        toolbox.TOOLS["get_quotes"][0],
        lambda a, c: fetched.append(a) or "NVDA 1"))

    def twice(execute):
        execute("get_quotes", {"tickers": ["NVDA"], "reason": "Precio de NVDA"})
        execute("get_quotes", {"tickers": ["NVDA"], "reason": "NVDA ahora"})
        return ToolRun("DONE", [])

    agent.gather(_Provider(twice), "k", _MSGS, toolbox.Context())
    assert len(fetched) == 1


# ------------------------------------------------------------- plan and finish


def test_a_deep_gather_tells_its_plan_without_counting_it(monkeypatch):
    fetched = []
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes", (
        toolbox.TOOLS["get_quotes"][0],
        lambda a, c: fetched.append(a) or "NVDA 1"))
    plans = []
    p = _Provider()

    def run(execute):
        said = execute(agent.PLAN, {"steps": [
            {"text": "Precio de **NVDA**", "done": False}, "Noticias de AMD"]})
        execute("get_quotes", {"tickers": ["NVDA"]})
        execute(agent.PLAN, {"steps": [{"text": "Precio de NVDA", "done": True},
                                       {"text": "Noticias de AMD"}]})
        return ToolRun("DONE", [ToolCall(agent.PLAN, {}, said)])

    p.run = run
    ev = agent.gather(p, "k", _MSGS, toolbox.Context(), model="big-model",
                      profile=agent.DEEP, on_plan=plans.append)
    names = [s.name for s in p.calls[0][4]]
    assert agent.PLAN in names and agent.FINISH in names
    assert plans[0] == [{"text": "Precio de NVDA", "done": False},
                        {"text": "Noticias de AMD", "done": False}]
    assert plans[-1][0]["done"] is True
    assert ev.plan == plans[-1]
    # Bookkeeping, not material: neither counted nor kept.
    assert ev.tools_used == ["get_quotes"] and len(fetched) == 1


def test_a_fast_gather_is_offered_no_plan():
    p = _Provider(ToolRun("DONE", []))
    agent.gather(p, "k", _MSGS, toolbox.Context())
    assert agent.PLAN not in [s.name for s in p.calls[0][4]]


def test_finishing_ends_the_loop_and_owns_up_to_the_gap(monkeypatch):
    monkeypatch.setitem(toolbox.TOOLS, "get_quotes",
                        (toolbox.TOOLS["get_quotes"][0], lambda a, c: "NVDA 1"))
    p = _Provider()
    seen = []

    def run(execute):
        execute("get_quotes", {"tickers": ["NVDA"]})
        seen.append(p.stop())
        execute(agent.FINISH, {"missing": "AMD's 2026 guidance"})
        seen.append(p.stop())
        return ToolRun("", [])

    p.run = run
    ev = agent.gather(p, "k", _MSGS, toolbox.Context(), model="big-model",
                      profile=agent.DEEP)
    assert seen == [False, True]
    assert ev.missing == "AMD's 2026 guidance"
    assert "could not find: AMD's 2026 guidance" in ev.augment("q")
    assert ev.tools_used == ["get_quotes"]


def test_a_question_about_results_or_a_move_gets_the_quote_too():
    """"Resultados ServiceNow de hoy" searched the web and nothing else, and
    the answer read the reaction off the book's stale session move."""
    rule = agent.GATHER_SYSTEM
    assert "results" in rule and "get_quotes" in rule
    assert "premarket and after-hours" in rule
