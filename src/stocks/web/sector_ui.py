"""The sector screen's written verdict — the Streamlit half of chat/sector_ai.

Same shape as `web/daily_ui`, and for the same reason: a model call is slow
enough that blocking the script on it would make the page feel broken, so the
generation runs on a thread, the script waits GRACE_S for it, and a fragment
polls until it lands. Everything with a side effect — the spent allowance, the
stored verdict — is applied back on the script thread, which is the one that
owns those files.

What is cached, and why it matters to the reader's allowance: a verdict is
keyed by (sector, the scan it read, language). Re-opening a sector the same
night is free; a new nightly scan is what makes it worth paying for again.
"""

from __future__ import annotations

import html
import threading

import streamlit as st

from stocks import obs
from stocks.chat import engine, sector_ai
from stocks.web import auth, skeletons
from stocks.web.i18n import active_language
from stocks.web.i18n import t as tr

# How long the script waits before handing over to the poller. A provider that
# answers inside this never shows a placeholder at all.
GRACE_S = 2.5

# How often the fragment asks whether the thread finished. Each tick is a
# websocket round trip, so this is as slow as it can be without the answer
# feeling late.
POLL_S = 1.5

_JOBS = "sector_verdict_jobs"
_DONE = "sector_verdict_done"


def _key(scan, lang: str) -> tuple:
    """What makes one verdict a different verdict. The scan's date is in it so
    a fresh cohort is re-read rather than described by yesterday's paragraph."""
    return (scan.sector, scan.as_of, lang)


def _stored(key: tuple) -> sector_ai.Verdict | None:
    raw = auth.load_verdicts().get(key[0])
    if not isinstance(raw, dict):
        return None
    verdict = sector_ai.Verdict.from_dict(raw)
    fresh = (verdict.sector, verdict.as_of, verdict.lang) == key
    return verdict if fresh and verdict.source == "llm" else None


def _start(prefs: dict, facts: dict, key: tuple) -> dict:
    """Kick off one generation on a background thread; return its job dict.

    The thread touches neither Streamlit nor the account's files. `spend`
    mutates this session's own prefs copy, which nothing writes until
    `_collect` does, back on the script thread.
    """
    job: dict = {"key": key, "prefs": prefs, "verdict": None,
                 "spent": False, "done": False}

    def spend(p: dict) -> bool:
        ok = engine.spend_free_quota(p)
        job["spent"] = job["spent"] or ok
        return ok

    def work() -> None:
        try:
            job["verdict"] = sector_ai.generate(
                prefs, facts, key[2], spend_free=spend
            )
        except Exception as exc:
            # sector_ai.generate swallows its own, but a thread that dies
            # silently would leave the fragment polling forever.
            obs.warn("sector.verdict_generate_failed",
                     error_type=type(exc).__name__, error=str(exc)[:200])
        finally:
            job["done"] = True

    thread = threading.Thread(target=work, name="sector-verdict", daemon=True)
    job["thread"] = thread
    thread.start()
    return job


def _collect(job: dict) -> sector_ai.Verdict | None:
    """A finished job's verdict, after its side effects are applied.

    Prefs are saved only when a unit was actually taken, and the verdict only
    when a model wrote it: a computed fallback is free to rebuild, and storing
    it would block the upgrade to a real read once the allowance resets.
    """
    if job.get("spent"):
        auth.save_prefs(job["prefs"])
    verdict = job.get("verdict")
    if verdict:
        stored = auth.load_verdicts()
        stored[verdict.sector] = verdict.to_dict()
        auth.save_verdicts(stored)
    return verdict


def _resolve(prefs: dict, facts: dict, key: tuple):
    """(verdict, still_writing). Never raises, never blocks past GRACE_S."""
    done = st.session_state.setdefault(_DONE, {})
    if key in done:
        return done[key], False

    jobs = st.session_state.setdefault(_JOBS, {})
    job = jobs.get(key)
    if job is None:
        stored = _stored(key)
        if stored is not None:
            done[key] = stored
            return stored, False
        if not auth.is_logged_in():
            # No account, no prefs to spend and nowhere to store the answer.
            return None, False
        job = jobs[key] = _start(prefs, facts, key)
        job["thread"].join(GRACE_S)

    if not job["done"]:
        return None, True
    jobs.pop(key, None)
    done[key] = _collect(job)
    return done[key], False


