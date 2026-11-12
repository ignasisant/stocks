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
    monkeypatch.setattr(feedback, "REPLIES_DIR", tmp_path / "feedback" / "replies")
    monkeypatch.setattr(feedback, "_memo", {})
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


def test_each_answer_keeps_its_own_last_thumbs():
    """Prod triage 2026-11-02: a thread with three answers voted down showed
    one, because ratings were reduced per conversation."""
    rating = {"kind": "rating", "user": "u1", "thread": "t1"}
    items = [
        {**rating, "turn": "a1", "vote": "down"},
        {**rating, "turn": "a1", "vote": "down", "reason": "wrong"},
        {**rating, "turn": "a2", "vote": "down"},
        {**rating, "turn": "a3", "vote": "up"},
        {"kind": "bug", "user": "u1", "text": "x"},
    ]
    kept = feedback.latest_ratings(items)
    assert [(it.get("turn"), it.get("reason")) for it in kept] == [
        ("a1", "wrong"), ("a2", None), ("a3", None), (None, None)]


def test_the_feedback_command_says_which_bucket_it_read(sandbox, capsys):
    from argparse import Namespace

    from stocks import cli

    cli.cmd_feedback(Namespace(kind=[], user=""))
    assert "local data/feedback only" in capsys.readouterr().out


# ------------------------------------------- the one-time app rating prompt


def test_an_app_rating_is_kept_with_or_without_a_comment(sandbox):
    bare = json.loads(feedback.rate_app(4, page="home").read_text())
    assert (bare["kind"], bare["stars"], bare["text"]) == ("app_rating", 4, "")
    said = json.loads(feedback.rate_app(2, "  the charts are slow ").read_text())
    assert (said["stars"], said["text"]) == (2, "the charts are slow")


def test_an_app_rating_outside_one_to_five_is_refused(sandbox):
    for stars in (0, 6, -1):
        with pytest.raises(ValueError):
            feedback.rate_app(stars)
    assert not sandbox.exists() or not list(sandbox.iterdir())


def test_the_feedback_command_averages_the_app_ratings(sandbox, capsys):
    from argparse import Namespace

    from stocks import cli

    feedback.rate_app(5)
    feedback.rate_app(2, "missing my broker")
    cli.cmd_feedback(Namespace(kind=[], user=""))
    out = capsys.readouterr().out
    assert "★★" in out and "missing my broker" in out
    assert "app rating: 3.5★ from 2" in out


def test_the_command_reads_one_kind_at_a_time(sandbox, capsys):
    # A week of thumbs on answers used to bury the one bug report.
    from argparse import Namespace

    from stocks import cli

    feedback.submit("the chart is upside down", "bug", "Cartera", sender="a_b_com_1")
    feedback.submit("a dark mode", "idea", sender="c_d_com_2")
    cli.cmd_feedback(Namespace(kind=["bug"], user=""))
    out = capsys.readouterr().out
    assert "upside down" in out and "dark mode" not in out
    assert "1 submissions" in out

    cli.cmd_feedback(Namespace(kind=[], user="c_d"))
    out = capsys.readouterr().out
    assert "dark mode" in out and "upside down" not in out

    cli.cmd_feedback(Namespace(kind=["other"], user=""))
    assert "(nothing of that kind)" in capsys.readouterr().out


# ------------------------------------------- the operator's answer, shown once


def _filed(sandbox, sender="a_b_com_1", kind="bug") -> str:
    return feedback.submit("the import read AMT", kind, sender=sender, lang="es").stem


def test_a_reply_is_filed_for_the_writer_and_the_last_one_counts(sandbox):
    first = _filed(sandbox)
    feedback.reply(first, "  Fixed:   upload it again. ")
    feedback.reply(first, "Fixed: upload the statement again.")
    rows = feedback.replies_for("a_b_com_1", now=0.0)
    assert [(r["id"], r["text"], r["kind"]) for r in rows] == [
        (first, "Fixed: upload the statement again.", "bug")
    ]
    assert rows[0]["about"] == json.loads((sandbox / f"{first}.json").read_text())["ts"]
    assert feedback.replies_for("c_d_com_2", now=0.0) == []


def test_nobody_is_answered_who_cannot_be_shown_it(sandbox):
    guest = _filed(sandbox, sender="guest")
    for bad in (guest, "2026-01-01T00-00-00Z-ffffff", "../../prefs", ""):
        with pytest.raises(feedback.NoSuchFeedback):
            feedback.reply(bad, "hello")
    with pytest.raises(ValueError):
        feedback.reply(_filed(sandbox), "   ")


def test_replies_are_not_read_back_as_submissions(sandbox, monkeypatch):
    feedback.reply(_filed(sandbox), "Fixed.")
    bucket = {"data/feedback/replies/a_b_com_1.json": b"[]"}
    monkeypatch.setattr(
        storage, "list_keys",
        lambda prefix="": sorted(k for k in bucket if k.startswith(prefix)),
    )
    monkeypatch.setattr(storage, "read_key", bucket.get)
    items = feedback.stored()
    assert [it["text"] for it in items] == ["the import read AMT"]
    assert items[0]["id"] == next(sandbox.glob("*.json")).stem


def test_an_account_asks_for_its_replies_once_per_while(sandbox):
    first = _filed(sandbox)
    assert feedback.replies_for("a_b_com_1", now=1000.0) == []
    (sandbox / "replies").mkdir()
    (sandbox / "replies" / "a_b_com_1.json").write_text(
        json.dumps([{"id": first, "text": "Fixed."}])
    )
    assert feedback.replies_for("a_b_com_1", now=1001.0) == []  # still held
    later = 1000.0 + feedback.REPLIES_TTL_S
    assert [r["text"] for r in feedback.replies_for("a_b_com_1", now=later)] == ["Fixed."]


def test_the_reply_command_files_it_and_says_the_push_did_not_go(
    sandbox, capsys, monkeypatch
):
    from argparse import Namespace

    from stocks import cli
    from stocks.notify import webpush

    monkeypatch.setattr(webpush, "configured", lambda: False)
    first = _filed(sandbox)
    cli.cmd_feedback_reply(Namespace(id=first, text="Fixed.", page=""))
    out = capsys.readouterr().out
    assert "filed for a_b_com_1" in out and "push: not sent" in out
    with pytest.raises(SystemExit):
        cli.cmd_feedback_reply(Namespace(id="nope", text="x", page=""))

    cli.cmd_feedback(Namespace(kind=[], user=""))
    assert f"id {first}" in capsys.readouterr().out

