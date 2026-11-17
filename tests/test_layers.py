"""Import layering of `src/stocks`: a package reaches down, never up.

Each top-level package or module has a rank. An import may go to the same
rank or lower; one that climbs has to be listed in `_ALLOWED_UP`, with the
reason it is there. The list is checked both ways, so an edge that is cut
also has to come off it.

Ranks say nothing about two packages of the same rank, or about a listed
climb, importing each other as they load. That loop is a module that only
imports when something else was imported first, so it is checked on its own:
no import a module runs at load time may close a loop through another package.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "stocks"

_RANKS: dict[str, int] = {
    # Foundation: settings, storage, per-account files, text, models, caches.
    **dict.fromkeys(
        (
            "config obs atomic storage secrets_env accounts userstore userprefs"
            " i18n llm baml_client cache cpu_hold frames formatting fuzzy jsonsafe"
            " schemas revocation session devices progress memstat watchlist search"
            " navigation learn backup ratelimit"
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
    ("chat/guide_ai.py", "web"): "the guide answers from the release registry",
    ("chat/knowledge.py", "web"): "a cited doc opens the tour step's page; lazy",
    ("chat/book.py", "web"): "a first typed trade raises the newcomer's tour; lazy",
    ("notify/weekly_email.py", "web"): "DS tokens, and the onboarding gaps",
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


def _module(path: Path) -> str:
    parts = ("stocks", *path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _at_load(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """The imports a module runs as it loads: everything outside a function
    body and outside `if TYPE_CHECKING:`."""
    found: list[ast.Import | ast.ImportFrom] = []
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.append(node)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        elif isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            stack.extend(node.orelse)
        else:
            stack.extend(ast.iter_child_nodes(node))
    return found


def _load_graph() -> dict[str, set[str]]:
    """module → the modules its load imports, parent packages included: a
    `from stocks.api import holds` runs `stocks/api/__init__.py` first."""
    paths = {_module(p): p for p in ROOT.rglob("*.py") if "baml_client" not in p.parts}

    def known(name: str) -> set[str]:
        parts = name.split(".")
        return {
            ".".join(parts[:i])
            for i in range(2, len(parts) + 1)
            if ".".join(parts[:i]) in paths
        }

    graph: dict[str, set[str]] = {}
    for module, path in paths.items():
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        edges: set[str] = set()
        for node in _at_load(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                base = node.module or ""
                if node.level:
                    up = package.split(".")
                    up = up[: len(up) - (node.level - 1)]
                    base = ".".join([*up, *([node.module] if node.module else [])])
                names = [base, *(f"{base}.{a.name}" for a in node.names)]
            for name in names:
                edges |= known(name)
        graph[module] = edges - {module}
    return graph


def _loops(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan: every group of modules that reach each other."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = len(index)
        stack.append(root)
        on.add(root)
        while work:
            node, edges = work[-1]
            for nxt in edges:
                if nxt not in index:
                    index[nxt] = low[nxt] = len(index)
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(graph[nxt])))
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    group: list[str] = []
                    while True:
                        member = stack.pop()
                        on.discard(member)
                        group.append(member)
                        if member == node:
                            break
                    if len(group) > 1:
                        out.append(sorted(group))
    return out


def test_no_load_time_loop_crosses_a_package():
    crossing = [
        loop
        for loop in _loops(_load_graph())
        if len({_package(m) or "stocks" for m in loop}) > 1
    ]
    assert not crossing, f"modules that import each other as they load: {crossing}"
