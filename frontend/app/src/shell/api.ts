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

const BASE = "/api/v1";

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
    ["rate_limited", "offline", "throttled"].includes(error.reason ?? "")
  );
}

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
  const response = await fetch(`${BASE}${path}${query}`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) await fail(response);
  return (await response.json()) as T;
}

type Verb = "POST" | "PATCH" | "PUT" | "DELETE";

export async function send<T>(verb: Verb, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: verb,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) await fail(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
