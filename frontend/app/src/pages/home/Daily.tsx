/**
 * The assistant's one-a-day briefing, first thing on the page.
 *
 * `web/daily_ui.py` is the specification, and its shape is the one this
 * component keeps: the day's first visit writes the card, a provider that
 * answers inside a couple of seconds lands straight away, and a slower one
 * leaves the computed card up — the same triggers, stated without a model —
 * with a pulsing line saying the real one is still being written, until it
 * swaps itself in. The section is never an empty slot and never a spinner.
 *
 * Three requests carry that over HTTP, and they are split on purpose:
 *
 * - `GET /daily` reads what is there. It never writes, because a GET that
 *   could spend the account's free allowance is a GET a prefetch could empty.
 * - `POST /daily` asks for today's card when the stored one no longer stands
 *   (a new day, a new session, a language switch). The server spends at most
 *   one generation per account per key; asking again after a failure returns
 *   the computed card rather than calling the same dead provider.
 * - While the answer says `pending`, the card polls `GET /daily` every
 *   `POLL_MS` — `daily_ui`'s timed fragment — and stops the moment it does not.
 *
 * "Regenerate" is `POST /daily?force=true`: the old card goes the instant it
 * is pressed (the reader just dismissed it; leaving it up would have them
 * reading a briefing they asked to replace), the button stays disabled while
 * its own rewrite is out, and a second press cannot start a second paid
 * generation. "Ask the assistant" opens the drawer, as the Streamlit button
 * does — it asks nothing on the reader's behalf.
 *
 * `source: "computed"` is the fallback built from the triggers alone when no
 * model answered. It is not prose, and it is not presented as a briefing: that
 * card carries `home.daily_computed_note` in place of the model disclaimer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { get, send } from "../../shell/api";
import { Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { openAssistant } from "../../shell/assistant";
import { Card, TickerCell } from "./ui";
import { dayKey, monthDay, type Translate } from "./format";
import type { DailyCard } from "./types";

/** How often a card that is still being written asks whether it is done. */
const POLL_MS = 1500;

/**
 * "Today · 09:14" / "2 Sep" — the stamp under the badge.
 *
 * Before the 09:00 cutoff the page shows *yesterday's* card (see
 * `daily.action_day`), so the date is never decoration: it is how the reader
 * knows the briefing predates this morning. The clock is the browser's own,
 * which is the reader's zone — the one thing the Streamlit page has to ask the
 * browser for.
 */
export function stampOf(
  card: Pick<DailyCard, "day" | "action_day" | "generated">,
  t: Translate,
  now: Date = new Date(),
): string {
  const stamp = card.day ?? card.action_day;
  if (stamp !== dayKey(now)) return monthDay(stamp, t) ?? stamp;
  if (!card.generated) return t("home.daily_today_no_time");
  const at = new Date(card.generated * 1000);
  const clock = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  return t("home.daily_today", { time: clock });
}

/**
 * Whether this card should be written now: it does not stand, nothing is
 * already writing it, and this page has not asked for this day yet.
 */
export function wantsWriting(card: DailyCard, asked: string | null): boolean {
  return !card.fresh && !card.pending && asked !== card.action_day;
}

type State =
  | { kind: "loading" }
  | { kind: "failed" }
  /** The first write of the day is out and there is nothing current to show. */
  | { kind: "writing" }
  | { kind: "card"; card: DailyCard };

