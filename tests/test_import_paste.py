"""Importing a statement that was never uploaded — the paste fallback.

The file picker is not a given. Managed Chrome can turn file dialogs off
outright (FileSelectionDialogsAllowed), a work phone can do the same, and a
browser that drops the app's cookies answers the uploader's PUT with 403
before any of the page runs. All three arrive in Python as "no file", so the
page cannot detect them — it can only offer a second door that needs no
dialog, no cookie and no upload request.

What must not break: a pasted statement rides the *identical* path an upload
does (parse, validation, preview, commit, undo record), the box is reachable
before anything has been uploaded, one broker's text never reaches another
broker's parser, and the diagnostic says which door it came through — a
reader who pastes is usually a reader whose upload could not work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from stocks.portfolio import diagnostics, last_import, platforms
from stocks.portfolio.ledger import all_transactions
from stocks.web import auth, widgets

PAGE = "src/stocks/web/app_pages/import_transactions.py"
ASSETS = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "assets"
SAMPLE = ASSETS / platforms.by_key("revolut").sample


@pytest.fixture
def paths(tmp_path):
    p = auth.paths_for("newbie@example.com", users_dir=tmp_path)
    p.root.mkdir(parents=True, exist_ok=True)
    p.prefs.write_text(json.dumps(dict(auth.DEFAULT_PREFS) | {"language": "en"}))
    return p


@pytest.fixture
def page(monkeypatch, paths):
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "db_path", lambda: paths.db)
    monkeypatch.setattr(auth, "watchlist_path", lambda: paths.watchlist)
    return AppTest.from_file(PAGE, default_timeout=120)


def _box(at):
    return [a for a in at.text_area if a.label == "Revolut statement text"]


def test_the_paste_box_is_offered_before_anything_has_been_uploaded(page):
    """It has to render above the st.stop() that ends the empty page — a
    fallback the blocked reader cannot see is not a fallback."""
    page.run()
    assert not page.exception
    assert _box(page)


def test_a_pasted_statement_previews_exactly_as_an_upload_would(page):
    page.run()
    _box(page)[0].input(SAMPLE.read_text(encoding="utf-8")).run()

    assert not page.exception
    # The real parser's own summary, not a canned line.
    assert any("importable" in str(s.value) for s in page.subheader)
    assert [b for b in page.button if b.label == "Commit to ledger"]


def test_a_pasted_statement_commits_and_stays_undoable(page, paths):
    page.run()
    _box(page)[0].input(SAMPLE.read_text(encoding="utf-8")).run()
    [b for b in page.button if b.label == "Commit to ledger"][0].click().run()

    assert not page.exception
    rows = all_transactions(paths.db)
    assert len(rows) == 25  # the same 25 the uploaded sample commits
    assert {t.note.split()[0] for t in rows} == {"revolut"}

    record = last_import.load(paths.last_import)
    assert record is not None
    assert record.platform == "revolut"
    assert len(record.tx_ids) == 25  # the undo knows exactly what to remove
    assert record.filename == "pasted.csv"  # named for how it arrived


def test_a_paste_is_recorded_as_its_own_surface(page, monkeypatch):
    """The number that says whether uploading is failing in the field."""
    seen: list[dict] = []
    monkeypatch.setattr(
        diagnostics,
        "report",
        lambda *a, **kw: seen.append(kw) or {},
    )
    page.run()
    _box(page)[0].input(SAMPLE.read_text(encoding="utf-8")).run()

    assert not page.exception
    assert seen and seen[0]["surface"] == "paste"


def test_the_shipped_example_is_still_recorded_as_an_ordinary_import(
    page, monkeypatch
):
    seen: list[dict] = []
    monkeypatch.setattr(
        diagnostics,
        "report",
        lambda *a, **kw: seen.append(kw) or {},
    )
    page.run()
    [b for b in page.button if b.label == "Load an example statement"][0].click().run()

    assert not page.exception
    assert seen and seen[0]["surface"] == "import"


def test_one_brokers_text_never_reaches_another_brokers_parser(page, monkeypatch):
    """Keyed by platform, like the uploader: switching platform must leave the
    pasted text behind rather than feed it to the next parser."""
    monkeypatch.setattr(widgets, "is_mobile", lambda: True)
    page.run()
    _box(page)[0].input(SAMPLE.read_text(encoding="utf-8")).run()
    assert _box(page)[0].value

    picker = [s for s in page.selectbox if s.label == "Importing from"][0]
    picker.set_value("generic").run()

    assert not page.exception
    generic_box = [a for a in page.text_area if a.label == "Generic CSV statement text"]
    assert generic_box and not generic_box[0].value
    # Nothing to preview: the generic parser was handed nothing at all.
    assert not [b for b in page.button if b.label == "Commit to ledger"]


# ---------------------------------------------------- formats with no text form

# A real PDF header is all the sniffer reads; padded past the 64 characters
# below which a blob is treated as ordinary text.
FAKE_PDF = b"%PDF-1.4\n" + b"x" * 64


def _b64(blob: bytes) -> str:
    import base64

    return base64.b64encode(blob).decode()


def test_a_base64_pdf_is_handed_to_the_pdf_branch_of_the_parser(page, monkeypatch):
    """A PDF has no paste-able text form, so the way in is base64 — and the
    filename it lands under is what picks the parser branch."""
    seen: list[tuple] = []
    monkeypatch.setattr(
        diagnostics, "report", lambda *a, **kw: seen.append(a) or {}
    )
    page.run()
    _box(page)[0].input(_b64(FAKE_PDF)).run()

    assert not page.exception
    assert seen and seen[0][1] == "pasted.pdf"  # not pasted.csv


def test_a_format_the_platform_cannot_read_is_refused_before_the_parser(
    page, monkeypatch
):
    """Generic CSV has no PDF branch: saying so here beats failing deep inside
    a parser that was handed bytes it never claimed to read."""
    monkeypatch.setattr(widgets, "is_mobile", lambda: True)
    page.run()
    [s for s in page.selectbox if s.label == "Importing from"][0].set_value(
        "generic"
    ).run()
    [a for a in page.text_area if a.label == "Generic CSV statement text"][0].input(
        _b64(FAKE_PDF)
    ).run()

    assert not page.exception
    assert any("PDF" in str(e.value) for e in page.error)
    assert not [b for b in page.button if b.label == "Commit to ledger"]


# --------------------------------------------------------------- after a commit


def test_a_committed_statement_cannot_be_committed_a_second_time(page, paths):
    """The ledger it would go into now already holds it: a second press adds
    the batch again under duplicate warnings rather than being refused."""
    page.run()
    _box(page)[0].input(SAMPLE.read_text(encoding="utf-8")).run()
    [b for b in page.button if b.label == "Commit to ledger"][0].click().run()

    assert not page.exception
    assert not [b for b in page.button if b.label == "Commit to ledger"]
    assert not _box(page)[0].value  # the box is empty again
    assert any("Imported 25 transactions" in str(s.value) for s in page.success)
    # And the page landed on the undo for exactly that batch.
    assert [b for b in page.button if b.label.startswith("Clear last import")]

    page.run()
    assert len(all_transactions(paths.db)) == 25


def test_no_blocked_upload_warning_when_there_is_no_browser_to_blame(page):
    """AppTest sends no cookies at all; a missing cookie jar is not a blocked
    one, and a false alarm on the working path is worse than silence."""
    page.run()
    assert not page.exception
    assert not [w for w in page.warning if "cookie" in str(w.value)]
