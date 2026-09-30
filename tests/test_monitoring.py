"""The alert definitions in infra/monitoring/ against the code that logs.

An alert on a log event is a string match on a name the code is free to
rename. Renamed, the alert keeps its green tick and never fires again — the
worst kind of monitoring, because it reads as "all quiet". So every event a
filter names has to still be emitted, every metric a policy counts has to be
one setup_monitoring.sh creates, and every filter has to watch the service
the script was pointed at rather than a name spelled into the file.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MONITORING = ROOT / "infra" / "monitoring"
POLICIES = sorted(MONITORING.glob("*.json"))
METRICS = sorted((MONITORING / "metrics").glob("*.json"))

_EVENT = re.compile(r'jsonPayload\.event\s*=\s*"([^"]+)"')
_USER_METRIC = re.compile(r"logging\.googleapis\.com/user/([A-Za-z0-9_.-]+)")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _filters(policy: dict) -> list[str]:
    return [
        body["filter"]
        for condition in policy["conditions"]
        for kind, body in condition.items()
        if kind.startswith("condition") and "filter" in body
    ]


def _all_filters() -> list[tuple[str, str]]:
    return [(path.name, f) for path in POLICIES for f in _filters(_load(path))] + [
        (f"metrics/{path.name}", _load(path)["filter"]) for path in METRICS
    ]


def test_there_is_something_to_check():
    assert POLICIES and METRICS


@pytest.mark.parametrize("path", POLICIES + METRICS, ids=lambda p: p.name)
def test_every_definition_is_valid_json(path):
    assert isinstance(_load(path), dict)


def test_every_event_a_filter_names_is_still_logged():
    source = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    missing = [
        f"{name}: {event}"
        for name, text in _all_filters()
        for event in _EVENT.findall(text)
        if f'"{event}"' not in source
    ]
    assert not missing, (
        "an alert matches an event nothing in src/ emits any more — rename "
        "the filter with the event:\n" + "\n".join(missing)
    )


def test_every_metric_a_policy_counts_is_created_by_the_setup_script():
    defined = {_load(path)["name"] for path in METRICS}
    for path in METRICS:
        assert _load(path)["name"] == path.stem, "setup reads the name, keep file = name"
    counted = {
        (path.name, metric)
        for path in POLICIES
        for text in _filters(_load(path))
        for metric in _USER_METRIC.findall(text)
    }
    assert counted, "no rate alert left: drop this test with the metrics dir"
    missing = [f"{name}: {metric}" for name, metric in counted if metric not in defined]
    assert not missing, "\n".join(missing)


def test_every_log_filter_watches_the_service_setup_was_pointed_at():
    for name, text in _all_filters():
        if "cloud_run_revision" in text and "metric.type" not in text:
            assert 'service_name="__SERVICE__"' in text, name


def test_every_per_line_alert_is_rate_limited():
    # A matched-log policy fires once per matching line; unlimited, a burst of
    # a thousand lines is a thousand emails.
    for path in POLICIES:
        policy = _load(path)
        if any("conditionMatchedLog" in c for c in policy["conditions"]):
            assert policy["alertStrategy"]["notificationRateLimit"]["period"], path.name


def test_a_labelled_metric_extracts_a_field_its_event_logs():
    source = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    for path in METRICS:
        metric = _load(path)
        for label, extractor in metric.get("labelExtractors", {}).items():
            field = re.fullmatch(r"EXTRACT\(jsonPayload\.(\w+)\)", extractor)
            assert field, f"{path.name}: {label}"
            for event in _EVENT.findall(metric["filter"]):
                call = re.search(rf'"{re.escape(event)}"[^)]*', source)
                assert call and f"{field[1]}=" in call[0], f"{path.name}: {event}"


def test_the_deploy_smoke_reads_a_route_a_guest_may_read():
    # deploy.sh asks the candidate for this path with no session; a route the
    # gate shuts to guests answers 401 and would block every deploy.
    from stocks.api import guest

    script = (ROOT / "scripts" / "deploy.sh").read_text()
    path = re.search(r'^API_SMOKE_PATH="/api(/v1/[^"]+)"', script, re.M)
    assert path, "deploy.sh lost its API smoke"
    assert (path[1], "GET") in guest.OPEN