export function Daily() {
  const t = useT();
  const lang = useLang();
  const [state, setState] = useState<State>({ kind: "loading" });
  // Which action day this page has already asked the server to write. The
  // server has its own once-a-day guard; this one stops a re-render from
  // firing a second POST while the first is still out.
  const asked = useRef<string | null>(null);
  // A Regenerate is out. The poll stands down meanwhile: a GET answered before
  // the server has registered the new job would hand back the card the reader
  // just dismissed.
  const posting = useRef(false);
  const write = useCallback(
    (force: boolean) =>
      send<DailyCard>(
        "POST",
        `/daily?${new URLSearchParams({ lang, force: String(force) }).toString()}`,
      ),
    [lang],
  );

  // First paint: read what is stored, and ask for today's if it no longer
  // stands. The language is part of that check, not decoration — a reader who
  // switched the app to Spanish should not be left holding an English card.
  useEffect(() => {
    let live = true;
    setState({ kind: "loading" });
    (async () => {
      const stored = await get<DailyCard>("/daily", { lang });
      if (!live) return;
      if (!wantsWriting(stored, asked.current)) {
        setState({ kind: "card", card: stored });
        return;
      }
      asked.current = stored.action_day;
      // An older card is not what `daily_ui.reserve` shows while today's is
      // written either: it says who is working, so the wait reads as writing
      // rather than as a page that broke.
      setState({ kind: "writing" });
      try {
        const card = await write(false);
        if (live) setState({ kind: "card", card });
      } catch {
        // The write is the extra; the stored card is still worth showing.
        if (live) setState({ kind: "card", card: stored });
      }
    })().catch(() => {
      // Never takes the dashboard down with it — the slot simply empties, as
      // `daily_ui.render` clears it on any failure.
      if (live) setState({ kind: "failed" });
    });
    return () => {
      live = false;
    };
  }, [lang, write]);

  // The poll: only while a briefing is being written, and one request at a
  // time — the next is scheduled when the last one has answered.
  const pending = state.kind === "card" && state.card.pending;
  useEffect(() => {
    if (!pending) return;
    let live = true;
    const timer = window.setTimeout(() => {
      if (posting.current) {
        setState((current) => ({ ...current }));
        return;
      }
      get<DailyCard>("/daily", { lang }).then(
        (card) => live && setState({ kind: "card", card }),
        // A failed poll keeps the card it has; the next render polls again.
        () => live && setState((current) => ({ ...current })),
      );
    }, POLL_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [pending, lang, state]);

  const regenerate = useCallback(() => {
    setState((current) =>
      current.kind === "card"
        ? {
            kind: "card",
            card: {
              ...current.card,
              headline: null,
              bullets: [],
              focus: [],
              pending: true,
            },
          }
        : current,
    );
    posting.current = true;
    write(true)
      .finally(() => {
        posting.current = false;
      })
      .then(
        (card) => setState({ kind: "card", card }),
        // Refused (rate limit, a dropped connection): put back whatever the
        // server says is current rather than leave the wait line up for good.
        () =>
          get<DailyCard>("/daily", { lang }).then(
            (card) => setState({ kind: "card", card }),
            () => setState({ kind: "failed" }),
          ),
      );
  }, [write, lang]);

  if (state.kind === "loading") return <Skeleton rows={4} />;
  if (state.kind === "failed") return null;
  if (state.kind === "writing") {
    return (
      <Card className="hm-daily">
        <Waiting title="home.daily_wait_title" />
      </Card>
    );
  }

  const card = state.card;
  // Nothing to brief on (no positions and no watchlist), or nothing stored and
  // nothing being written: the section stays off the page.
  if (!card.headline && !card.pending) return null;
  const regenerating = !card.headline;
  const written = monthDay(card.day ?? card.action_day, t);

  let note: string | null;
  if (regenerating) note = null;
  else if (card.pending) note = t("home.daily_computed_wait");
  else if (card.source === "computed") note = t("home.daily_computed_note");
  else note = null; // the model disclaimer, in its two lengths, below

  return (
    <Card className="hm-daily">
      {regenerating ? (
        <Waiting title="home.daily_regen_title" />
      ) : (
        <>
          <div className="hm-daily-head">
            <span className="hm-daily-badge">{t("home.daily_badge")}</span>
            <span className="hm-daily-when">{stampOf(card, t)}</span>
          </div>
          <p className="hm-daily-headline">{card.headline}</p>
          {card.bullets.length > 0 ? (
            <ul className="hm-daily-list">
              {card.bullets.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          ) : null}
          {card.focus.length > 0 ? (
            <div className="hm-daily-chips">
              {card.focus.map((ticker) => (
                <TickerCell key={ticker} ticker={ticker} name={false} />
              ))}
            </div>
          ) : null}
          {card.pending ? (
            // The difference between a card that looks final and one the
            // reader knows will improve on its own.
            <p className="hm-daily-pending" role="status">
              <span className="hm-daily-dot" aria-hidden="true" />
              {t("home.daily_pending")}
            </p>
          ) : null}
          {!card.fresh && !card.pending ? (
            <p className="hm-note">
              {t("home.daily_stale", { date: written ?? card.day ?? "" })}
            </p>
          ) : null}
        </>
      )}
      <div className="hm-daily-actions">
        <button type="button" className="ag-btn" onClick={() => openAssistant()}>
          <span className="hm-wide">{t("home.daily_ask")}</span>
          <span className="hm-narrow">{t("home.daily_ask_short")}</span>
        </button>
        <button
          type="button"
          className="ag-btn"
          onClick={regenerate}
          // Disabled while its own rewrite is out: a second press would spend
          // a second unit of the allowance on a card already being written.
          disabled={regenerating}
        >
          {t("home.daily_refresh")}
        </button>
      </div>
      {note ? <p className="hm-note">{note}</p> : null}
      {!regenerating && !card.pending && card.source !== "computed" ? (
        // Three lines on a phone under a card whose whole point is to be
        // skimmed in one; the short form says the same two things.
        <p className="hm-note">
          <span className="hm-wide">{t("home.daily_disclaimer")}</span>
          <span className="hm-narrow">{t("home.daily_disclaimer_short")}</span>
        </p>
      ) : null}
    </Card>
  );
}

/** The card chrome with a line naming who is writing, over a text shimmer. */
function Waiting({ title }: { title: string }) {
  const t = useT();
  return (
    <>
      <div className="hm-daily-head">
        <span className="hm-daily-badge">{t("home.daily_badge")}</span>
      </div>
      <p className="hm-daily-wait" role="status">
        <b>{t(title)}</b> {t("home.daily_wait_body")}
      </p>
      <Skeleton rows={3} />
    </>
  );
}
