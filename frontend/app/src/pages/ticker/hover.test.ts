/**
 * The price chart's hover box and fills against the Plotly chart they replace.
 *
 * Every assertion here is a field Streamlit's unified box prints, in the form
 * it prints it: which fills are drawn at all, which close a buy's return is
 * measured to, what a sell leaves out, where the one colour in a row lands.
 * None of it would show up wrong in a screenshot of an empty hover.
 *
 * The catalog strings are the English ones verbatim, markup and all, because
 * the markup is what `markup()` has to read.
 */

import { describe, expect, it } from "vitest";

import { resultsLines } from "./events";
import { barsDayPct, compactMoney, currencySymbol } from "./format";
import {
  averageRow,
  eventRows,
  fillRows,
  hoverTitle,
  markup,
  placeFills,
  priceRows,
} from "./hover";
import type { Bars, Trade } from "./types";

const CATALOG: Record<string, string> = {
  "ticker.price": "Price",
  "ticker.hover_ohlc": "open {open} · high {high} · low {low}",
  "ticker.hover_buy":
    "<b>Buy</b>  {qty} sh @ <b>{price}</b> · {date}<br><span style='color:{color}'><b>{pct}%</b></span> to current {last}",
  "ticker.hover_sell": "<b>Sell</b>  {qty} sh @ <b>{price}</b> · {date}",
  "ticker.hover_avg_buy": "<br>avg buy {avg}",
  "ticker.hover_results": "<b>Results</b> · {date}",
  "ticker.hover_vs_est": " vs est {est}",
  "ticker.hover_surprise": "surprise",
  "ticker.hover_move": "move {pct}% across print",
};

const t = (key: string, values?: Record<string, string | number>): string => {
  const template = CATALOG[key] ?? key;
  return values
    ? template.replace(/\{(\w+)\}/g, (whole, name: string) =>
        name in values ? String(values[name]) : whole,
      )
    : template;
};

const DAYS = ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"];

const trade = (date: string, action: string, price = 100, quantity = 2): Trade => ({
  date,
  action,
  price,
  quantity,
});

describe("which fills the chart draws", () => {
  it("draws buys AND sells inside the range, each on its own bar", () => {
    const fills = placeFills(
      [trade("2025-01-03", "buy"), trade("2025-01-07", "sell")],
      DAYS,
    );
    expect(fills.map((fill) => [fill.index, fill.trade.action])).toEqual([
      [1, "buy"],
      [3, "sell"],
    ]);
  });

  it("leaves out a fill older than the range instead of piling it on bar 0", () => {
    // Streamlit's `_chart_ts(t.date) >= chart_start`.
    const fills = placeFills(
      [trade("2022-05-24", "buy"), trade("2025-01-02", "sell")],
      DAYS,
    );
    expect(fills).toHaveLength(1);
    expect(fills[0]?.trade.action).toBe("sell");
  });

  it("puts a weekend fill on the next session and keeps every lot of a day", () => {
    const fills = placeFills(
      [
        trade("2025-01-04", "buy"),
        trade("2025-01-04", "buy", 101),
        trade("2025-01-06", "sell"),
      ],
      DAYS,
    );
    // No aggregation: Streamlit draws one marker per ledger row.
    expect(fills.map((fill) => fill.index)).toEqual([2, 2, 2]);
  });

  it("matches intraday bars by their calendar day", () => {
    const bars = ["2025-01-07 09:30:00", "2025-01-07 09:35:00"];
    expect(placeFills([trade("2025-01-07", "sell")], bars)[0]?.index).toBe(0);
  });

  it("draws nothing that is not a trade", () => {
    expect(placeFills([trade("2025-01-03", "dividend")], DAYS)).toEqual([]);
  });
});

