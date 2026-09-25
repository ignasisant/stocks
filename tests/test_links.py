"""Deep links from notifications back into the app (stocks.notify.links)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stocks.notify import links

WEB = Path(__file__).resolve().parents[1] / "src" / "stocks" / "web"


@pytest.fixture
def origin(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://topstocks.example/")
    return "https://topstocks.example"


def test_app_base_strips_the_trailing_slash(origin):
    assert links.app_base() == "https://topstocks.example"


def test_everything_is_none_without_a_configured_origin(monkeypatch):
    """A deploy that has not said where it lives must not emit links to a
    hostname nobody can reach — the messages render exactly as before."""
    monkeypatch.setenv("APP_PUBLIC_URL", "")
    monkeypatch.setattr(links, "secret", lambda *a, **k: "")
    assert links.app_base() is None
    assert links.page_url(links.PORTFOLIO) is None
    assert links.ticker_url("NVDA") is None


def test_page_url_builds_paths_and_query(origin):
    assert links.page_url(links.PORTFOLIO) == "https://topstocks.example/portfolio"
    assert links.page_url(links.HOME) == "https://topstocks.example/"
    assert (
        links.page_url(links.PORTFOLIO, tab="tax")
        == "https://topstocks.example/portfolio?tab=tax"
    )


def test_ticker_url_uppercases_and_uses_the_param_the_app_reads(origin):
    # app.py hydrates from `?ticker=`, not `?symbol=`.
    assert links.ticker_url("nvda") == "https://topstocks.example/ticker?ticker=NVDA"


def test_ticker_url_escapes_a_symbol_that_needs_it(origin):
    assert links.ticker_url("BRK.B").endswith("ticker=BRK.B")
    assert "%26" in links.ticker_url("A&B")


def test_an_explicit_base_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://ignored.example")
    assert links.page_url(links.PORTFOLIO, "https://given.example") == (
        "https://given.example/portfolio"
    )


def test_linked_pages_are_pages_that_exist():
    """The paths mirror what st.navigation derives from each page module's
    filename, so a page renamed in web/app.py must rename the link too."""
    for path in (links.PORTFOLIO, links.IMPORT, links.EARNINGS):
        assert (WEB / "app_pages" / f"{path}.py").exists(), path
    # And the menu agrees about where each of them lives. Asked of the table
    # rather than of app.py's source: the pages are built from it now, so this
    # is the claim itself instead of a grep for the line that used to make it.
    from stocks import navigation

    for path in (links.PORTFOLIO, links.IMPORT, links.EARNINGS, "ticker"):
        assert navigation.by_path(path) is not None, path
    assert links.TICKER == "ticker"
    assert (WEB / "app_pages" / "home.py").exists() and links.HOME == ""
