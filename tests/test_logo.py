"""Logo domain parsing, probe semantics and same-origin mirroring — no network."""

import pytest

import stocks.data.logo as logo_mod
from stocks.data.logo import domain_from_website

FMP_AAPL = "https://financialmodelingprep.com/image-stock/AAPL.png"
FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"


@pytest.fixture(autouse=True)
def _isolated_caches(tmp_path, monkeypatch):
    """Fresh disk cache and per-process memo for every test."""
    monkeypatch.setattr(logo_mod, "LOGO_CACHE", tmp_path / "logos.json")
    monkeypatch.setattr(logo_mod, "_inconclusive", {})
    monkeypatch.setattr(logo_mod, "_bucket", {"fold": False, "push": False})


@pytest.mark.parametrize(
    ("website", "expected"),
    [
        ("https://www.apple.com", "apple.com"),
        ("http://microsoft.com/", "microsoft.com"),
        ("https://investor.nvidia.com/home", "investor.nvidia.com"),
        ("nvidia.com", "nvidia.com"),
        ("www.tesla.com", "tesla.com"),
        ("", None),
        (None, None),
    ],
)
def test_domain_from_website(website, expected):
    assert domain_from_website(website) == expected


def test_logo_url_ok_probe_cached_to_disk(monkeypatch):
    probes = []

    def fake_probe(url):
        probes.append(url)
        return "ok"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)

    assert logo_mod.logo_url("aapl") == FMP_AAPL
    # Second call answers from the on-disk cache — one probe total, no yf.
    assert logo_mod.logo_url("AAPL") == FMP_AAPL
    assert probes == [FMP_AAPL]
    assert logo_mod._load_cache()["AAPL"] == FMP_AAPL


def test_a_torn_cache_file_is_read_as_empty_and_rewritten_whole(monkeypatch):
    """Two threads resolving at once used to interleave their writes into one
    file; every later read raised JSONDecodeError and the logo went with it."""
    import json
    import threading

    logo_mod.LOGO_CACHE.write_text('{"AAPL": "https://x"}{"MSFT": ')
    assert logo_mod._load_cache() == {}
    monkeypatch.setattr(logo_mod, "_probe", lambda url: "ok")
    threads = [
        threading.Thread(target=logo_mod.logo_url, args=(t,))
        for t in ("AAPL", "MSFT", "NVDA", "AMZN")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {"AAPL", "MSFT", "NVDA", "AMZN"} <= set(
        json.loads(logo_mod.LOGO_CACHE.read_text())
    )


def test_blocked_probe_returns_guess_without_disk_cache(monkeypatch):
    probes = []

    def fake_probe(url):
        probes.append(url)
        return "blocked"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)
    monkeypatch.setattr(logo_mod, "_company_domain", lambda t: "apple.com")

    url = logo_mod.logo_url("AAPL")
    assert url == FMP_AAPL  # best guess still handed to the browser
    # A blocked host must not poison the definitive cache…
    assert "AAPL" not in logo_mod._load_cache()
    # …but the process memoizes instead of re-probing every render.
    assert logo_mod.logo_url("AAPL") == FMP_AAPL
    assert probes == [FMP_AAPL, FAVICON.format(domain="apple.com")]


def test_blocked_verdict_outlives_the_process_for_a_week(monkeypatch):
    """A reboot must not re-probe every blocked logo — a few seconds each, on
    the first page anyone opens — but the host does try again after the TTL."""
    probes = []

    def fake_probe(url):
        probes.append(url)
        return "blocked"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)
    monkeypatch.setattr(logo_mod, "_company_domain", lambda t: None)
    now = 1_000_000.0
    monkeypatch.setattr(logo_mod.time, "time", lambda: now)

    assert logo_mod.logo_url("AAPL") == FMP_AAPL
    monkeypatch.setattr(logo_mod, "_inconclusive", {})  # "reboot"
    assert logo_mod.logo_url("AAPL") == FMP_AAPL
    assert probes == [FMP_AAPL]

    now += logo_mod.BLOCKED_TTL + 1
    monkeypatch.setattr(logo_mod, "_inconclusive", {})
    monkeypatch.setattr(logo_mod, "_probe", lambda url: "ok")
    assert logo_mod.logo_url("AAPL") == FMP_AAPL
    # Settled for good, and the blocked entry is gone.
    assert logo_mod._load_cache()["AAPL"] == FMP_AAPL
    assert "AAPL" not in logo_mod._load_file()["_blocked"]


def test_dead_everywhere_caches_negative(monkeypatch):
    probes = []

    def fake_probe(url):
        probes.append(url)
        return "dead"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)
    monkeypatch.setattr(logo_mod, "_company_domain", lambda t: "zzzz.example")

    assert logo_mod.logo_url("ZZZZ") is None
    assert logo_mod._load_cache()["ZZZZ"] == ""
    assert logo_mod.logo_url("ZZZZ") is None  # cache hit, no new probes
    assert len(probes) == 2  # FMP + favicon, once each


