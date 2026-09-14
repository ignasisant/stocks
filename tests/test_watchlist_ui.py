"""The rebuilt Watchlist tab: search to add, tag groups, saves as you edit.

The tab was one `st.data_editor` behind a Save button — a blank row you had to
spell a symbol into, tags as a comma string, and a favorite checkbox that did
nothing until Save. These cover what replaced it: the catalog-backed adder,
grouping by tag, the write-through of every grid edit, group rename/dissolve,
and the phone layout that renders controls instead of a panning grid.

`AppTest` has no `data_editor` accessor, so the grid's write-back is covered
where it lives — `watchlist_ui._apply`, the function the editor's diff goes
through — and the page tests cover everything a user can actually click.
"""

from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stocks.config import load_watchlist
from stocks.web import auth, search, watchlist_ui

PAGE = "src/stocks/web/app_pages/profile.py"


@pytest.fixture
def paths(tmp_path):
    return auth.UserPaths(
        root=tmp_path,
        watchlist=tmp_path / "watchlist.yaml",
        db=tmp_path / "portfolio.db",
        last_import=tmp_path / "last_import.json",
        prefs=tmp_path / "prefs.json",
        chat=tmp_path / "chat.json",
        bank=tmp_path / "bank.json",
        action=tmp_path / "daily_action.json",
    )


@pytest.fixture
def page(monkeypatch, paths):
    monkeypatch.setattr(auth, "require_login", lambda: paths)
    monkeypatch.setattr(auth, "user_paths", lambda: paths)
    monkeypatch.setattr(auth, "is_logged_in", lambda: True)
    monkeypatch.setattr(auth, "current_email", lambda: "me@example.com")
    # The two network tiers of the adder, pinned: the local catalogs (coins,
    # funds) stay real, Yahoo and the SEC map do not get called from a test.
    monkeypatch.setattr(search, "world_matches", lambda q: [])
    monkeypatch.setattr(search, "sec_matches", lambda q: [])
    st.cache_data.clear()
    return AppTest.from_file(PAGE, default_timeout=60)


def _html(at) -> str:
    bodies = (str(getattr(el.proto, "body", "")) for el in at.get("html"))
    return "\n".join(b for b in bodies if "ts-inline-css" not in b)


def _entries(path) -> dict[str, dict]:
    """The saved watchlist as {ticker: entry-ish}, for asserting writes."""
    return {
        h.ticker: {
            "name": h.name,
            "favorite": h.favorite,
            "tags": h.tags,
            "shares": h.shares,
            "cost": h.cost,
        }
        for h in load_watchlist(path)
    }


# ------------------------------------------------------------------- adder


def test_the_adder_searches_every_catalog_and_marks_what_is_already_followed(
    paths, monkeypatch
):
    """One query, all tiers: the account's own list first (flagged, so a
    duplicate reads as "you have this"), then the local catalogs."""
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n    name: Apple\n")
    monkeypatch.setattr(search, "world_matches", lambda q: [])
    monkeypatch.setattr(search, "sec_matches", lambda q: [])

    own = search.add_candidates("AAPL", path=paths.watchlist)
    assert own[0]["ticker"] == "AAPL"
    assert own[0]["kind"] == "watch" and own[0]["listed"] is True

    coin = search.add_candidates("BTC", path=paths.watchlist)
    # A coin arrives as the Yahoo pair, which is the whole point of the tier:
    # a bare "BTC" would collide with a stock ticker.
    assert ("BTC-USD", "crypto") in [(r["ticker"], r["kind"]) for r in coin]

    fund = search.add_candidates("IWDA", path=paths.watchlist)
    assert fund and fund[0]["kind"] == "fund" and fund[0]["ticker"].startswith("IWDA")


def test_a_symbol_no_catalog_knows_is_still_offered(paths, monkeypatch):
    """The picker's "Analyze SYMBOL" escape hatch, as an add: a plausible
    symbol nothing indexes is the user's call, not the catalog's."""
    monkeypatch.setattr(search, "world_matches", lambda q: [])
    monkeypatch.setattr(search, "sec_matches", lambda q: [])
    rows = search.add_candidates("ZZQQ", path=paths.watchlist)
    assert [(r["ticker"], r["kind"]) for r in rows] == [("ZZQQ", "raw")]
    # Not a symbol at all: no row to click, rather than a junk entry.
    assert search.add_candidates("a whole sentence", path=paths.watchlist) == []


