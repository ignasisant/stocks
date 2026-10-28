"""Short selling: the registers' parsers, the stored refresh and the route.

The payloads in tests/fixtures/shorts are trimmed copies of live downloads
(2026-10-27): AFM's CSV, FCA's aggregate CSV, a Federal Gazette result page and
FINRA's daily file. Nothing here touches the network.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from stocks.api import loaders
from stocks.api.app import app as fastapi_app
from stocks.data import shorts

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "shorts"
TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_afm_groups_holders_per_issuer_and_keeps_each_holders_latest_position():
    akzo = shorts.parse_afm(fixture("afm.csv"))["NL0013267909"]
    assert akzo.source == "AFM"
    names = [h.name for h in akzo.holders]
    # Millennium appears on two dates: one row, the later one.
    assert names.count("Millennium International Management LP") == 1
    millennium = next(h for h in akzo.holders if h.name.startswith("Millennium"))
    assert (millennium.pct, millennium.date) == (1.61, date(2026, 10, 23))
    # Largest first, and the total is the sum of what is disclosed.
    pcts = [h.pct for h in akzo.holders]
    assert pcts == sorted(pcts, reverse=True)
    assert akzo.total_pct == pytest.approx(1.0 + 0.69 + 1.61)
    assert akzo.as_of == date(2026, 10, 23)


def test_fca_gives_the_aggregate_without_holders():
    entry = shorts.parse_fca(fixture("fca.csv"))["GB0007908733"]
    got = (entry.source, entry.total_pct, entry.as_of)
    assert got == ("FCA", 1.4, date(2026, 10, 22))
    assert entry.holders == []


def test_bundesanzeiger_page_rows():
    rows = shorts.parse_bundesanzeiger_page(fixture("bundesanzeiger.html"))
    assert rows[0] == (
        "Citadel Advisors LLC", "CANCOM SE", "DE0005419105", 1.21, date(2026, 10, 26),
    )
    assert len(rows) == 4


def test_a_closed_position_is_not_a_short():
    rows = [("Fund A", "Acme AG", "DE000A", 0.0, date(2026, 1, 1)),
            ("Fund B", "Acme AG", "DE000A", 0.7, date(2026, 1, 2))]
    out = shorts._group(rows, "BaFin")
    assert [h.name for h in out["DE000A"].holders] == ["Fund B"]


def test_name_key_makes_yahoo_and_the_registers_agree():
    assert shorts.name_key("Akzo Nobel N.V.") == shorts.name_key("AKZO NOBEL NV")
    assert shorts.name_key("LANXESS Aktiengesellschaft") == shorts.name_key("Lanxess AG")
    assert shorts.name_key("BAE Systems plc") == shorts.name_key("Bae Systems Plc")
    assert shorts.name_key("Siemens AG") != shorts.name_key("Siemens Energy AG")


def test_finra_file_parses_to_short_and_total_volume():
    assert shorts.parse_finra(fixture("finra.txt"))["AAPL"] == [7033773, 12248785]


def test_yahoo_info_becomes_us_short_interest():
    stamp = int(datetime(2026, 9, 30, 12).timestamp())
    got = shorts.from_info({
        "shortPercentOfFloat": 0.0645, "sharesShort": 110_000_000.0, "shortRatio": 2.31,
        "sharesShortPriorMonth": 100_000_000.0, "dateShortInterest": stamp,
    })
    assert got.pct_float == 6.45
    assert got.days_to_cover == 2.31
    assert got.change_pct == 10.0
    assert got.as_of == date(2026, 9, 30)
    assert shorts.from_info({"longName": "x"}) is None
    assert shorts.from_info(None) is None


def stub_sources(monkeypatch, **sources):
    monkeypatch.setattr(shorts, "_SOURCES", sources)


def test_refresh_stores_each_register_and_lookup_finds_it_by_name(monkeypatch):
    stub_sources(monkeypatch, AFM=lambda: shorts.parse_afm(fixture("afm.csv")),
                 FCA=lambda: shorts.parse_fca(fixture("fca.csv")))
    assert shorts.refresh_registers() == {"AFM": "2 issuers", "FCA": "4 issuers"}
    assert shorts.net_short("AKZO NOBEL N.V.").total_pct == pytest.approx(3.3)
    assert shorts.net_short("SSE plc").source == "FCA"
    assert shorts.net_short("Unknown Co") is None
    # Survives a new process: the file is what a restart reads.
    shorts.clear_cache()
    assert shorts.net_short("Signify N.V.").holders[0].name.startswith("Citadel")


def test_a_failed_or_empty_download_keeps_the_last_good_register(monkeypatch):
    stub_sources(monkeypatch, AFM=lambda: shorts.parse_afm(fixture("afm.csv")))
    shorts.refresh_registers()

    def refuse():
        raise urllib.error.URLError("down")

    stub_sources(monkeypatch, AFM=refuse)
    assert shorts.refresh_registers(force=True) == {"AFM": "failed"}
    stub_sources(monkeypatch, AFM=dict)
    assert shorts.refresh_registers(force=True) == {"AFM": "empty"}
    assert shorts.net_short("Akzo Nobel N.V.") is not None


def test_a_fresh_register_is_not_downloaded_again(monkeypatch):
    calls = []
    def afm():
        calls.append(1)
        return shorts.parse_afm(fixture("afm.csv"))

    stub_sources(monkeypatch, AFM=afm)
    shorts.refresh_registers()
    assert shorts.refresh_registers() == {"AFM": "fresh"}
    assert calls == [1]


def test_volume_keeps_five_days_and_averages_them(monkeypatch):
    monkeypatch.setattr(shorts, "MIN_NAMES", 1)
    asked = []

    def get_bytes(url, **_):
        asked.append(url[-12:-4])
        return fixture("finra.txt").encode()

    monkeypatch.setattr(shorts.http, "get_bytes", get_bytes)
    monday = date(2026, 10, 26)
    assert shorts.refresh_volume(today=monday + timedelta(days=1)).endswith("days")
    # Weekends are never asked for, and no more than five days are kept.
    assert all(datetime.strptime(d, "%Y%m%d").weekday() < 5 for d in asked)
    assert len(json.loads(shorts.VOLUME_FILE.read_text())["days"]) == shorts.VOLUME_DAYS
    got = shorts.short_volume("tsla")
    assert got.days == 5
    assert got.ratio == pytest.approx(11546289 / 24676669 * 100, abs=0.1)


def test_volume_not_published_yet_is_not_a_failure(monkeypatch):
    def missing(url, **_):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    monkeypatch.setattr(shorts.http, "get_bytes", missing)
    assert shorts.refresh_volume(today=date(2026, 10, 27)) == "nothing new"
    assert shorts.short_volume("AAPL") is None


def test_a_truncated_finra_file_is_not_stored(monkeypatch):
    payload = fixture("finra.txt").encode()
    monkeypatch.setattr(shorts.http, "get_bytes", lambda *a, **k: payload)
    shorts.refresh_volume(today=date(2026, 10, 27))
    assert shorts.short_volume("AAPL") is None


# --- the route -----------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TestClient(fastapi_app)


class Fundamentals:
    def __init__(self, info):
        self.info = info


def test_route_us_name_reads_yahoo_info_and_stored_volume(client, monkeypatch):
    shorts._volume_store()["days"]["20261026"] = {"GME": [40, 100]}
    monkeypatch.setattr(loaders, "fundamentals", lambda t: Fundamentals({
        "shortPercentOfFloat": 0.2, "shortRatio": 3.0, "sharesShort": 50.0,
        "sharesShortPriorMonth": 40.0, "dateShortInterest": 1_790_000_000,
    }))
    body = client.get("/v1/ticker/GME/shorts", headers=AUTH).json()
    assert body["eu"] is None
    assert body["us"]["pct_float"] == 20.0
    assert body["us"]["days_to_cover"] == 3.0
    assert body["us"]["change_pct"] == 25.0
    assert body["us"]["volume_ratio"] == 40.0


def test_route_us_name_without_figures_is_null_not_zero(client, monkeypatch):
    monkeypatch.setattr(loaders, "fundamentals", lambda t: Fundamentals({}))
    body = client.get("/v1/ticker/ZZZZ/shorts", headers=AUTH).json()
    assert body == {"ticker": "ZZZZ", "us": None, "eu": None}


def test_route_eu_name_returns_total_and_top_holders(client, monkeypatch):
    stub_sources(monkeypatch, AFM=lambda: shorts.parse_afm(fixture("afm.csv")))
    shorts.refresh_registers()
    monkeypatch.setattr(loaders, "issuer_name", lambda t: "Akzo Nobel N.V.")
    body = client.get("/v1/ticker/AKZA.AS/shorts", headers=AUTH).json()
    assert body["us"] is None
    assert body["eu"]["source"] == "AFM"
    assert body["eu"]["total_pct"] == pytest.approx(3.3)
    assert body["eu"]["holders"][0]["name"].startswith("Millennium")
    assert body["eu"]["holders_count"] == 3


def test_route_eu_name_not_in_a_register_is_null(client, monkeypatch):
    monkeypatch.setattr(loaders, "issuer_name", lambda t: "Nobody SE")
    body = client.get("/v1/ticker/NOB.DE/shorts", headers=AUTH).json()
    assert body["eu"] is None and body["us"] is None
