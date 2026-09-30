/**
 * What `/api/v1/chat` says, in TypeScript.
 *
 * One file rather than a type beside each call, because the drawer's whole
 * job is holding these four shapes in agreement: the state decides what the
 * composer may offer, the thread list decides what the header says, and a
 * streamed turn has to end up looking exactly like a stored one — otherwise a
 * reload redraws the conversation differently from the way it was written.
 */

import type { A2uiMessage } from "./a2ui";

/** One web hit that grounded an answer. */
type Source = { title: string; url: string };

/** One tool line behind an answer: what ran, on what, and what came back. */
export type Step = { tool: string; arg: string; out: string };

/** One analyst's case in the bull/bear debate an answer weighed. */
export type DebateSide = { side: string; text: string };

/** A side of the debate while it is being argued (session-only). */
export type Arguing = DebateSide & { id: string; state: "arguing" | "done" | "failed" };

/** A tool line while the answer is still being researched: `out` once back. */
export type LiveStep = { id: string; tool: string; arg: string; out?: string };

/**
 * A frontend tool call an answer carried — AG-UI's, as the stream handed it
 * over and as the stored turn reads it back.
 *
 * `navigate` is a button: `{ step }` a walkthrough step, `{ page, tab?,
 * ticker? }` a page. `confirm_action` is a proposal card: `{ kind, ticker,
 * args }` is what would run, and `state` whether it still waits ("pending")
 * or was answered ("done", "cancelled").
 */
export type ToolCall = {
  id: string;
  name: string;
  args: Record<string, unknown>;
  state?: string | null;
};

/** What a `confirm_action` proposes, and where it stands. */
export type Proposal = {
  id: string;
  kind: string;
  ticker: string;
  args: Record<string, unknown>;
  state: "pending" | "done" | "cancelled";
};

/**
 * The reader's edits to a proposal before approving it: its A2UI form as
 * typed, or the symbol and arguments directly.
 */
export type Edits = {
  ticker?: string;
  args?: Record<string, unknown>;
  form?: Record<string, string>;
};

/**
 * An AG-UI activity under an answer. `type` "a2ui" is a surface the server
 * built (`chat/a2ui.tsx` draws it), and `content.messages` its A2UI messages.
 */
export type Activity = {
  id: string;
  type: string;
  content: { messages?: A2uiMessage[] } & Record<string, unknown>;
};

/** One stored turn, as the API returns it. */
type Message = {
  role: string;
  content: string;
  skills: string[];
  web: Source[];
  /** The tool trace. Stored, so a reloaded answer keeps its counter. */
  steps?: Step[];
  action: string | null;
  /**
   * Set on a turn the walkthrough wrote. `step` is the registry id its card
   * presents; `state` is "done" for a receipt and "end" for the last line.
   */
  guide?: { step: string; state?: string } | null;
  /**
   * The buttons and cards under the answer: page links, walkthrough jumps and
   * proposals. Checked on the server before they are stored, and never in the
   * prose — the model's markers are scrubbed from it.
   */
  tool_calls?: ToolCall[];
  /** Surfaces drawn under the answer: a pending proposal's edit form. */
  activities?: Activity[];
  /** The bull and bear cases argued before the answer was written. */
  debate?: DebateSide[];
};

/**
 * A turn on screen: a stored one, plus what only this session knows.
 *
 * The API stores neither a clock nor an elapsed cost (`Message` carries
 * role/content/skills/web/action and nothing else), so both are local and both
 * are absent from a thread read back from the server. A turn is drawn with
 * whatever it has rather than with a zero standing in for what was never
 * recorded.
 */
export type Turn = Message & {
  /** Epoch ms, set when this session wrote the turn. */
  ts?: number;
  /** Seconds the answer took, set when this session watched it arrive. */
  took?: number;
  /** i18n key of the refusal that replaced the answer. */
  error?: string;
  /** Seconds the refusal asks to wait — the burst wall names them. */
  wait?: number;
  /** Still being written — the stream is open. */
  pending?: boolean;
  /**
   * The research happening under a pending answer, as it happens: each tool
   * the server runs, and what it brought back once it has. Session-only and
   * dropped when the answer lands — its `steps` are the same lines, filed.
   */
  live?: LiveStep[];
  /**
   * The debate while it is argued: each side as it starts, speaks and ends.
   * Dropped when the answer lands, which carries the cases as `debate`.
   */
  arguing?: Arguing[];
  /**
   * What the turn is doing before it has words: `gathering`, `searching`,
   * `writing` — the key of the panel's own `chat.work_*` line.
   */
  phase?: string;
  /**
   * The reader stopped this answer before the stream ended.
   *
   * Session-only, and unlike an error it is not even a turn the server knows
   * about: aborting the request cancels the generator before the engine
   * records anything, so the thread on disk holds neither the question nor
   * the words that did arrive. What is on screen is what this session saw.
   */
  stopped?: boolean;
  /**
   * Which provider actually wrote this answer, and which one was supposed to.
   *
   * The `meta` frame names the first provider that produced a chunk, and the
   * chain's head is what `/chat/state` called `answering` when the question
   * went out. When they differ the first one answered for the second, which is
   * the only thing `chat.fallback_note` says. Both are session facts — a
   * stored turn records neither — so a reloaded thread names no provider
   * rather than naming today's.
   */
  by?: string;
  chose?: string;
  /**
   * This question was spoken, not typed.
   *
   * Session-only, like `stopped`: the thread stores the transcript and not how
   * it was dictated, so a reloaded turn is simply a question — which is what it
   * is. The badge is for the reader who is watching their own words arrive
   * through a transcription they did not proof-read.
   */
  spoken?: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  title_auto: boolean;
  created: string;
  updated: string;
  messages: number;
  active: boolean;
};

