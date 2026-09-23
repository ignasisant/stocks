"""The Import page's "importing from" picker, on both form factors.

Seven brands with logos fit a desktop segmented strip and do not fit a phone
row: the mobile stylesheet joins segmented cells edge to edge and refuses to
ellipsize their labels, so the strip overruns the viewport. Phones get a
dropdown instead. What must not break: every platform stays reachable on both,
and the phone still lands on the same default as the desktop strip.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from stocks.portfolio import platforms
from stocks.web import auth, widgets

PAGE = "src/stocks/web/app_pages/import_transactions.py"


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


def test_a_phone_picks_the_platform_from_a_dropdown(page, monkeypatch):
    monkeypatch.setattr(widgets, "is_mobile", lambda: True)
    page.run()
    assert not page.exception
    picker = [s for s in page.selectbox if s.label == "Importing from"]
    assert len(picker) == 1
    # Every platform reachable, named in plain text — a selectbox option
    # renders no markdown, so the logo markup of the desktop strip would
    # print as literal "![Revolut](data:image/...)".
    assert picker[0].options == [p.label for p in platforms.PLATFORMS]
    assert picker[0].value == platforms.PLATFORMS[0].key


def test_a_desktop_keeps_the_segmented_strip_with_its_logos(page, monkeypatch):
    monkeypatch.setattr(widgets, "is_mobile", lambda: False)
    page.run()
    assert not page.exception
    assert not [s for s in page.selectbox if s.label == "Importing from"]
    strip = [c for c in page.segmented_control if c.label == "Importing from"]
    assert len(strip) == 1
    assert strip[0].value == platforms.PLATFORMS[0].key
    # The desktop labels carry the brand logo as a markdown image; the
    # dropdown cannot, which is the whole reason the two differ. Only the
    # brandless "Generic CSV" reads as bare text on both.
    logoed = [o for o in strip[0].options if o.startswith("![")]
    assert len(logoed) == len([p for p in platforms.PLATFORMS if p.domain])
