/**
 * The thread list, which replaces the conversation rather than hovering over
 * it.
 *
 * A search field and date groups need width, and at the drawer's 380px a
 * popover could show a title and nothing that helps choose between two of
 * them. Same reason rename and delete take over the row they belong to: a
 * dialog over a list of threads hides the very titles the reader is deciding
 * between.
 */

import { useState } from "react";
import { useLang, useT } from "../shell/i18n";
import { group, stamp } from "./format";
import { Glyph } from "./icons";
import { Markdown } from "./markdown";
import type { Conversation } from "./types";

/** A thread's display name: its title, or a placeholder while unnamed. */
function label(conv: Conversation, t: (key: string) => string, limit = 30): string {
  const title = (conv.title || "").trim() || t("chat.untitled");
  return title.length <= limit ? title : `${title.slice(0, limit - 1)}…`;
}

function Row({
  conv,
  onOpen,
  onRename,
  onDelete,
}: {
  conv: Conversation;
  onOpen: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [mode, setMode] = useState<"rest" | "rename" | "delete">("rest");
  const [draft, setDraft] = useState(conv.title);

  if (mode === "rename") {
    return (
      <form
        className="ag-chat-card ag-chat-editing"
        onSubmit={(event) => {
          event.preventDefault();
          onRename(draft.trim());
          setMode("rest");
        }}
      >
        <input
          className="ag-chat-input"
          value={draft}
          aria-label={t("chat.rename")}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
        <div className="ag-chat-confirm-row">
          <button type="submit" className="ag-chat-btn ag-chat-btn-on">
            {t("chat.rename_save")}
          </button>
          <button
            type="button"
            className="ag-chat-btn"
            onClick={() => {
              setDraft(conv.title);
              setMode("rest");
            }}
          >
            {t("chat.cancel")}
          </button>
        </div>
      </form>
    );
  }

  if (mode === "delete") {
    // Deleting a thread drops its turns and its memory index with it, so the
    // count is named: "9 messages" is the fact that decides it.
    return (
      <div className="ag-chat-card ag-chat-editing">
        <div className="ag-chat-confirm">
          <Markdown
            text={t("chat.delete_confirm", {
              title: label(conv, t, 24),
              n: conv.messages,
            })}
          />
        </div>
        <div className="ag-chat-confirm-row">
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-bad"
            onClick={() => {
              setMode("rest");
              onDelete();
            }}
          >
            {t("chat.delete_yes")}
          </button>
          <button type="button" className="ag-chat-btn" onClick={() => setMode("rest")}>
            {t("chat.cancel")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`ag-chat-card${conv.active ? " ag-chat-card-on" : ""}`}>
      <button type="button" className="ag-chat-card-open" onClick={onOpen}>
        <span className="ag-chat-card-title">{label(conv, t, 26)}</span>
        <span className="ag-chat-card-meta">
          {t("chat.thread_meta", {
            when: stamp(conv.updated, lang),
            n: conv.messages,
          })}
        </span>
      </button>
      <button
        type="button"
        className="ag-chat-icon"
        title={t("chat.rename")}
        aria-label={t("chat.rename")}
        onClick={() => setMode("rename")}
      >
        <Glyph name="edit" size={15} />
      </button>
      <button
        type="button"
        className="ag-chat-icon"
        title={t("chat.delete_thread")}
        aria-label={t("chat.delete_thread")}
        onClick={() => setMode("delete")}
      >
        <Glyph name="trash" size={15} />
      </button>
    </div>
  );
}

export function Threads({
  threads,
  onBack,
  onOpen,
  onRename,
  onDelete,
}: {
  threads: Conversation[];
  onBack: () => void;
  onOpen: (cid: string) => void;
  onRename: (cid: string, title: string) => void;
  onDelete: (cid: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [needle, setNeedle] = useState("");

  // Client-side filtering: these are tens of threads and their titles are
  // already in memory from the listing above — an index would cost more than
  // it saves.
  const query = needle.trim().toLowerCase();
  const shown = query
    ? threads.filter((c) => (c.title || "").toLowerCase().includes(query))
    : threads;

  let heading = "";
  return (
    <div className="ag-chat-view">
      <div className="ag-chat-search">
        <Glyph name="search" size={15} />
        <input
          className="ag-chat-input"
          value={needle}
          placeholder={t("chat.threads_search")}
          aria-label={t("chat.threads_search")}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setNeedle(event.target.value)}
        />
      </div>
      {shown.map((conv) => {
        const next = group(conv.updated, t, lang);
        const first = next !== heading;
        heading = next;
        return (
          <div key={conv.id}>
            {first && next && <div className="ag-chat-group">{next}</div>}
            <Row
              conv={conv}
              onOpen={() => onOpen(conv.id)}
              onRename={(title) => onRename(conv.id, title)}
              onDelete={() => onDelete(conv.id)}
            />
          </div>
        );
      })}
      {/* Two different nothings: an account that has never opened a thread,
          and a search that ruled every thread out. */}
      {!shown.length && (
        <p className="ag-chat-note">
          {t(query ? "chat.threads_no_match" : "chat.threads_empty")}
        </p>
      )}
      <button type="button" className="ag-chat-btn ag-chat-back" onClick={onBack}>
        <Glyph name="back" size={15} />
        {t("chat.back_thread")}
      </button>
    </div>
  );
}
