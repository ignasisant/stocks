"""Trigger evals for the skill auto-router (web/chat_skills.py).

`evals/router/triggers.yaml` holds, per skill, questions it should be picked
for (`should`) and near-misses it should not be picked for (`near_miss`).
`score` runs any router (a question -> skill ids function) over them and
returns per-skill recall and false-positive rate.

Two runners share it. tests/test_skill_router_evals.py scores the keyword
fallback (`chat_skills.heuristic`), which needs no model, and pins a floor.
scripts/eval_router.py scores the real LLM router: a measurement that needs a
provider key, never part of CI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parents[3] / "evals" / "router" / "triggers.yaml"


@dataclass
class Row:
    skill: str
    hit: int = 0  # `should` questions that picked the skill
    total: int = 0
    false_pos: int = 0  # `near_miss` questions that picked it anyway
    near: int = 0
    missed: list[str] = field(default_factory=list)
    leaked: list[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.hit / self.total if self.total else 0.0

    @property
    def fp_rate(self) -> float:
        return self.false_pos / self.near if self.near else 0.0


def load(path: Path = PATH) -> dict[str, dict[str, list[str]]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: {"should": list(v["should"]), "near_miss": list(v["near_miss"])}
            for k, v in data.items()}


def score(route: Callable[[str], list[str] | None],
          cases: dict[str, dict[str, list[str]]] | None = None,
          only: set[str] | None = None) -> dict[str, Row]:
    """Per-skill rows; a router answering None (it failed) picked nothing."""
    cases = cases if cases is not None else load()
    rows: dict[str, Row] = {}
    for sid, c in cases.items():
        if only and sid not in only:
            continue
        row = rows[sid] = Row(sid)
        for q in c["should"]:
            row.total += 1
            if sid in (route(q) or []):
                row.hit += 1
            else:
                row.missed.append(q)
        for q in c["near_miss"]:
            row.near += 1
            if sid in (route(q) or []):
                row.false_pos += 1
                row.leaked.append(q)
    return rows


def totals(rows: dict[str, Row]) -> tuple[float, float]:
    """Micro-averaged (recall, false-positive rate) over every question."""
    hit = sum(r.hit for r in rows.values())
    total = sum(r.total for r in rows.values())
    fp = sum(r.false_pos for r in rows.values())
    near = sum(r.near for r in rows.values())
    return (hit / total if total else 0.0, fp / near if near else 0.0)
