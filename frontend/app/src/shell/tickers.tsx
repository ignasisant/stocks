/**
 * A ticker on screen is a logo and a link — everywhere, and in one request.
 *
 * The house rule (`ticker_cell` in the Streamlit app) is that a bare symbol is
 * never enough: a reader scanning a table recognises a mark long before they
 * read four letters, and a symbol with nowhere to click is a dead end. Getting
 * that right per row would be one `/ticker/{symbol}/profile` call per row, and
 * a seventeen-name cohort answering in seventeen requests is how a table gets
 * itself rate limited — which is what `/market/profiles` exists to prevent.
 *
 * So every cell asks this module, and this module asks the server once per
 * render pass: the registrations that happen while a table mounts are
 * collected and flushed together, in chunks the route will accept.
 *
 * Module-level rather than a context, because there is exactly one account per
 * document here — the session is resolved before anything renders and cannot
 * change without a reload, so a provider would be ceremony around a constant.
 * `reset()` exists for the one caller that is not a browser: a test.
 */

import { useEffect, useSyncExternalStore } from "react";

import { get } from "./api";
import { Link } from "./router";

export type Profile = {
  ticker: string;
  /** "" when no catalog this account has warmed knows the name. */
  name: string;
  /** null when nobody has a mark for it — a real answer, not a missing one. */
  logo: string | null;
};

/** The route's own cap. Asking for more is a 422, not a truncated answer. */
const CHUNK = 50;

const cache = new Map<string, Profile>();
// Asked and answered with nothing. Kept apart from `cache` so a symbol nobody
// has a logo for is not asked about again on every table that mentions it.
const answered = new Set<string>();
const listeners = new Set<() => void>();
let queue = new Set<string>();
let scheduled = false;

function announce() {
  for (const listener of listeners) listener();
}

async function flush() {
  scheduled = false;
  const wanted = [...queue];
  queue = new Set();
  for (let at = 0; at < wanted.length; at += CHUNK) {
    const batch = wanted.slice(at, at + CHUNK);
    try {
      const answer = await get<{ profiles: Profile[] }>("/market/profiles", {
        tickers: batch.join(","),
      });
      for (const profile of answer.profiles) {
        if (profile.logo || profile.name) cache.set(profile.ticker, profile);
      }
    } catch {
      // A logo is decoration on a link that already works. A failed batch is
      // marked answered so the page does not retry it on every scroll, and the
      // cells render as plain links — which is what they do anyway until this
      // lands.
    }
    for (const ticker of batch) answered.add(ticker);
  }
  announce();
}

function request(ticker: string) {
  if (cache.has(ticker) || answered.has(ticker) || queue.has(ticker)) return;
  queue.add(ticker);
  if (scheduled) return;
  scheduled = true;
  // A macrotask, not a microtask: effects from one commit run before the
  // browser yields, so this collects a whole table's worth of cells rather
  // than the first one alone.
  setTimeout(flush, 0);
}

export function useTickerProfile(ticker: string): Profile | null {
  const key = ticker.trim().toUpperCase();
  const value = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => cache.get(key) ?? null,
    () => null,
  );
  useEffect(() => {
    if (key) request(key);
  }, [key]);
  return value;
}

/**
 * The cell itself: the mark, the symbol, and the link to its page.
 *
 * `className` is the caller's, because a table cell and a chip are the same
 * content at two sizes and the page owns its own spacing. The logo carries an
 * empty alt: the symbol is right beside it, and a screen reader announcing
 * "Apple logo Apple" reads the name twice.
 */
export function TickerCell({
  ticker,
  className,
  children,
}: {
  ticker: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const profile = useTickerProfile(ticker);
  return (
    <Link
      page="ticker"
      params={{ ticker }}
      className={className}
      title={profile?.name || undefined}
    >
      {profile?.logo ? (
        <img className="ag-tick-logo" src={profile.logo} alt="" loading="lazy" />
      ) : null}
      {children ?? ticker}
    </Link>
  );
}
