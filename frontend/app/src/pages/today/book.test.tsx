/**
 * What Today's book tiles, book chart and brief sections draw from a card.
 *
 * The book is computed: each window's own move as the figure and the index's
 * under it, a move the index could not report printed as "n/a" rather than a
 * zero, and the chart opening on the whole book (from its first day), with
 * the last day in money under it. A brief section draws the chart its
 * figures came with, and nothing when they came with none. A list of wire
 * rows under All shows its first few and counts the rest.
 *
 * Rendered to static markup with no catalog: a key prints as itself. The
 * chart reads computed styles off the document, which a node test does not
 * have — stubbed as `chart.test.tsx` does, so the palette falls back.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BookChart,
  BookKpis,
  INDEXES,
  IndexKpis,
  RANGES,
  SameMoney,
  SectionChart,
} from "./Book";
import type { Line } from "../../chat/chart";
import { Rows } from "./Section";
import type { DailyBook, DailySection } from "../home/types";
import type { TodayRow } from "./types";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
  vi.stubGlobal("document", { documentElement: {} });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
});
afterEach(() => vi.unstubAllGlobals());

const line = {
  symbol: "@BOOK",
  currency: "EUR",
  dates: ["2026-09-01", "2026-09-29"],
  values: [100, 101.2],
  label: "Your portfolio",
  index: true,
};

const book: DailyBook = {
  index: "S&P 500",
  currency: "EUR",
  rows: [
    { window: "day", pct: 0.8, amount: 120, index_pct: 0.3 },
    { window: "month", pct: -2, amount: -300, index_pct: null },
  ],
  chart: [line],
};

describe("the book tiles", () => {
  const draw = () => renderToStaticMarkup(<BookKpis book={book} />);

  it("sets each window's move beside the index's", () => {
    const html = draw();
    expect(html).toContain("home.daily_book_day");
    expect(html).toContain("home.daily_book_month");
    expect(html).toContain("S&amp;P 500");
    expect(html).toContain("+0.80%");
    expect(html).toContain("+0.30%");
    expect(html).toContain("-2.00%");
  });

  it("prints a move the index could not report as n/a, not a zero", () => {
    const html = draw();
    expect(html).toContain("home.na");
    expect(html).not.toContain("+0.00%");
  });

  it("tones a move by its sign", () => {
    const html = draw();
    expect(html).toMatch(/ag-tone-up">(<span class="ag-count">)?\+0\.80%/);
    expect(html).toMatch(/ag-tone-down">(<span class="ag-count">)?-2\.00%/);
  });
});

describe("the index tiles, for a guest", () => {
  it("prints the index alone, an unknown window as n/a", () => {
    const html = renderToStaticMarkup(
      <IndexKpis index={{ name: "S&P 500", day: 0.4, week: null, month: -1.5 }} />,
    );
    expect(html).toContain("+0.40%");
    expect(html).toContain("-1.50%");
    expect(html).toContain("home.na");
    expect(html).toContain("S&amp;P 500");
  });
});

describe("the book chart", () => {
  it("opens on the whole book: holds the room until it lands, never the month", () => {
    const html = renderToStaticMarkup(<BookChart book={book} />);
    expect(html).toContain("td-chart-wait");
    expect(html).not.toContain("ag-a2ui-chart");
  });

  it("draws no chart when there is none", () => {
    expect(renderToStaticMarkup(<BookChart book={{ ...book, chart: [] }} />)).toBe("");
  });

  it("offers the windows and the indexes, from the first day against the S&P on", () => {
    const html = renderToStaticMarkup(<BookChart book={book} />);
    for (const range of RANGES) expect(html).toContain(`today.book_range_${range}`);
    for (const index of INDEXES) expect(html).toContain(`value="${index.id}"`);
    expect(html).toMatch(/aria-pressed="true"[^>]*>today\.book_range_max</);
    expect(html).toMatch(/<option value="SPY" selected="">/);
  });
});

describe("the chart's last day in money", () => {
  const own: Line = {
    ...line,
    dates: ["2026-01-05", "2026-09-29"],
    values: [1000, 1500],
    money: true,
    injected: [1000, 1200],
  };
  const spy: Line = {
    symbol: "SPY",
    currency: "EUR",
    dates: own.dates,
    values: [1000, 1400],
    label: "S&P 500",
    money: true,
  };

  it("sets the book, the index on the same deposits and the gap", () => {
    const html = renderToStaticMarkup(
      <SameMoney lines={[own, spy]} index="S&P 500" currency="EUR" />,
    );
    expect(html).toContain("today.same_book");
    expect(html).toContain("today.same_index");
    expect(html).toContain("today.same_put");
    expect(html).toMatch(/td-same-up/);
    expect(html).toContain("today.same_ahead");
    expect(html).toMatch(/\+€100\b/);
  });

  it("says the book is behind when the index is ahead", () => {
    const html = renderToStaticMarkup(
      <SameMoney
        lines={[own, { ...spy, values: [1000, 1700] }]}
        index="S&P 500"
        currency="EUR"
      />,
    );
    expect(html).toMatch(/td-same-down/);
    expect(html).toContain("today.same_behind");
  });

  it("draws nothing for growth-from-100 lines, which say nothing about money", () => {
    expect(
      renderToStaticMarkup(<SameMoney lines={[line]} index="S&P 500" currency="EUR" />),
    ).toBe("");
  });
});

describe("a brief section's chart", () => {
  const section = (over: Partial<DailySection> = {}): DailySection => ({
    title: "NVDA",
    asks: [1],
    lines: [],
    chart: null,
    ...over,
  });

  it("draws nothing when the figures came without one", () => {
    expect(renderToStaticMarkup(<SectionChart section={section()} />)).toBe("");
    const empty = section({ chart: { window: "1m", rebased: false, series: [] } });
    expect(renderToStaticMarkup(<SectionChart section={empty} />)).toBe("");
  });

  it("draws the series it came with", () => {
    const html = renderToStaticMarkup(
      <SectionChart
        section={section({
          chart: {
            window: "1m",
            rebased: false,
            series: [{ ...line, symbol: "NVDA" }],
          },
        })}
      />,
    );
    expect(html).toContain("ag-a2ui-chart");
  });
});

describe("wire rows", () => {
  const row = (n: number): TodayRow => ({
    key: `n${n}`,
    kind: "news",
    line: `Headline ${n}`,
    tickers: ["MSFT"],
    source: "yahoo",
    url: "https://example.com/a",
    date: "2026-10-13",
    data: {},
  });
  const rows = [1, 2, 3, 4, 5, 6, 7].map(row);
  const more = () => {};

  it("shows the first few under All and counts the rest", () => {
    const html = renderToStaticMarkup(<Rows rows={rows} limit={4} onMore={more} />);
    expect(html).toContain("Headline 4");
    expect(html).not.toContain("Headline 5");
    expect(html).toContain("today.more_rows");
  });

  it("never hides a single row behind a button", () => {
    const html = renderToStaticMarkup(
      <Rows rows={rows.slice(0, 5)} limit={4} onMore={more} />,
    );
    expect(html).toContain("Headline 5");
    expect(html).not.toContain("today.more_rows");
  });

  it("makes the headline the link to its article", () => {
    const html = renderToStaticMarkup(<Rows rows={[row(1)]} />);
    expect(html).toMatch(
      /<a class="td-headlink" href="https:\/\/example.com\/a"[^>]*>Headline 1<\/a>/,
    );
  });
});
