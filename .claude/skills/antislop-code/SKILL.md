---
name: antislop-code
description: "Comment hygiene: remove comments that add nothing (restating the code, step narration, empty labels, vague TODOs, emoji, end markers, change history) and keep the ones that carry a why the code cannot show. Never touches executable code. Use when writing or editing comments, when cleaning a file or a diff, or when the user says 'limpia comentarios', 'antislop', 'deslop', 'quita comentarios', 'clean up comments'."
allowed-tools: Read Edit Glob Grep Bash
---

# antislop-code

Adapted from `skills/antislop-code` in
[miqdadbadjuber/anti-slop](https://github.com/miqdadbadjuber/anti-slop) (MIT).
Two changes for this repo: it stands alone (no core file), and the length rule
counts facts, not lines, because this codebase keeps domain rules (tax,
dividends, broker quirks, quotas) in comments on purpose.

## Scope

Only comments and docstrings change. Never touch executable code, identifiers,
imports, formatting, indentation or control flow. When unsure whether a line is
a comment the code depends on (`# type: ignore`, `# noqa`, `// eslint-disable`,
`# pragma`, `@ts-expect-error`, shebangs, license headers), leave it.

## The test

A comment stays when it tells the reader something the code does not already
show: the reason, the constraint, the non-obvious behaviour, the trap. Everything
else goes.

## Remove

- **Restating the code.** `# Initialize the counter` above `count = 0`;
  `// User class` above `class User`; `"""Return the price."""` on `def price()`.
- **Step narration.** `# Step 1: validate`, `# First... Next... Finally...`.
  If the flow is hard to follow, that is a structure problem; fix it there.
- **Empty labels.** `# Main logic`, `# Helpers`, `# Error handling`,
  `# Note: this is important`.
- **Vague TODOs.** `# TODO: improve this`. A TODO stays only when it names the
  task and enough context to act on it.
- **Signature echo.** `@param price The price.` / `@returns The total.` when
  the name and types already say it.
- **Emoji and end markers.** `// ✅ Validation`, `} // end if`, `# end of function`.
- **Change history.** "used to", "previously", "before PR #12", "since v3",
  "this replaced X", issue numbers, who fixed what. Git keeps history; the
  comment keeps the constraint that is true now. Rewrite to the present-tense
  rule, or drop it if nothing remains.
- **Decorative banners.** `# ======= ROUTES =======`, boxed headers, ALL CAPS.
  The repo's `# ------------------- label` section rulers are a house style for
  long files: leave them while the file is long, drop them when a split makes
  each section its own module.

## Keep

Business and domain rules, why a value is what it is, security and privacy
reasoning, performance trade-offs, concurrency and ordering constraints,
protocol and third-party quirks (Yahoo, brokers, tax authorities), workarounds
(say what they work around), edge cases, assumptions, license notices.

```python
# A dividend is owed to whoever holds the share the day before it goes ex;
# the broker's statement has no say in it.
```

## How long

One line per fact. A block may run as long as it has distinct facts, each one
something a maintainer would get wrong without it. Cut, inside a kept block:

- the second phrasing of the same fact,
- "because X, so Y, and therefore Z" chains that the first clause already settles,
- history and attribution (see above),
- narration of the next lines.

One comment per logical block, not per line. Short, sentence case, plain voice.

## Checklist

- [ ] Every comment adds something the code does not show.
- [ ] No narration, empty labels, vague TODOs, emoji, end markers.
- [ ] No change history; the comment states what is true now.
- [ ] Multi-line blocks carry one fact per line, no restatements.
- [ ] Only comments changed: `git diff -w` shows no code lines.

Verify with the suite for the files touched (`uv run pytest -q <tests>`,
`npm --prefix frontend/app run test -- <files>`) and `git diff --stat`.
