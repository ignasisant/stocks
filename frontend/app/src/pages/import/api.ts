/**
 * The importer's slice of `/api/v1`, and the one place that turns a file the
 * reader picked into something the API will accept.
 *
 * The file travels as base64 inside a JSON body. That is deliberate and must
 * stay that way: a cross-site HTML form can send multipart, so accepting it
 * would hand back the CSRF hole every other write here avoids by requiring
 * `application/json`. The ~33% encoding overhead is nothing against a
 * statement.
 *
 * A parser that cannot read a file answers 422, and a file over the cap
 * answers 413. Neither is a failure of the request — they are the answer, and
 * the reader has to act on them — so they come back as data rather than as a
 * thrown error the shell would render as "something went wrong". Anything else
 * is rethrown and reaches `<Loaded>` as the defect it is.
 */

import { ApiError, get, send } from "../../shell/api";

/** Mirrors `MAX_BYTES` in `api/routes/import_statement.py`. Checked here so a
 *  file too big to send is refused before it is uploaded, not after. */
export const MAX_BYTES = 8 * 1024 * 1024;

export type Platform = {
  key: string;
  label: string;
  file_types: string[];
  hint: string;
  domain: string | null;
  has_sample: boolean;
};

export type Platforms = { platforms: Platform[] };

export type Issue = {
  /** "error" | "warning". */
  severity: string;
  field: string;
  /** i18n key, e.g. `validate.oversell` — the catalog renders it. */
  key: string;
  params: Record<string, string | number>;
  /** English rendering, and only a fallback for a key the catalog lacks. */
  message: string;
};

export type Row = {
  date: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  currency: string;
  fee: number;
  note: string;
  issues: Issue[];
  duplicate: boolean;
};

export type SkippedRow = Record<string, string | number | boolean | null>;

export type Preview = {
  platform: string;
  filename: string;
  digest: string;
  /** Clean and warned rows — exactly what a commit writes. */
  importable: Row[];
  /** Failed validation: quarantined, never committed. */
  rejected: Row[];
  duplicates: number;
  /** Left out by the parser by design: cash, fees, tax lines. */
  skipped: SkippedRow[];
  broker: string;
  needs_broker: boolean;
};

export type Result = {
  platform: string;
  filename: string;
  imported: number;
  tx_ids: number[];
  broker: string;
  imported_at: string;
  /** Re-validated at commit time and refused — what it actually did. */
  rejected: Row[];
};

/** A committed ledger row, as `/import/last` sends the ones that survive. */
type LedgerRow = {
  id: number | null;
  date: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  currency: string;
  fee: number;
  note: string;
};

export type LastImport = {
  filename: string | null;
  imported_at: string | null;
  platform: string | null;
  /** Rows the commit wrote. */
  rows: number;
  /** How many of them are still in the ledger — what an undo would take. */
  still_here: number;
  transactions: LedgerRow[];
  wiped: boolean;
};

/**
 * What the book holds, and how much of it was never real.
 *
 * `demo` is counted here rather than asked for, because no endpoint reports it:
 * the rule is the server's own and written down in `POST /v1/portfolio/demo` —
 * a demo row is marked by the note's first word, which is what `fees.broker_of`
 * reads. Two things on this page need it. The example statement is only offered
 * to an account with nothing real to lose, and the caption that says importing
 * removes the demo rows has to name how many.
 *
 * `complete` is whether the page saw every row. Past that many rows nothing is
 * claimed: a partial count printed as a total would be a wrong number, and a
 * book bigger than the page fetches is a book with real rows in it anyway —
 * `demo.seed` refuses a ledger that holds anything, so demo rows only ever
 * exist in a book that is nothing else.
 */
export type Book = { total: number; demo: number; complete: boolean };

/** `demo.BROKER` — the note's first word on every seeded row. */
const DEMO = "demo";

/** Whether a ledger row came from the demo book — `demo.is_demo`, same rule. */
export const isDemo = (note: string): boolean =>
  note.trim().split(/\s+/)[0]?.toLowerCase() === DEMO;

/** A file staged for preview: its name, its bytes as base64, and how many. */
export type Staged = { filename: string; content: string; bytes: number };

/**
 * Something the API refused, which the reader has to fix — not a defect.
 *
 * `unreadable` carries the parser's own reason, which is the only useful part
 * of a 422: "ClickTrade could not read this file: no header row".
 */
export type Refusal =
  | { kind: "unreadable"; detail: string }
  | { kind: "too_large" }
  | { kind: "changed" }
  | { kind: "refused"; detail: string };

