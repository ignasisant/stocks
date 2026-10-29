/**
 * The panel's body: two header rows, and whichever view the drawer is on.
 *
 * The rows cost about 70px between them and answer two questions without
 * opening anything — which thread is this, and what is answering it, on how
 * much allowance left.
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
import { usePhone } from "./phone";
import { Composer } from "./Composer";
import { Empty } from "./Empty";
import { Glyph, ProviderMark } from "./icons";
import { MemoryView } from "./Memory";
import { Settings } from "./Settings";
import { Setup, needsSetup } from "./Setup";
import { Threads } from "./Threads";
import { Status } from "../ui/Status";
import { rates, Turn } from "./Turn";
import type { ConnectAsk } from "./connect";
import type { Chat } from "./useChat";
import {
  WIDTHS,
  applyPixels,
  applyWidth,
  rememberPixels,
  restoreWidth,
  settle,
  storedWidth,
  stretchAt,
  widthAt,
  type WidthKey,
} from "./width";

/**
 * The grab strip on the panel's left edge.
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
    // Where on the strip the finger landed, kept for the whole drag: the edge
    // stays under that same spot instead of jumping to the cursor.
    const edge = grip.parentElement?.getBoundingClientRect().left ?? event.clientX;
    const grab = Math.round(event.clientX - edge);
    const move = (moved: PointerEvent) => applyPixels(stretchAt(moved.clientX - grab));
    const stop = (ended: PointerEvent) => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", stop);
      grip.removeEventListener("pointercancel", stop);
      document.body.classList.remove("ag-chat-dragging");
      // A release past a limit springs back to it rather than snapping.
      const x = ended.clientX - grab;
      if (stretchAt(x) !== widthAt(x)) settle();
      onWidth(rememberPixels(widthAt(x)));
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

/**
 * The phone header's ⋮: what the desktop header lays out as icons, in a list
 * that opens under the button. Pointerdown outside closes it, Esc hands the
 * focus back to the button, and the arrows walk it (`AiAsk`'s menu).
 */
