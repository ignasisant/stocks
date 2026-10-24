/**
 * The price row answers a holder in order: the price and why it moved, where
 * it sits, what it does to the holding — every figure of the holding priced
 * at the number on the price tile and printed in the reader's own money.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { calendarDay } from "../../shell/dates";
import { money, signedPercent } from "./format";
import { layout } from "./layout";
import { PriceSection } from "./Price";
import type { Bars, EarningsEvent, Quote, TickerPosition, Valuation } from "./types";

// The English strings the row is read through, slots filled as the real
// hook fills them; every other key renders as itself, as with no catalog.
vi.mock("../../shell/i18n", async (original) => ({
  ...(await original<typeof import("../../shell/i18n")>()),
  useT: () => (key: string, slots?: Record<string, string | number>) => {
    const catalog: Record<string, string> = {
      "ticker.position_value": "Position value",
      "ticker.unrealised_pl": "Unsold gain",
      "ticker.n_shares": "{n} shares",
      "ticker.hover_surprise": "surprise",
      "ticker.off_high": "{pct} off the high",
      "ticker.at_high": "at the high",
      "ticker.pe_vs_avg": "{pct} vs {rng} avg",
      "ticker.in_days": "in {n} days",
      "ticker.results_recent": "**Results {date}**  EPS {eps} vs {est} est.",
      "ticker.results_recent_bare": "**Results {date}**  EPS {eps}",
      "ticker.today_chip": "{amt} today",
      "ticker.avg_cost_note": "avg buy {avg}",
    };
    let value = catalog[key] ?? key;
    for (const [name, slot] of Object.entries(slots ?? {})) {
      value = value.replaceAll(`{${name}}`, String(slot));
    }
    return value;
  },
}));

// The chart's palette reads CSS tokens off the document; with none, each is "".
const dom = () => {
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
  vi.stubGlobal("document", { documentElement: {}, querySelector: () => null });
};
afterEach(() => vi.unstubAllGlobals());

function isoDay(offset: number): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  const month = String(day.getMonth() + 1).padStart(2, "0");
  return `${day.getFullYear()}-${month}-${String(day.getDate()).padStart(2, "0")}`;
}

/** `days` daily closes ending today, rising from `from` to `to`. */
function bars(days: number, from: number, to: number): Bars {
  const dates = Array.from({ length: days }, (_, i) => isoDay(i - days + 1));
  const close = dates.map((_, i) => from + ((to - from) * i) / (days - 1));
  return {
    ticker: "ORCL",
    range: "1y",
    interval: "1d",
    dates,
    series: { Close: close, SMA20: close, SMA50: close, SMA200: close, RSI14: close },
    dividends: dates.map(() => null),
    rsi_verdict: "neutral",
    rsi_tone: "gray",
    rangebreaks: [],
  };
}

// Pre-market after a miss: the quote is the honest price, the last bar is
// last night's close, and the row must not mix the two.
const quote: Quote = {
  ticker: "ORCL",
  price: 676.88,
  pct: -0.0296,
  session: "pre",
  as_of: isoDay(0),
  market_open: false,
  currency: "USD",
  price_base: 602.52,
  fx_rate: 0.8902,
  fx_as_of: isoDay(0),
  base: "EUR",
  high_52w: 760,
  low_52w: 550,
};

const position: TickerPosition = {
  ticker: "ORCL",
  held: true,
  shares: 8.8861,
  currency: "USD",
  cost_native: 5462.6,
  avg_cost_native: 614.78,
  base: "EUR",
  value: 5517.35,
  weight: 0.038,
  cost_base: 4782.09,
  trades: [],
  brokers: {},
  custody: [],
};

const events: EarningsEvent[] = [
  {
    date: isoDay(-1),
    eps_estimate: 5.46,
    reported_eps: 3.83,
    surprise_pct: -29.9,
    beat: false,
  },
  {
    date: isoDay(90),
    eps_estimate: 5.6,
    reported_eps: null,
    surprise_pct: null,
    beat: null,
  },
];

const valuation: Valuation = {
  ticker: "ORCL",
  source: "edgar",
  current: 31.4,
  current_verdict: "expensive",
  current_tone: "orange",
  dates: [],
  pe: [],
  windows: [
    {
      window: "1y",
      days: 365,
      mean: 30,
      median: 30,
      low: 20,
      high: 40,
      percentile: 55,
      premium: 0.05,
    },
    {
      window: "5y",
      days: 1825,
      mean: 28,
      median: 27,
      low: 15,
      high: 45,
      percentile: 85,
      premium: 0.12,
    },
  ],
};

