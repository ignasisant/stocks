/**
 * One hook for "fetch this, and tell me which of the four states we are in".
 *
 * Every page needs the same four: loading, signed out, failed, loaded. Writing
 * that per component is how a screen ends up rendering a spinner forever when
 * a call fails, or a zero where a number could not be fetched.
 *
 * Not a cache of its own. The API is cached server-side (`stocks.api.cache`),
 * and `shell/api` keeps a one-minute memo of what a screen opened with, so a
 * page revisited draws from what it already had.
 * This hook only decides when that memo may answer. A first fetch reads it,
 * and so does an input changing under a mounted component — a different
 * ticker, a card scrolled into view — because that is a new question, and
 * the memo and the shelf answer it as they would a screen opening. A reload
 * or retry is the reader asking for the server's word on what is on screen:
 * it forgets what that screen was built from, and no more, and the figures
 * stay up (`refreshing`) until the new ones land, rather than a skeleton
 * taking their place.
 *
 * A caller may ask for the same with `keep` when its inputs change — a window
 * picked on a chart, a sector chosen, a language switched: the figures on
 * screen are the wrong ones for a moment, but a dimmed chart of last month is
 * a better place to wait than a skeleton, and the page says so
 * (`Layout.Refreshable`). Off by default, because a symbol page re-asked for
 * another symbol must not show the first one's figures under the second's name.
 *
 * A first fetch may also be answered by the last visit (`shell/keep`): the
 * figures the reader saw then are drawn at once, and the same fetch runs again
 * for the live ones, which replace them when they land — the corner banner
 * says what is still out meanwhile. If that second run fails, the kept figures
 * stay up and the shell's stale line says how old they are.
 *
 * Figures the server itself answered stale (`X-Data-Stale-Since`) are asked
 * for again, quietly, a few times: the server refreshes behind a stale answer,
 * so the same request a little later usually comes back live — and replaces
 * what is on screen without a spinner. Without it the stale line promised the
 * figures would update and only the next navigation delivered. The same for
 * an answer the server says it is refreshing behind (`X-Data-Refreshing`):
 * recent figures, newer ones on the way. Each re-ask is announced
 * (`freshness.noteRetry`), so the line counts down to it and says when it is
 * out; once they stop, the line's own button asks again (`retryStale`).
 *
 * And it abandons what it asked for once nobody can see it: the component
 * unmounting (the reader moved to another screen, or closed this one) or its
 * inputs changing aborts the run's scope, and `shell/api` cancels any request
 * that run was the last one waiting on.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Cancelled,
  NotSignedIn,
  forget,
  fromKept,
  isTransient,
  refresh,
  watched,
  withMemo,
} from "./api";
import {
  isRefreshing,
  noteFreshness,
  noteKept,
  noteRetry,
  onRetryStale,
  retryStale,
  staleAt,
  staleUrls,
} from "./freshness";

/** When a stale answer is asked for again: past a refresh on the server's one
 * throttled vCPU, which runs twenty seconds to a minute. Then it stops — a
 * price source that is down stays down for longer, and the line says so. */
export const FOLLOW_MS = [15_000, 30_000, 60_000] as const;

type Asked<T> = { result: Promise<T>; urls: Set<string> };

/**
 * Ask again, on `FOLLOW_MS`, while any of `urls` last came back stale or
 * refreshing, and hand each answer to `landed`. A failed re-ask is dropped:
 * what is on screen stays, and so does the stale line. Each try is announced
 * under `id` (`freshness.noteRetry`): when it is due, while it is out, and
 * nothing once the follow ends. Returns the stop.
 */
export function followStale<T>(
  urls: Set<string>,
  ask: () => Asked<T>,
  landed: (data: T) => void,
  id = "",
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const announce = (at: number | null) => id && noteRetry(id, at);
  const step = (seen: Set<string>, attempt: number) => {
    const stale = [...seen].filter((url) => staleAt(url) !== null || isRefreshing(url));
    if (stopped || !stale.length || attempt >= FOLLOW_MS.length) {
      if (!stopped) announce(null);
      return;
    }
    // Only a stale answer is worth a countdown; a refreshing one is recent.
    const wait = FOLLOW_MS[attempt] ?? 0;
    if (stale.some((url) => staleAt(url) !== null)) announce(Date.now() + wait);
    timer = setTimeout(() => {
      if (stopped) return;
      if (stale.some((url) => staleAt(url) !== null)) announce(0);
      forget(stale);
      const next = ask();
      next.result.then(
        (data) => {
          if (stopped) return;
          landed(data);
          step(next.urls, attempt + 1);
        },
        () => {
          if (!stopped) announce(null);
        },
      );
    }, wait);
  };
  step(urls, 0);
  return () => {
    stopped = true;
    clearTimeout(timer);
    announce(null);
  };
}

/** Under this id the stale line hears about `retryNow`'s own asks. */
const ORPHANS = "orphans";

/**
 * The stale line's press. Each screen holding a stale URL asks again in place
 * (`retryStale`); a stale URL none of them took — its screen was left, or it
 * was fetched outside `useApi` — is asked for here, so its mark clears or
 * renews instead of the press doing nothing and the line staying for good.
 */
