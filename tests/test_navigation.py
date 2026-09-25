"""The app's menu: one table, four readers.

`stocks.navigation` says which pages exist. `st.navigation` builds the sidebar
from it, `web/nav.py` builds the phone tab bar, and `/v1/nav` hands it to the
React shell. What is tested here is that the table itself stays answerable —
every page it names exists, every label it names is translated, and the phone
bar names pages rather than strings nobody routed.

A page missing from one menu is not a bug anybody reports. It is a page nobody
finds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stocks import navigation
from stocks.api.app import app as fastapi_app
from stocks.web.i18n import catalog

PAGES = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web" / "app_pages"
TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)


def test_every_destination_points_at_a_page_that_exists():
    missing = [
        d.module
        for d in navigation.DESTINATIONS
        if not (PAGES / f"{d.module}.py").exists()
    ]
    assert not missing, f"the menu offers pages that are not there: {missing}"


def test_every_label_is_translated_in_both_languages():
    """A menu entry that falls through to its key reads as `nav.sector`."""
    for lang in ("en", "es"):
        strings = catalog(lang)
        missing = sorted(
            {d.label for d in navigation.DESTINATIONS if d.label not in strings}
            | {d.section for d in navigation.DESTINATIONS
               if d.section and d.section not in strings}
        )
        assert not missing, f"locales/{lang} has no string for: {missing}"


def test_the_default_page_is_the_only_one_served_at_the_root():
    roots = [d for d in navigation.DESTINATIONS if d.path == ""]
    assert len(roots) == 1, "two default pages is one page nobody reaches"
    assert roots[0].module == "home"


def test_paths_are_unique():
    paths = [d.path for d in navigation.DESTINATIONS]
    assert len(paths) == len(set(paths)), f"two pages share a URL: {paths}"


def test_the_phone_bar_carries_pages_and_not_strings():
    """Four destinations, each of them a page this table actually knows."""
    unknown = [p for p in navigation.BOTTOM_NAV if navigation.by_path(p) is None]
    assert not unknown, f"the tab bar links nowhere: {unknown}"
    assert len(navigation.BOTTOM_NAV) == 4, "the DS bar is four wide"


def test_sections_keep_the_tables_order():
    """The menu's order is the table's order, and a group that appears twice
    would be two groups on screen — so it is two groups here."""
    flat = [d for _, items in navigation.sections() for d in items]
    assert flat == list(navigation.DESTINATIONS)


def test_the_api_serves_the_same_menu():
    """The React shell holds no page list of its own; this is the only reason
    it can stay in step with a page added to the app."""
    body = TestClient(fastapi_app).get("/v1/nav", headers=AUTH).json()
    assert [d["path"] for d in body["destinations"]] == [
        d.path for d in navigation.DESTINATIONS
    ]
    assert body["bottom"] == list(navigation.BOTTOM_NAV)
    ticker = next(d for d in body["destinations"] if d["path"] == "ticker")
    # Key names, not strings: a translated payload would give this API a
    # language, and it serves two.
    assert ticker["label"] == "nav.ticker"
    assert ticker["icon"] == "query_stats"
    assert ticker["section"] == "nav.section_market"
