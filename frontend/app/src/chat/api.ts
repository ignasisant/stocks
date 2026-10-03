/**
 * The drawer's half of `/api/v1/chat`, including the one route that streams.
 *
 * Everything that answers JSON goes through `shell/api` so the credentials,
 * the CSRF story (a JSON body no cross-site form can send) and the error shape
 * — `NotSignedIn`, `ApiError` — are the shell's, not a second set invented
 * here. Only `run` is local, because `get`/`send` parse the body as JSON and a
 * turn arrives as `text/event-stream` — an AG-UI event stream.
 */

import type { ResumeEntry, RunAgentInput, Tool } from "@ag-ui/core";
import { ApiError, NotSignedIn, get, retryAfter, send } from "../shell/api";
import type { A2uiAction, A2uiMessage } from "./a2ui";
import { keyHeaders } from "./sessionKey";
import type {
  Activity,
  Arguing,
  ChatState,
  Committed,
  Conversation,
  Done,
  ImportRow,
  Learned,
  LiveStep,
  Memories,
  Memory,
  Meta,
  Preview,
  Proposal,
  Recalled,
  SettingsPatch,
  Thread,
  ToolCall,
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
  /** A corrected column mapping (the preview surface's): read with no model. */
  mapping?: Record<string, unknown>;
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

/**
 * A press on a surface the assistant drew (A2UI's client-to-server action),
 * answered with the messages that update it — a what-if slider let go comes
 * back as its new figures. No model is asked, and nothing is stored.
 */
export const pressSurface = (action: A2uiAction, lang?: string) =>
  send<{ messages: A2uiMessage[] }>("POST", "/chat/actions", { action, lang }).then(
    (body) => body.messages,
  );

/**
 * Take back a ledger edit the chat made. 409 when it is not one, or its rows
 * were changed again since — the detail is the locale key that says which.
 */
export const undoProposal = (pid: string, lang?: string) =>
  send<{ text: string; proposal: Proposal }>(
    "POST",
    `/chat/proposals/${id(pid)}/undo${lang ? `?lang=${encodeURIComponent(lang)}` : ""}`,
    {},
  );

/** Forget the stored key. 404 when there was none, which is not an error here. */
export const forgetKey = (provider: string) =>
  send<ChatState>("DELETE", `/chat/keys/${id(provider)}`);

// ------------------------------------------------------------ the memories

/** Everything the assistant remembers about the account, and its switches. */
export const readMemories = () => get<Memories>("/chat/memories");

/** Save one memory. 409 when the list is full: one has to go first. */
export const addMemory = (body: { text: string; kind?: string }) =>
  send<Memory>("POST", "/chat/memories", body);

export const editMemory = (lid: string, body: { text?: string; kind?: string }) =>
  send<Memory>("PATCH", `/chat/memories/${id(lid)}`, body);

/** Forget one. 404 when it is already gone — an undo that removed nothing. */
export const dropMemory = (lid: string) =>
  send<void>("DELETE", `/chat/memories/${id(lid)}`);

/** Forget every memory. Conversations are not touched. */
export const clearMemories = () => send<void>("DELETE", "/chat/memories");

// --------------------------------------------------------------- the stream

/**
 * The AG-UI events this drawer reads, as they arrive on the wire.
 *
 * Local rather than `@ag-ui/core`'s `AGUIEvent`: that union is keyed on a
 * TypeScript enum, and narrowing it by `type` needs the enum at runtime —
 * which is the package's zod schemas in the shell chunk every reader pays for.
 * The shapes are the protocol's; anything else the server sends is skipped.
 */
type Wire =
  | { type: "STEP_STARTED"; stepName: string }
  | { type: "CUSTOM"; name: string; value: unknown }
  | {
      type: "TEXT_MESSAGE_CONTENT";
      messageId: string;
      delta: string;
      subagentRunId?: string;
    }
  | { type: "SUBAGENT_STARTED"; subagentRunId: string; name: string }
  | { type: "SUBAGENT_FINISHED"; subagentRunId: string }
  | { type: "SUBAGENT_ERROR"; subagentRunId: string; code?: string }
  | { type: "TOOL_CALL_START"; toolCallId: string; toolCallName: string }
  | { type: "TOOL_CALL_ARGS"; toolCallId: string; delta: string }
  | { type: "TOOL_CALL_END"; toolCallId: string }
  | { type: "TOOL_CALL_RESULT"; toolCallId: string; content: string }
  | {
      type: "ACTIVITY_SNAPSHOT";
      messageId: string;
      activityType: string;
      content: Activity["content"];
    }
  | { type: "RUN_FINISHED"; result?: Partial<Done> }
  | { type: "RUN_ERROR"; message: string; code?: string };

/**
 * One SSE block's `data:` payload, or null for anything that is not an event.
 *
 * AG-UI frames carry their type inside the JSON, so there is no `event:` line
 * to read. A line opening with `:` is a comment — the server sends one
 * immediately so this reader resolves before the model has said anything.
 * `data:` may legally repeat, so the lines are joined before they are parsed,
 * even though this server never splits one (JSON never contains a raw newline).
 */
function parse(block: string): Wire | null {
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    const event = JSON.parse(data.join("\n")) as unknown;
    return event && typeof event === "object" && "type" in event
      ? (event as Wire)
      : null;
  } catch {
    // A truncated frame is the connection dying mid-write, which the caller
    // already handles as a turn that produced no answer. Dropping it here
    // keeps one failure path instead of two.
    return null;
  }
}

