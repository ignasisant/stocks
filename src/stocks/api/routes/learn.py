"""The Learn page: paths of short lessons, a glossary, and what this reader
has already read.

The curriculum is shipped files (`stocks.learn`), the same for every reader, so
the three reads are open to a guest. Only the progress is the account's own:
a list of lesson ids in prefs.json, written by `POST /learn/progress`. A guest
keeps theirs in the browser and is answered an empty list here — the demo's
prefs file is shared, and one visitor's ticks are not another's.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from stocks import accounts, learn
from stocks.api.deps import Account, Writer
from stocks.api.security import Who

router = APIRouter(prefix="/learn", tags=["learn"])

#: prefs.json key: the ids of the lessons this account marked read.
PREF_DONE = "learn_done"

Lang = Annotated[
    str,
    Query(min_length=2, max_length=8, description="Language the page is read in."),
]


class LessonRef(BaseModel):
    id: str
    title: str
    minutes: int


class PathOut(BaseModel):
    id: str
    icon: str
    lessons: list[LessonRef]


class Curriculum(BaseModel):
    """Every path with its lessons in order, and which of them are read."""

    paths: list[PathOut]
    done: list[str]
    terms: int


class TermRef(BaseModel):
    id: str
    label: str
    desc: str


class LessonOut(BaseModel):
    id: str
    path: str
    title: str
    minutes: int
    as_of: str
    body: str
    app: str
    terms: list[TermRef]
    before: LessonRef | None
    after: LessonRef | None
    done: bool


class TermOut(BaseModel):
    id: str
    label: str
    aliases: list[str]
    desc: str
    lesson: LessonRef | None


class Glossary(BaseModel):
    terms: list[TermOut]


class Progress(BaseModel):
    model_config = {"extra": "forbid"}

    lesson: str = Field(min_length=1, max_length=80)
    done: bool = True


class ProgressOut(BaseModel):
    done: list[str]


def _done(account, who) -> list[str]:
    if who.kind == "guest":
        return []
    stored = accounts.load_prefs(account.prefs).get(PREF_DONE)
    known = set(learn.lessons(learn.FALLBACK))
    # Ids of lessons since retired are kept on disk but not reported: a path's
    # progress bar counts only what the path still holds.
    return [i for i in stored or () if isinstance(i, str) and i in known]


def _ref(lesson_id: str | None, lang: str) -> LessonRef | None:
    found = learn.lesson(lesson_id, lang) if lesson_id else None
    if found is None:
        return None
    return LessonRef(id=found.id, title=found.title, minutes=found.minutes)


@router.get("", response_model=Curriculum, summary="The paths and their lessons")
def curriculum(account: Account, who: Who, lang: Lang = "en") -> Curriculum:
    paths = [
        PathOut(
            id=path.id,
            icon=path.icon,
            lessons=[ref for i in path.lessons if (ref := _ref(i, lang))],
        )
        for path in learn.paths()
    ]
    return Curriculum(paths=paths, done=_done(account, who),
                      terms=len(learn.glossary(lang)))


@router.get("/lessons/{lesson_id}", response_model=LessonOut, summary="One lesson")
def lesson(
    account: Account,
    who: Who,
    lesson_id: Annotated[str, Path(max_length=80)],
    lang: Lang = "en",
) -> LessonOut:
    found = learn.lesson(lesson_id, lang)
    if found is None:
        raise HTTPException(status_code=404, detail="No such lesson")
    glossary = {t.id: t for t in learn.glossary(lang)}
    before, after = learn.neighbours(found.id)
    return LessonOut(
        id=found.id,
        path=found.path,
        title=found.title,
        minutes=found.minutes,
        as_of=found.as_of,
        body=found.body,
        app=found.app,
        terms=[TermRef(id=t.id, label=t.label, desc=t.desc)
               for i in found.terms if (t := glossary.get(i))],
        before=_ref(before, lang),
        after=_ref(after, lang),
        done=found.id in _done(account, who),
    )


@router.get("/glossary", response_model=Glossary, summary="Every term")
def glossary(lang: Lang = "en") -> Glossary:
    return Glossary(terms=[
        TermOut(id=t.id, label=t.label, aliases=list(t.aliases), desc=t.desc,
                lesson=_ref(t.lesson, lang))
        for t in learn.glossary(lang)
    ])


@router.post("/progress", response_model=ProgressOut, summary="Mark a lesson read")
def progress(body: Progress, account: Writer) -> ProgressOut:
    """Add or remove one lesson from the account's read list."""
    if learn.lesson(body.lesson, learn.FALLBACK) is None:
        raise HTTPException(status_code=404, detail="No such lesson")
    with accounts.prefs_lock(account.prefs):
        stored = accounts.load_prefs(account.prefs).get(PREF_DONE)
        done = [i for i in stored or () if isinstance(i, str) and i != body.lesson]
        if body.done:
            done.append(body.lesson)
        accounts.update_prefs(account.prefs, {PREF_DONE: done})
    known = set(learn.lessons(learn.FALLBACK))
    return ProgressOut(done=[i for i in done if i in known])
