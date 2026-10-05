/**
 * What the Portfolio charts must keep saying.
 *
 * Things a hand-drawn chart has to do on purpose, each easy to lose in a
 * refactor without any screen going blank: a value axis with round labels, the
 * history tooltip's P/L as an amount and a percentage, the value line coloured
 * by the sign of that P/L, and the correlation grid's −1…+1 colour scale.
 *
 * `token()` reads computed styles off the document, which a node test does not
 * have — stubbed to "no token set", which is all a markup assertion needs.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { TaxPeriod } from "./api";
import {
  AxisLabel,
  BookAndRates,
  BookHistory,
  Donut,
  Heatmap,
  PeriodBars,
  ReturnLines,
  bookRatesTip,
  bookSpanTip,
  bookTip,
  correlationBand,
  correlationStats,
  foldSlices,
  lineMoney,
  dateTicks,
  niceTicks,
  plotHeightFor,
  sliceTip,
  type SliceDetail,
} from "./charts";

beforeAll(() => {
  vi.stubGlobal("document", { documentElement: {} });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
});

describe("niceTicks", () => {
  it("lands on round steps inside the span", () => {
    expect(niceTicks(11_843, 12_261)).toEqual([11_900, 12_000, 12_100, 12_200]);
    expect(niceTicks(-0.12, 0.31)).toEqual([-0.1, 0, 0.1, 0.2, 0.3]);
  });

  it("answers a flat series with the one value it has", () => {
    expect(niceTicks(5, 5)).toEqual([5]);
  });
});

describe("BookHistory", () => {
  const points = Array.from({ length: 10 }, (_, i) => ({
    date: `2026-01-${String(i + 1).padStart(2, "0")}`,
    injected: 1000,
    value: 1000 + i * 10,
    pnl_pct: (i * 10) / 1000,
  }));

  const labels = {
    injected: "Injected",
    value: "Value",
    profit: "Profit",
    loss: "Loss",
    pnl: "P/L",
  };
  const money = (v: number, signed?: boolean) => `${signed && v > 0 ? "+" : ""}€${v}`;
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

  it("carries the P/L amount and percentage in its tooltip", () => {
    const rows = bookTip(points[9]!, labels, money, pct);
    expect(rows.map((row) => `${row.label} ${row.value}`)).toEqual([
      "Profit €1090",
      "Injected €1000",
      "P/L +€90 (9.0%)",
    ]);
    // Under water, the value is named as the loss series is.
    expect(bookTip({ value: 900, injected: 1000 }, labels, money, pct)[0]?.label).toBe(
      "Loss",
    );
  });

  it("splits a span's change into money put in and what the market did", () => {
    const rows = bookSpanTip(
      { value: 1000, injected: 1000 },
      { value: 1600, injected: 1500 },
      labels,
      money,
    );
    expect(rows.map((row) => `${row.label} ${row.value}`)).toEqual([
      "Value +€600",
      "Injected +€500",
      "P/L +€100",
    ]);
  });

  it("draws the value line in two colours across a crossover", () => {
    const crossing = [1000, 1010, 990, 980].map((value, i) => ({
      date: `2026-02-0${i + 1}`,
      injected: 1000,
      value,
    }));
    const out = renderToStaticMarkup(
      <BookHistory
        points={crossing}
        labels={{ ...labels, reset: "Reset" }}
        money={money}
        percent={pct}
        formatDate={(iso) => iso}
      />,
    );
    // Injected (dashed) plus one value run per sign.
    expect(out.match(/<polyline/g)).toHaveLength(3);
    // Both legend entries, since this window draws both colours.
    expect(out).toContain("Profit");
    expect(out).toContain("Loss");
  });

  it("renders its axis and legend", () => {
    const out = renderToStaticMarkup(
      <BookHistory
        points={points}
        labels={{
          injected: "Injected",
          value: "Value",
          profit: "Profit",
          loss: "Loss",
          pnl: "P/L",
          reset: "Reset",
        }}
        money={(v, signed) => `${signed && v > 0 ? "+" : ""}€${v}`}
        percent={(v) => `${(v * 100).toFixed(1)}%`}
        formatDate={(iso) => iso}
      />,
    );
    // A value axis: at least one money label in the gutter.
    expect(out).toMatch(/text-anchor="end"[^>]*>€1/);
    // Not zoomed yet, so no reset button.
    expect(out).not.toContain("Reset");
  });
});

describe("BookAndRates", () => {
  const points = [1000, 1100, 950, 1200].map((value, i) => ({
    date: `2026-0${i + 1}-28`,
    value,
    invested: 1000,
  }));
  const render = (rate: (number | null)[]) =>
    renderToStaticMarkup(
      <BookAndRates
        points={points}
        series={[
          { label: "Your money", points: rate },
          { label: "Your picks", points: [0, 0.1, -0.05, 0.2], dashed: true },
        ]}
        labels={{
          invested: "Injected",
          value: "Value",
          profit: "Profit",
          loss: "Loss",
          gain: "Gain",
        }}
        money={(v) => `€${v}`}
        format={(v) => `${(v * 100).toFixed(0)}%`}
        formatDate={(iso) => iso}
      />,
    );

  it("draws the money and the rates under one legend", () => {
    const out = render([0, 0.1, -0.05, 0.2]);
    for (const label of ["Injected", "Profit", "Loss", "Your money", "Your picks"]) {
      expect(out).toContain(label);
    }
    // The money floor has its own gutter, and the rates' floor its zero line.
    expect(out).toMatch(/text-anchor="end"[^>]*>€1/);
    expect(out).toContain(">0%<");
  });

  it("breaks a rate line where a month has no rate instead of bridging it", () => {
    // Two leading nulls leave one run of two points for the money line.
    const out = render([null, null, -0.05, 0.2]);
    const money = out.match(/<path d="M[^"]*"[^>]*stroke-dasharray/g) ?? [];
    expect(money).toHaveLength(1); // only the dashed picks line is dashed
    expect(out.match(/<path d="M/g)?.length).toBeGreaterThanOrEqual(3);
  });

  it("stands each month's own return as a bar under the lines", () => {
    const out = renderToStaticMarkup(
      <BookAndRates
        points={points}
        series={[{ label: "Your money", points: [null, null, null, null] }]}
        bars={{ label: "That month", points: [0.02, -0.03, null, 0.05] }}
        labels={{
          invested: "Injected",
          value: "Value",
          profit: "Profit",
          loss: "Loss",
          gain: "Gain",
        }}
        money={(v) => `€${v}`}
        format={(v) => `${(v * 100).toFixed(0)}%`}
        formatDate={(iso) => iso}
      />,
    );
    // One bar per month that has a return, none for the one that does not —
    // and the bars draw even while every since-inception rate is still null.
    expect(out.match(/class="pf-rate-bar"/g)).toHaveLength(3);
    expect(out).toContain("That month");
    // The rates' scale holds them: the +5% bar tops out at the floor's inset
    // (money floor 8 + 200, inset 8), not past it.
    expect(out).toMatch(/class="pf-rate-bar"[^>]*y="216"/);
  });

  it("reads the month's own return in the box, between the money and the rates", () => {
    const rows = bookRatesTip(
      1,
      { value: 1100, invested: 1000 },
      {
        labels: { invested: "Injected", profit: "Profit", loss: "Loss", gain: "Gain" },
        money: (v, signed) => `${signed && v > 0 ? "+" : ""}€${v}`,
        format: (v) => `${(v * 100).toFixed(1)}%`,
        series: [{ label: "Your money", points: [null, null], color: "c" }],
        bars: {
          label: "That month",
          points: [0.02, -0.03],
          format: (v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`,
        },
      },
    );
    expect(rows.map((row) => `${row.label} ${row.value}`)).toEqual([
      "Profit €1100",
      "Injected €1000",
      "Gain +€100",
      "That month -3.0%",
      "Your money —",
    ]);
  });

  it("says in the box which reading a rate is, where the series says", () => {
    // The book's first year is its run so far; from the birthday, per year.
    const reading = (index: number) => (index < 1 ? "not annualised" : "annual");
    const tip = (index: number) =>
      bookRatesTip(
        index,
        { value: 1100, invested: 1000 },
        {
          labels: {
            invested: "Injected",
            profit: "Profit",
            loss: "Loss",
            gain: "Gain",
          },
          money: (v) => `€${v}`,
          format: (v) => `${(v * 100).toFixed(1)}%`,
          series: [
            { label: "Your money", points: [0.07, 0.12], color: "c", tipNote: reading },
            { label: "Your picks", points: [0.05, null], color: "d", tipNote: reading },
          ],
        },
      )
        .slice(3)
        .map((row) => `${row.label} ${row.value}`);
    expect(tip(0)).toEqual([
      "Your money 7.0% (not annualised)",
      "Your picks 5.0% (not annualised)",
    ]);
    // A month with no figure stays a bare dash, no note beside nothing.
    expect(tip(1)).toEqual(["Your money 12.0% (annual)", "Your picks —"]);
  });

  it("draws nothing for a single month", () => {
    const out = renderToStaticMarkup(
      <BookAndRates
        points={points.slice(0, 1)}
        series={[]}
        labels={{
          invested: "Injected",
          value: "Value",
          profit: "Profit",
          loss: "Loss",
          gain: "Gain",
        }}
        money={(v) => `€${v}`}
        format={(v) => `${v}`}
        formatDate={(iso) => iso}
      />,
    );
    expect(out).toBe("");
  });
});

describe("PeriodBars", () => {
  it("puts a value axis in the gutter", () => {
    const out = renderToStaticMarkup(
      <PeriodBars
        periods={[
          {
            period: "2024",
            realized_gain: 1200,
            deductible_loss: 300,
            recovered_loss: 0,
            net_taxable: 900,
          } as unknown as TaxPeriod,
        ]}
        labels={{ gains: "Gains", losses: "Losses", recovered: "Rec", net: "Net" }}
        money={(v) => `€${v}`}
      />,
    );
    expect(out).toMatch(/text-anchor="end"[^>]*>€1000</);
    expect(out).toMatch(/text-anchor="end"[^>]*>€0</);
  });
});

describe("Heatmap", () => {
  it("draws a single name as a 1×1 grid, as Plotly does", () => {
    const out = renderToStaticMarkup(
      <Heatmap matrix={{ A: { A: 1 } }} format={(v) => v.toFixed(2)} />,
    );
    expect(out.match(/pf-heat-cell/g)).toHaveLength(1);
  });

  it("draws its colour scale from −1 to +1", () => {
    const out = renderToStaticMarkup(
      <Heatmap
        matrix={{ A: { A: 1, B: 0.2 }, B: { A: 0.2, B: 1 } }}
        format={(v) => v.toFixed(2)}
      />,
    );
    expect(out).toContain("pf-heat-legend");
    expect(out).toContain("-1.00");
    expect(out).toContain("1.00");
  });
});

describe("correlationStats", () => {
  const matrix = {
    A: { A: 1, B: 0.9, C: -0.1 },
    B: { A: 0.9, B: 1, C: 0.3 },
    C: { A: -0.1, B: 0.3, C: 1 },
  };

  it("finds the most alike pair and the name least like the rest", () => {
    const stats = correlationStats(matrix);
    expect(stats.closest).toEqual({ a: "A", b: "B", value: 0.9 });
    expect(stats.diversifier?.name).toBe("C");
    expect(stats.perName.A?.peer?.name).toBe("B");
    expect(stats.perName.A?.hedge?.name).toBe("C");
    // Equal weights: the plain mean of the three pairs.
    expect(stats.average).toBeCloseTo((0.9 - 0.1 + 0.3) / 3);
  });

  it("weighs each pair by what the book holds of it", () => {
    const stats = correlationStats(matrix, { A: 0.45, B: 0.45, C: 0.1 });
    expect(stats.average).toBeGreaterThan(correlationStats(matrix).average!);
  });

  it("reads a value in words", () => {
    expect(correlationBand(0.85)).toBe("very_high");
    expect(correlationBand(0.5)).toBe("high");
    expect(correlationBand(0.25)).toBe("moderate");
    expect(correlationBand(0)).toBe("low");
    expect(correlationBand(-0.4)).toBe("negative");
  });
});

describe("lineMoney", () => {
  it("reads a shared-denominator return as euros, and the gap to the book", () => {
    // 10 000 in; the book is up 20 %, the index 35 %.
    expect(lineMoney(10_000, 0.2, null)).toEqual({
      worth: 12_000,
      gain: 2_000,
      versus: null,
    });
    const index = lineMoney(10_000, 0.35, 0.2);
    expect(index.worth).toBeCloseTo(13_500);
    expect(index.gain).toBeCloseTo(3_500);
    expect(index.versus).toBeCloseTo(1_500);
  });
});

describe("Donut", () => {
  const detail: SliceDetail = {
    money: (v, signed) => `${signed && v > 0 ? "+" : ""}€${v}`,
    change: (v) => `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`,
    labels: {
      value: "Value",
      invested: "Invested",
      result: "P/L",
      positions: "Positions",
      more: (n) => `+${n} more`,
      pin: "Click to pin",
      close: "Close",
    },
  };

  it("reads a slice as money: worth, what went in, and the P/L between", () => {
    const rows = sliceTip(
      {
        label: "Technology",
        weight: 0.4,
        value: 1500,
        cost: 1000,
        holdings: [
          { ticker: "NVDA", value: 1000, cost: 500 },
          { ticker: "MSFT", value: 500, cost: 500 },
        ],
      },
      detail,
    );
    expect(rows.map((row) => `${row.label} ${row.value}`)).toEqual([
      "Value €1500",
      "Invested €1000",
      "P/L +€500 (+50.0%)",
      "Positions 2",
    ]);
  });

  it("says nothing in money for a slice nothing priced", () => {
    expect(sliceTip({ label: "Unknown", weight: 0.1, value: null }, detail)).toEqual(
      [],
    );
  });

  it("folds the tail into one slice, one holding per ticker", () => {
    const folded = foldSlices(
      [
        {
          label: "Energy",
          weight: 0.02,
          value: 200,
          cost: 100,
          holdings: [{ ticker: "SPY", value: 200, cost: 100 }],
        },
        {
          label: "Utilities",
          weight: 0.01,
          value: 150,
          cost: 120,
          holdings: [
            { ticker: "SPY", value: 100, cost: 50 },
            { ticker: "NEE", value: 50, cost: 70 },
          ],
        },
        { label: "Unknown", weight: 0.01, value: null, cost: null },
      ],
      "Others",
    );
    expect(folded.weight).toBeCloseTo(0.04);
    expect(folded.value).toBe(350);
    expect(folded.cost).toBe(220);
    expect(folded.holdings).toEqual([
      { ticker: "SPY", value: 300, cost: 150 },
      { ticker: "NEE", value: 50, cost: 70 },
    ]);
  });

  it("names its largest slice in the hole and its money with it", () => {
    const html = renderToStaticMarkup(
      <Donut
        title="Sector"
        otherLabel="Others"
        format={(f) => `${(f * 100).toFixed(1)}%`}
        detail={detail}
        slices={[
          { label: "Health", weight: 0.25, value: 250, cost: 200 },
          { label: "Technology", weight: 0.75, value: 750, cost: 500 },
        ]}
      />,
    );
    expect(html).toContain(
      '<span class="pf-donut-center-label">Technology</span><strong>75.0%</strong>',
    );
    expect(html).toContain("€750");
  });
});

/** Every calendar day from `from` through `to`, as ISO dates. */
const days = (from: string, to: string) => {
  const out: string[] = [];
  const end = new Date(`${to}T00:00:00Z`);
  for (let at = new Date(`${from}T00:00:00Z`); at <= end;) {
    out.push(at.toISOString().slice(0, 10));
    at.setUTCDate(at.getUTCDate() + 1);
  }
  return out;
};

