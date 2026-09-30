"""Structured logging (stocks.obs): payload shape, context, timing."""

from __future__ import annotations

import json
import logging

import pytest

from stocks import obs


@pytest.fixture
def cloud_lines(monkeypatch) -> list[dict]:
    """Capture what the Cloud Run formatter would write, as parsed JSON."""
    written: list[dict] = []

    class Sink(logging.Handler):
        def emit(self, record):
            written.append(json.loads(obs.CloudLoggingFormatter().format(record)))

    monkeypatch.setattr(obs, "_ctx", type(obs._ctx)("test_ctx", default=None))
    logger = obs.log
    sink = Sink()
    logger.addHandler(sink)
    logger.setLevel(logging.DEBUG)
    old_propagate, logger.propagate = logger.propagate, False
    yield written
    logger.removeHandler(sink)
    logger.propagate = old_propagate


def test_event_lands_in_json_payload(cloud_lines):
    obs.event("chat.answered", provider="free", chars=120)
    (line,) = cloud_lines
    assert line["severity"] == "INFO"
    assert line["message"] == "chat.answered"
    assert line["event"] == "chat.answered"
    assert line["provider"] == "free"
    assert line["chars"] == 120


def test_bound_context_rides_every_record(cloud_lines):
    obs.bind(user="u_1", session="s_1")
    obs.event("one")
    obs.event("two", page="Cartera")
    assert [ln["user"] for ln in cloud_lines] == ["u_1", "u_1"]
    assert cloud_lines[1]["page"] == "Cartera"
    obs.unbind("session")
    obs.event("three")
    assert "session" not in cloud_lines[2]


def test_context_manager_restores_previous_fields(cloud_lines):
    obs.bind(user="u_1")
    with obs.context(page="Ticker"):
        obs.event("inside")
    obs.event("outside")
    assert cloud_lines[0]["page"] == "Ticker"
    assert "page" not in cloud_lines[1]


def test_bind_ignores_none_so_optional_fields_stay_absent(cloud_lines):
    obs.bind(user="u_1", revision=None)
    obs.event("e")
    assert "revision" not in cloud_lines[0]


def test_timed_records_duration_and_ok(cloud_lines):
    with obs.timed("page.render", page="Home") as extra:
        extra["rows"] = 7
    (line,) = cloud_lines
    assert line["ok"] is True
    assert line["rows"] == 7
    assert isinstance(line["duration_ms"], int)


def test_timed_logs_and_reraises_on_failure(cloud_lines):
    with pytest.raises(ValueError):
        with obs.timed("page.render"):
            raise ValueError("boom")
    (line,) = cloud_lines
    assert line["severity"] == "ERROR"
    assert line["ok"] is False
    assert line["error_type"] == "ValueError"
    # Error Reporting groups on the inline traceback, not the separate field.
    assert "ValueError: boom" in line["message"]
    assert line["@type"].endswith("ReportedErrorEvent")


def test_passthrough_exceptions_are_not_errors(cloud_lines):
    class Stop(BaseException):
        pass

    with pytest.raises(Stop):
        with obs.timed("page.render", passthrough=(Stop,)):
            raise Stop()
    (line,) = cloud_lines
    assert line["severity"] == "INFO"
    assert line["ok"] is True
    assert line["stopped"] is True


def test_swallow_logs_a_warning_without_reraising(cloud_lines):
    with obs.swallow("logo.mirror", ticker="AAPL"):
        raise KeyError("missing")
    (line,) = cloud_lines
    assert line["severity"] == "WARNING"
    assert line["ticker"] == "AAPL"
    assert line["error_type"] == "KeyError"
    # A degraded optional path must not open an Error Reporting group.
    assert "@type" not in line


def test_unserializable_values_do_not_lose_the_line(cloud_lines):
    obs.event("weird", path=object())
    assert cloud_lines[0]["event"] == "weird"


def test_setup_is_idempotent():
    obs.setup()
    obs.setup()
    handlers = [h for h in logging.getLogger().handlers if h.get_name() == "stocks-obs"]
    assert len(handlers) == 1


def test_yfinance_misses_are_warnings_and_its_blank_lines_are_dropped():
    # yfinance logs every symbol Yahoo has no data for at ERROR; in prod that
    # was most of `stocks logs errors` and hid the app's own failures.
    obs.setup(force=True)
    seen: list[logging.LogRecord] = []

    class Sink(logging.Handler):
        def emit(self, record):
            seen.append(record)

    yf_log = logging.getLogger("yfinance")
    # Another test (or yfinance itself) may have raised the logger's level or
    # disabled it; this one is about the filter, so hear everything.
    level, disabled = yf_log.level, yf_log.disabled
    yf_log.setLevel(logging.DEBUG)
    yf_log.disabled = False
    sink = Sink()
    yf_log.addHandler(sink)
    try:
        yf_log.error("$ORGN: possibly delisted; no price data found  (period=5y)")
        yf_log.error("")
        yf_log.critical("still not ours to page on")
    finally:
        yf_log.removeHandler(sink)
        yf_log.setLevel(level)
        yf_log.disabled = disabled
    assert [(r.levelname, r.getMessage()) for r in seen] == [
        ("WARNING", "$ORGN: possibly delisted; no price data found  (period=5y)"),
        ("WARNING", "still not ours to page on"),
    ]
    obs.setup(force=True)
    assert sum(isinstance(f, obs._YahooMissIsNotAnError) for f in yf_log.filters) == 1


def test_the_api_process_configures_logging_at_boot(monkeypatch):
    """The React shell leaves the API as the only process serving pages. Without
    `setup` there every event went out through logging's last resort: bare
    text, fields lost, and yfinance's misses back at ERROR."""
    import asyncio
    import importlib

    # The module, not the FastAPI instance the package re-exports as `app`.
    api_app = importlib.import_module("stocks.api.app")

    calls: list[str] = []
    monkeypatch.setattr(api_app.obs, "setup", lambda *a, **k: calls.append("obs"))
    monkeypatch.setattr(api_app.guestbook, "provision", lambda: calls.append("guest"))
    monkeypatch.setattr(api_app.warm, "start", lambda: calls.append("warm"))

    async def boot():
        async with api_app._lifespan(api_app.app):
            pass

    asyncio.run(boot())
    assert calls[0] == "obs"
