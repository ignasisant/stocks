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
 * This hook only decides when that memo may answer: a first fetch reads it, a
 * re-ask — retry, reload, or an input that changed under a mounted component —
 * drops it first, because those are a reader asking for the server's word.
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
 * recent figures, newer ones on the way.
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
  invalidate,
  watched,
  withMemo,
} from "./api";
import { isRefreshing, noteFreshness, staleAt } from "./freshness";

/** When a stale answer is asked for again: past a refresh on the server's one
 * throttled vCPU, which runs twenty seconds to a minute. Then it stops — a
 * price source that is down stays down for longer, and the line says so. */
export const FOLLOW_MS = [15_000, 30_000, 60_000] as const;

type Asked<T> = { result: Promise<T>; urls: Set<string> };

/**
 * Ask again, on `FOLLOW_MS`, while any of `urls` last came back stale or
 * refreshing, and hand each answer to `landed`. A failed re-ask is dropped:
 * what is on screen stays, and so does the stale line. Returns the stop.
 */
export function followStale<T>(
  urls: Set<string>,
  ask: () => Asked<T>,
  landed: (data: T) => void,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;
  const step = (seen: Set<string>, attempt: number) => {
    const stale = [...seen].filter((url) => staleAt(url) !== null || isRefreshing(url));
    if (stopped || !stale.length || attempt >= FOLLOW_MS.length) return;
    timer = setTimeout(() => {
      if (stopped) return;
      forget(stale);
      const next = ask();
      next.result.then(
        (data) => {
          if (stopped) return;
          landed(data);
          step(next.urls, attempt + 1);
        },
        () => undefined,
      );
    }, FOLLOW_MS[attempt]);
  };
  step(urls, 0);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}

export type Query<T> =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "failed"; error: unknown; retry: () => void }
  | { state: "loaded"; data: T; reload: () => void };

let marks = 0;

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): Query<T> {
  const [query, setQuery] = useState<Query<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  const again = useCallback(() => setNonce((n) => n + 1), []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fetcher, deps);

  const previous = useRef<typeof run | null>(null);

  useEffect(() => {
    let live = true;
    const reask = nonce > 0 || (previous.current !== null && previous.current !== run);
    if (reask) invalidate();
    previous.current = run;
    setQuery({ state: "loading" });
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
    const follow = (urls: Set<string>) => {
      if (live) stop = followStale(urls, ask, loaded);
    };
    if (reask) {
      const asked = ask();
      asked.result.then((data) => {
        loaded(data);
        follow(asked.urls);
      }, failed);
    } else {
      const first = watched(() => fromKept(run, scope.signal));
      first.result.answer.then((data) => {
        const at = first.result.keptAt();
        loaded(data);
        if (!live) return;
        if (at === null) {
          follow(first.urls);
          return;
        }
        const current = ask();
        current.result.then(
          (fresh) => {
            loaded(fresh);
            follow(current.urls);
          },
          (error) => {
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
      scope.abort();
      noteFreshness(mark, null);
    };
  }, [run, nonce, again]);

  return query;
}