def test_dead_fmp_falls_through_to_favicon(monkeypatch):
    def fake_probe(url):
        return "ok" if "favicons" in url else "dead"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)
    monkeypatch.setattr(logo_mod, "_company_domain", lambda t: "apple.com")

    url = logo_mod.logo_url("AAPL")
    assert url == FAVICON.format(domain="apple.com")
    assert logo_mod._load_cache()["AAPL"] == url


def test_company_domain_swallows_yfinance_errors(monkeypatch):
    class Boom:
        def __init__(self, ticker):
            pass

        @property
        def info(self):
            raise RuntimeError("429 Too Many Requests")

    import yfinance

    from stocks.data.fetch import clear_info_cache

    monkeypatch.setattr(yfinance, "Ticker", Boom)
    clear_info_cache()  # the shared .info memo would answer before Boom runs
    assert logo_mod._company_domain("AAPL") is None


def test_brand_logo_url_cached_with_prefix(monkeypatch):
    checks = []

    def fake_probe(url):
        checks.append(url)
        return "ok"

    monkeypatch.setattr(logo_mod, "_probe", fake_probe)

    url = logo_mod.brand_logo_url("degiro.com")
    assert url == FAVICON.format(domain="degiro.com")
    # Second call answers from the on-disk cache under the brand: prefix.
    assert logo_mod.brand_logo_url("degiro.com") == url
    assert len(checks) == 1
    assert logo_mod._load_cache()["brand:degiro.com"] == url


def test_mirror_logo_downloads_once_then_serves_from_disk(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: "https://x/AAPL.png")

    def fake_get(url, **kw):
        calls.append(url)
        return b"png-bytes", "image/png"

    monkeypatch.setattr(logo_mod, "get_bytes_and_type", fake_get)

    assert logo_mod.mirror_logo("aapl", tmp_path) == "AAPL.png"
    assert (tmp_path / "AAPL.png").read_bytes() == b"png-bytes"
    # Second call finds the file — the logo host is contacted exactly once.
    assert logo_mod.mirror_logo("AAPL", tmp_path) == "AAPL.png"
    assert len(calls) == 1


def test_mirror_logo_ignores_a_longer_stem(tmp_path, monkeypatch):
    """BRK's glob also matches BRK.B.png; that is not BRK's logo."""
    (tmp_path / "BRK.B.png").write_bytes(b"b")
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: "https://x/BRK.png")
    monkeypatch.setattr(
        logo_mod, "get_bytes_and_type", lambda url, **kw: (b"k", "image/png")
    )
    assert logo_mod.mirror_logo("BRK", tmp_path) == "BRK.png"


def test_mirror_logo_unresolved_and_failed_download(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: None)
    assert logo_mod.mirror_logo("ZZZZ", tmp_path) is None

    monkeypatch.setattr(logo_mod, "logo_url", lambda t: "https://x/y.png")

    def boom(url, **kw):
        raise OSError("network down")

    monkeypatch.setattr(logo_mod, "get_bytes_and_type", boom)
    assert logo_mod.mirror_logo("ZZZZ", tmp_path) is None
    assert not any(tmp_path.iterdir())  # nothing half-written


def test_mirror_rejects_non_image_body(tmp_path, monkeypatch):
    """A blocked CDN can answer 200 with an HTML challenge — never store it."""
    monkeypatch.setattr(logo_mod, "logo_url", lambda t: "https://x/AAPL.png")
    monkeypatch.setattr(
        logo_mod,
        "get_bytes_and_type",
        lambda url, **kw: (b"<html>are you human</html>", "text/html; charset=utf-8"),
    )
    assert logo_mod.mirror_logo("AAPL", tmp_path) is None
    assert not any(tmp_path.iterdir())


def test_mirror_brand_downloads_once_under_brand_stem(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        logo_mod, "brand_logo_url", lambda d: f"https://icons.example/{d}"
    )

    def fake_get(url, **kw):
        calls.append(url)
        return b"png-bytes", "image/png"

    monkeypatch.setattr(logo_mod, "get_bytes_and_type", fake_get)

    name = logo_mod.mirror_brand("trading212", "trading212.com", tmp_path)
    assert name == "brand-trading212.png"
    # Second call serves from disk; brand stem can't collide with a ticker.
    assert logo_mod.mirror_brand("trading212", "trading212.com", tmp_path) == name
    assert len(calls) == 1


def test_mirror_brand_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_mod, "brand_logo_url", lambda d: None)
    assert logo_mod.mirror_brand("generic", "example.com", tmp_path) is None