/** The frontend tools this drawer runs, declared on every run. */
const TOOLS: Tool[] = [
  {
    name: "navigate",
    description: "Offer the reader a button that opens one of the app's pages.",
    parameters: {
      type: "object",
      properties: {
        page: { type: "string" },
        tab: { type: "string" },
        ticker: { type: "string" },
        step: { type: "string" },
      },
    },
  },
];

/**
 * The calls this drawer runs or answers itself. Every other tool call on the
 * stream is research the server ran — told as it happens, and filed on the
 * answer as its `steps`.
 */
const FRONTEND = new Set(["navigate", "confirm_action"]);

const ARG_KEYS = ["query", "url", "tickers", "ticker", "symbol"];

/**
 * The argument that identifies a call — the query, the URL, the tickers — as
 * the server's `_step_arg` picks it, so a live line reads exactly like the
 * trace line that replaces it when the answer lands.
 */
function stepArg(raw: string): string {
  let args: Record<string, unknown> = {};
  try {
    args = JSON.parse(raw || "{}") as Record<string, unknown>;
  } catch {
    return "";
  }
  const key = ARG_KEYS.find((name) => args[name]);
  const value = key
    ? args[key]
    : Object.keys(args)
        .sort()
        .map((name) => args[name])
        .find(Boolean);
  const text = Array.isArray(value) ? value.join(", ") : String(value ?? "");
  return text.split(/\s+/).filter(Boolean).join(" ").slice(0, 56);
}

/** What one run asks: a question, a regenerate, or an answer to a proposal. */
export type Ask =
  | { message: string; regenerate?: never; resume?: never }
  | { regenerate: true; message?: never; resume?: never }
  | { resume: ResumeEntry; message?: never; regenerate?: never };

