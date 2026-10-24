/**
 * What the assistant remembers about the account, to read and to correct.
 *
 * Every memory rides in every prompt, so this list is the one piece of the
 * assistant's state the reader most needs to see — and to change without
 * asking a model nicely. Each row says what it is and where it came from (the
 * conversation it was said in opens from here), and can be reworded or
 * forgotten in place; a memory can also be typed rather than said, and the
 * whole list forgotten behind a confirmation.
 *
 * A memory can hold until a day ("until the end of the year"): past it, it
 * stays on the list, dimmed, and out of the prompt. A full list points at the
 * one used least, and the weekly tidy-up's proposals sit above the list —
 * only ever proposals, applied or dismissed here.
 *
 * A view of the drawer, like the thread list, and for the same reason: an
 * edit takes over the row it belongs to, so the reader never loses sight of
 * the memory they are changing. Every wait here draws a status line.
 */

import { useEffect, useState } from "react";
import { ApiError, scoped } from "../shell/api";
import { useLang, useT } from "../shell/i18n";
import { Status } from "../ui/Status";
import {
  addMemory,
  clearMemories,
  dropMemory,
  editMemory,
  readMemories,
  settleSuggestion,
} from "./api";
import { stamp } from "./format";
import { Glyph } from "./icons";
import type { Memories, Memory as Saved, Suggestion } from "./types";

/** `learnings.UNUSED_DAYS`: what an "idle" proposal means. */
const IDLE_DAYS = 60;