export type Thread = { id: string; title: string; messages: Message[] };

export type SkillInfo = { id: string; name: string; description: string };

export type ProviderInfo = {
  id: string;
  label: string;
  models: string[];
  /** The model this account would use here: its choice, or the default. */
  model: string;
  needs_key: boolean;
  has_key: boolean;
  /** Where this provider hands out keys. Empty for a keyless one. */
  console_url: string;
  key_placeholder: string;
  /** Days before the stored key lapses, or null when none is stored. */
  key_days_left: number | null;
  /** The last four characters of the key in use here, or null. Never more. */
  key_tail?: string | null;
  /** The key in use came with the request — this tab's, not stored. */
  key_session?: boolean;
  domain: string | null;
};

export type SkillsMode = "auto" | "manual" | "off";

/**
 * Everything the drawer has to know before anyone types.
 *
 * `free_left` is null — not 0 — for an account the free chain does not serve.
 * Zero is a wall that lifts tomorrow; null is an allowance that never existed,
 * and "0 of 30 left" at a reader who was never given 30 tells them they spent
 * messages they never sent. The two render differently on purpose.
 */
export type ChatState = {
  providers: ProviderInfo[];
  answering: string | null;
  /**
   * The provider the account chose, which is not always the one answering: a
   * BYOK provider picked and not yet given a key is preferred and does not
   * answer. The settings screen shows this one, or a tile would un-press
   * itself the moment it was chosen.
   */
  preferred: string | null;
  free_left: number | null;
  free_cap: number | null;
  cap_reason: string | null;
  skills: SkillInfo[];
  skills_mode: string;
  skills_selected: string[];
  max_manual: number;
  /** Extensions the paperclip may offer — every parser's, plus the mapper's. */
  upload_types: string[];
  upload_max_mb: number;
  /** Whether this deployment can transcribe at all. No key, no microphone. */
  voice: boolean;
  /**
   * Whether a key can be kept on the account at all. False leaves "this tab
   * only" as the one way to use a key of your own, and the form says so
   * instead of offering a Remember box the server would refuse.
   */
  key_storage?: boolean;
};

/** One ledger row as the preview shows it, and as the commit sends it back. */
export type ImportRow = {
  date: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  currency: string;
  fee: string | number;
  note: string;
  /** Why this row was flagged, rejected or held back. Empty on a clean one. */
  why: string;
};

/**
 * A statement read but not written.
 *
 * `fresh` is what the button commits. `duplicates` are rows the book already
 * holds — held back rather than imported with a warning, and offered by the
 * card's own checkbox for the honest repeat. `flagged` and `rejected` are both
 * about `fresh`: the first goes in with a caveat, the second does not go in.
 */
export type Preview = {
  filename: string;
  label: string;
  platform: string;
  kind: string;
  unavailable: boolean;
  broker: string;
  needs_broker: boolean;
  brokers: { key: string; label: string }[];
  fresh: ImportRow[];
  duplicates: ImportRow[];
  flagged: ImportRow[];
  rejected: ImportRow[];
  skipped: { row: string; type: string; reason: string }[];
  note: string;
  message: { role: string; content: string; action: string | null };
  conversation: string | null;
  /**
   * How an export no parser owns had its columns read, as an A2UI surface
   * whose "remap" action sends a corrected mapping back. Null for a file a
   * dedicated parser read.
   */
  surface?: A2uiMessage[] | null;
};

export type Committed = {
  imported: number;
  tx_ids: number[];
  total: number;
  broker: string;
  imported_at: string;
  message: { role: string; content: string; action: string | null };
};

/** The settings a client may change. Only the fields sent are applied. */
export type SettingsPatch = {
  skills_mode?: SkillsMode;
  skills?: string[];
  provider?: string;
  /** Belongs to a backend, so it travels with the provider that serves it. */
  model?: string;
};

/** Sent once a provider has actually started answering — never before. */
export type Meta = {
  provider: string;
  model: string;
  skills: string[];
  sources: Source[];
};

/**
 * How a run ended — `RUN_FINISHED`'s result, or `RUN_ERROR`'s code. Always
 * exactly one per run.
 */
export type Done = {
  text: string;
  skills: string[];
  sources: Source[];
  provider: string | null;
  error: string | null;
  steps?: Step[];
  /** The frontend tool calls the answer carried, whole. */
  calls: ToolCall[];
  /** The surfaces the run drew, by activity id — the last snapshot of each. */
  activities?: Activity[];
  /** A proposal this run asked, or one it just settled. */
  proposal?: Proposal;
  /** The cases argued before the answer. */
  debate?: DebateSide[];
};
