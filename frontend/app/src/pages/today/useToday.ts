/**
 * The page's card flow (`cardFlow`) over `GET/POST /today`.
 *
 * - `GET /today` reads the market read every account shares and the reader's
 *   stored card. When that card no longer stands `POST /today` asks for it;
 *   the server shares the job with Home's `POST /daily`, so the teaser and the
 *   page never start two generations. Meanwhile the market half stays on
 *   screen and a status line says the reader's half is coming.
 * - The poll runs every `POLL_MS.card` while the card is pending, every
 *   `POLL_MS.market` while the market read is a session behind, capped
 *   (`nextPoll`): a card still pending at the cap is `stalled`, and the page
 *   offers a retry.
 *
 * A guest never posts: there is no card of theirs to write.
 */

import { useMemo } from "react";
import { get, send } from "../../shell/api";
import { nextPoll } from "./card";
import { useCardFlow, type CardSource } from "./cardFlow";
import type { PersonalCard, TodayCard } from "./types";

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
  const source = useMemo<CardSource<TodayCard>>(
    () => ({
      read: () => get<TodayCard>("/today", { lang }),
      write: (force) =>
        send<TodayCard>(
          "POST",
          `/today?${new URLSearchParams({ lang, force: String(force) }).toString()}`,
        ),
      card: (view) => (guest ? null : view.personal),
      next: nextPoll,
      blank: (view) =>
        view.personal ? { ...view, personal: blank(view.personal) } : view,
    }),
    [lang, guest],
  );
  return useCardFlow(source);
}
