"""Editing one account's watchlist.yaml, without a UI framework.

Split out of `web.auth` for the same reason `stocks.accounts` was: the HTTP API
runs in an ASGI worker with no Streamlit session to resolve a path from, and
two implementations of "what a watchlist edit means" would drift. The pages
still reach these through `auth.`, which binds the session's own path and the
app's own bucket-failure handling.

Two rules hold across everything here:

* **An edit preserves what it does not name.** Every mutator is a read-modify-
  write of the whole YAML — other entries, alert rules and the top-level alias
  map ride through untouched. Rewriting the file from a narrower model is how
  a rule nobody was editing disappears.
* **Naming a ticker is enough to list it.** Favouriting or tagging a symbol
  that is not on the watchlist adds it, because that is what the reader meant.
  Removal is the one exception: dropping a symbol that was never listed is a
  no-op, not an add followed by a delete.

`persist` is injected rather than imported at the call site so the web layer
can keep its own answer to a bucket outage (a toast, not an exception) while a
headless caller gets the plain one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from stocks import storage
from stocks.config import load_watchlist, yaml_dump, yaml_load

# `persist` defaults to None and is resolved at call time rather than being
# bound as a default argument. A default captures the function object at import,
# which makes the bucket write unobservable to anything that swaps
# `storage.persist` afterwards — including the test that checks every write
# actually reaches the bucket. Late lookup keeps injection working and keeps
# the invariant checkable.
Persist = Callable[[Path], None]


def _persist(persist: Persist | None, path: Path) -> None:
    (persist or storage.persist)(path)


def clean_tags(tags) -> list[str]:
    """Normalize a tag list: strip, drop empties, de-dup case-insensitively
    (first spelling wins), keep entry order."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        tag = str(tag).strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def update_entry(
    path: Path, ticker: str, mutate, *, persist: Persist | None = None
) -> dict:
    """Apply `mutate(entry)` to a ticker's entry, creating it when unlisted.

    Everything else in the YAML — other entries, alerts, aliases — is preserved.
    Returns the entry as it was left.
    """
    raw = yaml_load(path.read_text()) if path.exists() else {}
    items: list[dict] = raw.get("watchlist") or []
    symbol = ticker.strip().upper()
    entry = next(
        (i for i in items if str(i.get("ticker", "")).upper() == symbol), None
    )
    if entry is None:
        entry = {"ticker": symbol}
        items.append(entry)
    mutate(entry)
    raw["watchlist"] = items
    path.write_text(yaml_dump(raw))
    _persist(persist, path)
    return entry


def toggle_favorite(
    path: Path, ticker: str, *, persist: Persist | None = None
) -> bool:
    """Flip a ticker's favorite flag; returns the new state."""

    def _flip(entry: dict) -> None:
        if entry.get("favorite"):
            entry.pop("favorite", None)
        else:
            entry["favorite"] = True

    return bool(update_entry(path, ticker, _flip, persist=persist).get("favorite"))


def set_favorite(
    path: Path, ticker: str, value: bool, *, persist: Persist | None = None
) -> None:
    """Set (not flip) a ticker's favorite flag — chat actions and HTTP clients
    both need idempotent semantics: "add to favorites" on an already-favorited
    ticker is a no-op, not a removal."""

    def _set(entry: dict) -> None:
        if value:
            entry["favorite"] = True
        else:
            entry.pop("favorite", None)

    update_entry(path, ticker, _set, persist=persist)


def set_tags(
    path: Path, ticker: str, tags: list[str], *, persist: Persist | None = None
) -> list[str]:
    """Replace a ticker's tags; an empty list removes the key entirely."""
    clean = clean_tags(tags)

    def _set(entry: dict) -> None:
        if clean:
            entry["tags"] = clean
        else:
            entry.pop("tags", None)

    update_entry(path, ticker, _set, persist=persist)
    return clean


def set_name(
    path: Path, ticker: str, name: str, *, persist: Persist | None = None
) -> None:
    """Set (or clear, with an empty string) a ticker's display label."""

    def _set(entry: dict) -> None:
        if name.strip():
            entry["name"] = name.strip()
        else:
            entry.pop("name", None)

    update_entry(path, ticker, _set, persist=persist)


