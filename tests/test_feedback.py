"""The feedback store (stocks.web.feedback) — submission files and read-back.

The route in front of it is held by test_api.py; what must not break
silently is the storage contract: a submission survives as a JSON file (mirrored to the
bucket) that `stocks feedback` can read back, including bucket-only copies a
fresh checkout has never seen.
"""

from __future__ import annotations

import io
import json

import pytest

from stocks import storage
from stocks.web import feedback


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path / "feedback")
    monkeypatch.setattr(storage, "_cached", {"config": None})  # bucket off
    return tmp_path / "feedback"


def test_submit_writes_one_json_file_per_submission(sandbox):
    p = feedback.submit("The chart is upside down", "bug", page="Cartera")
    data = json.loads(p.read_text())
    assert data["kind"] == "bug"
    assert data["text"] == "The chart is upside down"
    assert data["page"] == "Cartera"
    assert data["user"] == "guest"  # no session -> anonymous
    assert p.parent == sandbox


def test_submit_clamps_kind_and_length(sandbox):
    p = feedback.submit("x" * (feedback.MAX_CHARS + 500), "exploit")
    data = json.loads(p.read_text())
    assert data["kind"] == "other"
    assert len(data["text"]) == feedback.MAX_CHARS


def test_stored_merges_local_and_bucket_and_sorts(sandbox, monkeypatch):
    feedback.submit("local one", "idea")
    bucket = {
        "data/feedback/2020-01-01T00-00-00Z-aaaaaa.json": json.dumps(
            {"ts": "2020-01-01T00-00-00Z", "kind": "bug", "text": "old, bucket-only"}
        ).encode(),
        "data/feedback/not-json.txt": b"ignored",
    }
    monkeypatch.setattr(
        storage, "list_keys",
        lambda prefix="": sorted(k for k in bucket if k.startswith(prefix)),
    )
    monkeypatch.setattr(storage, "read_key", bucket.get)
    items = feedback.stored()
    assert len(items) == 2
    assert items[0]["text"] == "old, bucket-only"  # oldest first
    assert items[1]["text"] == "local one"


def test_stored_is_empty_when_nothing_anywhere(sandbox):
    assert feedback.stored() == []


# ------------------------------------------ the screenshot attachment (shot)


def _jpeg(width: int = 8, height: int = 8) -> bytes:
    """A real, tiny JPEG, the bytes the route hands over once decoded."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_submit_keeps_the_picture_beside_the_comment(sandbox):
    raw = _jpeg()
    path = feedback.submit("the chart is upside down", "bug", "Cartera", shot=raw)
    data = json.loads(path.read_text())
    image = sandbox / data["shot"]
    assert image.read_bytes() == raw
    assert image.stem == path.stem  # same submission, same name
    assert image.suffix == ".jpg"


def test_submit_without_a_picture_names_none(sandbox):
    path = feedback.submit("no screenshot here", "idea")
    assert "shot" not in json.loads(path.read_text())
    assert not list(sandbox.glob("*.jpg"))


def test_a_picture_that_cannot_be_stored_never_costs_the_comment(
    sandbox, monkeypatch
):
    """The text is the report; the image is an extra. A bucket that refuses
    the upload must not take the submission down with it — and must not leave
    a local orphan the JSON does not name."""
    def _boom(path):
        if path.suffix == ".jpg":
            raise OSError("bucket said no")

    monkeypatch.setattr(feedback.storage, "persist", _boom)
    path = feedback.submit("the chart is upside down", "bug", shot=_jpeg())
    assert json.loads(path.read_text())["text"] == "the chart is upside down"
    assert "shot" not in json.loads(path.read_text())
    assert not list(sandbox.glob("*.jpg"))


def test_shot_path_finds_the_local_file_and_refuses_a_traversal(sandbox):
    path = feedback.submit("with a picture", "bug", shot=_jpeg())
    name = json.loads(path.read_text())["shot"]
    assert feedback.shot_path(name) == sandbox / name
    assert feedback.shot_path("../../etc/passwd.jpg") is None
    assert feedback.shot_path("data/feedback/x.jpg") is None
    assert feedback.shot_path("") is None
    assert feedback.shot_path("nothing-stored-here.jpg") is None


def test_shot_path_pulls_a_bucket_only_picture_down(sandbox, monkeypatch):
    """`stocks feedback` on a fresh checkout has the JSON from the bucket but
    none of the images; asking for one fetches it."""
    raw = _jpeg()

    def _restore(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return True

    monkeypatch.setattr(feedback.storage, "restore", _restore)
    got = feedback.shot_path("2020-01-01T00-00-00Z-aaaaaa.jpg")
    assert got is not None and got.read_bytes() == raw
