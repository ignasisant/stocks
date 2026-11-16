/**
 * The book against the index, and a brief section's chart.
 *
 * The top of the page reads in five seconds: today, this week and this month,
 * each the server computed, the book's move as the figure and the index's
 * under it. A guest has no book, so the same three tiles carry the S&P 500
 * alone. The chart in the Portfolio section opens on the whole book against
 * the S&P 500, on the same money, and can be redrawn over a shorter window or
 * against another index (`GET /today/book`); only the card's own month against
 * the S&P 500 needs no call.
 */

import { useEffect, useState } from "react";
import { type Line, LineChart } from "../../chat/chart";
import { Cancelled, get, withMemo } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { Kpi, KpiGrid, chipFor, toneOf } from "../../ui/Kpi";
import { Segmented } from "../../ui/Segmented";
import { parseDay } from "../home/format";
import type { DailyBook, DailySection } from "../home/types";
import type { Since } from "./card";
import type { BookCompare, MarketCard } from "./types";
import { money, percent } from "../../shell/format";

const WINDOWS = {
  day: "home.daily_book_day",
  week: "home.daily_book_week",
  month: "home.daily_book_month",
} as const;

/** A move in percent as the tiles print it: signed, or "n/a" when unknown. */
function move(pct: number | null | undefined, lang: string, na: string): string {
  if (pct === null || pct === undefined) return na;
  return percent(pct / 100, { lang, digits: 2, signed: "always" }) ?? na;
}

/** The book's three windows, each beside the index's. */
export function BookKpis({ book, since }: { book: DailyBook; since?: Since | null }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  const cash = (value: number, currency: string) =>
    money(value, { currency, lang, signed: "always", digits: 0 }) ?? na;
  return (
    <KpiGrid>
      {book.rows.map((row) => (
        <Kpi
          key={row.window}
          label={t(WINDOWS[row.window])}
          value={move(row.pct, lang, na)}
          valueTone={toneOf(row.pct)}
          chip={chipFor(
            row.amount,
            money(row.amount, { currency: book.currency, lang, signed: "always" }),
          )}
          note={`${book.index} ${move(row.index_pct, lang, na)}`}
        />
      ))}
      {since ? (
        <Kpi
          label={t("today.since_label", { date: monthYear(since.date, lang) })}
          value={cash(since.gain, since.currency)}
          valueTone={toneOf(since.gain)}
          chip={chipFor(
            since.gap,
            t("today.since_vs", {
              amount: cash(since.gap, since.currency),
              index: since.index,
            }),
          )}
          note={t("today.since_note", {
            index: since.index,
            amount: cash(since.indexGain, since.currency),
          })}
        />
      ) : null}
    </KpiGrid>
  );
}

/** The index's three windows, for a reader with no book: the guest. */
export function IndexKpis({ index }: { index: NonNullable<MarketCard["index"]> }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
  const windows = [
    ["day", index.day],
    ["week", index.week],
    ["month", index.month],
  ] as const;
  return (
    <KpiGrid>
      {windows.map(([window, pct]) => (
        <Kpi
          key={window}
          label={t(WINDOWS[window])}
          value={move(pct, lang, na)}
          valueTone={toneOf(pct)}
          note={index.name}
        />
      ))}
    </KpiGrid>
  );
}

export const RANGES = ["1m", "3m", "6m", "ytd", "1y", "2y", "5y", "max"] as const;
export type Range = (typeof RANGES)[number];

/** What the book can be laid against (`daily_book.INDEXES`), by symbol. */
export const INDEXES = [
  { id: "SPY", name: "S&P 500" },
  { id: "QQQ", name: "Nasdaq 100" },
  { id: "URTH", name: "MSCI World" },
  { id: "EEM", name: "MSCI EM" },
  { id: "^STOXX50E", name: "Euro Stoxx 50" },
  { id: "^IBEX", name: "IBEX 35" },
] as const;

/** The pairing the card already carries: the month against the S&P 500. */
const CARD = { range: "1m", index: "SPY" } as const;

/** What the chart opens on: the whole book, from its first day. A window that
 * opens later forgives whatever the picks lost before it (CLAUDE.md), so the
 * shorter ones sit beside it, never in its place. */
const OPENS = { range: "max", index: "SPY" } as const;

type Drawn = {
  state: "ready" | "loading" | "failed";
  lines: Line[];
  since?: string | null;
};

/** The chart's lines plus the money put in as a line of its own: the book's
 * `injected` series, drawn beside the book and the index. Only for lines that
 * are amounts; an older card's growth-from-100 lines have no money to show. */
function withPutIn(lines: Line[], label: string): Line[] {
  const own = lines.find((line) => line.money && line.injected?.length);
  if (!own?.injected) return lines;
  return [
    ...lines,
    {
      symbol: "@PUT",
      currency: own.currency,
      dates: own.dates,
      values: own.injected,
      money: true,
      label,
    },
  ];
}

/** A day as month and year, where a young book's chart begins. */
function monthYear(iso: string, lang: string): string {
  const day = parseDay(iso);
  return day ? day.toLocaleDateString(lang, { month: "short", year: "numeric" }) : iso;
}

/** The book against an index over a window the reader picks, opening on the
 * whole book. The card's month is drawn without a call; any other pairing is
 * asked for, and the last chart stays up (dimmed) until it lands. */