const render = (
  held: TickerPosition | null,
  own: Quote | null = quote,
  history: Bars = bars(260, 560, 697.52),
) =>
  renderToStaticMarkup(
    <PriceSection
      query={{ state: "loaded", data: history, reload: () => {} }}
      quote={own}
      events={events}
      position={held}
      range="1y"
      offered={null}
      onRange={() => {}}
      candles={false}
      onCandles={() => {}}
      shape={layout("stock")}
      valuation={valuation}
    />,
  );

describe("the price row for a holder", () => {
  it("values the holding at the price on the tile, in the reader's money", () => {
    dom();
    const html = render(position);
    // 8.8861 shares at the pre-market 676.88, restated through the quote's
    // own rate: never the 697.52 close the last bar still carries.
    const valueBase = 8.8861 * 676.88 * (602.52 / 676.88);
    expect(html).toContain(`€${money(valueBase)}`);
    expect(html).not.toContain(money(8.8861 * 697.52));
    // The native figure stays as the note, and the day's move in euros rides
    // the tile as a chip, greyed because the session has not opened.
    expect(html).toContain(`${money(8.8861 * 676.88)} USD`);
    const today = valueBase - valueBase / (1 - 0.0296);
    expect(html).toContain(`-€${money(Math.abs(today))} today`);
    expect(html).toContain("ag-chip-flat");
    // The gain is value less the basis in euros at each trade's rate — the
    // Portfolio page's figure — with its percentage beside it.
    const gain = valueBase - 4782.09;
    expect(html).toContain(`+€${money(gain)}`);
    expect(html).toContain(signedPercent(gain / 4782.09, 2));
    expect(html).toContain("avg buy 614.78 USD");
    expect(html).toContain("3.8%");
    expect(html).toContain("8.8861 shares");
    // A holder reads euros on the value tile: no "≈ €" under the price.
    expect(html).not.toContain("≈ €");
  });

  it("frames the price in the year, the P/E in its history, and dates the next report", () => {
    dom();
    const html = render(position);
    expect(html).toContain("550 – 760");
    expect(html).toContain(`${signedPercent(676.88 / 760 - 1, 1)} off the high`);
    expect(html).toContain('class="tk-range"');
    expect(html).toContain("31.4");
    expect(html).toContain("+12% vs 5y avg");
    expect(html).toContain(calendarDay(isoDay(90)));
    expect(html).toContain("in 90 days");
    // RSI is a chart overlay now, not a tile.
    expect(html).not.toContain("RSI (14)");
  });

  it("says why the price moved when a report landed this week", () => {
    dom();
    const html = render(position);
    expect(html).toContain(`Results ${calendarDay(isoDay(-1))}`);
    expect(html).toContain("EPS 3.83 vs 5.46 est.");
    expect(html).toContain("-29.9%");
    expect(html).toContain("surprise");
  });

  it("falls back to the native gain when the base-currency basis is missing", () => {
    dom();
    const html = render({ ...position, cost_base: null });
    const gainNative = 8.8861 * 676.88 - 5462.6;
    expect(html).toContain(`+${money(gainNative)} USD`);
  });
});

describe("the price row for a reader who does not hold the name", () => {
  it("keeps the price in their money and the year's frame, and no holding", () => {
    dom();
    const html = render(null);
    expect(html).toContain("≈ €602.52");
    expect(html).toContain("550 – 760");
    expect(html).not.toContain("Position value");
    expect(html).not.toContain("Unsold gain");
  });

  it("reads the year off the bars when the quote has none", () => {
    dom();
    const html = render(
      null,
      { ...quote, high_52w: null, low_52w: null },
      bars(400, 100, 220),
    );
    // 400 days of bars, but the year is the last 365: the low is not the
    // first close.
    expect(html).not.toContain("100 – 220");
    expect(html).toContain("– 220");
  });

  it("prints a dash with no year anywhere", () => {
    dom();
    const html = render(
      null,
      { ...quote, high_52w: null, low_52w: null },
      bars(120, 100, 220),
    );
    expect(html).not.toContain("off the high");
    expect(html).not.toContain('class="tk-range"');
  });
});
