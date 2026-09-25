/**
 * The panel's body: two header rows, and whichever view the drawer is on.
 *
 * The rows cost about 70px between them and answer the two questions the old
 * Streamlit settings expander only answered once opened — which thread is
 * this, and what is answering it, on how much allowance left.
 *
 * This module is everything the drawer needs *after* it is opened, and it is
 * imported that way: the launcher and the state that outlives a close are in
 * `Drawer.tsx`, which every page pays for, and all of this arrives on the
 * press that needs it. The conversation is not in here either way — it is in
 * `useChat`, above the lazy boundary, so closing the drawer never cancels an
 * answer that is still being written.
 */

import { useEffect, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useStickToBottom } from "use-stick-to-bottom";
import { useT } from "../shell/i18n";
import { Skeleton } from "../shell/Layout";
import { Moves } from "../pages/import/Moves";
import "../pages/import/import.css";
import { Attachment } from "./Attachment";
import { Composer } from "./Composer";
import { Empty } from "./Empty";
import { Glyph } from "./icons";
import { Settings } from "./Settings";
import { Setup, needsSetup } from "./Setup";
import { Threads } from "./Threads";
import { Turn } from "./Turn";
import type { Chat } from "./useChat";
import {
  WIDTHS,
  applyPixels,
  applyWidth,
  rememberPixels,
  restoreWidth,
  storedWidth,
  widthAt,
  type WidthKey,
} from "./width";

/**
 * The grab strip on the panel's left edge — the Streamlit drawer's handle,
 * in the front end that owns its own DOM.
 *
 * The three presets cover the three shapes a conversation takes; this covers
 * the reader who wants their own. Pointer events rather than mouse ones, and
 * the pointer is captured on press: the cursor spends the whole drag over the
 * page *behind* the panel, and without capture the first move outside the
 * strip would end it.
 *
 * Keyboard readers get the same range through the arrow keys, because a
 * separator nobody can reach is a control only half the readers have — the
 * presets beside it are the coarse version of the same choice.
 */
function Grip({ onWidth }: { onWidth: (key: WidthKey | null) => void }) {
  const t = useT();

  const start = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const grip = event.currentTarget;
    grip.setPointerCapture(event.pointerId);
    document.body.classList.add("ag-chat-dragging");
    const move = (moved: PointerEvent) => applyPixels(widthAt(moved.clientX));
    const stop = (ended: PointerEvent) => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", stop);
      grip.removeEventListener("pointercancel", stop);
      document.body.classList.remove("ag-chat-dragging");
      onWidth(rememberPixels(widthAt(ended.clientX)));
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", stop);
    grip.addEventListener("pointercancel", stop);
    // A drag that starts by selecting the header text behind it reads as a
    // broken handle rather than as a resize.
    event.preventDefault();
  };

  const nudge = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowLeft" ? 24 : event.key === "ArrowRight" ? -24 : 0;
    if (!step) return;
    // The panel's rendered width, not the stored one: the stored one may be a
    // preset, `100vw`, or nothing at all, and all three have to grow by 24px.
    const now = event.currentTarget.parentElement?.getBoundingClientRect().width;
    if (!now) return;
    event.preventDefault();
    onWidth(rememberPixels(widthAt(window.innerWidth - (now + step))));
  };

  return (
    <div
      className="ag-chat-grip"
      role="separator"
      aria-orientation="vertical"
      aria-label={t("chat.width_drag")}
      title={t("chat.width_drag")}
      tabIndex={0}
      onPointerDown={start}
      onKeyDown={nudge}
    />
  );
}

