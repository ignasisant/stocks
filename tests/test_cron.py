"""The scheduled work lives on Google Cloud (infra/cron.tf), not on GitHub.

A `schedule:` on GitHub runs when a runner is free, which was two to five
hours late every day, so the Today page's market read and the price warm-up
fire from Cloud Scheduler: a Cloud Run job for the read, one HTTP call for
the warm-up. The pieces live in five places that cannot see each other — the
Terraform, the two workflows, the container entrypoint, deploy.sh, the CLI —
and a change to one that forgets another fails quietly on a morning. These
tests keep them agreeing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CRON_TF = (ROOT / "infra" / "cron.tf").read_text()


def triggers(workflow: str) -> dict:
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text())
    # PyYAML reads the bare `on:` key as the boolean True.
    return doc.get("on") or doc.get(True) or {}


def test_the_moved_workflows_keep_only_their_manual_trigger():
    for name in ("today.yml", "warm.yml"):
        on = triggers(name)
        assert "schedule" not in on, name
        assert "workflow_dispatch" in on, name


def test_the_market_read_fires_before_the_european_open_tuesday_to_saturday():
    assert re.search(r'schedule\s*=\s*"30 6 \* \* 2-6"', CRON_TF)
    assert re.search(r'time_zone\s*=\s*"Etc/UTC"', CRON_TF)


def test_the_warm_up_keeps_its_ticks_anchored_to_new_york():
    # Five ticks, Saturday included: the 04:35 one sits where the request log
    # showed its daily slow cluster, and a weekend reader used to find every
    # persisted memo past its grace.
    assert re.search(r'schedule\s*=\s*"35 0,4,9,12,16 \* \* 1-6"', CRON_TF)
    assert re.search(r'time_zone\s*=\s*"America/New_York"', CRON_TF)
    assert "/api/v1/warm" in CRON_TF


def test_the_warm_up_targets_a_route_the_api_serves():
    from stocks.api.warm import router

    assert any(r.path == "/warm" and "POST" in r.methods for r in router.routes)


def test_the_job_runs_a_cli_subcommand_that_exists():
    m = re.search(r"args\s*=\s*\[([^\]]*)\]", CRON_TF)
    assert m
    words = re.findall(r'"([^"]+)"', m.group(1))
    assert words[0].endswith("/stocks")
    assert f'"{words[1]}"' in (ROOT / "src" / "stocks" / "cli.py").read_text()


def test_the_job_name_is_the_same_everywhere():
    variables = (ROOT / "infra" / "variables.tf").read_text()
    assert re.search(r'default\s*=\s*"topstocks-cron"', variables)
    deploy = (ROOT / "scripts" / "deploy.sh").read_text()
    assert 'JOB="${STOCKS_GCP_JOB:-topstocks-cron}"' in deploy
    from stocks import logs_query

    assert logs_query.JOB == "topstocks-cron"


def test_the_entrypoint_hands_its_arguments_to_exec():
    script = (ROOT / "scripts" / "docker-entrypoint.sh").read_text()
    assert 'exec "$@"' in script
    # After the secrets file is written, before the server would start.
    marks = ("secrets.toml", 'exec "$@"', "uvicorn")
    secrets, run, serve = (script.index(s) for s in marks)
    assert secrets < run < serve


def test_deploy_moves_the_job_to_the_promoted_image_and_secret():
    script = (ROOT / "scripts" / "deploy.sh").read_text()
    assert "run jobs update" in script
    after = script.split("run jobs update", 1)[1]
    assert '--image "$IMAGE"' in after
    assert "STOCKS_SECRETS_TOML=$SECRET" in after
