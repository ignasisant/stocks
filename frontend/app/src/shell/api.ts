/**
 * Typed client for /api/v1 — the one place a page is allowed to reach the network.
 *
 * Authentication is the session cookie the app already set, so nothing here
 * carries a credential: `credentials: "same-origin"` is the whole of it. A 401
 * therefore means "not signed in", which is a state the shell renders rather
 * than an error a page has to handle.
 *
 * Writes go out as JSON, deliberately: a cross-site form post cannot set that
 * content type, and a cross-site fetch that does gets preflighted — which
 * nothing in the API answers. That is the whole CSRF story for the routes that
 * write, and it is why `send` never falls back to a form encoding.
 */

import { begin } from "./activity";
import { noteFreshness } from "./freshness";

const BASE = "/api/v1";

/**
 * A short memo of GET answers, keyed by path and query.
 *
 * The API is cached server-side, so a repeat is cheap — but not free: a page
 * revisited is a dozen round trips before anything draws. Entries live
 * `MEMO_MS`, and an in-flight promise is shared, so two components asking at
 * once make one request (React under StrictMode mounts everything twice).
 *
 * Only a screen *opening* reads it: `useApi` wraps its first fetch in
 * `withMemo`, and a `get` made anywhere else — a poll, a search keystroke, a
 * click handler — always reaches the server. Anything that could change an
 * answer drops the whole memo: a write (`send`), and an explicit reload, retry
 * or changed input (`useApi` calls `invalidate` before re-asking). A failure
 * is not an answer and is not kept.
 */
const MEMO_MS = 60_000;
const memo = new Map<string, { at: number; flight: Flight<unknown> }>();
let memoNext = false;

/**
 * A GET on the wire, and who is still waiting for it.
 *
 * A screen that closes, or a page the reader navigated away from, no longer
 * wants what it asked for, and a request nobody wants should not keep a
 * connection — and the reader's mobile data — busy for the tens of seconds a
 * cold upstream can take. So every `get` made inside a `scoped` call joins its
 * flight as one waiter under that scope's signal, and the flight is aborted
 * once its last waiter has left. Shared flights are why it is a count: the
 * memo hands one request to every screen that asks for it, and one of them
 * closing must not cancel it under the others. A `get` made outside any scope
 * — a click handler, the shell's own reads — pins its flight, which then runs
 * to the end as every request used to.
 *
 * The last waiter leaving is acted on a tick later, not at once: React's
 * StrictMode unmounts and remounts every effect straight away, and the
 * remount joins the same flight from the memo before the tick is up.
 */
type Flight<T> = {
  answer: Promise<T>;
  abort: AbortController;
  waiting: number;
  pinned: boolean;
  done: boolean;
};

let scope: AbortSignal | null = null;

/** Why a flight was aborted: given up on, or no longer wanted by anyone. */
const TIMED_OUT = "timeout";
const UNWANTED = "unwanted";

/** Forget every memoized answer. */
export function invalidate(): void {
  memo.clear();
}

/**
 * Run `fetch` with the memo switched on for the `get` calls it makes
 * synchronously — the ones at the top of a page's fetcher, before its first
 * `await`. Anything after an await is a second stage that already depends
 * on a live answer, and goes live too.
 *
 * With a `signal`, those same calls are also `scoped` to it.
 */
export function withMemo<T>(fetch: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  memoNext = true;
  try {
    return signal ? scoped(signal, fetch) : fetch();
  } finally {
    memoNext = false;
  }
}

/**
 * Run `fetch` with its synchronous `get` calls bound to `signal`: once it
 * aborts, a request only this caller was waiting for is cancelled (see
 * `Flight`). The same before-the-first-await rule as `withMemo` — a get made
 * after one runs unscoped, to the end.
 */
export function scoped<T>(signal: AbortSignal, fetch: () => Promise<T>): Promise<T> {
  const outer = scope;
  scope = signal;
  try {
    return fetch();
  } finally {
    scope = outer;
  }
}

/** A GET abandoned by everyone who asked for it. Nobody is left to show it to. */
export class Cancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "Cancelled";
  }
}

export class NotSignedIn extends Error {
  constructor() {
    super("not signed in");
    this.name = "NotSignedIn";
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly reason?: string,
    /** Seconds, from `Retry-After` — what a 429 says about when to come back. */
    readonly retryAfter?: number,
  ) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }
}