export function retryNow(): void {
  const taken = retryStale();
  const rest = staleUrls().filter((url) => !taken.has(url));
  if (!rest.length) return;
  noteRetry(ORPHANS, 0);
  const ask = (url: string) =>
    refresh(url).catch((error) => {
      // A URL that now fails outright will never answer live: drop its mark.
      if (!isTransient(error)) noteFreshness(url, null);
    });
  void Promise.all(rest.map(ask)).then(() => noteRetry(ORPHANS, null));
}

export type Query<T> =
  /** `urls`: what the first stage asked for, for the skeleton's caption. */
  | { state: "loading"; urls?: string[] }
  | { state: "signed-out" }
  | { state: "failed"; error: unknown; retry: () => void }
  /** `refreshing`: a reload is out, and `data` is the last answer meanwhile. */
  | { state: "loaded"; data: T; reload: () => void; refreshing?: boolean };

let marks = 0;

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[],
  {
    keep = false,
  }: {
    /** Keep the last answer up (`refreshing`) while a changed input is asked. */
    keep?: boolean;
  } = {},
): Query<T> {
  const [query, setQuery] = useState<Query<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  const again = useCallback(() => setNonce((n) => n + 1), []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fetcher, deps);

  const previous = useRef<typeof run | null>(null);
  const lastNonce = useRef(nonce);
  // What the answer on screen was built from: what a reload forgets.
  const held = useRef<Set<string>>(new Set());
  // Read when the run starts, not a reason to start one.
  const keeps = useRef(keep);
  keeps.current = keep;

  useEffect(() => {
    let live = true;
    const changed = previous.current !== null && previous.current !== run;
    const bumped = nonce !== lastNonce.current;
    previous.current = run;
    lastNonce.current = nonce;
    if (bumped) forget(held.current);
    // The figures stay up while the server is asked again — unless the
    // question changed too, when they would be the wrong figures; a caller
    // that would rather dim them than lose them says `keep`.
    const stays = keeps.current || (bumped && !changed);
    setQuery((q) =>
      q.state === "loaded" && stays ? { ...q, refreshing: true } : { state: "loading" },
    );
    const scope = new AbortController();
    // Its own mark in the stale line, for kept figures the live run failed to
    // replace; dropped with the component.
    const mark = `kept:${++marks}`;
    const loaded = (data: T) =>
      live && setQuery({ state: "loaded", data, reload: again });
    const failed = (error: unknown) =>
      live &&
      setQuery(
        error instanceof NotSignedIn
          ? { state: "signed-out" }
          : { state: "failed", error, retry: again },
      );
    const ask = () => watched(() => withMemo(run, scope.signal));
    let stop = () => {};
    // What the last answer was built from, for the stale line's own retry.
    let seen = new Set<string>();
    const follow = (urls: Set<string>) => {
      seen = urls;
      held.current = urls;
      if (live) stop = followStale(urls, ask, loaded, mark);
    };
    // The stale line's "retry": ask again now, in place — the figures stay
    // up while it is out, as with the scheduled re-asks.
    const unhear = onRetryStale(() => {
      const stale = [...seen].filter((url) => staleAt(url) !== null);
      if (!live || (!stale.length && staleAt(mark) === null)) return [];
      stop();
      noteRetry(mark, 0);
      forget(stale);
      const retried = ask();
      retried.result.then(
        (data) => {
          if (!live) return;
          noteFreshness(mark, null);
          loaded(data);
          follow(retried.urls);
        },
        () => live && noteRetry(mark, null),
      );
      return stale;
    });
    const waiting = (urls: Set<string>) => {
      held.current = urls;
      if (!live || !urls.size) return;
      setQuery((q) =>
        q.state === "loaded" && q.refreshing
          ? q
          : { state: "loading", urls: [...urls] },
      );
    };
    if (bumped) {
      const asked = ask();
      waiting(asked.urls);
      asked.result.then((data) => {
        loaded(data);
        follow(asked.urls);
      }, failed);
    } else {
      const first = watched(() => fromKept(run, scope.signal));
      waiting(first.urls);
      first.result.answer.then((data) => {
        const at = first.result.keptAt();
        loaded(data);
        if (!live) return;
        if (at === null) {
          follow(first.urls);
          return;
        }
        // Last visit's figures on screen: the shell says so until these land.
        noteKept(mark, at);
        const current = ask();
        current.result.then(
          (fresh) => {
            noteKept(mark, null);
            loaded(fresh);
            follow(current.urls);
          },
          (error) => {
            noteKept(mark, null);
            if (!live || error instanceof Cancelled) return;
            if (error instanceof NotSignedIn) failed(error);
            else noteFreshness(mark, new Date(at).toISOString());
          },
        );
      }, failed);
    }
    return () => {
      live = false;
      stop();
      unhear();
      scope.abort();
      noteFreshness(mark, null);
      noteKept(mark, null);
      noteRetry(mark, null);
    };
  }, [run, nonce, again]);

  return query;
}
