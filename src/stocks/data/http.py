"""Shared HTTP helpers — stdlib urllib with a User-Agent and timeout.

Every data source in this package (EDGAR, frankfurter, FMP, logos) is a plain
GET with a UA header; this is the single copy of that boilerplate.
"""

from __future__ import annotations

import functools
import json
import ssl
import urllib.error
import urllib.request

DEFAULT_UA = "stocks-toolkit"


@functools.lru_cache(maxsize=1)
def _context() -> ssl.SSLContext | None:
    """TLS context trusting certifi's roots, or None to keep urllib's default.

    urllib verifies against whatever root store OpenSSL was built to look at,
    which on macOS (and on slim container images) can lag the web: BaFin's
    portal chains to GlobalSign Root R46 and fails there while every browser
    and `curl` on the same machine accepts it. certifi ships with the app
    already — requests pulls it in — so this only widens the trusted set.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def get_bytes(
    url: str,
    *,
    user_agent: str = DEFAULT_UA,
    timeout: float = 30,
    headers: dict[str, str] | None = None,
) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": user_agent, **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
        return resp.read()


def get_json(
    url: str,
    *,
    user_agent: str = DEFAULT_UA,
    timeout: float = 30,
    headers: dict[str, str] | None = None,
) -> dict:
    return json.loads(
        get_bytes(url, user_agent=user_agent, timeout=timeout, headers=headers)
    )


def post_json(
    url: str,
    payload: object,
    *,
    user_agent: str = DEFAULT_UA,
    timeout: float = 30,
    headers: dict[str, str] | None = None,
) -> tuple[object, dict[str, str]]:
    """POST `payload` as JSON; the decoded answer and its (lowercased) headers.

    The headers come back because rate-limited APIs say there how long to wait.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
        head = {k.lower(): v for k, v in resp.headers.items()}
        return json.loads(resp.read()), head


def download(
    url: str, dest, *, user_agent: str = DEFAULT_UA, timeout: float = 60
) -> int:
    """Stream `url` into the file `dest` without holding it in memory; the
    byte count. `timeout` bounds each read, not the whole transfer."""
    import shutil

    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
        with open(dest, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)
    return int(dest.stat().st_size) if hasattr(dest, "stat") else 0


def get_bytes_and_type(
    url: str, *, user_agent: str = DEFAULT_UA, timeout: float = 30
) -> tuple[bytes, str]:
    """GET returning (body, content type) — for callers that store the body
    under a type-derived file extension (e.g. the logo mirror)."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def probe_image(url: str, *, user_agent: str = DEFAULT_UA, timeout: float = 6) -> str:
    """Whether `url` serves an image, as seen from THIS host.

    "ok"      — 200 with an image content type.
    "dead"    — definitively not an image: hard 404/410, or a 2xx serving
                something else (an HTML placeholder page).
    "blocked" — inconclusive: 403/429/5xx, timeout or network error. Logo
                CDNs routinely reject datacenter IPs, so callers must treat
                this as "unknown from here", never as "gone".
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
            ctype = resp.headers.get("Content-Type", "")
            return "ok" if ctype.startswith("image") else "dead"
    except urllib.error.HTTPError as e:
        return "dead" if e.code in (404, 410) else "blocked"
    except Exception:
        return "blocked"
