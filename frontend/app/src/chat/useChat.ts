/**
 * The drawer's state: which thread is open, what is in it, and what is being
 * written into it right now.
 *
 * It lives above the panel rather than inside it, so closing the drawer never
 * cancels an answer: the fetch, the reader and the turn being assembled all
 * belong to a hook the shell keeps mounted, and re-opening shows the answer
 * that carried on without anyone watching. Stopping is the one thing that
 * does cancel it, and it is a press, not a side effect of closing a panel.
 *
 * Nothing here is a cache. A completed turn is refetched — the list for its
 * auto-generated title and its message count, the state for what the turn just
 * spent — because both are decided on the server and a client that guessed
 * either would eventually disagree with the next reload.
 *
 * Provider keys are deliberately not handled here. This module is in the shell
 * chunk that every reader pays for, and the key form is opened by perhaps one
 * of them: `Settings.tsx` calls `storeKey`/`forgetKey` itself and hands the
 * state it gets back to `apply`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../shell/api";
import { useLang } from "../shell/i18n";
import { useRoute } from "../shell/router";
import {
  asBase64,
  ask,
  commitAttachment,
  dropThread,
  editThread,
  readState,
  readAttachment,
  readThread,
  readThreads,
  saveSettings,
  startThread,
} from "./api";
import {
  advanceGuide,
  finishGuide,
  readGuide,
  startGuide,
  syncGuide,
  type GuideState,
} from "./guide";
import type {
  ChatState,
  Conversation,
  ImportRow,
  Preview,
  SettingsPatch,
  Turn,
} from "./types";

const blank = (role: string, content: string): Turn => ({
  role,
  content,
  skills: [],
  web: [],
  action: null,
});

/** Whether this turn is one the server never stored — a refusal or a stop. */
const unfiled = (turn: Turn | undefined): boolean =>
  !!turn && turn.role === "assistant" && (!!turn.error || !!turn.stopped);

export type Chat = ReturnType<typeof useChat>;

