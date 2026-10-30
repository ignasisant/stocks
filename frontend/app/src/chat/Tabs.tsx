/**
 * The open conversations as tabs, under the header of a wide drawer.
 *
 * Switching threads otherwise takes the list: one press to open it, one to
 * pick. That is fine for finding last week's thread and slow for going back
 * and forth between two that are both live — the case detached runs made
 * common, where one thread gathers for minutes while the reader asks
 * something else on another. Here each of those is one press, and whether it
 * is still answering or has landed is in view without opening anything.
 *
 * Only where it fits: the strip's box is a container and the strip is hidden
 * below 560px of it (`chat.css`), so the 380px drawer and a phone keep the
 * header's title button and the list. One tab says nothing the header does
 * not, so a single one is not drawn either.
 */

import { useT } from "../shell/i18n";
import { Glyph } from "./icons";
import type { Conversation } from "./types";

export function Tabs({
  tabs,
  threads,
  activeId,
  unread,
  onOpen,
  onClose,
}: {
  tabs: string[];
  threads: Conversation[];
  activeId: string | null;
  unread: ReadonlySet<string>;
  onOpen: (cid: string) => void;
  onClose: (cid: string) => void;
}) {
  const t = useT();
  const byId = new Map(threads.map((c) => [c.id, c]));
  if (tabs.length < 2) return null;
  return (
    <div className="ag-chat-tabs-box">
      <nav className="ag-chat-tabs" aria-label={t("chat.tabs")}>
        {tabs.map((id) => {
          const conv = byId.get(id);
          const title = (conv?.title || "").trim();
          const on = id === activeId;
          // The same two states the list marks, and for the same reason the
          // list leaves them off the open thread: its answer is on screen.
          const state = on
            ? null
            : conv?.answering
              ? "answering"
              : unread.has(id)
                ? "unread"
                : null;
          const name = title || t("chat.untitled");
          const said = state
            ? `${name} · ${t(state === "answering" ? "chat.thread_answering" : "chat.thread_unread")}`
            : name;
          return (
            <div key={id} className={`ag-chat-tab${on ? " ag-chat-tab-on" : ""}`}>
              <button
                type="button"
                className="ag-chat-tab-open"
                title={said}
                aria-label={said}
                aria-current={on ? "true" : undefined}
                onClick={() => !on && onOpen(id)}
                // The middle button closes, as it does on a browser's tabs —
                // and not before it has stopped the autoscroll it starts.
                onMouseDown={(event) => event.button === 1 && event.preventDefault()}
                onAuxClick={(event) => {
                  if (event.button !== 1) return;
                  event.preventDefault();
                  onClose(id);
                }}
              >
                {state && (
                  <span className="ag-chat-dot" data-state={state} aria-hidden="true" />
                )}
                <span
                  className={
                    title ? "ag-chat-tab-title" : "ag-chat-tab-title ag-chat-untitled"
                  }
                >
                  {name}
                </span>
              </button>
              <button
                type="button"
                className="ag-chat-icon ag-chat-tab-close"
                title={t("chat.tab_close")}
                aria-label={t("chat.tab_close_named", { title: name })}
                onClick={() => onClose(id)}
              >
                <Glyph name="close" size={14} />
              </button>
            </div>
          );
        })}
      </nav>
    </div>
  );
}
