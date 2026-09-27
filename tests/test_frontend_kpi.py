"""The KPI tile and the delta pill are drawn in one place: `frontend/app/src/ui/`.

Every page used to draw its own — Home on the page ground, Portfolio sunken
with an uppercase label, the ticker page two ways, the earnings dialog and the
Pulse book two more — so the same figure read differently depending on the
screen. `ui/Kpi.tsx` is now the tile, its grid, its chip and its "?", and
`ui/ui.css` the only stylesheet that styles them. This fails when a page grows
its own again, which is how the six happened: one at a time, each reasonable.

Parsed as text on purpose: a selector is a selector whatever file it is in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "frontend" / "app" / "src"
SHARED = SRC / "ui"

# `.pf-kpi`, `.hm-kpis`, `.tk-kpi-value`, `.earn-tile`, `.tk-tiles`…
# The shared `ag-` classes are exempt: a page may place the grid, not restyle it.
_TILE = re.compile(r"\.(?!ag-)[a-z]+-(?:kpis?|tiles?)(?:-[a-z-]+)?\b")
# `.hm-chip-up`, `.tk-pill-down`, `.sn-pill-warn`… — a signed-move pill.
_TONE_PILL = re.compile(r"\.(?!ag-)[a-z-]+-(?:chip|pill)-(?:up|down|warn|flat)\b")


def _page_styles() -> list[Path]:
    return [path for path in sorted(SRC.rglob("*.css")) if SHARED not in path.parents]


@pytest.mark.skipif(not SRC.exists(), reason="frontend sources not checked out")
def test_no_page_styles_its_own_kpi_tile_or_delta_pill():
    offenders = []
    for path in _page_styles():
        text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
        for pattern in (_TILE, _TONE_PILL):
            for match in pattern.finditer(text):
                offenders.append(f"{path.relative_to(SRC)}: {match.group(0)}")
    assert not offenders, (
        "Use Kpi / KpiGrid / Chip from src/ui/Kpi.tsx instead of a page's own "
        "tile or pill:\n" + "\n".join(sorted(set(offenders)))
    )


def test_the_shared_primitives_exist():
    assert (SHARED / "Kpi.tsx").exists()
    css = (SHARED / "ui.css").read_text()
    selectors = (".ag-kpis", ".ag-kpi", ".ag-chip-up", ".ag-chip-down", ".ag-kpi-help")
    for selector in selectors:
        assert selector in css
