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
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { NotSignedIn, invalidate, withMemo } from "./api";

export type Query<T> =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "failed"; error: unknown; retry: () => void }
  | { state: "loaded"; data: T; reload: () => void };

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): Query<T> {
  const [query, setQuery] = useState<Query<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  const again = useCallback(() => setNonce((n) => n + 1), []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fetcher, deps);

  const previous = useRef<typeof run | null>(null);

  useEffect(() => {
    let live = true;
    if (nonce > 0 || (previous.current !== null && previous.current !== run)) {
      invalidate();
    }
    previous.current = run;
    setQuery({ state: "loading" });
    withMemo(run).then(
      (data) => live && setQuery({ state: "loaded", data, reload: again }),
      (error) =>
        live &&
        setQuery(
          error instanceof NotSignedIn
            ? { state: "signed-out" }
            : { state: "failed", error, retry: again },
        ),
    );
    return () => {
      live = false;
    };
  }, [run, nonce, again]);

  return query;
}