function refusalOf(error: unknown): Refusal | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 413) return { kind: "too_large" };
  if (error.status === 409) return { kind: "changed" };
  if (error.status === 422) return { kind: "unreadable", detail: error.detail };
  if (error.status === 404) return { kind: "refused", detail: error.detail };
  return null;
}

export type Outcome<T> = { ok: true; value: T } | { ok: false; refusal: Refusal };

async function attempt<T>(run: () => Promise<T>): Promise<Outcome<T>> {
  try {
    return { ok: true, value: await run() };
  } catch (error) {
    const refusal = refusalOf(error);
    if (refusal) return { ok: false, refusal };
    throw error; // a real failure — the shell draws it, with a retry
  }
}

export const listPlatforms = () => get<Platforms>("/import/platforms");

/** How many rows a page of the ledger is read for the demo count. */
const SCAN_ROWS = 200;

/** The ledger's size, and how much of it is the demo book. */
export const book = async (): Promise<Book> => {
  const page = await get<{ total: number; transactions: { note: string }[] }>(
    "/portfolio/transactions",
    { limit: SCAN_ROWS },
  );
  const demo = page.transactions.filter((row) => isDemo(row.note)).length;
  return {
    total: page.total,
    demo,
    complete: page.transactions.length >= page.total,
  };
};

export const lastImport = () => get<LastImport>("/import/last");

/**
 * Parse and validate a statement, writing nothing.
 *
 * `wipe` is not a write here and still belongs on the preview: with it set,
 * validation runs against an empty ledger, so nothing is flagged as a
 * duplicate of a row that is about to be deleted and no sell is rejected
 * against buys that are about to go. A preview taken without it would be a
 * preview of a different import.
 */
export const preview = (platform: string, file: Staged, wipe: boolean) =>
  attempt(() =>
    send<Preview>("POST", "/import/preview", {
      platform,
      filename: file.filename,
      content: file.content,
      wipe,
    }),
  );

/**
 * Write the importable rows.
 *
 * `expect` is the preview's digest: given it, a file that changed underneath
 * the reader is refused with a 409 rather than committed as something nobody
 * ever saw. The commit re-parses and re-validates regardless, so its answer —
 * not the preview's — is what actually happened.
 */
export const commit = (
  platform: string,
  file: Staged,
  broker: string,
  expect: string,
  wipe: { on: boolean; confirm: string },
) =>
  attempt(() =>
    send<Result>("POST", "/import/commit", {
      platform,
      filename: file.filename,
      content: file.content,
      broker,
      expect,
      wipe: wipe.on,
      // The two halves travel together on purpose: a client that emptied the
      // book with `DELETE /portfolio/transactions` and then failed its commit
      // would hold an empty ledger and no undo. Here nothing is deleted until
      // the statement has parsed, validated and produced rows worth writing.
      wipe_confirm: wipe.on ? wipe.confirm : "",
    }),
  );

/** Delete exactly the rows the last commit inserted. */
export const undoLast = () => attempt(() => send<LastImport>("DELETE", "/import/last"));

/**
 * A Blob as base64, via FileReader.
 *
 * `readAsDataURL` gives `data:<type>;base64,<payload>`, and the payload is
 * standard padded base64 with no line breaks — which is what the API's
 * `b64decode(validate=True)` insists on.
 */
export function asBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("file could not be read"));
    reader.onload = () => {
      const url = String(reader.result);
      const comma = url.indexOf(",");
      if (comma < 0) reject(new Error("file could not be read"));
      else resolve(url.slice(comma + 1));
    };
    reader.readAsDataURL(blob);
  });
}

/** Delete the last-import note and nothing else — the rows stay in the book. */
export const dismissRecord = () => send<LastImport>("DELETE", "/import/record");

/**
 * Empty the book. Every row, not one batch — and there is no undo.
 *
 * `confirm` is the signed-in address typed back, which is what the route
 * demands: a request that destroys a ledger has to name the ledger it is
 * destroying, so no client can do this by accident.
 */
export const wipeLedger = (confirm: string) =>
  send<{ removed: number }>("DELETE", "/portfolio/transactions", { confirm });

/* ------------------------------------------------------------- the repairs */

/**
 * One split the ledger never heard about, with the evidence that found it.
 *
 * Every figure is nullable because every one of them can genuinely be missing —
 * a holding Yahoo would not price has no close to divide by — and a missing
 * figure is not a zero. The proposal travels with its evidence because it is
 * only worth acting on beside it: this holding was bought at `priced_at` on
 * `priced_on`, a day whose split-adjusted close was `market_close`, and the
 * quotient of those two is a split nobody recorded.
 */
