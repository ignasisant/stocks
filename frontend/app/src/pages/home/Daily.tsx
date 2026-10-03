/**
 * The assistant's one-a-day briefing, first thing on the page.
 *
 * The day's first visit writes the card, a provider that answers inside a
 * couple of seconds lands straight away, and a slower one leaves the computed
 * card up — the same triggers, stated without a model — with a pulsing line
 * saying the real one is still being written, until it swaps itself in. The section is never an empty slot and never a spinner.
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
 *   `POLL_MS` and stops the moment it does not.
 *
 * "Regenerate" is `POST /daily?force=true`: the old card goes the instant it
 * is pressed (the reader just dismissed it; leaving it up would have them
 * reading a briefing they asked to replace), the button stays disabled while
 * its own rewrite is out, and a second press cannot start a second paid
 * generation. "Ask the assistant" opens the drawer — it asks nothing on the
 * reader's behalf.
 *
 * `source: "computed"` is the fallback built from the triggers alone when no
 * model answered. It is not prose, and it is not presented as a briefing: that
 * card carries `home.daily_computed_note` in place of the model disclaimer.
 * It is stored too (tomorrow's card has to know what it said), and while it is
 * `upgradable` the page asks for a written one again on its next visit.
 *
 * The card is a summary: the headline names the day's few things and each
 * line says one. Each line with a trigger behind it opens its own analysis
 * (`POST /daily/analysis?key=`): the comparison the line invites, made — the
 * company against its peers, its sector and the index, the tax arithmetic of
 * a sale, which positions explain a month behind the index — as a verdict, a
 * few points and the computed tables they can be checked against. Written on
 * the first click of that line, stored with the card and read for free after
 * that, so collapsing and reopening never asks twice.
 *
 * The card reads in the same four sections every day, in the same order, so
 * the eye knows where to go: **Portfolio** (the book against the index today,
 * this week and this month, computed and drawn with the drawer's own chart),
 * **Today's alerts** (the reader's alerts that fired, always all of them),
 * **Worth a look** (the rest of the triggers) and **Your routines** (the
 * questions the reader asks every day, answered before they ask). A section
 * with nothing in it is left out; a card stored before sections had none of
 * them and keeps its plain list.
 */

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { LineChart } from "../../chat/chart";
import { get, send } from "../../shell/api";
import { Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { openAssistant, openThread } from "../../shell/assistant";
import { Card, TickerCell } from "./ui";
import { dayKey, money, monthDay, percent, type Translate } from "./format";
import type {
  DailyAnalysis,
  DailyBook,
  DailyCard,
  DailyItem,
  DailyRoutine,
  DailyTable,
} from "./types";
import { Badge } from "../../ui/Badge";

/** How often a card that is still being written asks whether it is done. */
const POLL_MS = 1500;

/**
 * "Today · 09:14" / "2 Sep" — the stamp under the badge.
 *
 * Before the 09:00 cutoff the page shows *yesterday's* card (see
 * `daily.action_day`), so the date is never decoration: it is how the reader
 * knows the briefing predates this morning. The clock is the browser's own,
 * which is the reader's zone.
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
  return (!card.fresh || card.upgradable) && !card.pending && asked !== card.action_day;
}

/** The card's lines as items — its own, or a pre-key card's bullets. */
export function linesOf(card: Pick<DailyCard, "items" | "bullets">): DailyItem[] {
  if (card.items?.length) return card.items;
  return card.bullets.map((line, i) => ({
    key: `line:${i}`,
    kind: "",
    line,
    tickers: [],
  }));
}

/** Whether a line has an analysis to open: a trigger behind it. */
export function opens(item: DailyItem): boolean {
  return item.kind !== "";
}

/** The lines split into the card's two trigger sections, alerts first. */
export function sectionsOf(lines: DailyItem[]): {
  alerts: DailyItem[];
  watch: DailyItem[];
} {
  return {
    alerts: lines.filter((item) => item.section === "alerts"),
    watch: lines.filter((item) => item.section !== "alerts"),
  };
}

/**
 * Whether the card is drawn in sections: it has something besides the plain
 * list. A card stored before sections (or one with only "worth a look" in it)
 * reads as it always did — one heading over one list is a label, not a map.
 */
export function sectioned(
  card: Pick<DailyCard, "book" | "routines">,
  alerts: number,
): boolean {
  return (
    Boolean(card.book?.rows.length) || Boolean(card.routines?.length) || alerts > 0
  );
}

/**
 * The colour a table cell earns: a signed figure is a move, and reads green or
 * red; an unsigned one (a weight, a volatility, a multiple) is a level, and
 * stays ink.
 */
export function tone(cell: string): "up" | "down" | null {
  if (cell.startsWith("+")) return "up";
  if (cell.startsWith("-") || cell.startsWith("\u2212")) return "down";
  return null;
}

/** Which card an analysis belongs to — a new card never shows the old one's. */
function stampKey(card: DailyCard | null): string {
  return card ? `${card.day}|${card.generated}|${card.lang}` : "";
}

/** One line's analysis: absent while closed. */
type Panel =
  { kind: "loading" } | { kind: "failed" } | { kind: "open"; body: DailyAnalysis };

function without(panels: Record<string, Panel>, key: string): Record<string, Panel> {
  const rest = { ...panels };
  delete rest[key];
  return rest;
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
      // An older card is not what shows while today's is written either: the
      // slot says who is working, so the wait reads as writing rather than as
      // a page that broke.
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

  // Each line's analysis: closed until asked, then kept per card and line so
  // a collapse and reopen reads it from memory rather than asking again. Lines
  // open independently — each one is its own fetch and its own call.
  const shown = state.kind === "card" ? state.card : null;
  const stamp = stampKey(shown);
  const [panels, setPanels] = useState<Record<string, Panel>>({});
  const analyses = useRef(new Map<string, DailyAnalysis>());
  useEffect(() => {
    setPanels({});
  }, [stamp]);
  const toggle = useCallback(
    (key: string) => {
      const now = panels[key];
      if (now && now.kind !== "failed") {
        setPanels((current) => without(current, key));
        return;
      }
      const cached = analyses.current.get(`${stamp}|${key}`);
      if (cached) {
        setPanels((current) => ({ ...current, [key]: { kind: "open", body: cached } }));
        return;
      }
      setPanels((current) => ({ ...current, [key]: { kind: "loading" } }));
      const asked = stamp;
      send<DailyAnalysis>(
        "POST",
        `/daily/analysis?${new URLSearchParams({ key }).toString()}`,
      ).then(
        (body) => {
          analyses.current.set(`${asked}|${key}`, body);
          // Only onto the wait it answers: a line collapsed meanwhile stays
          // shut, and a new card has already cleared the panels.
          setPanels((current) =>
            current[key]?.kind === "loading"
              ? { ...current, [key]: { kind: "open", body } }
              : current,
          );
        },
        () =>
          setPanels((current) =>
            current[key]?.kind === "loading"
              ? { ...current, [key]: { kind: "failed" } }
              : current,
          ),
      );
    },
    [panels, stamp],
  );
  const ids = useId();

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
              routines: [],
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
  const lines = linesOf(card);
  const { alerts, watch } = sectionsOf(lines);
  const routines = card.routines ?? [];
  const book = card.book?.rows.length ? card.book : null;
  const split = sectioned(card, alerts.length);
  // Not while a briefing is still being written: the stand-in on screen is
  // about to be replaced, and its lines with it.
  const canOpen = !regenerating && !card.pending;

  const list = (items: DailyItem[]) => (
    <ul className="hm-daily-list">
      {items.map((item) => {
        const panel = panels[item.key];
        const expanded = panel !== undefined && panel.kind !== "failed";
        const id = `${ids}-an-${lines.indexOf(item)}`;
        return (
          <li key={item.key}>
            {item.line}
            {canOpen && opens(item) ? (
              <>
                {" "}
                <button
                  type="button"
                  className="hm-daily-toggle"
                  aria-expanded={expanded}
                  aria-controls={panel ? id : undefined}
                  onClick={() => toggle(item.key)}
                >
                  {expanded ? t("home.daily_an_hide") : t("home.daily_an_show")}
                </button>
                <AnalysisPanel id={id} panel={panel} />
              </>
            ) : null}
          </li>
        );
      })}
    </ul>
  );

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
            <Badge tone="brand">{t("home.daily_badge")}</Badge>
            <span className="hm-daily-when">{stampOf(card, t)}</span>
          </div>
          <p className="hm-daily-headline">{card.headline}</p>
          {!split ? (
            lines.length > 0 ? (
              list(lines)
            ) : null
          ) : (
            <>
              {book ? (
                <Section title={t("home.daily_sec_book")}>
                  <BookSection book={book} />
                </Section>
              ) : null}
              {alerts.length > 0 ? (
                <Section title={t("home.daily_sec_alerts")}>{list(alerts)}</Section>
              ) : null}
              {watch.length > 0 ? (
                <Section title={t("home.daily_sec_watch")}>{list(watch)}</Section>
              ) : null}
              {routines.length > 0 ? (
                <Section title={t("home.daily_sec_routines")}>
                  <Routines routines={routines} pending={card.pending} />
                </Section>
              ) : null}
            </>
          )}
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
        <button
          type="button"
          className="ag-btn"
          // The card is filed as a conversation of its own: asking from it
          // asks there, with the card above the question. A card not filed
          // yet (still being written) opens the assistant as it stands.
          onClick={() => (card.thread ? openThread(card.thread) : openAssistant())}
        >
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

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="hm-daily-sec">
      <h3 className="hm-daily-sec-title">{title}</h3>
      {children}
    </section>
  );
}

