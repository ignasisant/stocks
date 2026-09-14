"""The watchlist as a working surface — search to add, tag groups, live saves.

The Profile tab used to be one `st.data_editor` behind a Save button: adding a
symbol meant typing it from memory into a blank row, a tag group was a
comma-separated string, a favorite was a checkbox that did nothing until Save,
and on a phone seven columns panned sideways. This module replaces that with
the three things the list is actually for:

* **Find and add** — the same tiers the top-bar picker searches (this account's
  list, coins, funds, the SEC company map, worldwide Yahoo), so a symbol is
  added by picking it, with its real name, rather than spelled by hand.
* **Group** — tags are the app's grouping primitive (Overview renders one
  expander per tag, the picker matches them), so they are a multiselect of the
  groups that exist, the list can be grouped by them, and a group can be
  renamed or dissolved from its own header.
* **Save itself** — every edit writes through the per-ticker mutators in
  `stocks.web.auth` the moment it is made, which is what the rest of the
  Profile page already promises in its "changes save instantly" hint.

Per-ticker mutators, not `save_watchlist_entries`: the list renders in groups,
and rewriting the whole YAML from one group's rows would delete every holding
outside it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from stocks.config import Holding, load_watchlist
from stocks.web import auth, css, search
from stocks.web.ds import is_mobile
from stocks.web.i18n import t as tr
from stocks.web.logos import logo
from stocks.web.markup import esc, slug

# Session keys for this surface's controls. Prefixed so the Profile page's
# other tabs (and the tour, which seeds session state) never collide.
Q = "wl_q"  # the adder's query
ADD_TAGS = "wl_add_tags"  # groups a newly added symbol lands in
ADD_FAV = "wl_add_fav"  # whether it lands starred
FILTER = "wl_filter"  # free-text filter over the list
TAG_FILTER = "wl_tag_filter"  # keep only these groups
GROUP_BY = "wl_group_by"  # "tags" | "favorites" | "flat"

GROUP_MODES = ("tags", "favorites", "flat")

# Which catalog a candidate came from, as an icon: the tier is the difference
# between "you already follow this" and "Yahoo has never heard of it".
_KIND_ICONS = {
    "watch": "check_circle",
    "crypto": "currency_bitcoin",
    "fund": "donut_small",
    "sec": "business",
    "world": "public",
    "raw": "help",
}

# Phones render one control row per holding instead of a grid, so a 200-name
# watchlist would be a thousand widgets. Past this the list asks for a filter.
MOBILE_ROWS = 40

_CSS = """
/* ------------------------------------------------------------ the adder */
.wl-hint { padding: 0 24px; font-size: var(--ag-fs-sm); color: var(--ag-text-muted); }
/* Both cards are `pcard_` blocks, so the Profile page's own rule zeroes their
   padding and gap (each row carries its own). Put the gap back at that rule's
   specificity — this stylesheet is injected after it, so source order wins. */
[data-testid="stMainBlockContainer"]
  [data-testid="stVerticalBlock"][class*="st-key-pcard_wl"] {
  gap: 12px; padding-bottom: 18px;
}
[class*="st-key-wl_add_ctl"] { padding: 0 24px; gap: 10px; align-items: flex-end; }
[class*="st-key-wl_res"] { padding: 0 24px; gap: 6px; }
/* A candidate is one full-width row: symbol, name, tier. Left-aligned, so a
   list of them reads as a list rather than a row of centered buttons. */
