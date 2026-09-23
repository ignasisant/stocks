/**
 * The assistant, on every page: a launcher, and the panel it opens.
 *
 * Only this much is paid for by a reader who never opens it — the button, the
 * open flag and the conversation state. Everything the panel draws arrives on
 * the press that needs it, which is the same bargain `shell/pages.ts` makes
 * for a page nobody navigates to.
 *
 * The conversation lives here rather than inside the panel so that closing the
 * drawer is not a cancel: an answer keeps being written, the turn keeps being
 * assembled, and re-opening shows what carried on without anyone watching.
 *
 * Open survives a reload, because a panel that collapsed back to its icon on
 * every navigation would lose a conversation mid-question. The flag is the one
 * the Streamlit drawer already stores (`chat_panel_open` in prefs), so the two
 * surfaces agree about whether this account keeps the assistant open.
 */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { send } from "../shell/api";
import { useT } from "../shell/i18n";
import { useAssistantAsks } from "../shell/assistant";
import { useSession } from "../shell/session";
import { Glyph } from "./icons";
import { useRoute } from "../shell/router";
import { autoSeen, markAutoSeen, readGuide } from "./guide";
import { useChat } from "./useChat";
import "./chat.css";

const Panel = lazy(() => import("./Panel"));

export function Drawer() {
  const t = useT();
  const { prefs } = useSession();
  const [open, setOpen] = useState(prefs.chat_panel_open);
  const chat = useChat(open);

  const show = useCallback((next: boolean) => {
    setOpen(next);
    // Fire and forget: the panel has already moved, and a preference that
    // failed to save is worth exactly one lost reload — not an error in front
    // of someone who was trying to close a drawer.
    void send("PATCH", "/prefs", { chat_panel_open: next }).catch(() => {});
  }, []);

  // A page asked something (the Ticker header's "Analyse with AI"). Open, then
  // send — but not before the drawer knows which thread it is writing to, or
  // the question would open a second one. Queued rather than sent on the spot
  // for the same reason: the press happens while `useChat` is still loading.
  const [queued, setQueued] = useState<string | null>(null);
  const onAsk = useCallback(
    (prompt: string | null) => {
      // A null prompt is "show me the assistant" — the tour's stop and the
      // Home checklist's row both mean that, and neither should spend a turn.
      if (prompt) setQueued(prompt);
      show(true);
    },
    [show],
  );
  useAssistantAsks(onAsk);

  const { state, busy, send: ask } = chat;
  useEffect(() => {
    if (!queued || !open || !state || busy) return;
    setQueued(null);
    void ask(queued);
  }, [queued, open, state, busy, ask]);

  // The walkthrough opens itself, in the drawer — once per tab, and only for
  // an account the server says is still owed an automatic open (the guide is
  // not finished and fewer than three have been spent). `?guide=1` or
  // `?guide=<step>` opens it on request, which spends nothing, and is read
  // once and taken off the URL so the next navigation does not reopen what
  // was just closed.
  const { params, setParams } = useRoute();
  const [guideAsk, setGuideAsk] = useState<{ step?: string; auto: boolean } | null>(
    null,
  );
  const asked = params.get("guide");
  useEffect(() => {
    if (asked) {
      setParams({ guide: undefined });
      const top = ["1", "true", "yes"].includes(asked.toLowerCase());
      setGuideAsk({ auto: false, step: top ? undefined : asked });
      show(true);
      return;
    }
    if (autoSeen()) return;
    markAutoSeen();
    readGuide()
      .then((guide) => {
        if (guide.surface !== "chat" || !guide.auto_open) return;
        setGuideAsk({ auto: true });
        show(true);
      })
      .catch(() => {
        // A guest, or no walkthrough on this server: nothing is owed.
      });
    // Once per mount: the URL case re-runs only when `?guide=` itself changes.
  }, [asked]);

  // Started once the drawer has finished its own opening read — otherwise the
  // thread it was loading would land on top of the guide's.
  const { ready, guideStart } = chat;
  useEffect(() => {
    if (!guideAsk || !open || !ready) return;
    const ask = guideAsk;
    setGuideAsk(null);
    void guideStart(ask).catch(() => {});
  }, [guideAsk, open, ready, guideStart]);

  // The page makes room for the drawer rather than disappearing under it, and
  // it is marked on the document because the rule that does it lives in CSS
  // (`chat.css`), next to the width the drawer is sized by: the panel is fixed,
  // so nothing in the layout could otherwise know it is there.
  useEffect(() => {
    const root = document.documentElement;
    if (open) root.dataset.chat = "open";
    else delete root.dataset.chat;
    return () => {
      delete root.dataset.chat;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") show(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, show]);

  // Opening without moving the focus leaves a keyboard reader on the page
  // behind the drawer; closing without handing it back drops them on
  // `document.body`. The panel takes it, and the launcher takes it back — the
  // launcher through a ref rather than by remembering the element, because it
  // unmounts while the panel is open and returns as a new node.
  //
  // The first run is skipped on purpose: a reload that restored an open drawer
  // has not opened anything, and should not pull the focus out of the document.
  const panel = useRef<HTMLElement | null>(null);
  const fab = useRef<HTMLButtonElement | null>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (!opened.current) {
      opened.current = true;
      return;
    }
    if (open) panel.current?.focus();
    else fab.current?.focus();
  }, [open]);

  return (
    <>
      {!open && (
        <button
          type="button"
          ref={fab}
          className="ag-chat-fab"
          title={t("chat.title")}
          aria-label={t("chat.title")}
          onClick={() => show(true)}
        >
          <Glyph name="spark" size={22} />
        </button>
      )}
      {open && (
        <aside
          ref={panel}
          className="ag-chat-panel"
          role="dialog"
          aria-label={t("chat.title")}
          // Focusable only on purpose: the drawer is not modal (the page
          // behind it stays usable), so it is never a Tab stop of its own.
          tabIndex={-1}
        >
          <Suspense
            fallback={
              <div className="ag-chat-body">
                <div className="ag-skeleton" aria-hidden="true">
                  <div className="ag-skeleton-row" />
                  <div className="ag-skeleton-row" />
                  <div className="ag-skeleton-row" />
                </div>
              </div>
            }
          >
            <Panel chat={chat} onClose={() => show(false)} />
          </Suspense>
        </aside>
      )}
    </>
  );
}
