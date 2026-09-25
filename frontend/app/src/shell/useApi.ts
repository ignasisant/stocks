/**
 * One hook for "fetch this, and tell me which of the four states we are in".
 *
 * Every page needs the same four: loading, signed out, failed, loaded. Writing
 * that per component is how a screen ends up rendering a spinner forever when
 * a call fails, or a zero where a number could not be fetched.
 *
 * Deliberately not a cache. The API is cached server-side on the same keys the
 * Streamlit pages use, so a second request for the same thing is cheap and the
 * client does not need a second, differently-invalidated copy of that logic.
 */

import { useCallback, useEffect, useState } from "react";
import { NotSignedIn } from "./api";

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

  useEffect(() => {
    let live = true;
    setQuery({ state: "loading" });
    run().then(
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
