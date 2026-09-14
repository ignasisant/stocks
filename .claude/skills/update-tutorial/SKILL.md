---
name: update-tutorial
description: "Update the in-app guided tour and \"what's new\" (stocks.web.onboarding) after shipping a feature. Use whenever a user-visible feature is added, renamed, moved, gated or removed — a new page, a new tab, a new setting, a new importer, a new jurisdiction — or when the user asks to announce a release, refresh the tutorial, or add a step. Triggers: onboarding, tutorial, tour, guided tour, what's new, changelog, release notes, announce, RELEASES, tour.json, new feature."
---

# Updating the tutorial

The app carries its own onboarding: a modal that walks an account through the
features, plus a "what's new" list per release. Both read one registry, so a
shipped feature that nobody adds here is a feature no user is told about.

Everything lives in three places:

| What | Where |
|---|---|
| Step registry + release data | [src/stocks/web/onboarding.py](../../../src/stocks/web/onboarding.py) |
| Copy, English (source) | [src/stocks/web/locales/en/tour.json](../../../src/stocks/web/locales/en/tour.json) |
| Copy, Spanish | [src/stocks/web/locales/es/tour.json](../../../src/stocks/web/locales/es/tour.json) |

Read `onboarding.py`'s module docstring before editing it — the modal's
lifecycle has three non-obvious constraints (one dialog per run, navigation
closes it, a dialog is a fragment) and the code is shaped by them.

## Step 1 — decide what the change is

- **A feature a user can look at or switch on** → it needs a `Step`, and a
  release item pointing at that step.
- **A change to a feature that already has a step** (a new tab inside it, a
  new broker in the importer, a new jurisdiction) → edit that step's `_body`
  copy, and add a release item pointing at the existing step. Do **not** add
  a second step for it.
- **A refactor a user can see** (a page rebuilt, a panel reorganised, a flow
  moved) → no new step, but it does need a release item: the screen the user
  knows has changed under them.
- **Something with no user-visible surface** (an internal refactor, a perf
  fix, an infrastructure change) → nothing here. The tour is not a git log.
- **A feature that was removed or renamed** → delete or rename its step *and*
  its copy in every locale. A test fails on orphaned copy, which is the point.

## Step 2 — add or edit the step

Append to `STEPS` in the order the *user's work* flows, not the order of the
nav: get the ledger in, read what it derives, then market tools, then the
things that run without you (assistant, notifications), then settings.

```python
    Step(
        id="my_feature",              # also the copy key prefix: tour.my_feature_*
        icon="rocket_launch",         # Material Symbols ligature, no colons
        page="app_pages/thing.py",    # module path st.navigation knows; omit for
                                      # an in-page target (e.g. the chat panel)
        query={"tab": "slug"},        # lands with ?tab=slug (Portfolio tabs)
        session={"profile_tab": "x"}, # state seeded before navigating
        reset_keys=("thing_tab",),    # widget keys to drop so `default=` wins again
        gated=True,                   # target sits behind require_login()
        done=lambda prefs: bool(prefs.get("my_pref")),  # "is it switched on?"
    ),
```

Rules that matter:

- `page` must be a real module under `src/stocks/web/`, written the way
  `st.switch_page` takes it (`app_pages/foo.py`). A test checks the file
  exists. Home is the default page and resolves to url_path `""` — that is
  already handled by `_url_path`.
- Set `gated=True` whenever the target calls `auth.require_login()`. Guests
  then read the step with a disabled button and a sign-in hint instead of
  being dropped on a login wall.
- `done` is only for a capability the account switches **on** (a key, a link,
  a setting, an import). A page is not a capability — leave `done=None`.
- A feature that can be absent for a whole deploy (credentials missing, an
  allowlist) needs a visibility gate in `visible_steps()`, the way the bank
  step does. Do not ship a step that leads to a page that isn't in the nav.
- If the capability is one of the four the Home setup card shows, wire it
  through `setup_state()` rather than computing it twice.

## Step 3 — announce it in the release registry

Versions are date-based `YYYY.MM` and have nothing to do with
`pyproject.toml` — the tour's "new" means "new to look at". Append a
`Release` (oldest first; `CURRENT_VERSION` is derived from the last one), or
add a `News` item to the newest entry if it has not shipped yet.

```python
    Release(
        version="2026.10",
        date="2026-10",
        items=(
            News(slug="myfeature",        # copy-key suffix, unique per release
                 icon="rocket_launch",    # Material Symbols ligature, no colons
                 step="my_feature"),      # the step that explains it, or omit
        ),
    ),
```

One `News` is one card: the modal pages through the unseen ones a feature at
a time, newest release first, so how much a returning account reads is how
much shipped while it was away. That is why an item is a feature and not a
sentence about several — two things worth reading are two items.

- `slug` is half the copy key (`tour.news_<version with dots as underscores>_<slug>_title`
  / `_body`), so it must be unique inside its release. A test enforces both.
- `step` must exist in `STEPS`; the card's button hands the reader to that
  step, which is what makes the announcement actionable. Omit it only for
  something with no tour stop of its own — a card with a `step` that this
  deploy filters out of `visible_steps()` is dropped from the list entirely,
  announcement and all.
- `icon` sits next to the title. Reuse the step's icon unless the feature is
  narrower than the step.

Appending a new version means every account that had already caught up sees
"what's new" on its next session, once: every way out of the modal stamps
`tour_seen_version`. Do not add a version for a change with no card worth
reading.

## Step 4 — write the copy, both languages

For each new step, in **both** `en/tour.json` and `es/tour.json`:

- `tour.<id>_title` — a short noun phrase, sentence case.
- `tour.<id>_body` — two to four sentences: what it does, then the one thing
  that is actually non-obvious about it (the *why*, a real constraint, a
  number). `**bold**` for the sub-features being named. No marketing.
- `tour.<id>_cta` — optional, overrides the generic "take me there"
  ("Open Import", "Set up Telegram"). Skip it and the generic label is used.

For each `News` item, in both catalogs:

- `tour.news_<version>_<slug>_title` — the feature's name, sentence case, no
  trailing period. It is the card's heading, not a sentence.
- `tour.news_<version>_<slug>_body` — one to three sentences on what it does
  and the one thing worth knowing. `**bold**` for sub-features being named.

Keep the two catalogs in the same key order, and keep placeholders identical
between languages — `tests/test_i18n_parity.py` fails on a mismatch. Write
copy that matches what the code actually does; check the feature's own module
docstring rather than guessing (the app's docstrings are unusually specific,
and the tour's credibility is that its claims are true).

## Step 5 — verify

```bash
uv run pytest tests/test_onboarding.py tests/test_i18n_parity.py -q
uv run ruff check src/stocks/web/onboarding.py
```

`tests/test_onboarding.py` is the guard rail for everything above: unique
ids, page modules that exist, releases naming real steps, copy present in
every language, and no copy left behind for a step that is gone. If a new
step needs a new kind of check (a gate, a `done` that reads a file), add the
test with it.

Then look at it: `uv run stocks dashboard`, and open `?tour=<step id>` to land
straight on the new step (`?tour=1` starts from the top). A step whose body
does not match what the page shows is worse than no step.
