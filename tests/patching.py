"""Patch a name on a split package everywhere the package binds it.

The chat engine, the API loaders and the import routes are packages whose
`__init__` re-exports its leaves, and the leaves import each other's names. So
a patch on the package alone misses a call made inside a leaf (`chain` calling
`attempts`), and a patch on the owner alone misses the package, which other
modules call through. These set the name on every module that binds it.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import pytest

from stocks.api import loaders
from stocks.api.routes import import_statement
from stocks.chat import engine


def _modules(package: ModuleType) -> list[ModuleType]:
    return [package] + [
        importlib.import_module(f"{package.__name__}.{m.name}")
        for m in pkgutil.iter_modules(package.__path__)
    ]


_ENGINE = _modules(engine)
_LOADERS = _modules(loaders)
_IMPORT = _modules(import_statement)


def _patch(
    modules: list[ModuleType], monkeypatch: pytest.MonkeyPatch, name: str, value: object
) -> None:
    bound = [m for m in modules if name in vars(m)]
    assert bound, f"{modules[0].__name__} binds no {name!r}"
    for m in bound:
        monkeypatch.setattr(m, name, value)


def patch_engine(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    _patch(_ENGINE, monkeypatch, name, value)


def patch_loaders(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    _patch(_LOADERS, monkeypatch, name, value)


def patch_import(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    _patch(_IMPORT, monkeypatch, name, value)