# ------------------------------------------------------------------ painting


# Tokens only — `--ag-text-dim` was a name this design system never had, so
# every line below used to inherit body colour and the read looked like page
# copy rather than something written about the podium.
_CSS = """
<style>
.ag-sv { display:flex; flex-direction:column; gap:.5rem; }
.ag-sv-head {
  font-weight:600; line-height:1.35; color:var(--ag-text-primary);
}
.ag-sv-line {
  color:var(--ag-text-secondary); line-height:1.5;
  font-variant-numeric:tabular-nums;
}
.ag-sv-note {
  color:var(--ag-text-muted); font-size:var(--ag-fs-xs);
  border-top:1px solid var(--ag-border); padding-top:.5rem; margin-top:.15rem;
}
</style>
"""


def _markup(verdict: sector_ai.Verdict, *, note: str = "") -> str:
    lines = "".join(
        f'<div class="ag-sv-line">{html.escape(b)}</div>' for b in verdict.bullets
    )
    tail = f'<div class="ag-sv-note">{html.escape(note)}</div>' if note else ""
    return (
        _CSS + '<div class="ag-sv">'
        f'<div class="ag-sv-head">{html.escape(verdict.headline)}</div>'
        f"{lines}{tail}</div>"
    )


def reserve(container=None):
    """Reserve the verdict's place above the table, so the page does not jump."""
    return skeletons.reserve("text", lines=4, border=True, container=container)


def render(slot, scan, held: tuple[str, ...] = ()) -> None:
    """Fill the reserved slot with this sector's read.

    Never raises. A verdict is the one block on this page that depends on a
    third party answering, and no paragraph is worth taking the screen down —
    any failure clears the slot and leaves the podium and the table standing.
    """
    try:
        _render(slot, scan, held)
    except Exception as exc:
        obs.warn("sector.verdict_render_failed",
                 error_type=type(exc).__name__, error=str(exc)[:200])
        if not slot.resolved:
            slot.clear()


def _render(slot, scan, held: tuple[str, ...]) -> None:
    if not scan.podium:
        slot.clear()
        return
    lang = active_language()
    key = _key(scan, lang)
    prefs = auth.load_prefs() if auth.is_logged_in() else {}
    facts = sector_ai.build_facts(scan, held)
    verdict, writing = _resolve(prefs, facts, key)

    if writing:
        with slot.container(), st.container(border=True, key="ag_sector_verdict"):
            st.subheader(tr("sector.verdict_title"))
            st.html(skeletons.html("text", lines=3))
            st.caption(tr("sector.verdict_waiting"))
            _poll(scan, held)
        return

    # Its own card, like the podium above it. Without one the read sat loose
    # between the picker and the table and parsed as page copy — which is the
    # wrong claim for the one block on this page a model wrote.
    with slot.container(), st.container(border=True, key="ag_sector_verdict"):
        st.subheader(tr("sector.verdict_title"))
        _paint(verdict, facts, lang)


def _paint(verdict, facts: dict, lang: str) -> None:
    """The resolved verdict, or the computed stand-in when none was written."""
    if verdict is not None:
        st.html(_markup(verdict))
        return
    note = tr("sector.verdict_signin") if not auth.is_logged_in() else tr(
        "sector.verdict_computed"
    )
    st.html(_markup(sector_ai.computed(facts, lang), note=note))


@st.fragment(run_every=POLL_S)
def _poll(scan, held: tuple[str, ...]) -> None:
    """Redraw in place once the thread lands.

    A `run_every` fragment cannot stop itself, so this one reruns the whole
    page as soon as there is an answer — which both paints it and takes the
    poller off the socket.
    """
    lang = active_language()
    key = _key(scan, lang)
    jobs = st.session_state.get(_JOBS) or {}
    job = jobs.get(key)
    if job is None or job.get("done"):
        st.rerun()