function HeadMenu({
  onNew,
  onThreads,
  onSettings,
}: {
  onNew: () => void;
  onThreads: () => void;
  onSettings: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    items.current[0]?.focus();
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  const walk = (event: ReactKeyboardEvent) => {
    const list = items.current.filter(Boolean) as HTMLButtonElement[];
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
      if (event.key === "Escape") {
        // The drawer's own Esc would close it too: one press, one step back.
        event.stopPropagation();
        event.nativeEvent.stopImmediatePropagation();
        toggle.current?.focus();
      }
      return;
    }
    const next =
      event.key === "ArrowDown"
        ? (at + 1) % list.length
        : event.key === "ArrowUp"
          ? (at - 1 + list.length) % list.length
          : null;
    if (next === null) return;
    event.preventDefault();
    list[next]?.focus();
  };
  const entries: { key: string; glyph: string; run: () => void }[] = [
    { key: "chat.new", glyph: "add", run: onNew },
    { key: "chat.threads_title", glyph: "forum", run: onThreads },
    { key: "chat.settings_short", glyph: "settings", run: onSettings },
  ];
  return (
    <div className="ag-chat-menu" ref={box}>
      <button
        ref={toggle}
        type="button"
        className="ag-chat-icon"
        aria-haspopup="menu"
        aria-expanded={open}
        title={t("chat.menu")}
        aria-label={t("chat.menu")}
        onClick={() => setOpen((was) => !was)}
      >
        <Glyph name="more" size={18} />
      </button>
      {open && (
        <div
          className="ag-chat-menu-list"
          role="menu"
          aria-label={t("chat.menu")}
          onKeyDown={walk}
        >
          {entries.map((entry, n) => (
            <button
              key={entry.key}
              ref={(el) => {
                items.current[n] = el;
              }}
              type="button"
              role="menuitem"
              className="ag-chat-menu-item"
              onClick={() => {
                setOpen(false);
                entry.run();
              }}
            >
              <Glyph name={entry.glyph} size={16} />
              {t(entry.key)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Panel({
  chat,
  connect = null,
  onConnectTaken,
  memory = false,
  onMemoryTaken,
  thread = null,
  onThreadTaken,
  onClose,
  onPark,
}: {
  chat: Chat;
  /** Back from a provider's sign-in: the settings view finishes it. */
  connect?: ConnectAsk | null;
  onConnectTaken?: () => void;
  /** Sent here to the saved memories (`?chat=memory`, the profile's link). */
  memory?: boolean;
  onMemoryTaken?: () => void;
  /** Sent here to one conversation (the daily card's "Ask"). */
  thread?: string | null;
  onThreadTaken?: () => void;
  onClose: () => void;
  /**
   * Step aside for a page the walkthrough sent the reader to, on a phone —
   * closing, and leaving the parked strip behind (`guide.goto`). Falls back
   * to a plain close where the drawer has no strip to leave.
   */
  onPark?: () => void;
}) {
  const t = useT();
  const [view, setView] = useState<"thread" | "threads" | "settings" | "memory">(
    "thread",
  );
  // The reader left from the key section and comes back to it: the settings
  // view is where the sign-in is finished and where its outcome is said.
  useEffect(() => {
    if (connect) setView("settings");
  }, [connect]);
  useEffect(() => {
    if (!memory) return;
    setView("memory");
    onMemoryTaken?.();
  }, [memory]);
  // An earlier conversation named under an answer, or the one a memory was
  // said in: the thread view, on that thread.
  const openThread = (cid: string) => {
    setView("thread");
    void chat.open(cid);
  };
  // Not before the drawer's own opening read has landed: it would put the
  // active thread back on top of the one asked for.
  useEffect(() => {
    if (!thread || !chat.ready) return;
    openThread(thread);
    onThreadTaken?.();
  }, [thread, chat.ready]);
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
  // A file dropped on a desktop panel is a file the reader wants to read:
  // its preview opens wide as it lands. Spent once the card has mounted.
  const [dropWide, setDropWide] = useState(false);
  const phone = usePhone();
  useEffect(() => {
    if (chat.preview) setDropWide(false);
  }, [chat.preview]);
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
  // Regenerate, for a finished answer: a refusal carries its own Retry.
  const last = chat.turns[chat.turns.length - 1];
  const regen =
    !chat.busy &&
    !chat.reading &&
    chat.turns.length > 1 &&
    last?.role === "assistant" &&
    !last.error &&
    !last.stopped;
  // Scrolled up from the end: the way back down, and the fade under it.
  const below = !isAtBottom && chat.turns.length > 0;
  const named = (open?.title || "").trim();
  const state = chat.state;
  const provider = state?.providers.find((p) => p.id === state.answering);
  const byok = provider?.needs_key ?? false;
  // Null is not zero: an account the free chain never served has no counter,
  // because "0 of 30 left" would tell it that it spent messages it never sent.
  const quota =
    !byok && state && state.free_left !== null && state.free_cap !== null
      ? t("chat.free_left", { left: state.free_left, cap: state.free_cap })
      : null;

  return (
    <>
      <Grip onWidth={setWidth} />
      <header className="ag-chat-head">
        <button
          type="button"
          className="ag-chat-thread-btn"
          title={named || t("chat.threads_title")}
          aria-label={
            chat.unread.size > 0
              ? `${t("chat.threads_title")} · ${t("chat.unread_any")}`
              : t("chat.threads_title")
          }
          onClick={() => setView("threads")}
        >
          <Glyph name="forum" size={16} />
          {/* An answer landed on another thread: the way to the list says
              so, since the list is where it is marked. */}
          {chat.unread.size > 0 && (
            <span
              className="ag-chat-dot ag-chat-head-dot"
              data-state="unread"
              aria-hidden="true"
            />
          )}
          <span className="ag-chat-head-text">
            <span
              className={
                named ? "ag-chat-head-title" : "ag-chat-head-title ag-chat-untitled"
              }
            >
              {named || t("chat.untitled")}
            </span>
            {/* A phone's second line: the status row folded under the title,
                since that row is hidden there to keep the thread's height. */}
            {provider && (
              <span className="ag-chat-head-sub">
                {quota ? `${provider.label} · ${quota}` : provider.label}
              </span>
            )}
          </span>
        </button>
        <button
          type="button"
          className="ag-chat-icon ag-chat-head-wide"
          title={t("chat.new")}
          aria-label={t("chat.new")}
          onClick={() => {
            setView("thread");
            void chat.create();
          }}
        >
          <Glyph name="add" size={18} />
        </button>
        {/* Three widths, because a table or a set of sources is unreadable in
            a 380px column, and an import review wants the screen. Hidden on a
            phone, where the panel is already the whole viewport. */}
        <div className="ag-chat-widths" role="group" aria-label={t("chat.width")}>
          {WIDTHS.map(({ key, icon }) => (
            <button
              key={key}
              type="button"
              className={`ag-chat-icon ag-chat-width-${key}${key === width ? " ag-chat-width-on" : ""}`}
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
          className="ag-chat-icon ag-chat-head-wide"
          title={t("chat.settings_short")}
          aria-label={t("chat.settings_short")}
          aria-pressed={view === "settings" || view === "memory"}
          onClick={() =>
            setView(view === "settings" || view === "memory" ? "thread" : "settings")
          }
        >
          <Glyph name="settings" size={18} />
        </button>
        {/* A phone keeps two controls in the header, at 44px: this menu
            (new conversation, the list, settings) and Close. */}
        <HeadMenu
          onNew={() => {
            setView("thread");
            void chat.create();
          }}
          onThreads={() => setView("threads")}
          onSettings={() => setView("settings")}
        />
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
      {/* The handle a finger pulls the phone's drawer down by (`Drawer`'s
          swipe); nothing to drag on a desktop, where it is not drawn. */}
      <div className="ag-chat-handle" aria-hidden="true" />

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
            <ProviderMark provider={provider} />
            {provider.label}
          </span>
          {quota && (
            <span className="ag-chat-quota" title={t("chat.free_left_label")}>
              {quota}
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
          unread={chat.unread}
          onBack={() => setView("thread")}
          onOpen={openThread}
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
          connect={connect}
          onConnectTaken={onConnectTaken}
          onMemory={() => setView("memory")}
          onLeave={onPark ?? onClose}
        />
      )}

      {state && view === "memory" && (
        <MemoryView onBack={() => setView("settings")} onOpen={openThread} />
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
              if (dropped && !chat.busy && !chat.reading) {
                setDropWide(true);
                void chat.attach(dropped);
              }
            }}
          >
            {overDrop && (
              <p className="ag-chat-drop">
                {t("chat.drop_zone", { mb: state.upload_max_mb })}
              </p>
            )}
            <div
              className={[
                "ag-chat-scroll",
                regen && "ag-chat-scroll-regen",
                below && "ag-chat-scroll-fade",
              ]
                .filter(Boolean)
                .join(" ")}
              ref={scrollRef}
            >
              <div className="ag-chat-stream" ref={contentRef}>
                {chat.turns.length ? (
                  chat.turns.map((turn, i, all) => (
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
                      // Who else could answer this minute: the free chain
                      // while today's allowance lasts, a BYOK provider only
                      // with a key in hand. A pick that still needs one goes
                      // through settings instead.
                      switchTo={state.providers.filter(
                        (p) =>
                          p.id !== state.answering &&
                          (p.needs_key ? p.has_key : (state.free_left ?? 0) > 0),
                      )}
                      onSwitch={(provider) => void chat.retryWith(provider)}
                      onPickAi={() => setView("settings")}
                      // A table wider than the column it landed in: one press
                      // to the next width that holds it.
                      onWiden={
                        phone || width === "wide" || width === "full"
                          ? undefined
                          : () => resize(window.innerWidth >= 1100 ? "wide" : "full")
                      }
                      onDecide={chat.decide}
                      onUndo={chat.undo}
                      onLeave={onPark ?? onClose}
                      onPress={(activity, action) => chat.press(i, activity, action)}
                      onOpenThread={openThread}
                      onMemory={() => setView("memory")}
                      askRating={rates(turn)}
                      // The exchange being asked right now: the question and
                      // the answer under it come in; a thread opened onto
                      // history is already there and does not.
                      fresh={chat.busy && i >= all.length - 2}
                      onRated={(vote) => turn.id && chat.rated(turn.id, vote)}
                    />
                  ))
                ) : chat.opening ? (
                  // Not the starters: they are an empty thread's, and this one
                  // is only empty until its turns arrive.
                  <Status label={t("common.loading")} />
                ) : needsSetup(state) ? (
                  <Setup
                    state={state}
                    onSave={(patch) => void chat.settings(patch)}
                    onSettings={() => setView("settings")}
                  />
                ) : (
                  <Empty
                    onAsk={(question) => void chat.send(question)}
                    onLeave={onPark ?? onClose}
                  />
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
                    importing={chat.work?.kind === "importing"}
                    wide={dropWide}
                    onImport={(broker, fresh, dupes) =>
                      void chat.commitImport(broker, fresh, dupes)
                    }
                    onDiscard={chat.discardImport}
                    onRemap={chat.remap}
                  />
                )}
                {/* At the bottom, where the card is about to land — below
                    the one it replaces, if there is one. Reading a statement
                    can take a model call on an unknown format, and the clip
                    going grey is all that would happen otherwise. */}
                {chat.work?.kind === "reading" && (
                  <Status
                    label={t("chat.work_reading", { filename: chat.work.filename })}
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
            {(regen || below) && (
              <div className="ag-chat-float">
                {below && (
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
                {regen && (
                  <button
                    type="button"
                    className="ag-chat-regen"
                    onClick={chat.regenerate}
                  >
                    <Glyph name="refresh" size={13} />
                    {t("chat.regenerate")}
                  </button>
                )}
              </div>
            )}
          </div>
          <Composer
            state={state}
            busy={chat.busy}
            reading={chat.reading}
            onSend={(text, spoken, deep) => void chat.send(text, spoken, false, deep)}
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