const fresh = () =>
  globalThis.crypto?.randomUUID?.() ??
  `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/**
 * The run as AG-UI's `RunAgentInput`.
 *
 * Only the new message travels: the thread on disk is the history, and the
 * server reads nothing else of `messages`. Where the reader is rides in
 * `state`; what AG-UI has no field for (the language, regenerate, the staged
 * statement) in `forwardedProps`.
 */
export function runInput(
  ask: Ask,
  where: {
    conversation?: string;
    lang?: string;
    /** The page slug the reader is on, for the prompt's "Current view". */
    view?: string;
    /** The ticker on screen, so "is it cheap?" has an "it". */
    focus?: string;
    /** The statement a preview card is waiting on, when there is one. */
    staged_import?: string;
  },
): RunAgentInput {
  const props: Record<string, unknown> = {};
  if (where.lang) props.lang = where.lang;
  if (ask.regenerate) props.regenerate = true;
  if (where.staged_import && ask.message !== undefined)
    props.staged_import = where.staged_import;
  return {
    threadId: where.conversation ?? "",
    runId: fresh(),
    messages:
      ask.message !== undefined
        ? [{ id: fresh(), role: "user", content: ask.message }]
        : [],
    state: { view: where.view ?? "", ...(where.focus ? { focus: where.focus } : {}) },
    tools: TOOLS,
    context: [],
    forwardedProps: props,
    ...(ask.resume ? { resume: [ask.resume] } : {}),
  };
}

/**
 * Run the assistant, and hand the answer over as it is written.
 *
 * Resolves with how the run ended, which is authoritative: `RUN_FINISHED`'s
 * `result.text` is the finished answer and the deltas are only what made the
 * wait bearable. A stream that ends without an ending is a dropped
 * connection, and it resolves as the same refusal the server would have sent
 * rather than as a thrown error the composer would have to translate a second
 * way.
 *
 * `signal` is the exception to that: an abort *throws*, because a stopped turn
 * is not a failed one and the caller keeps the words that had already arrived.
 */
export async function run(
  input: RunAgentInput,
  onMeta: (meta: Meta) => void,
  onText: (chunk: string) => void,
  onPhase: (phase: string) => void,
  signal?: AbortSignal,
  /** A piece of research starting, and again once it has come back. */
  onTool?: (line: LiveStep) => void,
  /** A side of the bull/bear debate starting, speaking, ending or failing. */
  onSide?: (side: Arguing) => void,
  /** The earlier conversations the answer was handed, before it is written. */
  onRecalled?: (recalled: Recalled[]) => void,
): Promise<Done> {
  const response = await fetch("/api/v1/chat/runs", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      // A key held for this tab only, when there is one (`sessionKey.ts`).
      ...keyHeaders(),
    },
    body: JSON.stringify(input),
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
  // Tool calls as they are assembled: named on START, argued in pieces.
  const calls = new Map<string, { name: string; args: string }>();
  // Surfaces by activity id: a later snapshot of the same one replaces it.
  const activities = new Map<string, Activity>();
  // The debate's sides by subagent run id, as they are argued.
  const sides = new Map<string, Arguing>();
  // A memory command the run carried out before it failed: `RUN_ERROR` has
  // no result, so the change arrives ahead of it on its own.
  let learned: Learned[] | undefined;
  const side = (id: string, change: Partial<Arguing>) => {
    const was = sides.get(id);
    if (!was) return;
    const now = { ...was, ...change };
    sides.set(id, now);
    onSide?.(now);
  };
  for (;;) {
    const step = await reader.read();
    if (step.done) break;
    // CRLF is normalised on the way in so the block split below has one
    // separator to look for rather than three.
    buffer += decoder.decode(step.value, { stream: true }).replace(/\r\n/g, "\n");
    for (let cut = buffer.indexOf("\n\n"); cut >= 0; cut = buffer.indexOf("\n\n")) {
      const event = parse(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (!event) continue;
      switch (event.type) {
        case "STEP_STARTED":
          onPhase(event.stepName);
          break;
        case "CUSTOM":
          if (event.name === "chat.meta") onMeta(event.value as Meta);
          else if (event.name === "chat.recalled")
            onRecalled?.(event.value as Recalled[]);
          else if (event.name === "chat.learned") learned = event.value as Learned[];
          break;
        case "TEXT_MESSAGE_CONTENT":
          // A subagent's words are its own: they never join the answer's.
          if (event.subagentRunId) {
            side(event.subagentRunId, {
              text: (sides.get(event.subagentRunId)?.text ?? "") + event.delta,
            });
          } else onText(event.delta);
          break;
        case "SUBAGENT_STARTED": {
          const fresh: Arguing = {
            id: event.subagentRunId,
            side: event.name,
            text: "",
            state: "arguing",
          };
          sides.set(fresh.id, fresh);
          onSide?.(fresh);
          break;
        }
        case "SUBAGENT_FINISHED":
          side(event.subagentRunId, { state: "done" });
          break;
        case "SUBAGENT_ERROR":
          side(event.subagentRunId, { state: "failed" });
          break;
        case "TOOL_CALL_START":
          calls.set(event.toolCallId, { name: event.toolCallName, args: "" });
          break;
        case "TOOL_CALL_ARGS": {
          const call = calls.get(event.toolCallId);
          if (call) call.args += event.delta;
          break;
        }
        case "TOOL_CALL_END": {
          const call = calls.get(event.toolCallId);
          if (call && !FRONTEND.has(call.name)) {
            onTool?.({
              id: event.toolCallId,
              tool: call.name,
              arg: stepArg(call.args),
            });
          }
          break;
        }
        case "TOOL_CALL_RESULT": {
          const call = calls.get(event.toolCallId);
          if (call && !FRONTEND.has(call.name)) {
            onTool?.({
              id: event.toolCallId,
              tool: call.name,
              arg: stepArg(call.args),
              out: String(event.content),
            });
          }
          break;
        }
        case "ACTIVITY_SNAPSHOT":
          activities.set(event.messageId, {
            id: event.messageId,
            type: event.activityType,
            content: event.content,
          });
          break;
        case "RUN_FINISHED":
          done = {
            text: "",
            skills: [],
            sources: [],
            provider: null,
            ...event.result,
            error: null,
            calls: assemble(calls, event.result?.proposal?.id),
            activities: [...activities.values()],
          };
          break;
        case "RUN_ERROR":
          done = {
            ...FAILED,
            error: event.code ?? "chat.api_error",
            ...(learned ? { learned } : {}),
          };
          break;
      }
    }
  }
  return done ?? FAILED;
}

const FAILED: Done = {
  text: "",
  skills: [],
  sources: [],
  provider: null,
  error: "chat.api_error",
  calls: [],
};

/**
 * The finished calls. Arguments are only acted on once whole (AG-UI's rule),
 * and one whose arguments do not parse is dropped rather than half-drawn. The
 * proposal's call starts out pending: that is what the run stopped on.
 */
function assemble(
  calls: Map<string, { name: string; args: string }>,
  asking?: string,
): ToolCall[] {
  const out: ToolCall[] = [];
  for (const [id, call] of calls) {
    if (!FRONTEND.has(call.name)) continue;
    try {
      const args = JSON.parse(call.args || "{}") as Record<string, unknown>;
      out.push({
        id,
        name: call.name,
        args,
        ...(id === asking ? { state: "pending" } : {}),
      });
    } catch {
      continue;
    }
  }
  return out;
}
