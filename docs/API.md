# HTTP API conventions (`/api/v1`)

The internal API (`src/stocks/api`, mounted at `/api`, versioned in the path)
is about to meet third-party callers. This is the convention it follows, what
the audit found, and what was and was not changed. `tests/test_api_contract.py`
enforces the parts marked (T).

## Conventions

- **Path**: every route is under `/api/v1` (T). Lowercase kebab-case segments,
  `snake_case` path params (T). File-ish answers carry an extension
  (`.csv`, `.md`, `.zip`).
- **Fields and query params**: `snake_case` (T). Exception: the AG-UI chat
  protocol models, which keep the protocol's camelCase (see v2 candidates).
- **Methods**: `GET` reads and never writes; `POST` creates or runs; `PUT`
  replaces; `PATCH` edits; `DELETE` removes. Success is `200`, `201` for a
  create, `202` for accepted work, `204` for an empty answer.
- **Auth**: bearer token or session cookie; anything unauthenticated is `401`
  with `WWW-Authenticate: Bearer`. A guest reaches only the routes named in
  `api/guest.py`.
- **Errors** (T): every 4xx/5xx, including unknown paths, wrong methods, bad
  input and unhandled bugs, has this body (`api/errors.py`):

  ```json
  {"error": {"code": "not_found", "message": "unknown account"},
   "detail": "unknown account",
   "reason": "rate_limited"}
  ```

  `error.code` is a stable slug, one per status (`bad_request`,
  `unauthenticated`, `forbidden`, `not_found`, `method_not_allowed`,
  `conflict`, `payload_too_large`, `unsupported_media_type`,
  `validation_error`, `rate_limited`, `unavailable`, `bad_gateway`,
  `internal_error`); `error.message` is for humans. `detail` is the legacy
  spelling the web shell reads (a string, or FastAPI's list of
  `{loc, msg, type}` on a 422); `reason` appears only on upstream refusals
  (`rate_limited`, `offline`), with `Retry-After`. `detail` and `reason` stay
  until a v2. `message` may be an i18n key (`chat.rate_limited`,
  `common.storage_restore_failed`) when the shell renders it; branch on `code`
  and `reason`, never on the text. A 500 never carries the exception text.
- **Paging** (T): `limit` (bounded, per-route default) and `offset` (>= 0),
  with a `total` in the body. Helper: `api/paging.py`. No cursors, no
  `page`/`page_size`.

## Audit

138 paths, 5 methods, 39 top-level resources.

| Finding | Done | 
| --- | --- |
| Errors were FastAPI's `{"detail": ...}`, with a second shape (`detail` + `reason`) for upstream 503s, and framework answers (404 unknown path, 405, 422) in a third | One envelope via exception handlers on the app; `detail`/`reason` kept so `shell/api.ts` and `chat/api.ts` keep working |
| Unhandled exceptions gave Starlette's plain-text `Internal Server Error` | JSON 500 envelope, no exception text |
| `/transactions` paged with `limit`/`offset`, other lists with `limit` only, with the bounds written per route | Convention is limit/offset; `/portfolio/transactions` moved to the shared `paging.page` dependency (same names, defaults 200/1000, same schema) |
| Other lists keep `limit` alone: `/search` (20..50), `/journal` (500), `/portfolio/...` at lines with limit 50 and 200 | Left: they are top-N windows, not collections a client walks. Adding `offset` is additive, do it when a caller needs it |
| Paths and fields are already kebab / snake | Locked by test |
| camelCase fields in the AG-UI models (`threadId`, `runId`, `toolCalls`, `subagentRunId`, `mimeType`, ...) | Left: the wire format of the protocol the chat speaks, which the shell and `chat/api.ts` consume. v2 candidate |
| Mixed plural/singular roots: `/me`, `/nav`, `/progress`, `/profile`, `/prefs` (singletons) next to `/sectors`, `/connections`, `/watchlist`; `/extremes`, `/movers` as nouns without an id | Left: singletons are intentionally singular, and renaming breaks the shell and the MCP connector. v2 candidate: `/watchlist` -> `/watchlists`-style consistency is not worth a break |
| Status codes used: 200/201/202/204, 401, 403, 404, 409, 413, 415, 422 (the most used), 429, 502, 503 | Consistent enough. 401 vs 403: 401 no/invalid credentials, 403 authenticated but refused. 422 for bad input, 409 for state conflicts |
| Streaming routes (chat SSE) report failures as in-stream events once the stream has started, not as HTTP errors | Left: inherent to SSE; the envelope applies to anything refused before the first byte |
| `/chat/runs/...` public `holds` routes authenticate by run token, not account | By design, documented in `api/runs.py` |
| `/v1/journal.md`, `/portfolio/transactions.csv` return non-JSON on success | Allowed; errors on them are still the JSON envelope |
| OpenAPI is published only off Cloud Run (`STOCKS_API_DOCS=1` to override) | Left. Third-party docs need it published: decide when the API opens |

## v2 candidates (would break a client)

- Drop top-level `detail` and `reason`; keep `error.{code,message}` and move
  `reason` into `error`.
- Replace i18n keys in `message` with plain text plus a `code`.
- Snake-case the AG-UI models, or version them as their own protocol.
- Singular/plural normalisation of roots, `limit`/`offset` and `total` on
  every list.
