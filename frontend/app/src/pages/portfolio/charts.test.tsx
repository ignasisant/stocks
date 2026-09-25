/**
 * The Portfolio charts' parity claims with the Streamlit (Plotly) ones.
 *
 * Three things a hand-drawn chart has to do on purpose that Plotly did for
 * free, each easy to lose in a refactor without any screen going blank: a
 * value axis with round labels, the history tooltip's P/L as an amount and a
 * percentage, the value line coloured by the sign of that P/L, and the
 * correlation grid's −1…+1 colour scale.
 *
 * `token()` reads computed styles off the document, which a node test does not
 * have — stubbed to "no token set", which is all a markup assertion needs.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { TaxPeriod } from "./api";
import { BookHistory, Heatmap, PeriodBars, bookTip, niceTicks } from "./charts";

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

  const labels = { injected: "Injected", profit: "Profit", loss: "Loss", pnl: "P/L" };
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
