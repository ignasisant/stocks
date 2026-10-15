/**
 * The assistant as a guest meets it: there, and locked.
 *
 * The real drawer spends the operator's keys and writes a conversation file,
 * so a guest never gets one — but a guest who never sees the assistant has no
 * idea it is the reason to sign in. This draws the same launcher and the same
 * panel frame, with one exchange written in advance about the demo book in
 * place of a conversation, and the sign-in in place of the composer. Nothing
 * here calls the API.
 *
 * A page that asks something (`askAssistant` — Review's "Ask the AI", the
 * ticker's "Analyse") opens this instead, shows the question as the reader's
 * own turn, and keeps it for after the sign-in (`draft.ts`).
 *
 * Open or shut is this tab's only: a guest has no prefs to write it to.
 */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../shell/i18n";
import { useAssistantAsks } from "../shell/assistant";
import { useKeyboardFit, usePresence, useSwipeDismiss } from "../shell/useSheet";
import { Glyph } from "./icons";
import { keepDraft } from "./draft";
import "./chat.css";

const LockedPanel = lazy(() => import("./LockedPanel"));

export function LockedDrawer() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState<string | null>(null);

  const onAsk = useCallback((prompt: string | null) => {
    if (prompt) {
      setAsked(prompt);
      keepDraft(prompt);
    }
    setOpen(true);
  }, []);
  useAssistantAsks(onAsk);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Always over the page, never beside it: one exchange does not need the
  // page to make room, and a guest's page is the thing being sold.
  useEffect(() => {
    const root = document.documentElement;
    if (!open) return;
    root.dataset.chat = "overlay";
    return () => {
      delete root.dataset.chat;
    };
  }, [open]);

  const panel = useRef<HTMLElement | null>(null);
  const fab = useRef<HTMLButtonElement | null>(null);
  const opened = useRef(false);
  const presence = usePresence(open);
  useSwipeDismiss(panel, "x", () => setOpen(false), {
    handle: ".ag-chat-head",
    enabled: presence.mounted,
  });
  useKeyboardFit(panel, presence.mounted);
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
          className="ag-ai ag-chat-fab"
          title={t("chat.title")}
          aria-label={t("chat.title")}
          onClick={() => setOpen(true)}
        >
          <Glyph name="spark" size={22} />
        </button>
      )}
      {presence.mounted && (
        <aside
          ref={panel}
          className="ag-chat-panel ag-chat-locked"
          data-leaving={presence.leaving ? "" : undefined}
          role="dialog"
          aria-label={t("chat.title")}
          tabIndex={-1}
        >
          <Suspense fallback={<div className="ag-chat-body" />}>
            <LockedPanel asked={asked} onClose={() => setOpen(false)} />
          </Suspense>
        </aside>
      )}
    </>
  );
}