describe("dateTicks", () => {
  const span = days("2022-04-11", "2026-10-02");

  it("labels whole months across a wide plot, not whichever days the ends are", () => {
    const { indices, yearly } = dateTicks(span, 1800);
    expect(yearly).toBe(false);
    expect(indices.every((index) => span[index]!.endsWith("-01"))).toBe(true);
    expect(indices.map((index) => span[index])).toContain("2024-01-01");
  });

  it("falls back to years on a phone", () => {
    const { indices, yearly } = dateTicks(span, 300);
    expect(yearly).toBe(true);
    expect(indices.map((index) => span[index])).toEqual([
      "2023-01-01",
      "2024-01-01",
      "2025-01-01",
      "2026-01-01",
    ]);
  });

  it("keeps start, middle and end for a window inside one month", () => {
    const short = days("2026-09-02", "2026-09-30");
    expect(dateTicks(short, 600).indices).toEqual([0, 14, 28]);
  });
});

describe("ReturnLines", () => {
  const dates = days("2025-01-01", "2025-12-31");
  const ramp = (to: number) => dates.map((_, i) => (to * i) / (dates.length - 1));
  const render = (label?: string) =>
    renderToStaticMarkup(
      <ReturnLines
        dates={dates}
        label={label}
        format={(v) => `${(v * 100).toFixed(1)}%`}
        tickFormat={(v) => `${Math.round(v * 100)}%`}
        formatDate={(iso) => iso.slice(0, 7)}
        legendValues
        series={[
          { label: "Mine", points: ramp(0.3), color: "#fff", focal: true },
          { label: "Basket", points: ramp(0.2), color: "#bbb", dashed: true },
          { label: "SPY", points: ramp(0.1), color: "#00f" },
        ]}
      />,
    );

  it("says where each line ends on its legend entry", () => {
    const out = render();
    expect(out).toMatch(/Mine<\/span><strong class="pf-legend-value">30\.0%</);
    expect(out).toMatch(/SPY<\/span><strong class="pf-legend-value">10\.0%</);
  });

  it("draws the focal line last, heavier, with a dot where it ends", () => {
    const out = render();
    const order = [...out.matchAll(/data-series="([^"]+)"/g)].map((m) => m[1]);
    expect(order.at(-1)).toBe("Mine");
    expect(out).toMatch(/data-series="Mine"[^>]*stroke-width="2"/);
    expect(out).toMatch(/data-series="SPY"[^>]*stroke-width="1.5"/);
    expect(out.match(/<circle/g)).toHaveLength(1);
  });

  it("keys a solid line by a stroke and the backtest by a dashed one", () => {
    const out = render();
    expect(out.match(/pf-swatch pf-swatch-line/g)).toHaveLength(2);
    expect(out.match(/pf-swatch pf-swatch-dashed/g)).toHaveLength(1);
  });

  it("labels the value axis with the tick format, not the reading's", () => {
    const out = render();
    expect(out).toMatch(/text-anchor="end"[^>]*>10%</);
    expect(out).not.toMatch(/text-anchor="end"[^>]*>10\.0%</);
  });

  it("is a focusable, named plot", () => {
    const out = render("Return vs benchmarks");
    expect(out).toMatch(/<svg[^>]*role="img"[^>]*aria-label="Return vs benchmarks"/);
    expect(out).toMatch(/<svg[^>]*tabindex="0"/);
  });
});

