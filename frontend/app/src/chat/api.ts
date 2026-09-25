/**
 * The drawer's half of `/api/v1/chat`, including the one route that streams.
 *
 * Everything that answers JSON goes through `shell/api` so the credentials,
 * the CSRF story (a JSON body no cross-site form can send) and the error shape
 * — `NotSignedIn`, `ApiError` — are the shell's, not a second set invented
 * here. Only `ask` is local, because `get`/`send` parse the body as JSON and a
 * turn arrives as `text/event-stream`.
 */

import { ApiError, NotSignedIn, get, retryAfter, send } from "../shell/api";
import { keyHeaders } from "./sessionKey";
import type {
  ChatState,
  Committed,
  Conversation,
  Done,
  ImportRow,
  Meta,
  Preview,
  SettingsPatch,
  Thread,
} from "./types";

const id = (cid: string) => encodeURIComponent(cid);

/** The error a failed response stands for — `shell/api`'s, for local fetches. */
async function refusal(response: Response): Promise<never> {
  if (response.status === 401) throw new NotSignedIn();
  const detail = await response
    .json()
    .then((parsed: { detail?: string; reason?: string }) => parsed)
    .catch(() => ({}) as { detail?: string; reason?: string });
  throw new ApiError(
    response.status,
    detail.detail ?? response.statusText,
    detail.reason,
    retryAfter(response),
  );
}

/**
 * `shell/api`'s `get`/`send`, plus the tab's session-only key when it holds one.
 *
 * Only the calls whose answer depends on which key would serve go through
 * here: the state (who answers), the settings patch (it answers with the
 * state), the attachment read (the column mapper runs on the account's
 * provider) and the walkthrough's advance (its one generated line). Everything
 * else stays on the shell's helpers, so the key rides on as few requests as
 * it can.
 */
export async function keyed<T>(
  verb: "GET" | "POST" | "PATCH",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: verb,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(verb === "GET" ? {} : { "Content-Type": "application/json" }),
      ...keyHeaders(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) await refusal(response);
  return (await response.json()) as T;
}

export const readState = () => keyed<ChatState>("GET", "/chat/state");

export const readThreads = () =>
  get<{ conversations: Conversation[] }>("/chat/conversations").then(
    (body) => body.conversations,
  );

export const readThread = (cid: string) =>
  get<Thread>(`/chat/conversations/${id(cid)}`);

export const startThread = () => send<Conversation>("POST", "/chat/conversations", {});

export const editThread = (cid: string, body: { title?: string; active?: boolean }) =>
  send<Conversation>("PATCH", `/chat/conversations/${id(cid)}`, body);

export const dropThread = (cid: string) =>
  send<void>("DELETE", `/chat/conversations/${id(cid)}`);

export const saveSettings = (body: SettingsPatch) =>
  keyed<ChatState>("PATCH", "/chat/settings", body);

/**
 * Read a statement attached to the thread. Writes no ledger rows.
 *
 * The file travels as base64 inside a JSON body for the reason every write
 * here does: a cross-site form can send multipart, and cannot send
 * `application/json`. The ~33% overhead is nothing against a statement.
 */
export const readAttachment = (body: {
  filename: string;
  content: string;
  conversation?: string;
  lang?: string;
}) => keyed<Preview>("POST", "/chat/attachments", body);

/**
 * Write the rows the preview showed.
 *
 * The rows go back up rather than the file: re-reading an export no parser
 * owns would mean a second model call, whose mapping can differ from the one
 * that was just approved on screen.
 */
export const commitAttachment = (body: {
  filename: string;
  platform: string;
  broker: string;
  rows: ImportRow[];
  conversation?: string;
  lang?: string;
}) => send<Committed>("POST", "/chat/attachments/commit", body);

/**
 * A Blob as base64, via FileReader.
 *
 * `readAsDataURL` gives `data:<type>;base64,<payload>`, and the payload is
 * padded base64 with no line breaks — what the API's `b64decode(validate=True)`
 * insists on. The Import page reads its own uploads the same way.
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

/**
 * Hand a provider key over to be stored, and take the new state back.
 *
 * The key travels in a JSON body and in nothing else: not in the path, not in
 * a query, not in a log line here or anywhere this module can reach. The reply
 * is the whole state, so one round trip both stores the key and says who
 * answers now — which changes, because a provider with a key of its own goes
 * to the head of the chain.
 *
 * A 503 is this deployment saying it has no encryption secret and will not
 * write a provider key in the clear. It is a refusal, not a hiccup: the caller
 * says so and does not retry.
 */
