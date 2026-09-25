/**
 * Linking a Telegram chat: the four-step dance, as one hook.
 *
 * Press Connect, open the deep link, press Start in Telegram, wait. The
 * waiting is the part that cannot be done any other way: the chat id is
 * written by a different process entirely — the scheduled job that reads the
 * bot's updates and matches "/start <code>" — so the only way this screen
 * learns the link took is to ask `GET /notify/telegram` until `linked` turns
 * true. `stocks.api.routes.notify` says the same thing from the other side.
 *
 * Two rules about that poll, both of them the reason this is a hook and not
 * three `useEffect`s in a component: it stops when the code lapses (ten
 * minutes, the server's own TTL, which it hands back as `expires_in`), and it
 * stops while nobody is looking — an unmounted component or a hidden tab
 * leaves no interval behind asking the API a question nobody is waiting for.
 */

import { useCallback, useEffect, useState } from "react";
import { NotSignedIn, get, send } from "../../shell/api";
import { useSession } from "../../shell/session";
import { describe } from "./errors";

/** `GET /notify/telegram` — `routes.notify.Telegram`. */
type Telegram = {
  /** Whether this deployment has a bot at all. False is not an error. */
  configured: boolean;
  linked: boolean;
  /** A code was issued and has not been matched or lapsed yet. */
  pending: boolean;
  /** The linked chat's @handle, without the @; null when it has none. */
  username?: string | null;
};

/** `POST /notify/telegram` — `routes.notify.Link`. */
type Issued = { code: string; deep_link: string; bot: string; expires_in: number };

/** A code this session issued, and the instant it stops being matchable. */
type Pending = {
  code: string;
  /** The t.me URL that carries the code — the server builds it, not this. */
  deepLink: string;
  /** The bot's @username, for a client with no Start button. */
  bot: string;
  deadline: number;
};

/**
 * What just happened, as an outcome rather than a sentence: the copy for each
 * of these lives in the catalog, and the catalog is read in the view.
 */
type Note =
  | { kind: "test_sent" }
  | { kind: "test_failed"; error: string }
  | { kind: "unlinked" }
  | { kind: "failed"; error: string };

type Action = "connect" | "test" | "unlink";

export type Channel = {
  /** Null until the first read lands; the card says it is loading. */
  state: Telegram | null;
  pending: Pending | null;
  /** The code lapsed before anyone pressed Start. */
  expired: boolean;
  /** A poll tick did not come back. The next one retries. */
  stalled: boolean;
  busy: Action | null;
  note: Note | null;
  connect: () => void;
  test: () => void;
  unlink: () => void;
};

/** The Streamlit page's own interval. Slow enough to be free, fast enough to feel live. */
const POLL_MS = 3000;

export function useTelegram(offline: string): Channel {
  // `reload` is the only thing wanted from the session here, and it is stable
  // across renders (the session object itself is not — it is rebuilt each
  // time, so putting it in a dependency list would re-run the effect forever).
  const { reload } = useSession();
  const [state, setState] = useState<Telegram | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [expired, setExpired] = useState(false);
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState<Action | null>(null);
  const [note, setNote] = useState<Note | null>(null);

  // A session that ended mid-flow is not this page's error to word: reloading
  // it puts the shell's own sign-in wall up, as every other write here does.
  const refused = useCallback(
    (error: unknown): Note | null => {
      if (error instanceof NotSignedIn) {
        reload();
        return null;
      }
      return { kind: "failed", error: describe(error, offline) };
    },
    [reload, offline],
  );

  useEffect(() => {
    let alive = true;
    get<Telegram>("/notify/telegram").then(
      (fresh) => alive && setState(fresh),
      (error: unknown) => {
        if (!alive) return;
        setNote(refused(error));
      },
    );
    return () => {
      alive = false;
    };
  }, [refused]);

  // Whether anyone is looking. A hidden tab polls nothing at all: the interval
  // is torn down rather than left running with its requests skipped.
  const [visible, setVisible] = useState(
    () => typeof document === "undefined" || !document.hidden,
  );
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  useEffect(() => {
    if (!pending || !visible) return;
    // Coming back to a tab that was hidden longer than the code lives: the
    // deadline is wall-clock, so it is already past and there is nothing to
    // poll for.
    if (Date.now() >= pending.deadline) {
      setPending(null);
      setExpired(true);
      return;
    }
    let alive = true;
    const timer = window.setInterval(() => {
      if (Date.now() >= pending.deadline) {
        setPending(null);
        setExpired(true);
        return;
      }
      get<Telegram>("/notify/telegram").then(
        (fresh) => {
          if (!alive) return;
          setStalled(false);
          setState(fresh);
          if (fresh.linked) setPending(null);
        },
        // Transient by assumption — the next tick retries, and the reader is
        // told the wait is still a wait rather than shown a dead screen.
        () => alive && setStalled(true),
      );
    }, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [pending, visible]);

  const connect = useCallback(() => {
    setBusy("connect");
    setNote(null);
    setExpired(false);
    send<Issued>("POST", "/notify/telegram").then(
      (issued) => {
        setBusy(null);
        setPending({
          code: issued.code,
          deepLink: issued.deep_link,
          bot: issued.bot,
          deadline: Date.now() + issued.expires_in * 1000,
        });
      },
      (error: unknown) => {
        setBusy(null);
        setNote(refused(error));
      },
    );
  }, [refused]);

  const test = useCallback(() => {
    setBusy("test");
    setNote(null);
    send<Telegram>("POST", "/notify/telegram/test").then(
      (fresh) => {
        setBusy(null);
        setState(fresh);
        setNote({ kind: "test_sent" });
      },
      (error: unknown) => {
        setBusy(null);
        if (error instanceof NotSignedIn) {
          reload();
          return;
        }
        // Telegram's own reason for refusing, which the route passes through
        // on its 502. Swallowing it would leave "it didn't work" and no idea
        // why — and the why here is usually "you blocked the bot".
        setNote({ kind: "test_failed", error: describe(error, offline) });
      },
    );
  }, [reload, offline]);

  const unlink = useCallback(() => {
    setBusy("unlink");
    setNote(null);
    send<Telegram>("DELETE", "/notify/telegram").then(
      (fresh) => {
        setBusy(null);
        setState(fresh);
        setPending(null);
        setExpired(false);
        setNote({ kind: "unlinked" });
      },
      (error: unknown) => {
        setBusy(null);
        setNote(refused(error));
      },
    );
  }, [refused]);

  return { state, pending, expired, stalled, busy, note, connect, test, unlink };
}
