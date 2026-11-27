"""The public FIFO calculator: its maths against the engine, its page against the CSP.

`calculator.js` re-implements the savings scale and FIFO in the browser so a
statement never leaves it; the scale it uses is the engine's own, handed over
as data, and these tests pin the two together.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from stocks.portfolio.tax import es
from stocks.web import calculator, csp, guides

BASE = "https://topstocks.example"
LANGS = tuple(guides.PATHS)
JS = Path(calculator.__file__).with_name("calculator.js")

node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(body: str):
    script = (
        f"const c = require({json.dumps(str(JS))});\n"
        f"const scales = {json.dumps(calculator._scales())};\n"
        f"const out = (() => {{ {body} }})();\n"
        "console.log(JSON.stringify(out));"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          check=True)
    return json.loads(done.stdout)


@node
@pytest.mark.parametrize("year", [2023, 2025, 2026])
@pytest.mark.parametrize("base", [0, 500, 6000, 12345.67, 50000, 250000, 400000])
def test_tax_matches_the_engine(year, base):
    got = run_js(f"return c.progressiveTax({base}, c.bracketsFor(scales, {year}));")
    assert got == pytest.approx(float(es.tax_on_savings_base(base, year)), abs=0.01)


@node
def test_fifo_consumes_oldest_lot_first_and_holds_back_a_repurchased_loss():
    rows = calculator._EXAMPLE
    got = run_js(
        f"const p = c.parseRows({json.dumps(rows)}); "
        "if (p.errors.length) return p.errors; "
        "return c.compute(p.rows, 2026, scales);"
    )
    t = got["totals"]
    assert got["errors"] == []
    assert t["losses"] == pytest.approx(-622.2, abs=0.01)
    assert t["deferred"] == pytest.approx(-200.92, abs=0.01)
    assert t["net"] == pytest.approx(-421.28, abs=0.01)
    assert t["tax"] == 0 and t["carry"] == pytest.approx(421.28, abs=0.01)
    assert [p["qty"] for p in got["pieces"]] == [10, 2]


@node
def test_selling_more_than_held_is_reported_not_invented():
    got = run_js(
        "const p = c.parseRows('2026-01-02;buy;X;1;10\\n2026-02-02;sell;X;3;12'); "
        "return c.compute(p.rows, 2026, scales).errors;"
    )
    assert got and got[0]["code"] == "oversell" and got[0]["missing"] == 2


@node
def test_bad_lines_are_named_by_number():
    got = run_js("return c.parseRows('2026-01-02;buy;X;1;10\\nnonsense here').errors;")
    assert [e["line"] for e in got] == [2]


@pytest.mark.parametrize("lang", LANGS)
def test_page_is_self_contained_and_csp_covers_its_script(lang):
    doc = calculator.page(lang, BASE)
    policy = csp.for_document(doc, fonts=False)
    assert "'unsafe-inline'" not in policy
    scripts = re.findall(r"<script>(.*?)</script>", doc, re.S)
    assert len(scripts) == 1
    for tag in ("fetch(", "XMLHttpRequest", "sendBeacon", "innerHTML"):
        assert tag not in scripts[0]
    assert "script-src 'self' 'sha256-" in policy
    cfg = json.loads(re.search(r'id="calc-cfg">(.*?)</script>', doc, re.S).group(1))
    assert set(cfg["t"]) == set(calculator._COPY["es"]["t"])
    assert cfg["scales"]["2025"][-1] == [None, 0.30]


@pytest.mark.parametrize("lang", LANGS)
def test_page_seo(lang):
    doc = calculator.page(lang, BASE)
    c = calculator._COPY[lang]
    assert len(c["desc"]) <= guides.DESCRIPTION_MAX
    assert f'<link rel="canonical" href="{BASE}{calculator.path(lang)}">' in doc
    for code in LANGS:
        assert f'hreflang="{code}" href="{BASE}{calculator.path(code)}"' in doc
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', doc, re.S)
    ld = json.loads(block.group(1))
    assert {d["@type"] for d in ld} == {"WebApplication", "BreadcrumbList"}


def test_copy_languages_have_the_same_keys():
    keys = {k: set(v) for k, v in calculator._COPY.items()}
    assert keys["es"] == keys["en"] == keys["it"]
    assert all(len(v["t"]["cols"]) == 8 for v in calculator._COPY.values())


def test_slug_lookup_is_per_language():
    assert calculator.find("calculadora-fifo", "es")
    assert not calculator.find("calculadora-fifo", "en")
