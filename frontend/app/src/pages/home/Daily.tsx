/**
 * The assistant's one-a-day briefing on Home: the teaser of the Today page.
 *
 * Home is where the reader lands, not where they read: the card says the
 * day's headline and its first few lines — the fired alerts first — and
 * points at Today (`pages/today/`) for the rest: the full card with each
 * line's analysis, news, filings, insiders, the comparisons and the market.
 *
 * The day's first visit writes the card, a provider that answers inside a
 * couple of seconds lands straight away, and a slower one leaves the computed
 * card up — the same triggers, stated without a model — with a status line
 * saying the real one is still being written, until it swaps itself in. The
 * section is never an empty slot and never a spinner.
 *
 * Three requests carry that over HTTP, and they are split on purpose:
 *
 * - `GET /daily` reads what is there. It never writes, because a GET that
 *   could spend the account's free allowance is a GET a prefetch could empty.
 * - `POST /daily` asks for today's card when the stored one no longer stands
 *   (a new day, a new session, a language switch). The server spends at most
 *   one generation per account per key, and shares the job with Today's
 *   `POST /today`, so the teaser and the page never start two.
 * - While the answer says `pending`, the card polls `GET /daily` every
 *   `POLL_MS` and stops the moment it does not.
 *
 * Regenerate is `POST /daily?force=true`: the old card goes the instant it
 * is pressed, the button stays disabled while its own rewrite is out, and a
 * second press cannot start a second paid generation. Ask opens the drawer —
 * it asks nothing on the reader's behalf. Editing the brief lives on Today.
 *
 * `source: "computed"` is the fallback built from the triggers alone when no
 * model answered. It is not presented as a briefing: that card carries
 * `home.daily_computed_note` in place of the model disclaimer.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { get, send } from "../../shell/api";
import { Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { openAssistant, openThread } from "../../shell/assistant";
import { Link } from "../../shell/router";
import { Glyph } from "../../chat/icons";
import { Badge } from "../../ui/Badge";
import { Status } from "../../ui/Status";
import {
  POLL_MS,
  badgeKey,
  noteKey,
  stampOf,
  teaserOf,
  wantsWriting,
} from "../today/card";
import { Card, TickerCell } from "./ui";
import { Go } from "./Go";
import { monthDay } from "./format";
import type { DailyCard, DailyItem } from "./types";

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
      setState({ kind: "writing" });
      try {
        const card = await write(false);
        if (live) setState({ kind: "card", card });
      } catch {
        // The write is the extra; the stored card is still worth showing.
        if (live) setState({ kind: "card", card: stored });
      }
    })().catch(() => {
      // Never takes the dashboard down with it — on any failure the slot
      // simply empties.
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
              items: [],
              focus: [],
              book: null,
              sections: [],
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
  const note = regenerating ? null : noteKey(card);
  const { lines, more } = teaserOf(card);

  const tools = (
    <div className="hm-daily-tools">
      <IconButton
        icon="refresh"
        label={t("home.daily_refresh")}
        // Disabled while its own rewrite is out: a second press would spend a
        // second unit of the allowance on a card already being written.
        disabled={regenerating}
        onClick={regenerate}
      />
      <IconButton
        icon="forum"
        label={t("home.daily_ask")}
        // The card is filed as a conversation of its own: asking from it asks
        // there, with the card above the question. A card not filed yet
        // (still being written) opens the assistant as it stands.
        onClick={() => (card.thread ? openThread(card.thread) : openAssistant())}
      />
    </div>
  );

  if (regenerating) {
    return (
      <Card className="hm-daily">
        <Waiting title="home.daily_regen_title" tools={tools} />
      </Card>
    );
  }

  return (
    <Card className="hm-daily">
      <div className="hm-daily-head">
        <Badge tone={badgeKey(card) === "home.daily_badge" ? "brand" : "neutral"}>
          {t(badgeKey(card))}
        </Badge>
        <span className="hm-daily-when">{stampOf(card, t)}</span>
        {tools}
      </div>
      {/* Said before the headline: a fallback read as the AI's answer first
          is already misread by the time the note comes. */}
      {note ? (
        <p className="hm-note" role="status">
          {t(note)}
        </p>
      ) : null}
      <p className="hm-daily-headline">{card.headline}</p>
      {lines.length ? <Lines items={lines} /> : null}
      {card.pending ? <Status label={t("home.daily_pending")} /> : null}
      <div className="hm-daily-open">
        <Link page="today" className="ag-btn">
          {t("home.daily_open")}
        </Link>
        {more ? (
          <span className="hm-daily-when">{t("home.daily_more", { n: more })}</span>
        ) : null}
      </div>
      {!card.fresh && !card.pending ? (
        <p className="hm-note">
          {t("home.daily_stale", {
            date: monthDay(card.day ?? card.action_day, t) ?? card.day ?? "",
          })}
        </p>
      ) : null}
      {!note && !card.pending ? (
        <p className="hm-note">{t("home.daily_disclaimer")}</p>
      ) : null}
    </Card>
  );
}

/** The teaser's lines: the text in full, its tickers and the page that acts
 * on it at its end. */
function Lines({ items }: { items: DailyItem[] }) {
  return (
    <ul className="hm-daily-list">
      {items.map((item) => (
        <li key={item.key}>
          {item.line}
          {item.tickers.length > 0 ? (
            <span className="hm-daily-tks">
              {item.tickers.map((ticker) => (
                <TickerCell key={ticker} ticker={ticker} name={false} />
              ))}
            </span>
          ) : null}
          {item.go ? (
            <>
              {" "}
              <Go go={item.go} className="hm-daily-go" />
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** One of the header's controls: an icon, its name as label and tooltip. */
function IconButton({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="hm-icon-btn"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      <Glyph name={icon} size={17} />
    </button>
  );
}

/** The card chrome with a line naming who is writing, over a text shimmer. */
function Waiting({ title, tools }: { title: string; tools?: ReactNode }) {
  const t = useT();
  return (
    <>
      <div className="hm-daily-head">
        <Badge tone="brand">{t("home.daily_badge")}</Badge>
        {tools}
      </div>
      <Status label={t(title)} />
      <Skeleton rows={3} />
    </>
  );
}