describe("the hover box", () => {
  it("is titled with the bar's own stamp, with the clock only intraday", () => {
    expect(hoverTitle("2025-01-03", false)).toBe("2025-01-03");
    expect(hoverTitle("2025-01-03T15:35:00", true)).toBe("2025-01-03 15:35");
  });

  it("prints the price row with its change on the previous close, coloured alone", () => {
    const [row] = priceRows({ close: 110, prev: 100, ohlc: null, swatch: "#a" }, t);
    expect(row?.text).toBe("Price 110.00 +10.00%");
    expect(row?.swatch).toBe("#a");
    expect(row?.parts[0]).toEqual({ text: "Price", tone: "dim" });
    expect(row?.parts.at(-1)).toEqual({ text: "+10.00%", bold: true, tone: "up" });
  });

  it("adds the open/high/low line on candles, muted", () => {
    const rows = priceRows(
      { close: 110, prev: 100, ohlc: { open: 101, high: 112, low: 99 }, swatch: "#a" },
      t,
    );
    expect(rows[1]?.text).toBe("open 101.00 · high 112.00 · low 99.00");
    expect(rows[1]?.parts[0]?.tone).toBe("dim");
  });

  it("gives each moving average a row, and none while it warms up", () => {
    expect(averageRow("SMA50", 201.333, "#b")?.text).toBe("SMA50 201.33");
    expect(averageRow("SMA200", null, "#c")).toBeNull();
  });

  it("measures a buy to the range's last close and colours only the return", () => {
    const rows = fillRows(
      trade("2025-01-03", "buy", 100, 2),
      { last: 90, avgCost: 95, swatch: "#fff" },
      t,
    );
    expect(rows.map((row) => row.text)).toEqual([
      "Buy 2.0000 sh @ 100.00 · 2025-01-03",
      "-10.00% to current 90.00",
      "avg buy 95.00",
    ]);
    // One swatch per trace entry, on its first row.
    expect(rows.map((row) => row.swatch)).toEqual(["#fff", undefined, undefined]);
    const coloured = rows[1]?.parts.filter((part) => part.tone);
    expect(coloured).toEqual([{ text: "-10.00%", bold: true, tone: "down" }]);
  });

  it("prices no return on a sell, as Streamlit's sell row does not", () => {
    const rows = fillRows(
      trade("2025-01-07", "sell", 130, 4),
      { last: 90, avgCost: 95, swatch: "#f00" },
      t,
    );
    expect(rows.map((row) => row.text)).toEqual([
      "Sell 4.0000 sh @ 130.00 · 2025-01-07",
    ]);
    expect(rows[0]?.parts.some((part) => part.tone)).toBe(false);
  });

  it("colours the surprise inside a results row, not the whole line", () => {
    const event = {
      date: "2025-01-06",
      eps_estimate: 1.5,
      reported_eps: 1.53,
      surprise_pct: 2.0,
      beat: true,
    };
    const rows = eventRows(
      resultsLines(event, [100, 102, 108, 107], 2, true, t),
      "#blue",
    );
    expect(rows.map((row) => row.text)).toEqual([
      "Results · 2025-01-06",
      "EPS 1.53 vs est 1.50 · +2.0% surprise",
      "move +4.9% across print",
    ]);
    expect(rows[1]?.parts.filter((part) => part.tone)).toEqual([
      { text: "+2.0%", bold: true, tone: "up" },
    ]);
    // The move is context, uncoloured, as Streamlit prints it.
    expect(rows[2]?.parts.some((part) => part.tone)).toBe(false);
  });

  it("reads the catalog dialect without handing any of it over as HTML", () => {
    expect(markup("<b>A</b> <i>b</i><br><br>c")).toEqual([
      [{ text: "A", bold: true }, { text: " " }, { text: "b" }],
      [{ text: "c" }],
    ]);
  });
});

describe("money as Streamlit prints it", () => {
  it("is compact_money: the mark first, one decimal on a suffix", () => {
    expect(compactMoney(1.49e12, "EUR")).toBe("€1.5T");
    expect(compactMoney(40.7e9, "EUR")).toBe("€40.7B");
    expect(compactMoney(811.9e9, "USD")).toBe("$811.9B");
    expect(compactMoney(-114.5e6, "USD")).toBe("-$114.5M");
    expect(compactMoney(950, "USD")).toBe("$950");
    expect(compactMoney(19.8e6, null)).toBe("19.8M");
    expect(compactMoney(null, "USD")).toBe("—");
  });

  it("writes the code where the currency has no mark of its own", () => {
    expect(currencySymbol("SEK")).toBe("SEK ");
    expect(currencySymbol("gbp")).toBe("£");
    expect(currencySymbol(null)).toBe("");
  });
});

describe("the day change without a quote", () => {
  const bars = (dates: string[], close: (number | null)[], interval = "1d"): Bars =>
    ({ dates, interval, series: { Close: close } }) as unknown as Bars;

  it("is the last two closes on a daily range", () => {
    expect(barsDayPct(bars(DAYS, [100, 100, 100, 110]))).toBeCloseTo(0.1, 9);
  });

  it("skips a trailing gap rather than reading it as a price", () => {
    expect(barsDayPct(bars(DAYS, [100, 100, 110, null]))).toBeCloseTo(0.1, 9);
  });

  it("is measured on the previous session's close on an intraday range", () => {
    const stamps = ["2025-01-06 15:55", "2025-01-07 09:30", "2025-01-07 09:35"];
    expect(barsDayPct(bars(stamps, [100, 104, 105], "5m"))).toBeCloseTo(0.05, 9);
  });

  it("is null with fewer than two closes", () => {
    expect(barsDayPct(bars(["2025-01-06"], [100]))).toBeNull();
    expect(barsDayPct(null)).toBeNull();
  });
});
