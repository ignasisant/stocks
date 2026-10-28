"""`api.holds`: Cloud Run's CPU for a refresh no request is waiting on.

Billed per request, an instance between requests runs at a sliver of a CPU,
and the book's price download a stale memo left behind froze there until its
budget ran out. Pinned here: one hold open while any refresh runs, none off
Cloud Run, and a route only this process can call.
"""

from __future__ import annotations

import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from stocks.api import holds
from stocks.api.app import app


@pytest.fixture(autouse=True)
def fresh():
    holds._reset()
    yield
    holds._reset()


def test_off_cloud_run_nothing_is_held(monkeypatch):
    monkeypatch.delenv("K_SERVICE", raising=False)
    posted: list[str] = []
    monkeypatch.setattr("httpx.post", lambda url, **_: posted.append(url))
    token = holds.BASE.set("http://testserver/api/")
    try:
        holds.keep(threading.Event())
    finally:
        holds.BASE.reset(token)
    assert posted == []


def test_one_hold_covers_every_refresh_in_flight(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "topstocks")
    posted: list[str] = []
    released = threading.Event()

    def post(url, headers, **_):
        posted.append(url)
        assert headers["X-Hold"] == holds._TOKEN
        holds._wait(timeout=5)
        released.set()
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("httpx.post", post)
    first, second = threading.Event(), threading.Event()
    token = holds.BASE.set("http://testserver/api/")
    try:
        holds.keep(first)
        holds.keep(second)
    finally:
        holds.BASE.reset(token)
    first.set()
    assert not released.wait(0.2), "still one refresh running"
    second.set()
    assert released.wait(6)
    assert posted == ["http://testserver/api/v1/hold"]


def test_a_hold_that_is_not_answered_ends_rather_than_asking_again(monkeypatch):
    """A redirect comes back at once; asking again at once would be a loop."""
    monkeypatch.setenv("K_SERVICE", "topstocks")
    posted: list[str] = []

    def post(url, **_):
        posted.append(url)
        return httpx.Response(302, request=httpx.Request("POST", url))

    monkeypatch.setattr("httpx.post", post)
    token = holds.BASE.set("http://testserver/api/")
    try:
        holds.keep(threading.Event())  # never lands
    finally:
        holds.BASE.reset(token)
    for _ in range(100):
        if not holds._active:
            break
        threading.Event().wait(0.01)
    assert posted == ["http://testserver/api/v1/hold"] and not holds._active


def test_spawn_holds_the_cpu_while_the_thread_runs(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "topstocks")
    posted: list[str] = []
    released = threading.Event()

    def post(url, **_):
        posted.append(url)
        holds._wait(timeout=5)
        released.set()
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("httpx.post", post)
    finish = threading.Event()
    token = holds.BASE.set("http://testserver/api/")
    try:
        thread = holds.spawn("test-work", lambda: finish.wait(5))
    finally:
        holds.BASE.reset(token)
    assert thread.daemon and thread.name == "test-work"
    assert not released.wait(0.2), "held while the work runs"
    finish.set()
    thread.join(5)
    assert released.wait(6)
    assert posted == ["http://testserver/api/v1/hold"]


def test_spawn_lets_go_when_the_work_raises(monkeypatch):
    monkeypatch.setenv("K_SERVICE", "topstocks")
    released = threading.Event()

    def post(url, **_):
        holds._wait(timeout=5)
        released.set()
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("httpx.post", post)
    monkeypatch.setattr(threading, "excepthook", lambda _: None)  # the raise is the point

    def work():
        raise RuntimeError("the pull failed")

    token = holds.BASE.set("http://testserver/api/")
    try:
        holds.spawn("test-work", work).join(5)
    finally:
        holds.BASE.reset(token)
    assert released.wait(6)


def test_keep_until_lets_go_once_every_late_pull_lands(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("K_SERVICE", "topstocks")
    released = threading.Event()

    def post(url, **_):
        holds._wait(timeout=5)
        released.set()
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("httpx.post", post)
    first, second = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pulls = [pool.submit(first.wait, 5), pool.submit(second.wait, 5)]
        token = holds.BASE.set("http://testserver/api/")
        try:
            holds.keep_until(pulls)
        finally:
            holds.BASE.reset(token)
        first.set()
        assert not released.wait(0.2), "one pull still running"
        second.set()
        assert released.wait(6)


def test_keep_until_with_nothing_still_running_holds_nothing(monkeypatch):
    from concurrent.futures import Future

    monkeypatch.setenv("K_SERVICE", "topstocks")
    posted: list[str] = []
    monkeypatch.setattr("httpx.post", lambda url, **_: posted.append(url))
    landed: Future = Future()
    landed.set_result(None)
    token = holds.BASE.set("http://testserver/api/")
    try:
        holds.keep_until([landed])
        holds.keep_until([])
    finally:
        holds.BASE.reset(token)
    assert posted == [] and not holds._active


def test_the_route_answers_only_this_process():
    client = TestClient(app)
    assert client.post("/v1/hold", headers={"X-Hold": "guess"}).status_code == 404
    response = client.post("/v1/hold", headers={"X-Hold": holds._TOKEN})
    assert response.status_code == 204  # nothing pending: lets go at once


def test_the_hold_is_aimed_under_the_mount(monkeypatch):
    # Prod serves the API under `/api`; Starlette's `base_url` leaves a mount
    # out, and the hold went to `/v1/hold` — a 404 on every refresh.
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from stocks.api.app import MOUNT_PATH

    seen: list[str] = []
    monkeypatch.setattr(holds, "pinned", lambda url: seen.append(url) or url)
    shell = Starlette(routes=[Mount(MOUNT_PATH, app=app)])
    TestClient(shell).get(f"{MOUNT_PATH}/v1/health")
    assert seen == ["http://testserver/api/"]


def test_the_async_wait_lets_go_when_the_refresh_lands():
    import asyncio

    done = threading.Event()
    with holds._lock:
        holds._pending.add(done)
    # Pending: a short wait runs out.
    asyncio.run(holds._wait_async(timeout=0.05))
    assert holds._waiting()
    done.set()
    asyncio.run(holds._wait_async(timeout=5))
    assert not holds._waiting()