export const storeKey = (provider: string, key: string) =>
  send<ChatState>("PUT", `/chat/keys/${id(provider)}`, { key });

/**
 * The stored key, in full — the Streamlit panel's "Show key".
 *
 * A POST with an empty body rather than a GET: the one request any page can
 * make is a GET, and a secret has no business in a response a prefetch might
 * cache. Session only on the server (a bearer token is refused), and the
 * caller holds the answer in component state for as long as it is on screen
 * and no longer.
 */
export const revealKey = (provider: string) =>
  send<{ provider: string; key: string }>(
    "POST",
    `/chat/keys/${id(provider)}/reveal`,
    {},
  ).then((body) => body.key);

/** Forget the stored key. 404 when there was none, which is not an error here. */
export const forgetKey = (provider: string) =>
  send<ChatState>("DELETE", `/chat/keys/${id(provider)}`);

// --------------------------------------------------------------- the stream

/** One parsed SSE block: its event name and its decoded `data:` payload. */
type Frame = { event: string; data: unknown };

/**
 * One `event:`/`data:` block, or null for anything that is not a frame.
 *
 * A line opening with `:` is a comment — the server sends one immediately so
 * this reader resolves before the model has said anything — and a block of
 * nothing but comments is not an event. `data:` may legally repeat, so the
 * lines are joined before they are parsed, even though this server never
 * splits one (JSON never contains a raw newline).
 */
function parse(block: string): Frame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const cut = line.indexOf(":");
    const field = cut < 0 ? line : line.slice(0, cut);
    const value = cut < 0 ? "" : line.slice(cut + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) as unknown };
  } catch {
    // A truncated frame is the connection dying mid-write, which the caller
    // already handles as a turn that produced no answer. Dropping it here
    // keeps one failure path instead of two.
    return null;
  }
}

/**
 * Ask, and hand the answer over as it is written.
 *
 * Resolves with the `done` frame, which is authoritative: `done.text` is the
 * finished answer and the chunks are only what made the wait bearable. A
 * stream that ends without one is a dropped connection, and it resolves as the
 * same refusal the server would have sent rather than as a thrown error the
 * composer would have to translate a second way.
 *
 * `signal` is the exception to that: an abort *throws*, because a stopped turn
 * is not a failed one and the caller keeps the words that had already arrived.
 */
export async function ask(
  body: {
    message?: string;
    /** Answer the question already on the thread again. Sent without a message. */
    regenerate?: boolean;
    /** The statement a preview card is waiting on, when there is one. */
    staged_import?: string;
    conversation?: string;
    lang?: string;
    /** The page slug the reader is on, for the prompt's "Current view". */
    view?: string;
    /** The ticker on screen, so "is it cheap?" has an "it". */
    focus?: string;
  },
  onMeta: (meta: Meta) => void,
  onText: (chunk: string) => void,
  onPhase: (phase: string) => void,
  signal?: AbortSignal,
): Promise<Done> {
  const response = await fetch("/api/v1/chat/messages", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      // A key held for this tab only, when there is one (`sessionKey.ts`).
      ...keyHeaders(),
    },
    body: JSON.stringify(body),
    // Aborting rejects both the fetch and the reader below, so a stop takes
    // effect between two chunks rather than at the end of the answer.
    signal,
  });
  if (!response.ok) await refusal(response);

  const reader = response.body?.getReader();
  if (!reader) throw new ApiError(response.status, "the response carried no body");

  const decoder = new TextDecoder();
  let buffer = "";
  let done: Done | null = null;
  for (;;) {
    const step = await reader.read();
    if (step.done) break;
    // CRLF is normalised on the way in so the block split below has one
    // separator to look for rather than three.
    buffer += decoder.decode(step.value, { stream: true }).replace(/\r\n/g, "\n");
    for (let cut = buffer.indexOf("\n\n"); cut >= 0; cut = buffer.indexOf("\n\n")) {
      const frame = parse(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (!frame) continue;
      if (frame.event === "phase") onPhase((frame.data as { phase: string }).phase);
      else if (frame.event === "meta") onMeta(frame.data as Meta);
      else if (frame.event === "text") onText((frame.data as { chunk: string }).chunk);
      else if (frame.event === "done") done = frame.data as Done;
    }
  }
  return (
    done ?? {
      text: "",
      skills: [],
      sources: [],
      provider: null,
      error: "chat.api_error",
    }
  );
}