def test_picking_a_result_adds_it_with_its_name_groups_and_star(page, paths):
    page.run()
    page.text_input(key=watchlist_ui.Q).set_value("BTC").run()
    page.multiselect(key=watchlist_ui.ADD_TAGS).set_value(["crypto"]).run()
    page.checkbox(key=watchlist_ui.ADD_FAV).set_value(True).run()
    page.button(key="wl_add_BTC_USD").click().run()

    saved = _entries(paths.watchlist)
    assert saved["BTC-USD"]["name"] == "Bitcoin"  # the catalog's, not typed
    assert saved["BTC-USD"]["tags"] == ["crypto"]
    assert saved["BTC-USD"]["favorite"] is True
    # The taken offer clears the field, the way the top-bar picker does.
    assert page.text_input(key=watchlist_ui.Q).value == ""


def test_a_symbol_already_on_the_list_cannot_be_added_twice(page, paths):
    paths.watchlist.write_text("watchlist:\n  - ticker: AAPL\n    name: Apple\n")
    page.run()
    page.text_input(key=watchlist_ui.Q).set_value("AAPL").run()
    row = page.button(key="wl_add_AAPL")
    assert row.proto.disabled
    assert "Already on your watchlist" in row.proto.help


def test_the_adder_leads_the_tab_even_with_nothing_on_the_list(page, paths):
    """An empty watchlist has no list card, so the adder IS the tab — and the
    empty state points at it instead of at a plus button on a grid."""
    page.run()
    body = _html(page)
    assert ">Find a ticker<" in body
    assert "Watchlist</span>" not in body  # no list card until there is a list
    # And the empty state sends the reader to the search, not to a plus button
    # at the bottom of a grid that no longer exists.
    assert any(
        "Search for a ticker below" in c.value for c in page.caption
    ), [c.value for c in page.caption][:6]


# ------------------------------------------------------------------ groups


def test_the_list_groups_by_tag_with_favorites_first_and_loose_names_last():
    """Overview's own order: favorites, then each tag, then whatever carries
    neither — and a ticker in two tags shows up in both."""
    holdings = load_watchlist_from(
        """
        watchlist:
          - ticker: NVDA
            favorite: true
            tags: [semis, tech]
          - ticker: ASML
            tags: [semis]
          - ticker: KO
        """
    )
    got = [(gid, label, [h.ticker for h in rows], tag)
           for gid, label, rows, tag in watchlist_ui.groups(holdings, "tags")]
    assert got == [
        ("fav", "Favorites", ["NVDA"], None),
        ("tag_semis", "semis", ["NVDA", "ASML"], "semis"),
        ("tag_tech", "tech", ["NVDA"], "tech"),
        ("none", "No group", ["KO"], None),
    ]


def test_the_other_two_groupings_are_favorites_and_one_flat_list():
    holdings = load_watchlist_from(
        """
        watchlist:
          - ticker: NVDA
            favorite: true
          - ticker: KO
            tags: [dividends]
        """
    )
    assert [(g[0], [h.ticker for h in g[2]])
            for g in watchlist_ui.groups(holdings, "favorites")] == [
        ("fav", ["NVDA"]),
        ("rest", ["KO"]),
    ]
    flat = watchlist_ui.groups(holdings, "flat")
    assert len(flat) == 1 and [h.ticker for h in flat[0][2]] == ["NVDA", "KO"]


def test_a_grid_gets_a_new_widget_when_its_membership_moves():
    """`st.data_editor` replays its edits by row position. Starring a name
    moves it out of its group, so the next frame is a different set of rows —
    a stale diff would then apply one ticker's edit to another."""
    a = watchlist_ui._ed_key("fav", ("AAPL", "MSFT"))
    assert a == watchlist_ui._ed_key("fav", ("AAPL", "MSFT"))  # stable otherwise
    assert a != watchlist_ui._ed_key("fav", ("AAPL",))
    assert a != watchlist_ui._ed_key("fav", ("MSFT", "AAPL"))
    assert a != watchlist_ui._ed_key("none", ("AAPL", "MSFT"))


def test_the_page_renders_a_section_per_group_with_its_count(page, paths):
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: NVDA\n    tags: [semis]\n"
        "  - ticker: ASML\n    tags: [semis]\n"
        "  - ticker: KO\n"
    )
    page.run()
    body = _html(page)
    assert '<span class="wl-gt">semis</span><span class="wl-gc">2</span>' in body
    assert '<span class="wl-gt">No group</span><span class="wl-gc">1</span>' in body
    assert "3 on the watchlist." in body


