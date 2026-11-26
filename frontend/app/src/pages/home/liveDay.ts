/**
 * The book's day kept live while the reader watches it.
 *
 * The book behind Home is one burst of eight reads; asking all of it again
 * every minute would rebuild the week and the month for nothing. Only the day
 * moves under a reader, so only `/movers?window=day` is asked again, every
 * `POLL_MS.movers`, and laid over the book the page already holds. The
 * server answers it off its shared quote board (a minute old at most for a
 * name that is trading), so the poll costs the market-data feeds nothing per
 * reader.
 *
 * Every minute while some name in the book is moving (`active`: a live
 * session, US pre/after-hours, or a coin); every five while none is, only to
 * notice an open on a page left up since before it. Never while the tab is
 * hidden, and at once when it comes back stale. One request at a time, the
 * next scheduled when the last answers. A failed ask keeps the last answer up
 * and tries again on the next beat.
 */

import { useEffect, useMemo, useState } from "react";
import { forgetUnder, get } from "../../shell/api";
import { POLL_MS } from "../../shell/poll";
import type { Query } from "../../shell/useApi";
import type { Book } from "./Glance";
import type { Movers } from "./types";

/** Whether any row of the day is a move under way. */
export function moving(day: Movers | null | undefined): boolean {
  if (!day) return false;
  return [...day.gainers, ...day.losers].some((row) => row.active);
}

/**
 * `quoted_at` as the reader's clock reads it: "15:42", or "25 nov, 15:42" when
 * it is not today's (an answer kept from the last visit). Null when unset.
 */
export function quotedTime(
  at: string | null | undefined,
  lang: string,
  now: Date = new Date(),
): string | null {
  if (!at) return null;
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return null;
  const clock = { hour: "2-digit", minute: "2-digit" } as const;
  if (when.toDateString() === now.toDateString()) {
    return when.toLocaleTimeString(lang, clock);
  }
  return when.toLocaleString(lang, { day: "numeric", month: "short", ...clock });
}

export function useLiveDay(query: Query<Book | null>): Query<Book | null> {
  const book = query.state === "loaded" ? query.data : null;
  const day = book?.movers.day ?? null;
  // Tied to the day it refreshed: a reload of the whole book brings its own.
  const [fresh, setFresh] = useState<{ from: Movers; day: Movers } | null>(null);
  const live = fresh?.from === day ? fresh.day : day;
  const trading = moving(live);

  useEffect(() => {
    if (!day) return undefined;
    const every = trading ? POLL_MS.movers : POLL_MS.moversIdle;
    let stop = false;
    let asking = false;
    let asked = Date.now();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const beat = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(tick, every);
    };
    const tick = async () => {
      if (stop || asking) return;
      if (document.visibilityState === "hidden") return beat();
      asking = true;
      asked = Date.now();
      // Past the API memo: this ask exists to get what the memo would hide.
      forgetUnder(["/movers?window=day"]);
      try {
        const next = await get<Movers>("/movers", { window: "day", all: "true" });
        if (!stop) setFresh({ from: day, day: next });
      } catch {
        // The last answer stays up; the next beat asks again.
      }
      asking = false;
      if (!stop) beat();
    };
    // Back on the tab after a beat or more away: ask now, not a beat later.
    const back = () => {
      if (document.visibilityState === "visible" && Date.now() - asked >= every) {
        void tick();
      }
    };
    document.addEventListener("visibilitychange", back);
    beat();
    return () => {
      stop = true;
      document.removeEventListener("visibilitychange", back);
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [day, trading]);

  return useMemo(() => {
    if (query.state !== "loaded" || !query.data || !live || live === day) return query;
    return {
      ...query,
      data: { ...query.data, movers: { ...query.data.movers, day: live } },
    };
  }, [query, live, day]);
}