/** An ISO day as the row says it: "31 dic 2026". */
function day(iso: string, lang: string): string {
  const when = new Date(`${iso}T00:00:00`);
  return Number.isNaN(when.getTime())
    ? iso
    : when.toLocaleDateString(lang, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
}

/** Where a memory came from, as the line under it says it. */
function Origin({ memory, onOpen }: { memory: Saved; onOpen: (cid: string) => void }) {
  const t = useT();
  if (memory.source === "chat" && memory.thread) {
    const thread = memory.thread;
    return (
      <button
        type="button"
        className="ag-chat-memory-from"
        title={t("chat.recalled_open")}
        onClick={() => onOpen(thread)}
      >
        {t("chat.mem_from_chat", {
          title: (memory.thread_title ?? "").trim() || t("chat.untitled"),
        })}
      </button>
    );
  }
  return (
    <span>
      {t(
        memory.source === "deleted" ? "chat.mem_from_deleted" : "chat.mem_from_manual",
      )}
    </span>
  );
}

function Row({
  memory,
  maxChars,
  least,
  onSaved,
  onDropped,
  onOpen,
}: {
  memory: Saved;
  maxChars: number;
  /** The one a full list offers to let go. */
  least: boolean;
  onSaved: (next: Saved) => void;
  onDropped: () => void;
  onOpen: (cid: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [mode, setMode] = useState<"rest" | "edit" | "delete">("rest");
  const [draft, setDraft] = useState(memory.text);
  const [until, setUntil] = useState(memory.until ?? "");
  const [working, setWorking] = useState(false);
  const [failed, setFailed] = useState(false);
  const dated = memory.kind !== "routine";

  const save = async () => {
    const text = draft.trim();
    if (!text || working) return;
    const changes: { text?: string; until?: string | null } = {};
    if (text !== memory.text) changes.text = text;
    if (dated && until !== (memory.until ?? "")) changes.until = until || null;
    if (!Object.keys(changes).length) {
      setMode("rest");
      return;
    }
    setWorking(true);
    setFailed(false);
    try {
      onSaved(await editMemory(memory.id, changes));
      setMode("rest");
    } catch {
      setFailed(true);
    } finally {
      setWorking(false);
    }
  };

  const forget = async () => {
    setWorking(true);
    setFailed(false);
    try {
      await dropMemory(memory.id);
      onDropped();
    } catch (failure) {
      // Already gone — another tab, or an undo under a turn. The list says
      // what is true either way.
      if (failure instanceof ApiError && failure.status === 404) onDropped();
      else setFailed(true);
    } finally {
      setWorking(false);
    }
  };

  if (mode === "edit") {
    return (
      <form
        className="ag-chat-card ag-chat-editing"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <textarea
          className="ag-chat-input ag-chat-memory-input"
          value={draft}
          maxLength={maxChars}
          rows={3}
          aria-label={t("chat.mem_edit")}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
        {dated && (
          <label className="ag-chat-memory-until">
            <span>{t("chat.mem_until_label")}</span>
            <input
              className="ag-chat-input"
              type="date"
              value={until}
              onChange={(event) => setUntil(event.target.value)}
            />
            <span className="ag-chat-hint">{t("chat.mem_until_hint")}</span>
          </label>
        )}
        {working ? (
          <Status label={t("chat.mem_saving")} />
        ) : (
          <div className="ag-chat-confirm-row">
            <button
              type="submit"
              className="ag-chat-btn ag-chat-btn-on"
              disabled={!draft.trim()}
            >
              {t("chat.rename_save")}
            </button>
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => {
                setDraft(memory.text);
                setUntil(memory.until ?? "");
                setMode("rest");
              }}
            >
              {t("chat.cancel")}
            </button>
          </div>
        )}
        {failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}
      </form>
    );
  }

  if (mode === "delete") {
    return (
      <div className="ag-chat-card ag-chat-editing">
        <p className="ag-chat-confirm">
          {t("chat.mem_delete_confirm", { text: memory.text })}
        </p>
        {working ? (
          <Status label={t("chat.mem_forgetting")} />
        ) : (
          <div className="ag-chat-confirm-row">
            <button
              type="button"
              className="ag-chat-btn ag-chat-btn-bad"
              onClick={() => void forget()}
            >
              {t("chat.mem_forget")}
            </button>
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => setMode("rest")}
            >
              {t("chat.cancel")}
            </button>
          </div>
        )}
        {failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}
      </div>
    );
  }

  return (
    <div
      className={`ag-chat-card ag-chat-memory-row${memory.expired ? " ag-chat-memory-expired" : ""}`}
    >
      <div className="ag-chat-memory-body">
        <span className="ag-chat-memory-text">{memory.text}</span>
        <span className="ag-chat-card-meta ag-chat-memory-meta">
          <span>{t(`chat.mem_kind_${memory.kind}`)}</span>
          <span aria-hidden="true">·</span>
          <Origin memory={memory} onOpen={onOpen} />
          <span aria-hidden="true">·</span>
          <span>{stamp(memory.updated, lang)}</span>
          {memory.until && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {t(memory.expired ? "chat.mem_expired" : "chat.mem_until", {
                  date: day(memory.until, lang),
                })}
              </span>
            </>
          )}
          {memory.uses > 0 && (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {memory.uses === 1
                  ? t("chat.mem_uses_one")
                  : t("chat.mem_uses_n", { n: memory.uses })}
              </span>
            </>
          )}
        </span>
        {least && <span className="ag-chat-hint">{t("chat.mem_least_used")}</span>}
      </div>
      <button
        type="button"
        className="ag-chat-icon"
        title={t("chat.mem_edit")}
        aria-label={t("chat.mem_edit")}
        onClick={() => {
          setDraft(memory.text);
          setUntil(memory.until ?? "");
          setMode("edit");
        }}
      >
        <Glyph name="edit" size={15} />
      </button>
      <button
        type="button"
        className="ag-chat-icon"
        title={t("chat.mem_forget")}
        aria-label={t("chat.mem_forget")}
        onClick={() => setMode("delete")}
      >
        <Glyph name="trash" size={15} />
      </button>
    </div>
  );
}