def test_the_filters_narrow_the_list_and_say_when_nothing_matches(page, paths):
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: NVDA\n    name: Nvidia\n    tags: [semis]\n"
        "  - ticker: KO\n    name: Coca-Cola\n    tags: [dividends]\n"
    )
    page.run()
    page.multiselect(key=watchlist_ui.TAG_FILTER).set_value(["semis"]).run()
    assert '<span class="wl-gc">1</span>' in _html(page)
    page.multiselect(key=watchlist_ui.TAG_FILTER).set_value([]).run()
    page.text_input(key=watchlist_ui.FILTER).set_value("coca").run()
    body = _html(page)
    assert '<span class="wl-gt">dividends</span>' in body  # name matched, not tag
    page.text_input(key=watchlist_ui.FILTER).set_value("nothing here").run()
    assert "No entry matches that filter." in _html(page)


# ------------------------------------------------------- write-through edits


def test_every_grid_edit_writes_on_the_spot(paths):
    """The tab's own promise, and the page's: no Save button anywhere."""
    paths.watchlist.write_text(
        "watchlist:\n  - ticker: NVDA\n    tags: [semis]\n    alerts:\n"
        "      - type: above\n        price: 200\n"
    )
    before = [
        {"ticker": "NVDA", "name": "", "favorite": False, "tags": ["semis"],
         "shares": None, "cost": None},
    ]
    after = [
        {"ticker": "NVDA", "name": "Nvidia", "favorite": True,
         "tags": ["semis", "ai"], "shares": 12, "cost": 95.5},
    ]
    assert watchlist_ui._apply(before, after, paths.watchlist) == 1
    saved = _entries(paths.watchlist)["NVDA"]
    assert saved == {
        "name": "Nvidia", "favorite": True, "tags": ["semis", "ai"],
        "shares": 12.0, "cost": 95.5,
    }
    # Alert rules are not the editor's to touch.
    assert load_watchlist(paths.watchlist)[0].alerts[0].price == 200


def test_an_untouched_grid_writes_nothing(paths):
    paths.watchlist.write_text("watchlist:\n  - ticker: NVDA\n    tags: [semis]\n")
    stamp = paths.watchlist.stat().st_mtime_ns
    rows = [
        {"ticker": "NVDA", "name": "", "favorite": False, "tags": ["semis"],
         "shares": None, "cost": None},
    ]
    assert watchlist_ui._apply(rows, list(rows), paths.watchlist) == 0
    assert paths.watchlist.stat().st_mtime_ns == stamp


def test_clearing_a_number_cell_clears_the_position(paths):
    """`set_position` leaves a field alone on None and clears it on 0 — an
    emptied cell has to arrive as the second, or a typo is unfixable."""
    paths.watchlist.write_text(
        "watchlist:\n  - ticker: NVDA\n    shares: 12\n    cost: 95.5\n"
    )
    before = [{"ticker": "NVDA", "name": "", "favorite": False, "tags": [],
               "shares": 12.0, "cost": 95.5}]
    after = [{"ticker": "NVDA", "name": "", "favorite": False, "tags": [],
              "shares": float("nan"), "cost": float("nan")}]
    assert watchlist_ui._apply(before, after, paths.watchlist) == 1
    saved = _entries(paths.watchlist)["NVDA"]
    assert saved["shares"] == 0 and saved["cost"] is None


def test_the_row_action_opens_or_drops_the_row_it_was_clicked_on(paths):
    paths.watchlist.write_text("watchlist:\n  - ticker: NVDA\n  - ticker: KO\n")
    # Open hands the ticker to the picker's own contract rather than
    # navigating from inside a callback.
    st.session_state["act"] = {"row": 0, "label": ":material/open_in_new: Open"}
    watchlist_ui._row_action("act", ("NVDA", "KO"), paths.watchlist)
    assert st.session_state["picker_selected"] == "NVDA"
    assert st.session_state["picker_clicked"] is True
    assert list(_entries(paths.watchlist)) == ["NVDA", "KO"]  # opening drops nothing

    st.session_state["act"] = {"row": 1, "label": ":material/delete: Remove"}
    watchlist_ui._row_action("act", ("NVDA", "KO"), paths.watchlist)
    assert list(_entries(paths.watchlist)) == ["NVDA"]
    # A click that arrives without a resolvable row is a no-op, not a crash.
    st.session_state["act"] = {"row": 9, "label": ":material/delete: Remove"}
    watchlist_ui._row_action("act", ("NVDA",), paths.watchlist)
    assert list(_entries(paths.watchlist)) == ["NVDA"]


# -------------------------------------------------------- group management