def set_alerts(
    path: Path, ticker: str, alerts: list[dict], *, persist: Persist | None = None
) -> None:
    """Replace a ticker's alert rules; an empty list removes the key entirely.

    Each dict is the YAML shape `config.Alert` accepts: {"type": …, and one of
    price/pct/level, optional window}. None values are dropped so the YAML stays
    clean.
    """
    clean = [
        {k: v for k, v in alert.items() if v is not None and v != ""}
        for alert in alerts
    ]
    clean = [alert for alert in clean if alert.get("type")]

    def _set(entry: dict) -> None:
        if clean:
            entry["alerts"] = clean
        else:
            entry.pop("alerts", None)

    update_entry(path, ticker, _set, persist=persist)


def set_position(
    path: Path,
    ticker: str,
    shares: float | None = None,
    cost: float | None = None,
    *,
    persist: Persist | None = None,
) -> None:
    """Set a ticker's held quantity and/or average cost.

    None leaves that field alone, 0 clears it — so "I hold 12 shares" can be
    recorded without inventing a cost basis. This is the watchlist fallback the
    app values when no ledger exists; an imported ledger still wins.
    """

    def _set(entry: dict) -> None:
        for field, value in (("shares", shares), ("cost", cost)):
            if value is None:
                continue
            if value:
                entry[field] = float(value)
            else:
                entry.pop(field, None)

    update_entry(path, ticker, _set, persist=persist)


def add_entry(
    path: Path, ticker: str, name: str = "", *, persist: Persist | None = None
) -> None:
    """Put a ticker on the watchlist (a no-op when it is already there).

    `name` only fills a blank one — a symbol the reader already labelled keeps
    its label when something re-adds it.
    """

    def _set(entry: dict) -> None:
        if name.strip() and not entry.get("name"):
            entry["name"] = name.strip()

    update_entry(path, ticker, _set, persist=persist)


def remove_entry(
    path: Path, ticker: str, *, persist: Persist | None = None
) -> bool:
    """Drop a ticker from the watchlist, alerts and tags with it.

    Unlike the other mutators this never creates the entry: removing a symbol
    that is not listed is a no-op. Returns whether anything was actually
    removed, which is what lets a caller answer 404 instead of pretending.
    """
    if not path.exists():
        return False
    raw = yaml_load(path.read_text())
    items = raw.get("watchlist") or []
    symbol = ticker.strip().upper()
    kept = [i for i in items if str(i.get("ticker", "")).upper() != symbol]
    if len(kept) == len(items):
        return False
    raw["watchlist"] = kept
    path.write_text(yaml_dump(raw))
    _persist(persist, path)
    return True


def all_tags(path: Path) -> list[str]:
    """Every tag used on this account's watchlist, sorted case-insensitively."""
    seen: dict[str, str] = {}
    for holding in load_watchlist(path):
        for tag in holding.tags:
            seen.setdefault(tag.lower(), tag)
    return sorted(seen.values(), key=str.lower)


def rename_tag(
    path: Path, old: str, new: str, *, persist: Persist | None = None
) -> int:
    """Rename a tag group across every holding that carries it.

    A group only exists as the tag repeated on its members, so renaming one is a
    rewrite of each member's tag list — in place, so the group keeps its
    position in a holding's tags. Merging into an existing group (renaming
    "semis" to "tech" when both exist) de-dups through `clean_tags`. Returns how
    many holdings were touched; 0 when `new` is blank or nothing carries `old`.
    """
    new = new.strip()
    if not new or new.lower() == old.strip().lower():
        return 0
    touched = 0
    for holding in load_watchlist(path):
        if not any(t.lower() == old.lower() for t in holding.tags):
            continue
        set_tags(
            path,
            holding.ticker,
            [new if t.lower() == old.lower() else t for t in holding.tags],
            persist=persist,
        )
        touched += 1
    return touched


def delete_tag(path: Path, tag: str, *, persist: Persist | None = None) -> int:
    """Drop a tag group, keeping its members on the watchlist.

    Ungrouping is not un-following: the tickers stay listed, they just stop
    being a group. Returns how many holdings lost the tag.
    """
    touched = 0
    for holding in load_watchlist(path):
        if not any(t.lower() == tag.lower() for t in holding.tags):
            continue
        set_tags(
            path,
            holding.ticker,
            [t for t in holding.tags if t.lower() != tag.lower()],
            persist=persist,
        )
        touched += 1
    return touched