/** One tidy-up proposal, with its apply and its dismiss. */
function Proposal({
  suggestion,
  texts,
  onSettled,
}: {
  suggestion: Suggestion;
  /** The memories' current words, by id. */
  texts: Map<string, string>;
  onSettled: () => void;
}) {
  const t = useT();
  const [working, setWorking] = useState(false);
  const [failed, setFailed] = useState(false);
  const first = texts.get(suggestion.ids[0] ?? "") ?? "";

  const settle = async (action: "apply" | "dismiss") => {
    setWorking(true);
    setFailed(false);
    try {
      await settleSuggestion(suggestion.sid, action);
      onSettled();
    } catch (failure) {
      // Settled already, or about a memory deleted since: the list re-read
      // says what is true.
      if (failure instanceof ApiError && failure.status === 404) onSettled();
      else setFailed(true);
    } finally {
      setWorking(false);
    }
  };

  const what =
    suggestion.action === "drop"
      ? t("chat.mem_sug_drop", { text: first })
      : suggestion.action === "merge"
        ? t("chat.mem_sug_merge", { n: suggestion.ids.length, text: suggestion.text })
        : t("chat.mem_sug_reword", { was: first, text: suggestion.text });
  const why =
    suggestion.reason === "model"
      ? suggestion.note
      : suggestion.reason === "idle"
        ? t("chat.mem_why_idle", { days: IDLE_DAYS })
        : t(`chat.mem_why_${suggestion.reason}`);

  return (
    <div className="ag-chat-card ag-chat-memory-row ag-chat-memory-proposal">
      <div className="ag-chat-memory-body">
        <span className="ag-chat-memory-text">{what}</span>
        {suggestion.action === "merge" &&
          suggestion.ids.map((lid) => (
            <span key={lid} className="ag-chat-hint">
              «{texts.get(lid) ?? ""}»
            </span>
          ))}
        {why && <span className="ag-chat-card-meta">{why}</span>}
        {working ? (
          <Status label={t("chat.mem_applying")} />
        ) : (
          <div className="ag-chat-confirm-row">
            <button
              type="button"
              className="ag-chat-btn ag-chat-btn-on"
              onClick={() => void settle("apply")}
            >
              {t("chat.mem_apply")}
            </button>
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => void settle("dismiss")}
            >
              {t("chat.mem_dismiss")}
            </button>
          </div>
        )}
        {failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}
      </div>
    </div>
  );
}