export type SplitGap = {
  ticker: string;
  /** The split's own day, YYYY-MM-DD. */
  date: string;
  /** Shares out per share in — 20 for a 20-for-1 split. */
  ratio: number;
  held_before: number | null;
  held_after: number | null;
  priced_at: number | null;
  priced_on: string;
  market_close: number | null;
  currency: string;
};

export type SplitGaps = {
  splits: SplitGap[];
  /** Yahoo was refusing this deployment: an empty list means "could not tell". */
  throttled: boolean;
};

export type SplitsApplied = { applied: number; splits: SplitGap[] };

/** One departure and one arrival that are the same shares changing custodian. */
export type Move = {
  ticker_out: string;
  /** How the receiving broker labels it — and the label that survives. */
  ticker_in: string;
  quantity: number | null;
  broker_out: string;
  broker_in: string;
  date_out: string;
  date_in: string;
  /** Per-share price the departure was booked at: the market print. */
  booked_at: number | null;
  basis_out: number | null;
  /** Per-share cost the arrival carries. That this matches `basis_out` and not
   *  `booked_at` is the whole of the evidence. */
  basis_in: number | null;
  phantom_gain: number | null;
  currency: string;
  rekey: boolean;
  out_ids: number[];
  in_id: number | null;
};

export type Moves = { moves: Move[] };

export type MovesApplied = { applied: number; moves: Move[] };

/** Price every holding against Yahoo and report the splits the book lacks. */
export const scanSplits = () => get<SplitGaps>("/import/splits/scan");

/**
 * Write the named splits, and only those.
 *
 * Named rather than "all": the scan shows its evidence one row at a time, and a
 * reader who believes one of them and not another has to be able to say so. The
 * body says *which* split and never what it is — the ratio and the row that
 * lands in the ledger come from a scan the server runs again, so a name this
 * ledger no longer misses is a 409 and nothing is written.
 */
export const applySplits = (picks: { ticker: string; date: string }[]) =>
  send<SplitsApplied>("POST", "/import/splits/apply", { splits: picks });

/** Departures and arrivals in this book that are one move of shares. */
export const scanMoves = () => get<Moves>("/import/moves/scan");

/**
 * Book the named moves as transfers.
 *
 * Named by the ledger ids the scan handed back, not by ticker and date: two
 * equal parcels of one security leaving the same broker on the same day differ
 * in nothing else, and accepting "one of them" under a name they share would
 * accept both.
 */
export const applyMoves = (picks: { out_ids: number[]; in_id: number | null }[]) =>
  send<MovesApplied>("POST", "/import/moves/apply", { moves: picks });

/* ------------------------------------------------------ the example statement */

/**
 * `/api/v1`, because the shell's client keeps it private and this is the one
 * call on the page that does not want JSON back.
 */
const BASE = "/api/v1";

/** The filename the response carries, which is the one the parser reads. */
export function namedBy(disposition: string | null): string | null {
  const match = /filename="?([^";]+)"?/.exec(disposition ?? "");
  return match?.[1]?.trim() || null;
}

/**
 * The shipped example statement, as the bytes a file picker would have handed
 * over.
 *
 * Deliberately not a route of its own through the app: these bytes go into the
 * same `stage -> preview -> commit -> undo` path a real upload takes, which is
 * the whole point of shipping a real statement rather than fabricating a
 * ledger. A separate "load the demo" path would be the one that drifts, and the
 * reader would learn a flow they never use again.
 *
 * `null` for every refusal, because there is nothing to say: 404 is both "this
 * platform ships no example" and "this deployment was trimmed", and the page's
 * answer to either is to not offer one. A raw `fetch` rather than the shell's
 * client only because that client parses JSON and this is a file; the cookie,
 * the origin and the base path are the same.
 */
export async function sampleStatement(
  platform: string,
): Promise<{ filename: string; blob: Blob } | null> {
  try {
    const response = await fetch(
      `${BASE}/import/sample?platform=${encodeURIComponent(platform)}`,
      { credentials: "same-origin" },
    );
    if (!response.ok) return null;
    const blob = await response.blob();
    if (blob.size === 0) return null;
    return {
      filename: namedBy(response.headers.get("Content-Disposition")) ?? "",
      blob,
    };
  } catch {
    return null;
  }
}
