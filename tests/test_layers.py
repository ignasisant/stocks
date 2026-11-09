"""Import layering of `src/stocks`: a package reaches down, never up.

Each top-level package or module has a rank. An import may go to the same
rank or lower; one that climbs has to be listed in `_ALLOWED_UP`, with the
reason it is there. The list is checked both ways, so an edge that is cut
also has to come off it.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "stocks"

_RANKS: dict[str, int] = {
    # Foundation: settings, storage, per-account files, text, models, caches.
    **dict.fromkeys(
        (
            "config obs atomic storage secrets_env accounts userstore userprefs"
            " i18n llm baml_client cache frames formatting fuzzy jsonsafe schemas"
            " revocation session devices progress memstat watchlist search"
            " navigation learn backup"
        ).split(),
        0,
    ),
    # Market data, statements and bank feeds.
    "data": 1,
    "bank": 1,
    # The ledger and what a symbol is.
    "portfolio": 2,
    "identity": 2,
    "analysis": 3,
    # Cached loads a screen, the chat and the jobs share.
    "loaders": 4,
    # The app: what the user reads and is told.
    "chat": 5,
    "notify": 5,
    "views": 5,
    # Adapters onto HTTP, MCP, the shell and the terminal.
    "api": 6,
    "connector": 6,
    "web": 6,
    "cli": 6,
    "loadtest": 6,
    "logs_query": 6,
}

# (file under src/stocks, package it climbs to): why it is allowed.
_ALLOWED_UP: dict[tuple[str, str], str] = {
    ("chat/toolbox.py", "api"): (
        "the chat reads the ticker page through its route readers, so both "
        "answer with the same figures; lazy"
    ),
    ("chat/guide_ai.py", "web"): "the guide answers from the release registry",
    ("chat/knowledge.py", "web"): "a cited doc opens the tour step's page; lazy",
    ("notify/weekly_email.py", "web"): "DS tokens, and the onboarding gaps",
    ("views/review.py", "api"): "holds Cloud Run CPU while the review runs",
    ("views/briefing.py", "api"): "holds Cloud Run CPU while the briefing runs",
    ("loaders/market.py", "chat"): "caches the chat's market snapshot; lazy",
    ("loaders/assets.py", "chat"): "caches the chat's what-if replay; lazy",
    ("schemas/prefs.py", "notify"): "validates a push time with its parser; lazy",
}


def _package(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "stocks" or len(parts) < 2:
        return None
    return parts[1]


def _climbs() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        own = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        if own not in _RANKS:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module == "stocks":
                    targets = [f"stocks.{a.name}" for a in node.names]
                else:
                    targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            else:
                continue
            for target in targets:
                pkg = _package(target)
                if pkg and pkg != own and _RANKS.get(pkg, 0) > _RANKS[own]:
                    found.add((rel.as_posix(), pkg))
    return found


def test_every_package_has_a_rank():
    names = {
        p.stem
        for p in ROOT.iterdir()
        if not p.name.startswith("__") and (p.suffix == ".py" or p.is_dir())
    }
    assert names <= _RANKS.keys(), f"no rank for {sorted(names - _RANKS.keys())}"


def test_imports_never_climb_unless_listed():
    climbs = _climbs()
    new = climbs - _ALLOWED_UP.keys()
    assert not new, f"import climbs a layer: {sorted(new)}"
    stale = _ALLOWED_UP.keys() - climbs
    assert not stale, f"edge gone, drop it from _ALLOWED_UP: {sorted(stale)}"