export function BookChart({ book }: { book: DailyBook }) {
  const t = useT();
  const lang = useLang();
  const [range, setRange] = useState<Range>(OPENS.range);
  const [index, setIndex] = useState<string>(OPENS.index);
  // Nothing drawn until the whole book lands: the card's month on screen
  // under "All" would be read as the book's whole life.
  const [drawn, setDrawn] = useState<Drawn>({ state: "loading", lines: [] });
  // A card stored before the index was bought from the book's first day is
  // asked for again.
  const isCard =
    range === CARD.range &&
    index === CARD.index &&
    book.chart.some((line) => line.opens);

  useEffect(() => {
    if (isCard) {
      setDrawn({ state: "ready", lines: book.chart });
      return;
    }
    const scope = new AbortController();
    setDrawn((was) => ({ ...was, state: "loading" }));
    withMemo(
      () => get<BookCompare>("/today/book", { range, index, lang }),
      scope.signal,
    ).then(
      (answer) => {
        if (scope.signal.aborted) return;
        setDrawn({ state: "ready", lines: answer.chart, since: answer.since });
      },
      (error) => {
        if (scope.signal.aborted || error instanceof Cancelled) return;
        setDrawn((was) => ({ ...was, state: "failed" }));
      },
    );
    return () => scope.abort();
  }, [isCard, range, index, lang, book.chart]);

  if (!book.chart.length) return null;
  const plotted = withPutIn(drawn.lines, t("today.put_line"));
  const name = INDEXES.find((item) => item.id === index)?.name ?? index;
  const empty = drawn.state === "ready" && !drawn.lines.length;
  return (
    <div className="td-chart">
      <div className="td-chart-tools">
        <Segmented
          items={RANGES.map((id) => ({ id, label: t(`today.book_range_${id}`) }))}
          value={range}
          onPick={setRange}
          label={t("today.book_range")}
        />
        <select
          className="td-chart-index"
          value={index}
          aria-label={t("today.book_index")}
          onChange={(event) => setIndex(event.target.value)}
        >
          {INDEXES.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      {drawn.state === "ready" ? (
        <SameMoney lines={drawn.lines} index={name} currency={book.currency} />
      ) : null}
      {empty ? (
        <p className="hm-note">{t("today.book_empty")}</p>
      ) : (
        <div className="td-chart-plot" aria-busy={drawn.state === "loading"}>
          {drawn.lines.length ? (
            <LineChart
              series={plotted}
              rebased={!drawn.lines.some((line) => line.money)}
              label={t("today.book_chart", {
                index: name,
                window: t(`chat.chart_window_${range}`),
              })}
            />
          ) : drawn.state === "loading" ? (
            <div
              className="td-chart-wait"
              aria-label={t("common.loading")}
              role="img"
            />
          ) : null}
        </div>
      )}
      {drawn.since && !empty ? (
        <p className="hm-note">
          {t("today.book_since", { date: monthYear(drawn.since, lang) })}
        </p>
      ) : null}
      {drawn.state === "failed" ? (
        <p className="hm-note" role="status">
          {t("today.book_failed")}
        </p>
      ) : null}
    </div>
  );
}

/** The chart's last day in money: the book, the same deposits in the index,
 * and the gap between them. Only when both lines are amounts — an older
 * card's growth-from-100 lines say nothing about money. */
export function SameMoney({
  lines,
  index,
  currency,
}: {
  lines: Line[];
  index: string;
  currency: string;
}) {
  const t = useT();
  const lang = useLang();
  const own = lines.find((line) => line.money && line.injected);
  const other = lines.find((line) => line.money && !line.injected);
  const mine = own?.values.at(-1);
  const theirs = other?.values.at(-1);
  if (!own || mine === undefined || theirs === undefined) return null;
  const put = own.injected?.at(-1);
  const gap = mine - theirs;
  const first = parseDay(own.dates[0] ?? "");
  const since = first
    ? first.toLocaleDateString(lang, {
        day: "numeric",
        month: "short",
        year: "2-digit",
      })
    : null;
  const cash = (value: number, signed = false) =>
    money(value, {
      currency,
      lang,
      digits: 0,
      signed: signed ? "always" : undefined,
    }) ?? t("home.na");
  return (
    <dl className="td-same">
      <div>
        <dt>{t("today.same_book")}</dt>
        <dd>{cash(mine)}</dd>
        {since ? <small>{t("today.same_since", { date: since })}</small> : null}
      </div>
      <div>
        <dt>{t("today.same_index", { index })}</dt>
        <dd>{cash(theirs)}</dd>
        {put !== undefined ? (
          <small>{t("today.same_put", { amount: cash(put) })}</small>
        ) : null}
      </div>
      <div className={gap >= 0 ? "td-same-up" : "td-same-down"}>
        <dt>{t("today.same_gap")}</dt>
        <dd>{cash(gap, true)}</dd>
        <small>
          {t(gap >= 0 ? "today.same_ahead" : "today.same_behind", { index })}
        </small>
      </div>
    </dl>
  );
}

/** A brief section's chart, when its figures drew one. */
export function SectionChart({ section }: { section: DailySection }) {
  if (!section.chart?.series.length) return null;
  return (
    <div className="td-chart">
      <LineChart
        series={section.chart.series}
        rebased={section.chart.rebased}
        label={section.title}
      />
    </div>
  );
}