const WINDOWS = {
  day: "home.daily_book_day",
  week: "home.daily_book_week",
  month: "home.daily_book_month",
} as const;

/** A move as the section prints it: signed, toned, "n/a" when unknown. */
function Move({ pct }: { pct: number | null }) {
  const t = useT();
  const lang = useLang();
  const text = pct === null ? null : percent(pct / 100, lang, { signed: true });
  if (pct === null || text === null)
    return <span className="hm-daily-na">{t("home.na")}</span>;
  return <span className={pct < 0 ? "hm-an-down" : "hm-an-up"}>{text}</span>;
}

/**
 * The book against the index: today, this week, this month, each figure the
 * server computed, and the month drawn beside them with the drawer's chart.
 */
export function BookSection({ book }: { book: DailyBook }) {
  const t = useT();
  const lang = useLang();
  return (
    <div className="hm-daily-book">
      <table className="hm-table hm-daily-book-table">
        <thead>
          <tr>
            <th scope="col" />
            <th scope="col" className="hm-num">
              {t("home.daily_book_you")}
            </th>
            <th scope="col" className="hm-num">
              {book.index}
            </th>
          </tr>
        </thead>
        <tbody>
          {book.rows.map((row) => {
            const amount = money(row.amount, book.currency, lang, { signed: true });
            return (
              <tr key={row.window}>
                <th scope="row">{t(WINDOWS[row.window])}</th>
                <td className="hm-num">
                  <Move pct={row.pct} />
                  {amount ? <span className="hm-daily-amount">{amount}</span> : null}
                </td>
                <td className="hm-num">
                  <Move pct={row.index_pct} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {book.chart.length > 0 ? (
        <LineChart
          series={book.chart}
          rebased
          label={t("home.daily_book_chart", { index: book.index })}
        />
      ) : null}
    </div>
  );
}

/**
 * The reader's routines, each question over its answer. An empty answer is
 * one still being fetched, said so while the card is being written; a card
 * that is done always carries one, if only "no data today".
 */
export function Routines({
  routines,
  pending,
}: {
  routines: DailyRoutine[];
  pending: boolean;
}) {
  const t = useT();
  return (
    <ul className="hm-daily-routines">
      {routines.map((routine) => (
        <li key={routine.id} className="hm-routine">
          <p className="hm-routine-ask">{routine.text}</p>
          {routine.answer ? (
            <p className="hm-routine-answer">{routine.answer}</p>
          ) : pending ? (
            <p className="hm-daily-pending" role="status">
              <span className="hm-daily-dot" aria-hidden="true" />
              {t("home.daily_routine_pending")}
            </p>
          ) : null}
          {routine.chart && routine.chart.series.length > 0 ? (
            <LineChart
              series={routine.chart.series}
              rebased={routine.chart.rebased}
              label={routine.text}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** One line's analysis, under it: the wait, the failure, or the verdict, the
 * points and the tables. */
function AnalysisPanel({ id, panel }: { id: string; panel: Panel | undefined }) {
  const t = useT();
  if (!panel) return null;
  if (panel.kind === "loading") {
    return (
      <div className="hm-an" id={id}>
        <p className="hm-daily-wait" role="status">
          {t("home.daily_an_loading")}
        </p>
        <Skeleton rows={3} />
      </div>
    );
  }
  if (panel.kind === "failed") {
    return (
      <p className="hm-note hm-an-failed" id={id} role="status">
        {t("home.daily_an_failed")}
      </p>
    );
  }
  const { body } = panel;
  return (
    <div className="hm-an" id={id}>
      {body.verdict ? (
        <p className="hm-an-verdict">
          <b>{t("home.daily_an_verdict")}</b> {body.verdict}
        </p>
      ) : null}
      {body.points.length > 0 ? (
        <div className="hm-an-points">
          {body.points.map((point, n) => (
            <section key={n} className="hm-an-point">
              <h4 className="hm-an-title">{point.title}</h4>
              <p>{point.text}</p>
            </section>
          ))}
        </div>
      ) : null}
      {body.tables.length > 0 ? (
        <div className="hm-an-tables">
          {body.tables.map((table, n) => (
            <AnalysisTable key={n} table={table} />
          ))}
        </div>
      ) : null}
      {body.source === "computed" ? (
        <p className="hm-note">{t("home.daily_an_computed")}</p>
      ) : null}
    </div>
  );
}

/** A computed table under an analysis. Every symbol is a ticker cell — logo
 * and link — with the company's name beside it. */
function AnalysisTable({ table }: { table: DailyTable }) {
  return (
    <figure className="hm-an-table">
      <figcaption className="hm-an-caption">{table.title}</figcaption>
      <div className="hm-an-scroll">
        <table className="hm-table">
          <thead>
            <tr>
              {table.columns.map((column, n) => (
                <th key={n} scope="col" className={n ? "hm-num" : undefined}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, n) => (
              <tr key={n} className={row.highlight ? "hm-an-hl" : undefined}>
                <td className="hm-an-name">
                  {row.ticker ? (
                    <span className="hm-an-who">
                      <TickerCell ticker={row.ticker} name={false} />
                      {row.label ? (
                        <span className="hm-an-label">{row.label}</span>
                      ) : null}
                    </span>
                  ) : (
                    row.label
                  )}
                </td>
                {row.cells.map((cell, m) => {
                  const sign = tone(cell);
                  return (
                    <td key={m} className={sign ? `hm-num hm-an-${sign}` : "hm-num"}>
                      {cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note ? <p className="hm-note">{table.note}</p> : null}
    </figure>
  );
}

/** The card chrome with a line naming who is writing, over a text shimmer. */
function Waiting({ title }: { title: string }) {
  const t = useT();
  return (
    <>
      <div className="hm-daily-head">
        <Badge tone="brand">{t("home.daily_badge")}</Badge>
      </div>
      <p className="hm-daily-wait" role="status">
        <b>{t(title)}</b> {t("home.daily_wait_body")}
      </p>
      <Skeleton rows={3} />
    </>
  );
}