def test_renaming_a_group_renames_it_on_every_member(paths):
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: NVDA\n    tags: [semis, tech]\n"
        "  - ticker: ASML\n    tags: [semis]\n"
        "  - ticker: KO\n    tags: [dividends]\n"
    )
    assert auth.rename_tag("semis", "chips", paths.watchlist) == 2
    saved = _entries(paths.watchlist)
    assert saved["NVDA"]["tags"] == ["chips", "tech"]  # renamed in place
    assert saved["ASML"]["tags"] == ["chips"]
    assert saved["KO"]["tags"] == ["dividends"]
    # Renaming onto a group that exists merges rather than duplicating.
    assert auth.rename_tag("chips", "tech", paths.watchlist) == 2
    assert _entries(paths.watchlist)["NVDA"]["tags"] == ["tech"]
    # Nothing to do: a blank name, or a name that is already the group's.
    assert auth.rename_tag("tech", "  ", paths.watchlist) == 0
    assert auth.rename_tag("tech", "TECH", paths.watchlist) == 0


def test_dissolving_a_group_keeps_its_tickers_on_the_list(paths):
    """Ungrouping is not un-following."""
    paths.watchlist.write_text(
        "watchlist:\n"
        "  - ticker: NVDA\n    tags: [semis, tech]\n"
        "  - ticker: ASML\n    tags: [semis]\n"
    )
    assert auth.delete_tag("semis", paths.watchlist) == 2
    saved = _entries(paths.watchlist)
    assert list(saved) == ["NVDA", "ASML"]
    assert saved["NVDA"]["tags"] == ["tech"] and saved["ASML"]["tags"] == []


def test_a_tag_group_carries_its_own_rename_and_dissolve(page, paths):
    paths.watchlist.write_text("watchlist:\n  - ticker: NVDA\n    tags: [semis]\n")
    page.run()
    assert page.button(key="wl_grn_tag_semis"), "rename"
    page.text_input(key="wl_gname_tag_semis").set_value("chips").run()
    page.button(key="wl_grn_tag_semis").click().run()
    assert _entries(paths.watchlist)["NVDA"]["tags"] == ["chips"]
    page.button(key="wl_gdel_tag_chips").click().run()
    assert _entries(paths.watchlist)["NVDA"]["tags"] == []
    # Favorites and the ungrouped bucket are not tags: nothing to rename.
    assert not [b for b in page.get("button") if b.key == "wl_grn_none"]


# ------------------------------------------------------------------ phones


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setattr(watchlist_ui, "is_mobile", lambda: True)


def test_a_phone_gets_controls_per_holding_instead_of_a_panning_grid(
    page, paths, phone
):
    paths.watchlist.write_text(
        "watchlist:\n  - ticker: NVDA\n    name: Nvidia\n    tags: [semis]\n"
    )
    page.run()
    body = _html(page)
    assert 'class="wl-m-s">NVDA<' in body and "<span>semis</span>" in body
    # The star writes on the tap, and the row's popover carries the rest.
    page.button(key="wl_fav_NVDA").click().run()
    assert _entries(paths.watchlist)["NVDA"]["favorite"] is True
    page.multiselect(key="wl_mtags_NVDA").set_value(["semis", "ai"]).run()
    assert _entries(paths.watchlist)["NVDA"]["tags"] == ["semis", "ai"]
    page.number_input(key="wl_msh_NVDA").set_value(8.0).run()
    assert _entries(paths.watchlist)["NVDA"]["shares"] == 8.0
    page.button(key="wl_mdel_NVDA").click().run()
    assert not _entries(paths.watchlist)


def test_the_phone_list_stops_at_its_cap_and_says_so(page, paths, phone, monkeypatch):
    """One control row per holding is five widgets; a 200-name list on a phone
    is not a layout, it is a stall. Past the cap the list asks for a filter."""
    monkeypatch.setattr(watchlist_ui, "MOBILE_ROWS", 2)
    paths.watchlist.write_text(
        "watchlist:\n" + "".join(f"  - ticker: T{i}\n" for i in range(5))
    )
    page.run()
    body = _html(page)
    assert 'class="wl-m-s">T1<' in body and 'class="wl-m-s">T3<' not in body
    assert "3 more in this group" in body


# ---------------------------------------------------------------- helpers


def load_watchlist_from(text: str):
    """Parse an indented YAML literal into holdings (via a temp file)."""
    import tempfile
    import textwrap
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "watchlist.yaml"
        p.write_text(textwrap.dedent(text))
        return load_watchlist(p)