[class*="st-key-wl_res"] .stButton button { justify-content: flex-start; }
[class*="st-key-wl_res"] .stButton button p { text-align: left; }
/* ---------------------------------------------------------- group header */
.wl-gh {
  display: flex; align-items: center; gap: 10px; min-width: 0;
  padding: 2px 0;
}
.wl-gt {
  font-size: var(--ag-fs-md); font-weight: 600; color: var(--ag-text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.wl-gc {
  border-radius: var(--ag-radius-pill); padding: 1px 8px;
  background: var(--ag-surface-page); border: 1px solid var(--ag-border);
  font-size: var(--ag-fs-xs); font-weight: 600; color: var(--ag-text-muted);
}
[class*="st-key-wl_ghead"] { padding: 14px 24px 0; align-items: center; }
[class*="st-key-wl_ghead"] > [data-testid="stElementContainer"]:first-child {
  flex: 1 1 auto; min-width: 0;
}
[class*="st-key-wl_tools"] { padding: 4px 24px 0; gap: 12px; align-items: flex-end; }
[class*="st-key-wl_tools"] .stTextInput,
[class*="st-key-wl_tools"] .stMultiSelect { min-width: 0; }
[class*="st-key-wl_grid"] { padding: 8px 24px 4px; }
[class*="st-key-wl_foot"] { padding: 14px 24px; gap: 10px; }
/* ----------------------------------------------------------- phone rows */
[class*="st-key-wl_row"] {
  padding: 10px 16px; gap: 8px; align-items: center; position: relative;
}
[class*="st-key-wl_row"]::before {
  content: ""; position: absolute; left: 16px; right: 16px; top: 0;
  height: 1px; background: var(--ag-border);
}
[class*="st-key-wl_row"] > [data-testid="stElementContainer"]:first-child {
  flex: 1 1 auto; min-width: 0;
}
[class*="st-key-wl_row"] .stButton button,
[class*="st-key-wl_row"] .stPopover button { padding: 4px 8px; }
.wl-m { display: flex; align-items: center; gap: 10px; min-width: 0; }
.wl-m img {
  width: 26px; height: 26px; flex: 0 0 auto; border-radius: 6px;
  background: var(--ag-surface-page); object-fit: contain;
}
.wl-m-t { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.wl-m-s {
  font-family: "Martian Mono", monospace; font-size: var(--ag-fs-sm);
  font-weight: 600; color: var(--ag-text-primary);
}
.wl-m-n {
  font-size: var(--ag-fs-xs); color: var(--ag-text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.wl-m-g { display: flex; flex-wrap: wrap; gap: 4px; }
.wl-m-g span {
  border-radius: var(--ag-radius-pill); padding: 0 7px;
  background: var(--ag-purple-900); color: var(--ag-purple-400);
  font-size: var(--ag-fs-2xs); font-weight: 600;
}
@media (max-width: 640px) {
  .wl-hint, [class*="st-key-wl_add_ctl"], [class*="st-key-wl_res"],
  [class*="st-key-wl_ghead"], [class*="st-key-wl_tools"],
  [class*="st-key-wl_foot"] { padding-left: 16px; padding-right: 16px; }
  [class*="st-key-wl_add_ctl"] { flex-wrap: wrap; }
}
"""


# --------------------------------------------------------------- utilities


def _as_list(value) -> list[str]:
    """A tags cell as a clean list — the grid hands back lists, tuples,
    numpy arrays or NaN depending on how the row was edited."""
    if value is None or isinstance(value, float):  # NaN is the empty cell
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return [str(v).strip() for v in list(value) if str(v).strip()]


def _num(value) -> float | None:
    """A number cell as a float, or None for blank/NaN."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matches(h: Holding, needle: str) -> bool:
    """Whether a holding answers the list's free-text filter."""
    if not needle:
        return True
    n = needle.strip().upper()
    return (
        n in h.ticker.upper()
        or n in (h.name or "").upper()
        or any(n in t.upper() for t in h.tags)
    )


def groups(
    holdings: list[Holding], mode: str
) -> list[tuple[str, str, list[Holding], str | None]]:
    """The list split into sections: `(id, label, rows, tag)` each.

    `tag` is the group's own tag when the section IS a tag group — that is
    what lets its header carry rename/dissolve — and None for the buckets that
    are not (favorites, ungrouped, the flat list).

    Tag mode puts favorites first (they are the group the app itself treats as
    one, and Overview renders them first too), then every tag alphabetically,
    then whatever carries neither. A ticker in two tags appears in both, the
    same way Overview groups it.
    """
    if mode == "flat":
        return [("all", tr("watchlist.g_all"), list(holdings), None)]
    favs = [h for h in holdings if h.favorite]
    out: list[tuple[str, str, list[Holding], str | None]] = []
    if favs:
        out.append(("fav", tr("watchlist.g_favorites"), favs, None))
    if mode == "favorites":
        rest = [h for h in holdings if not h.favorite]
        if rest:
            out.append(("rest", tr("watchlist.g_rest"), rest, None))
        return out
    by_tag: dict[str, tuple[str, list[Holding]]] = {}
    for h in holdings:
        for tag in h.tags:
            label, rows = by_tag.setdefault(tag.lower(), (tag, []))
            rows.append(h)
    for key in sorted(by_tag):
        label, rows = by_tag[key]
        out.append((f"tag_{slug(label)}", label, rows, label))
    loose = [h for h in holdings if not h.tags and not h.favorite]
    if loose:
        out.append(("none", tr("watchlist.g_untagged"), loose, None))
    return out


def _ed_key(gid: str, tickers: tuple[str, ...]) -> str:
    """A grid key that changes with the group's membership.

    `st.data_editor` keeps its edits as a diff against the frame it was given,
    addressed by row position. Starring a name moves it between groups, so the
    next run's frame is a different set of rows — replaying the old diff onto
    it would apply one ticker's edit to another. A membership-derived key
    hands that run a brand-new widget with no diff instead.
    """
    digest = hashlib.md5("|".join(tickers).encode()).hexdigest()[:8]
    return f"wl_ed_{gid}_{digest}"


# ------------------------------------------------------------------- adder


def _add(ticker: str, name: str, path: Path) -> None:
    """Put a candidate on the list, with the groups and star the adder holds."""
    t = ticker.strip().upper()
    auth.add_entry(t, name, path)
    tags = _as_list(st.session_state.get(ADD_TAGS))
    if tags:
        existing = next(
            (h.tags for h in load_watchlist(path) if h.ticker.upper() == t), []
        )
        auth.set_tags(t, list(existing) + tags, path)
    if st.session_state.get(ADD_FAV):
        auth.set_favorite(t, True, path)
    st.session_state[Q] = ""  # a taken offer clears the query, like the picker
    st.toast(tr("watchlist.added", ticker=t), icon=":material/playlist_add_check:")


def add_card(container, path: Path) -> None:
    """Search every catalog and add what comes back — the tab's first card."""
    card = container.container(border=True, key="pcard_wladd")
    card.html(
        _card_head(tr("watchlist.add_title"), tr("watchlist.add_sub"))
    )
    ctl = card.container(horizontal=not is_mobile(), key="wl_add_ctl")
    query = ctl.text_input(
        tr("watchlist.add_title"),
        key=Q,
        placeholder=tr("watchlist.add_placeholder"),
        label_visibility="collapsed",
        width="stretch",
    )
    ctl.multiselect(
        tr("watchlist.add_groups"),
        options=auth.all_tags(path),
        key=ADD_TAGS,
        accept_new_options=True,
        placeholder=tr("watchlist.add_groups_ph"),
        help=tr("watchlist.add_groups_help"),
        label_visibility="collapsed",
        width="stretch" if is_mobile() else 260,
    )
    ctl.checkbox(tr("watchlist.add_fav"), key=ADD_FAV)

    if not (query or "").strip():
        card.html(f'<div class="wl-hint">{esc(tr("watchlist.add_hint"))}</div>')
        return
    rows = search.add_candidates(query, path=path)
    if not rows:
        card.html(f'<div class="wl-hint">{esc(tr("watchlist.add_none"))}</div>')
        return
    res = card.container(key="wl_res")
    for row in rows:
        t, name, kind = row["ticker"], row["name"], row["kind"]
        icon = f":material/{_KIND_ICONS.get(kind, 'help')}:"
        tail = f" — {name}" if name else ""
        label = f"{icon} **{t}**{tail}"
        if row["listed"]:
            res.button(
                label,
                key=f"wl_add_{slug(t)}",
                disabled=True,
                help=tr("watchlist.add_listed"),
                width="stretch",
            )
            continue
        res.button(
            label,
            key=f"wl_add_{slug(t)}",
            help=tr(f"watchlist.kind_{kind}"),
            on_click=_add,
            args=(t, name, path),
            width="stretch",
        )


# -------------------------------------------------------------------- grid


def _grid(container, gid: str, rows: list[Holding], path: Path) -> None:
    """One group as an editable grid, saving every edit as it is made."""
    tickers = tuple(h.ticker for h in rows)
    key = _ed_key(gid, tickers)
    before = [
        {
            "logo": logo(h.ticker),
            "ticker": h.ticker,
            "name": h.name or "",
            "favorite": bool(h.favorite),
            "tags": list(h.tags),
            "shares": h.shares or None,
            "cost": h.cost,
            "actions": [
                f":material/open_in_new: {tr('watchlist.act_open')}",
                f":material/delete: {tr('watchlist.act_remove')}",
            ],
        }
        for h in rows
    ]
    frame = pd.DataFrame(
        before,
        columns=[
            "logo", "ticker", "name", "favorite", "tags",
            "shares", "cost", "actions",
        ],
    )
    edited = container.container(key=f"wl_grid_{gid}").data_editor(
        frame,
        key=key,
        num_rows="fixed",  # rows arrive through the adder, which resolves names
        hide_index=True,
        width="stretch",
        # The ticker is the row's identity (every mutator addresses it), and
        # the logo is derived. Renaming a symbol is a remove plus an add.
        disabled=("logo", "ticker"),
        column_order=(
            ("ticker", "favorite", "tags", "shares", "cost", "actions")
            if is_mobile()
            else None
        ),
        column_config={
            "logo": st.column_config.ImageColumn("", width=40),
            "ticker": st.column_config.TextColumn(
                tr("watchlist.col_ticker"), pinned=True
            ),
            "name": st.column_config.TextColumn(tr("watchlist.col_name")),
            "favorite": st.column_config.CheckboxColumn(
                tr("watchlist.col_favorite"), default=False
            ),
            "tags": st.column_config.MultiselectColumn(
                tr("watchlist.col_tags"),
                help=tr("watchlist.col_tags_help"),
                options=auth.all_tags(path),
                accept_new_options=True,
                color="auto",
                width="medium",
            ),
            "shares": st.column_config.NumberColumn(
                tr("watchlist.col_shares"), min_value=0.0
            ),
            "cost": st.column_config.NumberColumn(
                tr("watchlist.col_cost"),
                min_value=0.0,
                help=tr("watchlist.col_cost_help"),
            ),
            "actions": st.column_config.ButtonColumn(
                tr("watchlist.col_actions"),
                key=f"{key}_act",
                on_click=_row_action,
                args=(f"{key}_act", tickers, path),
                help=tr("watchlist.col_actions_help"),
            ),
        },
    )
    if _apply(before, edited.to_dict("records"), path):
        st.rerun()


def _row_action(state_key: str, tickers: tuple[str, ...], path: Path) -> None:
    """The grid's per-row button: open the ticker page, or drop the row.

    Which button was pressed is read off the icon rather than the localized
    text — the label is translated, `:material/delete:` is not.
    """
    click = st.session_state.get(state_key) or {}
    try:
        ticker = tickers[int(click["row"])]
    except (KeyError, IndexError, TypeError, ValueError):
        return
    if "delete" in str(click.get("label", "")):
        auth.remove_entry(ticker, path)
        st.toast(
            tr("watchlist.removed", ticker=ticker), icon=":material/delete:"
        )
        return
    # The picker's own contract (search._go_ticker): set the shared selection
    # and raise "picker_clicked", and app.py switches to the Ticker page on the
    # rerun this callback triggers. A callback is not a place to navigate from.
    st.session_state["picker_selected"] = ticker
    st.session_state["picker_clicked"] = True


def _apply(before: list[dict], after: list[dict], path: Path) -> int:
    """Write back whatever the grid changed; returns how many rows moved.

    Row order and length are the grid's own (`num_rows="fixed"`, ticker
    disabled), so position identifies the holding on both sides.
    """
    changed = 0
    for old, new in zip(before, after, strict=False):
        ticker = old["ticker"]
        touched = False
        if bool(new.get("favorite")) != bool(old["favorite"]):
            auth.set_favorite(ticker, bool(new.get("favorite")), path)
            touched = True
        if _as_list(new.get("tags")) != list(old["tags"]):
            auth.set_tags(ticker, _as_list(new.get("tags")), path)
            touched = True
        name = str(new.get("name") or "").strip()
        if name != (old["name"] or ""):
            auth.set_name(ticker, name, path)
            touched = True
        shares, cost = _num(new.get("shares")), _num(new.get("cost"))
        if shares != _num(old["shares"]) or cost != _num(old["cost"]):
            # None leaves a field alone in set_position; a cleared cell has to
            # arrive as 0, which is what clears it.
            auth.set_position(ticker, shares or 0.0, cost or 0.0, path)
            touched = True
        changed += bool(touched)
    return changed


# ------------------------------------------------------------- phone rows


def _phone_rows(container, rows: list[Holding], path: Path) -> None:
    """One control row per holding: the grid's actions without the panning."""
    for h in rows:
        box = container.container(
            horizontal=True, vertical_alignment="center", key=f"wl_row_{slug(h.ticker)}"
        )
        src = logo(h.ticker)
        img = f'<img src="{esc(src)}" alt="">' if src else ""
        chips = "".join(f"<span>{esc(t)}</span>" for t in h.tags)
        box.html(
            '<div class="wl-m">'
            f"{img}"
            '<div class="wl-m-t">'
            f'<span class="wl-m-s">{esc(h.ticker)}</span>'
            f'<span class="wl-m-n">{esc(h.name or "")}</span>'
            f'<span class="wl-m-g">{chips}</span>'
            "</div></div>"
        )
        box.button(
            ":material/star:" if h.favorite else ":material/star_border:",
            key=f"wl_fav_{slug(h.ticker)}",
            help=tr("watchlist.col_favorite"),
            on_click=_toggle_fav,
            args=(h.ticker, path),
        )
        with box.popover(":material/more_vert:", help=tr("watchlist.row_more")):
            st.multiselect(
                tr("watchlist.col_tags"),
                options=auth.all_tags(path),
                default=list(h.tags),
                key=f"wl_mtags_{slug(h.ticker)}",
                accept_new_options=True,
                placeholder=tr("watchlist.add_groups_ph"),
                on_change=_save_tags,
                args=(h.ticker, f"wl_mtags_{slug(h.ticker)}", path),
            )
            st.number_input(
                tr("watchlist.col_shares"),
                min_value=0.0,
                value=float(h.shares or 0.0),
                key=f"wl_msh_{slug(h.ticker)}",
                on_change=_save_position,
                args=(h.ticker, f"wl_msh_{slug(h.ticker)}", "shares", path),
            )
            st.number_input(
                tr("watchlist.col_cost"),
                min_value=0.0,
                value=float(h.cost or 0.0),
                key=f"wl_mco_{slug(h.ticker)}",
                help=tr("watchlist.col_cost_help"),
                on_change=_save_position,
                args=(h.ticker, f"wl_mco_{slug(h.ticker)}", "cost", path),
            )
            st.button(
                tr("watchlist.act_remove"),
                key=f"wl_mdel_{slug(h.ticker)}",
                icon=":material/delete:",
                on_click=_remove,
                args=(h.ticker, path),
                width="stretch",
            )


def _toggle_fav(ticker: str, path: Path) -> None:
    now = auth.toggle_favorite(ticker, path)
    st.toast(
        tr("watchlist.fav_on" if now else "watchlist.fav_off", ticker=ticker),
        icon=":material/star:",
    )


def _save_tags(ticker: str, key: str, path: Path) -> None:
    auth.set_tags(ticker, _as_list(st.session_state.get(key)), path)


def _save_position(ticker: str, key: str, field: str, path: Path) -> None:
    value = _num(st.session_state.get(key)) or 0.0
    auth.set_position(
        ticker,
        shares=value if field == "shares" else None,
        cost=value if field == "cost" else None,
        path=path,
    )


def _remove(ticker: str, path: Path) -> None:
    auth.remove_entry(ticker, path)
    st.toast(tr("watchlist.removed", ticker=ticker), icon=":material/delete:")


# ------------------------------------------------------------- group header


def _group_head(container, gid: str, label: str, count: int, tag: str | None,
                path: Path) -> None:
    """A section's title and count, plus the group's own rename/dissolve."""
    head = container.container(horizontal=True, key=f"wl_ghead_{gid}")
    head.html(
        '<div class="wl-gh">'
        f'<span class="wl-gt">{esc(label)}</span>'
        f'<span class="wl-gc">{count}</span>'
        "</div>"
    )
    if tag is None:
        return
    with head.popover(
        tr("watchlist.group_manage"), icon=":material/label:"
    ):
        st.caption(tr("watchlist.group_manage_help"))
        new = st.text_input(
            tr("watchlist.group_rename"),
            value=tag,
            key=f"wl_gname_{gid}",
        )
        if st.button(
            tr("watchlist.group_rename_apply"),
            key=f"wl_grn_{gid}",
            icon=":material/edit:",
            width="stretch",
        ):
            n = auth.rename_tag(tag, new, path)
            if n:
                st.toast(
                    tr("watchlist.group_renamed", group=new.strip(), n=n),
                    icon=":material/label:",
                )
                st.rerun()
        if st.button(
            tr("watchlist.group_delete"),
            key=f"wl_gdel_{gid}",
            icon=":material/label_off:",
            width="stretch",
            help=tr("watchlist.group_delete_help"),
        ):
            n = auth.delete_tag(tag, path)
            st.toast(
                tr("watchlist.group_deleted", group=tag, n=n),
                icon=":material/label_off:",
            )
            st.rerun()


# ------------------------------------------------------------------ render


def _card_head(title: str, sub: str = "") -> str:
    """The Profile page's card header strip (same markup, same stylesheet)."""
    parts = [f'<span class="ag-cardtitle">{esc(title)}</span>']
    if sub:
        parts.append(f'<span class="ag-cardsub">{esc(sub)}</span>')
    return f'<div class="ag-cardhead">{"".join(parts)}</div>'


def list_card(container, holdings: list[Holding], path: Path) -> None:
    """Filter, group and edit what is already on the list."""
    card = container.container(border=True, key="pcard_wllist")
    card.html(_card_head(tr("watchlist.list_title"), tr("watchlist.list_sub")))
    tools = card.container(horizontal=not is_mobile(), key="wl_tools")
    needle = tools.text_input(
        tr("watchlist.filter"),
        key=FILTER,
        placeholder=tr("watchlist.filter_ph"),
        label_visibility="collapsed",
        width="stretch",
    )
    keep_tags = tools.multiselect(
        tr("watchlist.tag_filter"),
        options=auth.all_tags(path),
        key=TAG_FILTER,
        placeholder=tr("watchlist.tag_filter_ph"),
        label_visibility="collapsed",
        width="stretch" if is_mobile() else 260,
    )
    mode = tools.segmented_control(
        tr("watchlist.group_by"),
        options=GROUP_MODES,
        format_func=lambda m: tr(f"watchlist.group_{m}"),
        default="tags",
        key=GROUP_BY,
        label_visibility="collapsed",
    ) or "tags"

    keep = {t.lower() for t in keep_tags}
    shown = [
        h
        for h in holdings
        if _matches(h, needle)
        and (not keep or any(t.lower() in keep for t in h.tags))
    ]
    if not shown:
        card.html(f'<div class="wl-hint">{esc(tr("watchlist.no_match"))}</div>')
        return

    for gid, label, rows, tag in groups(shown, mode):
        _group_head(card, gid, label, len(rows), tag, path)
        if is_mobile():
            _phone_rows(card, rows[:MOBILE_ROWS], path)
            if len(rows) > MOBILE_ROWS:
                card.html(
                    f'<div class="wl-hint">'
                    f'{esc(tr("watchlist.mobile_cap", n=len(rows) - MOBILE_ROWS))}'
                    "</div>"
                )
        else:
            _grid(card, gid, rows, path)

    foot = card.container(horizontal=True, vertical_alignment="center", key="wl_foot")
    foot.html(
        f'<div class="wl-hint">{esc(tr("watchlist.count", n=len(holdings)))}</div>'
    )
    with foot.popover(tr("watchlist.how_open"), icon=":material/help_outline:"):
        st.markdown(tr("watchlist.how"))


def render(container, path: Path | None = None) -> None:
    """The whole surface: the adder, then the grouped list.

    Reads the watchlist itself rather than taking the page's copy — every edit
    here writes and reruns, so the rows have to be the ones on disk now.
    """
    p = path or auth.watchlist_path()
    css.inject(_CSS)
    add_card(container, p)
    holdings = load_watchlist(p)
    if holdings:
        list_card(container, holdings, p)
