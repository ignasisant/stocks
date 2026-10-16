/**
 * The book against the index, and a brief section's chart.
 *
 * The top of the page reads in five seconds: today, this week and this month,
 * each the server computed, the book's move as the figure and the index's
 * under it. A guest has no book, so the same three tiles carry the S&P 500
 * alone. The month is drawn with the drawer's chart in the Portfolio section,
 * and can be redrawn over another window or against another index
 * (`GET /today/book`); the card's own month against the S&P 500 needs no call.
 */

import { useEffect, useState } from "react";
import { type Line, LineChart } from "../../chat/chart";
import { Cancelled, get, withMemo } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { Kpi, KpiGrid, chipFor, toneOf } from "../../ui/Kpi";
import { Segmented } from "../../ui/Segmented";
import { money, parseDay, percent } from "../home/format";
import type { DailyBook, DailySection } from "../home/types";
import type { BookCompare, MarketCard } from "./types";

const WINDOWS = {
  day: "home.daily_book_day",
  week: "home.daily_book_week",
  month: "home.daily_book_month",
} as const;

/** A move in percent as the tiles print it: signed, or "n/a" when unknown. */
function move(pct: number | null | undefined, lang: string, na: string): string {
  if (pct === null || pct === undefined) return na;
  return percent(pct / 100, lang, { signed: true }) ?? na;
}

/** The book's three windows, each beside the index's. */
export function BookKpis({ book }: { book: DailyBook }) {
  const t = useT();
  const lang = useLang();
  const na = t("home.na");
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
            money(row.amount, book.currency, lang, { signed: true }),
          )}
          note={`${book.index} ${move(row.index_pct, lang, na)}`}
        />
      ))}
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

type Drawn = {
  state: "ready" | "loading" | "failed";
  lines: Line[];
  since?: string | null;
};

/** A day as month and year, where a young book's chart begins. */
function monthYear(iso: string, lang: string): string {
  const day = parseDay(iso);
  return day ? day.toLocaleDateString(lang, { month: "short", year: "numeric" }) : iso;
}

/** The book against an index, as growth from 100, over a window the reader
 * picks. The card's month is drawn at once; any other pairing is asked for,
 * and the last chart stays up (dimmed) until it lands. */
export function BookChart({ book }: { book: DailyBook }) {
  const t = useT();
  const lang = useLang();
  const [range, setRange] = useState<Range>(CARD.range);
  const [index, setIndex] = useState<string>(CARD.index);
  const [drawn, setDrawn] = useState<Drawn>({ state: "ready", lines: book.chart });
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
      {empty ? (
        <p className="hm-note">{t("today.book_empty")}</p>
      ) : (
        <div className="td-chart-plot" aria-busy={drawn.state === "loading"}>
          <LineChart
            series={drawn.lines}
            rebased={!drawn.lines.some((line) => line.money)}
            label={t("today.book_chart", {
              index: name,
              window: t(`chat.chart_window_${range}`),
            })}
          />
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
