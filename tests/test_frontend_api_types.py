"""`frontend/app/src/api.gen.ts` is what the API's schema says today.

The file is generated (`npm run gen:api`) and `get()` infers its answers from
it, so a response model changed without regenerating it would leave every page
typed against yesterday's API.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from stocks.api.app import app

APP = Path(__file__).resolve().parents[1] / "frontend" / "app"
SCRIPT = APP / "scripts" / "gen_api_types.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists(), reason="frontend sources not checked out"
)


def _generator():
    spec = importlib.util.spec_from_file_location("gen_api_types", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_types_match_the_schema():
    generator = _generator()
    committed = (APP / "src" / "api.gen.ts").read_text(encoding="utf-8")
    assert committed == generator.render(app.openapi()), (
        "api.gen.ts is stale: run `npm run gen:api` in frontend/app"
    )