/** A memory typed rather than said. */
function Add({
  full,
  maxChars,
  onAdded,
}: {
  full: boolean;
  maxChars: number;
  onAdded: (memory: Saved) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const save = async () => {
    const said = text.trim();
    if (!said || working) return;
    setWorking(true);
    setFailed(null);
    try {
      onAdded(await addMemory({ text: said }));
      setText("");
    } catch (failure) {
      setFailed(
        failure instanceof ApiError && failure.status === 409
          ? "chat.mem_full_note"
          : failure instanceof ApiError && failure.status === 422
            ? "chat.mem_unfit"
            : "chat.api_error",
      );
    } finally {
      setWorking(false);
    }
  };

  return (
    <form
      className="ag-chat-memory-add"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <textarea
        className="ag-chat-input ag-chat-memory-input"
        value={text}
        maxLength={maxChars}
        rows={2}
        placeholder={t("chat.mem_add_placeholder")}
        aria-label={t("chat.mem_add")}
        disabled={full}
        onChange={(event) => setText(event.target.value)}
      />
      {working ? (
        <Status label={t("chat.mem_saving")} />
      ) : (
        <div className="ag-chat-import-acts">
          <button
            type="submit"
            className="ag-chat-btn ag-chat-btn-on"
            disabled={full || !text.trim()}
          >
            <Glyph name="add" size={14} />
            {t("chat.mem_add")}
          </button>
        </div>
      )}
      {full && <p className="ag-chat-hint">{t("chat.mem_full_note")}</p>}
      {failed && <p className="ag-chat-note">{t(failed)}</p>}
    </form>
  );
}

export function MemoryView({
  onBack,
  onOpen,
}: {
  /** Back to the settings this screen was opened from. */
  onBack: () => void;
  /** Open the conversation a memory was said in. */
  onOpen: (cid: string) => void;
}) {
  const t = useT();
  const [read, setRead] = useState<Memories | null>(null);
  const [failed, setFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearFailed, setClearFailed] = useState(false);
  // Bumped after a proposal is settled: one apply can reword, merge or drop
  // several rows, so the list is read again rather than patched.
  const [reads, setReads] = useState(0);

  useEffect(() => {
    let alive = true;
    const scope = new AbortController();
    scoped(scope.signal, readMemories).then(
      (got) => alive && setRead(got),
      () => alive && setFailed(true),
    );
    return () => {
      alive = false;
      scope.abort();
    };
  }, [reads]);

  const list = read?.memories ?? [];
  const texts = new Map(list.map((m) => [m.id, m.text]));
  const open = (read?.suggestions ?? []).filter((s) =>
    s.ids.every((lid) => texts.has(lid)),
  );
  const full = !!read && list.length >= read.max;
  const put = (next: Saved[]) =>
    setRead((was) => (was ? { ...was, memories: next } : was));

  const clear = async () => {
    setClearing(true);
    setClearFailed(false);
    try {
      await clearMemories();
      put([]);
      setConfirming(false);
    } catch {
      setClearFailed(true);
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="ag-chat-body ag-chat-settings ag-chat-memory">
      <button type="button" className="ag-chat-back" onClick={onBack}>
        <Glyph name="back" size={16} />
        {t("chat.mem_back")}
      </button>
      <p className="ag-chat-group">{t("chat.sec_memory")}</p>
      <p className="ag-chat-hint">{t("chat.mem_explain")}</p>

      {!read && !failed && <Status label={t("chat.mem_loading")} />}
      {failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}

      {read && (
        <>
          {/* Off is not empty: the list is kept, and simply not read. */}
          {!read.enabled && <p className="ag-chat-note">{t("chat.mem_is_off")}</p>}
          <p className="ag-chat-hint ag-chat-memory-count">
            {t("chat.mem_count", { n: list.length, max: read.max })}
          </p>
          {open.length > 0 && (
            <>
              <p className="ag-chat-group">{t("chat.mem_suggestions")}</p>
              <p className="ag-chat-hint">{t("chat.mem_suggestions_hint")}</p>
              {open.map((suggestion) => (
                <Proposal
                  key={suggestion.sid}
                  suggestion={suggestion}
                  texts={texts}
                  onSettled={() => setReads((n) => n + 1)}
                />
              ))}
            </>
          )}
          <Add
            full={full}
            maxChars={read.max_chars}
            onAdded={(memory) =>
              put([...list.filter((m) => m.id !== memory.id), memory])
            }
          />
          {list.map((memory) => (
            <Row
              key={memory.id}
              memory={memory}
              maxChars={read.max_chars}
              least={full && read.suggest_drop === memory.id}
              onSaved={(next) => put(list.map((m) => (m.id === next.id ? next : m)))}
              onDropped={() => put(list.filter((m) => m.id !== memory.id))}
              onOpen={onOpen}
            />
          ))}
          {!list.length && <p className="ag-chat-note">{t("chat.mem_empty")}</p>}

          {list.length > 0 &&
            (confirming ? (
              <div className="ag-chat-confirm">
                <p>{t("chat.mem_clear_confirm", { n: list.length })}</p>
                {clearing ? (
                  <Status label={t("chat.mem_forgetting")} />
                ) : (
                  <div className="ag-chat-import-acts">
                    <button
                      type="button"
                      className="ag-chat-btn ag-chat-btn-bad"
                      onClick={() => void clear()}
                    >
                      {t("chat.mem_clear_yes")}
                    </button>
                    <button
                      type="button"
                      className="ag-chat-btn"
                      onClick={() => setConfirming(false)}
                    >
                      {t("chat.cancel")}
                    </button>
                  </div>
                )}
                {clearFailed && <p className="ag-chat-note">{t("chat.api_error")}</p>}
              </div>
            ) : (
              <button
                type="button"
                className="ag-chat-btn ag-chat-memory-clear"
                onClick={() => setConfirming(true)}
              >
                <Glyph name="trash" size={14} />
                {t("chat.mem_clear")}
              </button>
            ))}
        </>
      )}
    </div>
  );
}