export default function Panel({
  chat,
  onClose,
  onPark,
}: {
  chat: Chat;
  onClose: () => void;
  /**
   * Step aside for a page the walkthrough sent the reader to, on a phone —
   * closing, and leaving the parked strip behind (`guide.goto`). Falls back
   * to a plain close where the drawer has no strip to leave.
   */
  onPark?: () => void;
}) {
  const t = useT();
  const [view, setView] = useState<"thread" | "threads" | "settings">("thread");
  // Opening the drawer on the guide's own thread is the moment a capability
  // may have been switched on somewhere the guide was not looking — an import
  // in another tab, a key saved in settings. Catch the thread up then, once
  // per open: the walkthrough shows progress rather than a step to re-read.
  const { guideSync, guide, activeId } = chat;
  const synced = useRef(false);
  useEffect(() => {
    if (synced.current || !guide?.active || guide.thread !== activeId) return;
    synced.current = true;
    void guideSync().catch(() => {});
  }, [guide, activeId, guideSync]);

  // A file is being dragged over the conversation. The counter is what makes
  // the overlay survive the pointer crossing a bubble on its way in.
  const [overDrop, setOverDrop] = useState(false);
  const dragging = useRef(0);

  // The width lives on the document, which a reload clears; the choice lives
  // in the browser, which one does not. Put the second back on the first as
  // soon as there is a panel to size.
  const [width, setWidth] = useState<WidthKey | null>(storedWidth);
  useEffect(restoreWidth, []);
  const resize = (key: WidthKey) => {
    setWidth(key);
    applyWidth(key);
  };

  // The newest turn stays in view while it writes itself — until the reader
  // scrolls up, and then it stops. That second half is why this is a library
  // and not two lines: `turns` changes on every animation frame of a stream,
  // so pinning the region on each of them means anyone who scrolls back to
  // re-read a figure is dragged to the bottom again a frame later.
  //
  // `initial: "instant"` because opening a thread that already has fifty
  // turns should land at the newest one, not animate down through all of them.
  // Growth while streaming keeps the spring, which is what makes the text
  // read as arriving rather than jumping. Scrolling the region and not the
  // document is still what keeps the page underneath where it was left.
  //
  // A reader who asked for less motion is given none of it: the spring that
  // makes the text read as arriving is exactly the animation the preference
  // is about, and `chat.css` already honours it for the working glyph.
  const calm =
    typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({
    initial: "instant",
    resize: calm ? "instant" : undefined,
  });

  const open = chat.threads?.find((c) => c.id === chat.activeId);
  const named = (open?.title || "").trim();
  const state = chat.state;
  const provider = state?.providers.find((p) => p.id === state.answering);
  const byok = provider?.needs_key ?? false;

  return (
    <>
      <Grip onWidth={setWidth} />
      <header className="ag-chat-head">
        <button
          type="button"
          className="ag-chat-thread-btn"
          title={t("chat.threads_title")}
          onClick={() => setView("threads")}
        >
          <Glyph name="forum" size={16} />
          <span className={named ? "" : "ag-chat-untitled"}>
            {named || t("chat.untitled")}
          </span>
        </button>
        <button
          type="button"
          className="ag-chat-icon"
          title={t("chat.new")}
          aria-label={t("chat.new")}
          onClick={() => {
            setView("thread");
            void chat.create();
          }}
        >
          <Glyph name="add" size={18} />
        </button>
        {/* The three widths the Streamlit header offers, and for the same
            reason: a table or a set of sources is unreadable in a 380px
            column, and an import review wants the screen. Hidden on a phone,
            where the panel is already the whole viewport. */}
        <div className="ag-chat-widths" role="group" aria-label={t("chat.width")}>
          {WIDTHS.map(({ key, icon }) => (
            <button
              key={key}
              type="button"
              className={
                key === width ? "ag-chat-icon ag-chat-width-on" : "ag-chat-icon"
              }
              title={t(`chat.width_${key}`)}
              aria-label={t(`chat.width_${key}`)}
              aria-pressed={key === width}
              onClick={() => resize(key)}
            >
              <Glyph name={icon} size={16} />
            </button>
          ))}
        </div>
        <button
          type="button"
          className="ag-chat-icon"
          title={t("chat.settings_short")}
          aria-label={t("chat.settings_short")}
          aria-pressed={view === "settings"}
          onClick={() => setView(view === "settings" ? "thread" : "settings")}
        >
          <Glyph name="settings" size={18} />
        </button>
        <button
          type="button"
          className="ag-chat-icon"
          title={t("chat.close")}
          aria-label={t("chat.close")}
          onClick={onClose}
        >
          <Glyph name="close" size={18} />
        </button>
      </header>

      {provider && (
        <div className="ag-chat-status">
          <span
            className="ag-chat-provider"
            title={
              chat.model
                ? t("chat.using", { provider: provider.label, model: chat.model })
                : undefined
            }
          >
            <Glyph name="spark" size={12} />
            {provider.label}
          </span>
          {/* Null is not zero: an account the free chain never served has no
              counter, because "0 of 30 left" would tell it that it spent
              messages it never sent. */}
          {!byok && state && state.free_left !== null && state.free_cap !== null && (
            <span className="ag-chat-quota" title={t("chat.free_left_label")}>
              {t("chat.free_left", { left: state.free_left, cap: state.free_cap })}
            </span>
          )}
        </div>
      )}

      {chat.failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}

      {!state && !chat.failed && (
        <div className="ag-chat-body">
          <Skeleton rows={4} />
        </div>
      )}

      {state && view === "threads" && (
        <Threads
          threads={chat.threads ?? []}
          onBack={() => setView("thread")}
          onOpen={(cid) => {
            setView("thread");
            void chat.open(cid);
          }}
          onRename={(cid, title) => void chat.rename(cid, title)}
          onDelete={(cid) => void chat.remove(cid)}
        />
      )}

      {state && view === "settings" && (
        <Settings
          state={state}
          busy={chat.busy}
          thread={
            open ? { id: open.id, title: open.title, messages: open.messages } : null
          }
          onBack={() => setView("thread")}
          onSave={(patch) => void chat.settings(patch)}
          onState={chat.apply}
          onDeleteThread={(cid) => void chat.remove(cid)}
        />
      )}

      {state && view === "thread" && (
        <>
          {/* Dropping a statement on the conversation is the same import the
              paperclip starts — the drawer simply says so while something is
              being dragged over it. Counted rather than toggled: dragleave
              fires on every child the pointer crosses. */}
          <div
            className="ag-chat-stage"
            onDragEnter={(event) => {
              if (!event.dataTransfer.types.includes("Files")) return;
              event.preventDefault();
              dragging.current += 1;
              setOverDrop(true);
            }}
            onDragOver={(event) => {
              if (event.dataTransfer.types.includes("Files")) event.preventDefault();
            }}
            onDragLeave={() => {
              dragging.current = Math.max(0, dragging.current - 1);
              if (!dragging.current) setOverDrop(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              dragging.current = 0;
              setOverDrop(false);
              const dropped = event.dataTransfer.files?.[0];
              // One file: an attachment is a preview somebody confirms, and a
              // second would queue a second card behind the first.
              if (dropped && !chat.busy && !chat.reading) void chat.attach(dropped);
            }}
          >
            {overDrop && (
              <p className="ag-chat-drop">
                {t("chat.drop_zone", { mb: state.upload_max_mb })}
              </p>
            )}
            <div className="ag-chat-scroll" ref={scrollRef}>
              <div className="ag-chat-stream" ref={contentRef}>
                {chat.turns.length ? (
                  chat.turns.map((turn, i) => (
                    <Turn
                      key={i}
                      turn={turn}
                      skills={state.skills}
                      providers={state.providers}
                      walk={
                        chat.guide
                          ? {
                              state: chat.guide,
                              onNext: chat.guideAdvance,
                              onSkip: () => void chat.guideFinish("skipped"),
                              onLeave: onPark ?? onClose,
                            }
                          : null
                      }
                      cap={state.free_cap}
                      onRetry={chat.retry}
                      // Only the newest turn can be discarded: an older refusal
                      // is history the reader has already moved past.
                      onDrop={i === chat.turns.length - 1 ? chat.drop : undefined}
                    />
                  ))
                ) : needsSetup(state) ? (
                  <Setup
                    state={state}
                    onSave={(patch) => void chat.settings(patch)}
                    onSettings={() => setView("settings")}
                  />
                ) : (
                  <Empty onAsk={(question) => void chat.send(question)} />
                )}
                {/* Below the turns, not inside one: the note the server filed
                    is the turn, and this card is the offer it refers to —
                    which is why a reload keeps the first and drops the
                    second. */}
                {/* Shares that only changed broker, offered where the import
                    happened. A statement cannot say "these moved": the old
                    broker prints a sale and the new one a balance, and a file
                    imported through the assistant never passes the Import
                    page that has always asked. Only after a batch this drawer
                    wrote — a book nobody touched here is that page's business,
                    and scanning it on every open would cost a request for a
                    question nobody raised. */}
                {chat.imported > 0 && !chat.preview && (
                  <Moves enabled nonce={chat.imported} onApplied={() => {}} />
                )}
                {chat.preview && (
                  <Attachment
                    preview={chat.preview}
                    busy={chat.reading}
                    onImport={(broker, dupes) => void chat.commitImport(broker, dupes)}
                    onDiscard={chat.discardImport}
                  />
                )}
              </div>
            </div>
            {/* Escaping the lock has to be undoable, or the reader who
                scrolled up to check something is left scrolling back down
                through an answer that grew while they read. */}
            {/* Regenerate, and only that: clearing the thread is destructive
                and lives in the settings view, behind a confirmation. Drawn
                for a finished answer — a refusal carries its own Retry. */}
            {!chat.busy &&
              chat.turns.length > 1 &&
              chat.turns[chat.turns.length - 1]?.role === "assistant" &&
              !chat.turns[chat.turns.length - 1]?.error &&
              !chat.turns[chat.turns.length - 1]?.stopped && (
                <button
                  type="button"
                  className="ag-chat-regen"
                  onClick={chat.regenerate}
                >
                  <Glyph name="refresh" size={13} />
                  {t("chat.regenerate")}
                </button>
              )}
            {!isAtBottom && chat.turns.length > 0 && (
              <button
                type="button"
                className="ag-chat-down"
                title={t("chat.scroll_down")}
                aria-label={t("chat.scroll_down")}
                onClick={() => void scrollToBottom(calm ? "instant" : undefined)}
              >
                <Glyph name="down" size={18} />
              </button>
            )}
          </div>
          <Composer
            state={state}
            busy={chat.busy}
            reading={chat.reading}
            onSend={(text, spoken) => void chat.send(text, spoken)}
            onStop={chat.stop}
            onSave={(patch) => void chat.settings(patch)}
            onAttach={(file) => void chat.attach(file)}
            onSettings={() => setView("settings")}
          />
        </>
      )}
    </>
  );
}
