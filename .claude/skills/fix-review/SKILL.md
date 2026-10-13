---
name: fix-review
description: "Work through the browser reviews Claude in Chrome writes as Claude Docs titled \"TopStocks · Review · AAAA-MM-DD\": find them in the account's artifacts, read them with the Claude Docs tools, and for every unchecked \"- [ ]\" item apply the fix, run the tests, commit with the item's ID, then tick the box and append the hash. An item that can't be resolved gets a comment on its line and stays unticked. Use when the user runs /fix-review, says 'arregla la revisión', 'resuelve los puntos', 'fix the review', or names review IDs like GLB-05, INI-03, ASG-21."
---

# Fixing a review

The loop has three steps. The user reviews the live app with Claude in Chrome,
which writes a Claude Doc titled `TopStocks · Review · AAAA-MM-DD`. One `##`
section per page holds a checklist. This skill turns the checklist into
commits and ticks the doc as it goes. The doc is the only source of truth, so
don't copy it into the repo.

The reviewer looked at screens, not code. Each item is a **claim to verify**,
not an instruction to execute.

## Arguments

`/fix-review [fecha] [alta|media|baja] [prefijo…|ID…]`, combined freely, e.g.
`/fix-review alta`, `/fix-review ASG`, `/fix-review GLB-05 TCK-01`. With no
argument, take every unchecked item of every review doc, oldest doc first.

## Step 1: find and read the docs

1. Load the docs skill (`anthropic-skills:docs`). If its tools are deferred,
   fetch `mcp__claude_ai_Claude_Docs__read`, `__query`, `__create` and
   `__update` via ToolSearch. Call `guide(["topic.index","topic.editing","topic.comments"])`
   once before the first docs call.
2. `Artifact(action="list", scope="mine", limit=200)` and keep the titles that
   start with `TopStocks · Review ·`. If none match, say so and stop: there is
   nothing else to read.
3. For each doc, `read(ref={"object":"project","id":"<id from the link>"})`
   returns `files[0].content.id` (the body). Read the body as an outline, then
   each `kind='check'` list in full with `{"kind":"view","parentId":"<list id>"}`.
   Keep each listItem's id and `h`, plus the doc `rev` as your bookmark.
4. Read the **Protocolo** section at the top of the doc: it can change these
   rules, and the doc wins.
5. List the comment threads (`query`, `"under": {"object":"file","id":"<tab id>"}`).
   An item with an open thread from you and no reply from the user is still
   waiting: skip it. If the user replied, act on the reply.

An item is pending when its listItem has no `checked='true'`. Its text is
`ID [prioridad] problema → propuesta`.

## Step 2: triage before touching code

Read the code (CodeGraph first, see `~/.claude/CLAUDE.md`) and, for data claims,
the actual book through `data/` or the API. Sort every pending item in scope:

| Bucket | Meaning | Action |
|---|---|---|
| fix | Real defect or real copy/i18n/format problem | Step 3 |
| root | Same cause as another item ("ver GLB-09") | Fixed by that root's commit |
| decision | Rename, product behaviour, or conflict with a rule below | Comment, leave unticked |
| wrong | The claim is false or the screen was misread | Comment with the evidence, leave unticked |

Order: `alta` first, then the roots with the most dependants (one shared
formatter fixes GLB-05, TCK-01 and SEC-01 at once), then the rest page by page.
When the scope is more than a handful of items, show the triage first: IDs per
bucket, one line each.

## Step 3: fix, test, commit, one ID (or one root) at a time

**Where.** Work in a worktree on `fix/review-<fecha>`, branched from `main`'s
HEAD:
`git worktree add ../stocks-review-<fecha> -b fix/review-<fecha>`, then
`npm --prefix frontend/app ci` inside it. The main checkout usually carries
uncommitted work in progress, and a per-ID commit there would sweep it in.
Never push or open a PR unless the user asks. Merges here keep the commits,
so the hashes in the doc stay valid.

**Project rules the review does not override:**

- **Full width** ([CLAUDE.md](../../../CLAUDE.md)): no `max-width` on pages,
  `@container ag-main` queries, and the open chat drawer pads the shell. A layout
  proposal that breaks this ("chat en overlay") is a `decision`.
- **Fixes are announced nowhere**: no "what's new" card. Touch
  [tour.json](../../../src/stocks/web/locales/en/tour.json) only when a step's
  copy is now false.
- **Copy** is short, lives in `src/stocks/web/locales/{en,es}/*.json`, and
  every key goes in both locales. Numbers, dates and money go through the
  frontend's format helpers. Text sent to the LLM is already formatted for the
  user's locale.
- **Mobile**: 11px floor, 44px touch targets, check narrow widths. **Speed**:
  no new serial loads and no per-row network on a page.
- A parser bug that wrote bad rows also needs a migration or doctor fix for
  existing books, not only the parser change.

**Tests, all green before the commit:**

```bash
uv run ruff check .
uv run pytest tests/test_i18n_parity.py tests/test_frontend_i18n_keys.py tests/test_frontend_layout.py -q
uv run pytest tests/<module(s) of the fix> -q
npm --prefix frontend/app run build   # only if frontend/ changed: prettier, tsc, vitest, bundle
```

The build rewrites `src/stocks/web/static/app/`, and CI checks that the bundle
is fresh, so commit it with the fix (`git add -A src/stocks/web/static/app`).
If BAML changed, run `uv run baml-cli generate`. For visual items (layout,
truncation, chat open), take a screenshot at the width the item describes.
Run `uv run pytest -q` in full before you report the run done. If it fails,
fix that before ticking anything more.

**Commit.** Stage only the files of this fix (never `git add -A .`). Message:

```
fix(<página>): <ID>[, <ID>…] <qué cambia>

<por qué, una o dos líneas>

Co-Authored-By: <the attribution line from the system reminder>
```

A root commit lists every ID it resolves.

## Step 4: write back to the doc

First, `read(…, {"kind":"view","sinceRev":<bookmark>})`, because the user or
Chrome may have edited the doc. Their edit wins.

- **Resolved:** in one `update` on the body, first
  `{"op":"set","target":{"kind":"blocks","ids":["<listItem id>"]},"attrs":{"checked":true}}`,
  then append ` · <hash corto>` by replacing the item's last words
  (`find` + `"as":"text"`). Every item a root commit resolves gets the same hash.
- **Not resolved** (`decision`, `wrong`, tests that won't go green, missing
  data): leave it unticked and `create` an utterance anchored on the item's
  first words (`"anchor":{"kind":"find","text":"<ID> [prioridad] …"}`). Say
  why and, for a decision, the concrete question. Keep it to about 20 words.
  Never two threads on the same item.

## Step 5: report

In chat, give the branch, the commits (hash · IDs), and the items commented
and left unticked with one line each. Add the full-suite line
(`N passed`) and the doc link once.
