/**
 * The page's one state machine: read, ask for today's card, follow it.
 *
 * - `GET /today` reads what is there and never writes: the market read every
 *   account shares and the reader's stored card. It paints at once.
 * - When the stored card no longer stands (a new day, a language switch, a
 *   computed card that can be upgraded) `POST /today` asks for it, once per
 *   day per page. The server shares the job with Home's `POST /daily`, so the
 *   teaser and the page never start two generations; meanwhile the market
 *   half stays on screen and a status line says the reader's half is coming.
 * - While the card says `pending` the page polls `GET /today` every
 *   `POLL_MS`; while the market read is a session behind and a newer one is
 *   being built, every `MARKET_POLL_MS`. One request at a time, capped.
 * - Regenerate is `POST /today?force=true`: the old card goes the instant it
 *   is pressed, and the poll stands down until the server has the new job.
 *
 * A guest never posts: there is no card of theirs to write.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { get, send } from "../../shell/api";
import { nextPoll, wantsWriting } from "./card";
import type { PersonalCard, TodayCard } from "./types";

export type TodayState =
  | { kind: "loading" }
  | { kind: "failed" }
  /** `writing`: today's card has been asked for and is not on screen yet. */
  | { kind: "ready"; view: TodayCard; writing: boolean };

/** A card wiped for its rewrite: the reader just dismissed what it said. */
function blank(card: PersonalCard): PersonalCard {
  return {
    ...card,
    headline: null,
    bullets: [],
    items: [],
    focus: [],
    book: null,
    sections: [],
    today: [],
    pending: true,
  };
}

export function useToday(lang: string, guest: boolean) {
  const [state, setState] = useState<TodayState>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  // Which action day this page has already asked the server to write: a
  // re-render must not fire a second POST while the first is out.
  const asked = useRef<string | null>(null);
  // A Regenerate is out; a GET answered before the server registered the new
  // job would hand back the card the reader just dismissed.
  const posting = useRef(false);
  const polls = useRef(0);

  const write = useCallback(
    (force: boolean) =>
      send<TodayCard>(
        "POST",
        `/today?${new URLSearchParams({ lang, force: String(force) }).toString()}`,
      ),
    [lang],
  );

  useEffect(() => {
    let live = true;
    setState({ kind: "loading" });
    polls.current = 0;
    (async () => {
      const view = await get<TodayCard>("/today", { lang });
      if (!live) return;
      const card = view.personal;
      if (guest || !card || !wantsWriting(card, asked.current)) {
        setState({ kind: "ready", view, writing: false });
        return;
      }
      asked.current = card.action_day;
      setState({ kind: "ready", view, writing: true });
      try {
        const written = await write(false);
        if (live) setState({ kind: "ready", view: written, writing: false });
      } catch {
        // The write is the extra; what is stored is still worth showing.
        if (live) setState({ kind: "ready", view, writing: false });
      }
    })().catch(() => {
      if (live) setState({ kind: "failed" });
    });
    return () => {
      live = false;
    };
  }, [lang, guest, write, reload]);

  // The poll: one request at a time, the next scheduled when the last has
  // answered, and none once the card and the market read both stand.
  const view = state.kind === "ready" && !state.writing ? state.view : null;
  const delay = view ? nextPoll(view, polls.current) : null;
  useEffect(() => {
    if (delay === null) {
      polls.current = 0;
      return;
    }
    let live = true;
    const timer = window.setTimeout(() => {
      polls.current += 1;
      if (posting.current) {
        setState((current) => ({ ...current }));
        return;
      }
      get<TodayCard>("/today", { lang }).then(
        (next) => live && setState({ kind: "ready", view: next, writing: false }),
        // A failed poll keeps what it has; the next render polls again.
        () => live && setState((current) => ({ ...current })),
      );
    }, delay);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [delay, lang, state]);

  const regenerate = useCallback(() => {
    setState((current) =>
      current.kind === "ready" && current.view.personal
        ? {
            ...current,
            view: { ...current.view, personal: blank(current.view.personal) },
          }
        : current,
    );
    posting.current = true;
    polls.current = 0;
    write(true)
      .finally(() => {
        posting.current = false;
      })
      .then(
        (next) => setState({ kind: "ready", view: next, writing: false }),
        // Refused (rate limit, a dropped connection): put back whatever the
        // server says is current rather than leave the wait line up for good.
        () =>
          get<TodayCard>("/today", { lang }).then(
            (next) => setState({ kind: "ready", view: next, writing: false }),
            () => setState({ kind: "failed" }),
          ),
      );
  }, [write, lang]);

  /** Read again from the top, asking for today's card anew (a brief changed). */
  const restart = useCallback(() => {
    asked.current = null;
    setReload((n) => n + 1);
  }, []);

  return { state, regenerate, restart };
}