export function useChat(live: boolean) {
  const lang = useLang();
  // Where the reader is, told to the model with every question — the
  // Streamlit panel's `_view_context`. The Ticker page's company is its
  // `?ticker=` (the page writes its default there when the URL has none), and
  // no other page has a single company in focus, so no other page names one:
  // a symbol left over in some other page's URL is not what "this" means.
  const route = useRoute();
  const view = route.page;
  const focus =
    route.page === "ticker"
      ? (route.params.get("ticker") ?? route.params.get("symbol") ?? "").trim()
      : "";
  const [state, setState] = useState<ChatState | null>(null);
  const [threads, setThreads] = useState<Conversation[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  // The statement waiting on its button, and the file being read into one.
  // Session-only on purpose: the preview card is not a turn, so a reload
  // leaves the note the server filed and drops the card — which is the same
  // thing a closed Streamlit session does, and for the same reason (the
  // uploaded bytes are never kept anywhere).
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reading, setReading] = useState(false);
  // Bumped by every batch this drawer writes. The broker-move repair below
  // the thread is a question about the ledger, and the ledger just changed.
  const [imported, setImported] = useState(0);
  // Where the walkthrough is. The server owns it; this is the last answer.
  const [guide, setGuide] = useState<GuideState | null>(null);

  // Chunks are collected and written once a frame. A fast provider sends
  // hundreds of them in a few seconds, and a setState per chunk re-renders the
  // whole thread that often — which is how a streaming answer ends up slower
  // to read than a blocking one.
  const pending = useRef("");
  const frame = useRef(0);
  // The turn in flight, so that Stop has something to pull on.
  const flight = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const [next, list] = await Promise.all([readState(), readThreads()]);
    setState(next);
    setThreads(list);
    return list;
  }, []);

  // Where the walkthrough is, read once when the drawer first opens — it moves
  // only when the reader moves it, and every move answers with the new state.
  // Beside the opening read, never in its way: an account the route refuses
  // (a guest) or a server without it simply has no walkthrough.
  const guideRead = useRef(false);
  useEffect(() => {
    if (!live || guideRead.current) return;
    guideRead.current = true;
    readGuide().then(setGuide, () => setGuide(null));
  }, [live]);

  // Once per mount, and keyed on nothing the read itself changes: `refresh()`
  // sets `state` halfway through, and an effect that depended on `state` was
  // torn down by its own first write — `alive` went false before the thread
  // was read, so the drawer opened on the empty state over a thread that had
  // turns in it (the guide's welcome, most visibly).
  const opened = useRef(false);
  useEffect(() => {
    if (!live || opened.current) return;
    opened.current = true;
    let alive = true;
    let done = false;
    (async () => {
      try {
        const list = await refresh();
        const open = list.find((c) => c.active) ?? list[0];
        if (alive && open) {
          setActiveId(open.id);
          const thread = await readThread(open.id);
          if (alive) setTurns(thread.messages.map((m) => ({ ...m })));
        }
      } catch {
        if (alive) setFailed(true);
      } finally {
        // Whatever the opening read found — a thread, none, or a failure —
        // it is over, and nothing that switches threads may start before it
        // or the late answer would paint the wrong conversation over it.
        if (alive) setReady(true);
        done = true;
      }
    })();
    return () => {
      alive = false;
      // Closed (or unmounted) before the read landed: let the next open try
      // again rather than leave a drawer that never loaded.
      if (!done) opened.current = false;
    };
  }, [live, refresh]);

  const write = useCallback((edit: (turn: Turn) => Turn) => {
    setTurns((list) => {
      const last = list[list.length - 1];
      if (!last) return list;
      return [...list.slice(0, -1), edit(last)];
    });
  }, []);

  const flush = useCallback(() => {
    const chunk = pending.current;
    pending.current = "";
    frame.current = 0;
    if (chunk) write((turn) => ({ ...turn, content: turn.content + chunk }));
  }, [write]);

  /** Drop the frame loop and hand back whatever it was still holding. */
  const settle = useCallback(() => {
    if (frame.current) cancelAnimationFrame(frame.current);
    frame.current = 0;
    const tail = pending.current;
    pending.current = "";
    return tail;
  }, []);

  const send = useCallback(
    async (text: string, spoken = false, again = false) => {
      const message = text.trim();
      // A second send while one is in flight is refused, not queued: the
      // engine writes one thread and the second turn would land inside the
      // first one's history half-written.
      if ((!message && !again) || busy) return;
      setBusy(true);
      setModel(null);
      const started = Date.now();
      const control = new AbortController();
      flight.current = control;
      // Who was supposed to answer, read before the question goes out. The
      // `meta` frame names who actually did, and the pair is the whole of
      // `chat.fallback_note` — read afterwards it would name whoever the next
      // state refresh put at the head of the chain instead.
      const chose = state?.answering ?? null;
      // Regenerating rewinds the thread server-side, so the question stays
      // where it is on screen and only the answer under it is replaced.
      setTurns((list) => [
        ...(again ? list.slice(0, -1) : list),
        ...(again ? [] : [{ ...blank("user", message), ts: started, spoken } as Turn]),
        { ...blank("assistant", ""), pending: true },
      ]);
      // Read when the question goes out, not when it is answered: a reader who
      // navigates while the answer is written asked about the page they were on.
      const where = { view, ...(focus ? { focus } : {}) };
      try {
        const done = await ask(
          again
            ? { regenerate: true, conversation: activeId ?? undefined, lang, ...where }
            : {
                message,
                conversation: activeId ?? undefined,
                lang,
                ...where,
                // A card is waiting: "import these" is answered with its button.
                staged_import: preview?.filename,
              },
          (meta) => {
            setModel(meta.model);
            write((turn) => ({
              ...turn,
              skills: meta.skills,
              by: meta.provider,
              ...(chose ? { chose } : {}),
            }));
          },
          (chunk) => {
            pending.current += chunk;
            if (!frame.current) frame.current = requestAnimationFrame(flush);
          },
          (phase) => write((turn) => ({ ...turn, phase })),
          control.signal,
        );
        settle();
        const took = (Date.now() - started) / 1000;
        write((turn) => ({
          ...turn,
          // `done.text` is the answer; the chunks were only what made the
          // wait bearable, and a provider that died after its first words
          // leaves the two disagreeing.
          content: done.text,
          skills: done.skills,
          web: done.sources,
          steps: done.steps ?? [],
          // The walkthrough's jump, already checked against the registry.
          guide_goto: done.goto ?? null,
          pending: false,
          phase: undefined,
          ts: Date.now(),
          took,
          ...(done.error ? { error: done.error } : {}),
        }));
        // A refused turn is never written to disk, so the thread on the
        // server is unchanged and there is nothing to re-read; a served one
        // has a new title, a new count and a spent allowance.
        if (!done.error) {
          const list = await refresh();
          const open = list.find((c) => c.active);
          if (open) setActiveId(open.id);
        }
      } catch (failure) {
        const tail = settle();
        if (control.signal.aborted) {
          // Stopped, not failed. The words that arrived are kept and marked
          // as cut short; the server recorded none of it, so the thread is
          // unchanged and only the spent allowance is worth re-reading.
          write((turn) => ({
            ...turn,
            content: turn.content + tail,
            pending: false,
            stopped: true,
            ts: Date.now(),
            took: (Date.now() - started) / 1000,
          }));
          await refresh().catch(() => {});
        } else if (failure instanceof ApiError && failure.status === 429) {
          // The burst wall, shared with the Streamlit composer. Not a fault,
          // and not unfiled forever either: Retry lands once the window moves.
          write((turn) => ({
            ...turn,
            pending: false,
            error: "chat.rate_limited",
            wait: failure.retryAfter,
          }));
        } else {
          write((turn) => ({ ...turn, pending: false, error: "chat.api_error" }));
        }
      } finally {
        flight.current = null;
        setBusy(false);
      }
    },
    [activeId, busy, flush, focus, lang, preview, refresh, settle, state, view, write],
  );

  /** Cut the answer being written. Nothing is queued: the press is the abort. */
  const stop = useCallback(() => {
    flight.current?.abort();
  }, []);

  /**
   * Ask the last question again, in place of the pair it left behind.
   *
   * Only ever offered on a turn the server never filed — a refusal or a stop —
   * which is what makes this honest: the thread on disk does not hold the
   * question, so asking it again replaces that turn rather than adding a
   * second copy of it under the first.
   */
  const retry = useCallback(() => {
    const answer = turns[turns.length - 1];
    const question = turns[turns.length - 2];
    if (busy || !unfiled(answer) || question?.role !== "user") return;
    setTurns((list) => list.slice(0, -2));
    void send(question.content);
  }, [busy, send, turns]);

  /**
   * Answer the last question again.
   *
   * Not `retry`: that one is for a question that was never answered, and it
   * re-sends it. This one has an answer on the thread, and the server rewinds
   * the pair before writing a new one — so the thread ends up holding one
   * exchange, not the same question twice.
   */
  const regenerate = useCallback(() => {
    const answer = turns[turns.length - 1];
    if (busy || !answer || answer.role !== "assistant" || answer.pending) return;
    if (answer.error || answer.stopped) return; // `retry` owns those
    void send("", false, true);
  }, [busy, send, turns]);

  /**
   * Take the unanswered question off the thread, refusal and all — the
   * Streamlit composer's "Discard question" beside Retry.
   *
   * Local only, and correctly so: a refused or stopped turn is never written
   * (the engine saves the pair only once an answer exists), so the thread on
   * disk already holds neither and there is nothing to delete there. A failed
   * attachment is the exception to taking two: it has no question of its own
   * above it, and the user turn there belongs to an exchange that was filed.
   */
  const drop = useCallback(() => {
    if (busy) return;
    setTurns((list) => {
      const last = list[list.length - 1];
      if (!unfiled(last)) return list;
      return last?.action !== "import" && list[list.length - 2]?.role === "user"
        ? list.slice(0, -2)
        : list.slice(0, -1);
    });
  }, [busy]);

  const open = useCallback(async (cid: string) => {
    setActiveId(cid);
    setTurns([]);
    await editThread(cid, { active: true });
    const thread = await readThread(cid);
    setTurns(thread.messages.map((m) => ({ ...m })));
    setThreads((list) => (list ?? []).map((c) => ({ ...c, active: c.id === cid })));
  }, []);

  const create = useCallback(async () => {
    // Pressing New twice cannot stack blanks: the API hands back the empty
    // thread that already exists.
    const thread = await startThread();
    setActiveId(thread.id);
    setTurns([]);
    await refresh();
  }, [refresh]);

  const rename = useCallback(
    async (cid: string, title: string) => {
      await editThread(cid, { title });
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (cid: string) => {
      await dropThread(cid);
      const list = await refresh();
      if (cid !== activeId) return;
      const open = list.find((c) => c.active) ?? list[0];
      setActiveId(open?.id ?? null);
      setTurns(open ? (await readThread(open.id)).messages.map((m) => ({ ...m })) : []);
    },
    [activeId, refresh],
  );

  /**
   * Read a statement the reader just attached, and show what it would import.
   *
   * One file at a time: an attachment is a preview somebody confirms, and a
   * second one would either queue a second card behind the first or be
   * dropped with an apology. The note the server files lands on the thread,
   * so it is appended here too rather than re-read.
   */
  const attach = useCallback(
    async (file: File) => {
      if (reading || busy) return;
      setReading(true);
      try {
        const found = await readAttachment({
          filename: file.name,
          content: await asBase64(file),
          conversation: activeId ?? undefined,
          lang,
        });
        setTurns((list) => [...list, { ...found.message, skills: [], web: [] }]);
        // Only a file with something in it gets a card. The note already says
        // what happened to one that has not.
        if (found.fresh.length || found.duplicates.length) setPreview(found);
        await refresh().catch(() => {});
      } catch (failure) {
        const walled = failure instanceof ApiError && failure.status === 429;
        setTurns((list) => [
          ...list,
          {
            role: "assistant",
            content: "",
            skills: [],
            web: [],
            action: "import",
            error: walled ? "chat.rate_limited" : "chat.api_error",
            wait: walled ? failure.retryAfter : undefined,
            ts: Date.now(),
          },
        ]);
      } finally {
        setReading(false);
      }
    },
    [activeId, busy, lang, reading, refresh],
  );

  /** Write the rows on the card, plus whichever duplicates were opted in. */
  const commitImport = useCallback(
    async (broker: string, duplicates: ImportRow[] = []) => {
      if (!preview) return;
      setReading(true);
      try {
        const done = await commitAttachment({
          filename: preview.filename,
          platform: preview.platform,
          broker,
          rows: [...preview.fresh, ...duplicates],
          conversation: activeId ?? undefined,
          lang,
        });
        setPreview(null);
        setImported((n) => n + 1);
        setTurns((list) => [...list, { ...done.message, skills: [], web: [] }]);
        await refresh().catch(() => {});
      } catch {
        setTurns((list) => [
          ...list,
          {
            role: "assistant",
            content: "",
            skills: [],
            web: [],
            action: "import",
            error: "chat.api_error",
            ts: Date.now(),
          },
        ]);
      } finally {
        setReading(false);
      }
    },
    [activeId, lang, preview, refresh],
  );

  /** Re-read one thread in place — no blank frame between the two versions. */
  const reread = useCallback(async (cid: string) => {
    const thread = await readThread(cid);
    setTurns(thread.messages.map((m) => ({ ...m })));
  }, []);

  /**
   * Open the walkthrough on its own thread.
   *
   * `auto` is the automatic open, which spends one of the account's three; one
   * the reader asked for spends nothing. The server has already made the
   * guide's thread the active one, so this only follows it there.
   */
  const guideStart = useCallback(
    async (opts: { step?: string; auto?: boolean } = {}) => {
      const next = await startGuide({ ...opts, lang });
      setGuide(next);
      if (next.thread) {
        setActiveId(next.thread);
        await reread(next.thread);
        await refresh().catch(() => {});
      }
      return next;
    },
    [lang, refresh, reread],
  );

  /**
   * Catch the guide's thread up with what the account did meanwhile — an
   * import in another tab is progress, not a step to re-read. Only ever the
   * guide's own thread, and only while it is the one on screen.
   */
  const guideSync = useCallback(async () => {
    if (!guide?.active || !guide.thread || guide.thread !== activeId) return;
    const next = await syncGuide(lang);
    setGuide(next);
    if (next.changed && next.thread) await reread(next.thread);
  }, [activeId, guide, lang, reread]);

  /** Next step. Resolves with the new state, so the caller can follow it. */
  const guideAdvance = useCallback(async () => {
    const next = await advanceGuide(lang);
    setGuide(next);
    if (next.thread) await reread(next.thread);
    return next;
  }, [lang, reread]);

  const guideFinish = useCallback(async (reason: string) => {
    setGuide(await finishGuide(reason));
  }, []);

  /** Throw the card away. Nothing was written, so nothing has to be undone. */
  const discardImport = useCallback(() => setPreview(null), []);

  const settings = useCallback(async (patch: SettingsPatch) => {
    setState(await saveSettings(patch));
  }, []);

  /**
   * Take a state the caller already has.
   *
   * Storing or forgetting a key answers with the whole state, because both
   * change who serves the next turn. Handing it back here rather than
   * re-reading keeps the header, the composer's wall and the settings view
   * agreeing within the same press.
   */
  const apply = useCallback((next: ChatState) => setState(next), []);

  return {
    state,
    threads,
    activeId,
    turns,
    busy,
    failed,
    model,
    send,
    stop,
    retry,
    regenerate,
    drop,
    open,
    create,
    rename,
    remove,
    settings,
    apply,
    preview,
    reading,
    imported,
    ready,
    guide,
    guideStart,
    guideSync,
    guideAdvance,
    guideFinish,
    attach,
    commitImport,
    discardImport,
  };
}
