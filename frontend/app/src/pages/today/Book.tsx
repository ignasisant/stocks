/**
 * The book against the index, and a brief section's chart.
 *
 * The top of the page reads in five seconds: today, this week and this month,
 * each the server computed, the book's move as the figure and the index's
 * under it. A guest has no book, so the same three tiles carry the S&P 500
 * alone. The month is drawn with the drawer's chart in the Portfolio section.
 */

import { LineChart } from "../../chat/chart";
import { useLang, useT } from "../../shell/i18n";
import { Kpi, KpiGrid, chipFor, toneOf } from "../../ui/Kpi";
import { money, percent } from "../home/format";
import type { DailyBook, DailySection } from "../home/types";
import type { MarketCard } from "./types";

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

/** The month, the book against the index, as growth from 100. */
export function BookChart({ book }: { book: DailyBook }) {
  const t = useT();
  if (!book.chart.length) return null;
  return (
    <div className="td-chart">
      <LineChart
        series={book.chart}
        rebased
        label={t("home.daily_book_chart", { index: book.index })}
      />
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