/**
 * Whether this failure is the upstream being unreachable rather than a bug.
 *
 * The API says so in `reason` on both the 503 for a throttled provider and the
 * 429 for a client asking too fast. A page shows those as "try again in a
 * moment"; anything else is a defect and should look like one.
 */
export function isTransient(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    ["rate_limited", "offline", "throttled", "timeout"].includes(error.reason ?? "")
  );
}

/**
 * How long a GET may take before it is given up on.
 *
 * Generous — a cold book priced from scratch or a first SEC insider pull runs
 * into tens of seconds on a throttled host — but finite: a request the upstream
 * never answers would otherwise hold its screen's spinner, and the corner
 * banner, for as long as the tab stays open.
 */
export const TIMEOUT_MS = 90_000;

/** `Retry-After` in seconds, when the server sent one as a number. */
export function retryAfter(response: Response): number | undefined {
  const raw = Number(response.headers.get("Retry-After"));
  return Number.isFinite(raw) && raw > 0 ? raw : undefined;
}

async function fail(response: Response): Promise<never> {
  if (response.status === 401) throw new NotSignedIn();
  const body = await response
    .json()
    .then((parsed: { detail?: string; reason?: string }) => parsed)
    .catch(() => ({}) as { detail?: string; reason?: string });
  throw new ApiError(
    response.status,
    body.detail ?? response.statusText,
    body.reason,
    retryAfter(response),
  );
}

export async function get<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v !== undefined);
  const query = entries.length
    ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}`
    : "";
  const url = `${BASE}${path}${query}`;
  if (!memoNext) return join(start<T>(url), scope);
  const hit = memo.get(url);
  if (hit && Date.now() - hit.at < MEMO_MS) return join(hit.flight as Flight<T>, scope);
  const flight = start<T>(url);
  memo.set(url, { at: Date.now(), flight });
  flight.answer.catch(() => {
    if (memo.get(url)?.flight === flight) memo.delete(url);
  });
  return join(flight, scope);
}

function start<T>(url: string): Flight<T> {
  const abort = new AbortController();
  const flight: Flight<T> = {
    answer: fetchJson<T>(url, abort),
    abort,
    waiting: 0,
    pinned: false,
    done: false,
  };
  const land = () => {
    flight.done = true;
  };
  flight.answer.then(land, land);
  return flight;
}

/** One more caller waiting on `flight`, for as long as `signal` lets it. */
function join<T>(flight: Flight<T>, signal: AbortSignal | null): Promise<T> {
  if (flight.done) return flight.answer;
  if (!signal) {
    flight.pinned = true;
    return flight.answer;
  }
  flight.waiting += 1;
  const leave = () => {
    flight.waiting -= 1;
    setTimeout(() => {
      if (!flight.done && !flight.pinned && flight.waiting === 0) {
        flight.abort.abort(UNWANTED);
      }
    }, 0);
  };
  if (signal.aborted) leave();
  else signal.addEventListener("abort", leave, { once: true });
  return flight.answer;
}

async function fetchJson<T>(url: string, abort: AbortController): Promise<T> {
  // Out until the body has arrived, not just the headers: the corner banner
  // (`shell/activity`) counts what a reader is actually still waiting for.
  const landed = begin(url);
  try {
    return await read<T>(url, abort);
  } finally {
    landed();
  }
}

async function read<T>(url: string, abort: AbortController): Promise<T> {
  const timer = setTimeout(() => abort.abort(TIMED_OUT), TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: abort.signal,
    });
    if (!response.ok) await fail(response);
    // What the server had to say about the age of these figures, if anything.
    noteFreshness(url, response.headers.get("x-data-stale-since"));
    return (await response.json()) as T;
  } catch (error) {
    if (abort.signal.aborted) {
      if (abort.signal.reason === UNWANTED) throw new Cancelled();
      // Transient, so a page says "retry in a moment" rather than "failed".
      throw new ApiError(504, "timed out", "timeout");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

type Verb = "POST" | "PATCH" | "PUT" | "DELETE";

export async function send<T>(
  verb: Verb,
  path: string,
  body?: unknown,
  headers?: Record<string, string>,
): Promise<T> {
  // Whatever this changes, a memoized answer may now be wrong about it.
  invalidate();
  const response = await fetch(`${BASE}${path}`, {
    method: verb,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) await fail(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