describe("narrow plots", () => {
  it("takes a squarer shape as the plot narrows, and the desktop's past 480", () => {
    // A 350px phone: four fifths of the width, not the desktop's 300 and not
    // the half-height strip a scaled viewBox gave.
    expect(plotHeightFor(350, 300)).toBe(280);
    // Never under 240, never over the desktop height.
    expect(plotHeightFor(240, 300)).toBe(240);
    expect(plotHeightFor(720, 300)).toBe(300);
    expect(plotHeightFor(720, 240)).toBe(240);
  });

  const label = (props: Partial<Parameters<typeof AxisLabel>[0]>) =>
    renderToStaticMarkup(
      <svg>
        <AxisLabel text="10k" at={100} left={8} right={342} {...props} />
      </svg>,
    );

  it("centres a gutter label on its line, right-aligned", () => {
    expect(label({ left: 64 })).toMatch(/x="58" y="104"[^>]*text-anchor="end"/);
  });

  it("sits an inside label on its line, haloed, and starts it at the plot's edge", () => {
    const out = label({ inside: true });
    expect(out).toMatch(/x="12" y="96"[^>]*text-anchor="start"[^>]*class="pf-halo"/);
    // The rates' side hangs from the right edge instead.
    expect(label({ inside: true, side: "right" })).toMatch(
      /x="338" y="96"[^>]*text-anchor="end"/,
    );
  });

  it("drops a label on the top edge under its line rather than past the card", () => {
    expect(label({ inside: true, at: 8, top: 8 })).toMatch(/y="20"/);
  });

  it("keeps every chart's legend in a scroller and its plot a scrub surface", () => {
    const out = renderToStaticMarkup(
      <PeriodBars
        periods={[
          {
            period: "2024",
            realized_gain: 1,
            deductible_loss: 0,
            recovered_loss: 0,
            net_taxable: 1,
          } as unknown as TaxPeriod,
        ]}
        labels={{ gains: "Gains", losses: "Losses", recovered: "Rec", net: "Net" }}
        money={(v) => `€${v}`}
      />,
    );
    expect(out).toContain('class="pf-legend-strip ag-fade-x"');
    expect(out).toContain('class="pf-plot pf-scrub"');
    // Drawn 1:1 at the measured width (the fallback, here): no scaled frame.
    expect(out).toContain('viewBox="0 0 720 240"');
  });
});
