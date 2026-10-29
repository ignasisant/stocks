/**
 * The drawer's price chart, as a surface draws it (`stocks/chat/charts.py`
 * builds the surface; `a2ui.tsx` puts the `Chart` and the window chips on it).
 *
 * Rendered to static markup, like the renderer's own tests. `token()` reads
 * computed styles off the document, which a node test does not have — stubbed
 * to "no token set", so the palette falls back to its defaults.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Surface, type A2uiMessage } from "./a2ui";
import { NumbersIn } from "../shell/i18n";
import { LineChart, price } from "./chart";
import { figuresIn } from "./format";

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

const eurusd = {
  symbol: "EURUSD=X",
  currency: "USD",
  dates: ["2025-10-01", "2026-01-02", "2026-04-01", "2026-07-01", "2026-10-01"],
  values: [1.08, 1.1, 1.12, 1.09, 1.15],
};

const surface = (data: object): A2uiMessage[] => [
  { version: "v0.9", createSurface: { surfaceId: "chart", catalogId: "urn:x" } },
  {
    version: "v0.9",
    updateComponents: {
      surfaceId: "chart",
      components: [
        { id: "root", component: "Column", children: ["plot", "windows"] },
        {
          id: "plot",
          component: "Chart",
          series: { path: "/chart" },
          mode: "price",
          label: "Price · past year",
        },
        {
          id: "windows",
          component: "ChoicePicker",
          options: [
            { label: "1M", value: "1m" },
            { label: "1Y", value: "1y" },
            { label: "5Y", value: "5y" },
          ],
          value: { path: "/window" },
          variant: "chips",
          action: {
            event: { name: "rechart", context: { window: { path: "/window" } } },
          },
        },
      ] as never,
    },
  },
  { version: "v0.9", updateDataModel: { surfaceId: "chart", value: data } },
];

describe("a chart surface", () => {
  it("draws the server's closes as a labelled line, and the windows as chips", () => {
    const out = renderToStaticMarkup(
      <Surface messages={surface({ window: "1y", chart: [eurusd] })} />,
    );
    expect(out).toContain('role="img"');
    // The label is the summary a glance gives: window, then the change.
    expect(out).toContain(
      'aria-label="Price · past year, Oct 1, 2025 – Oct 1, 2026: EURUSD=X +6.5%"',
    );
    expect(out).toContain("<polyline");
    // One line is drawn with its area under it, and needs no legend.
    expect(out).toContain("<path");
    expect(out).not.toContain("tk-legend");
    // The window in the data is the chip that is on, and only that one.
    expect(out.match(/ag-toggle-on/g)).toHaveLength(1);
    expect(out).toMatch(/ag-toggle ag-toggle-on"[^>]*>1Y</);
    // Chips, not the dropdown a plain ChoicePicker is.
    expect(out).not.toContain("<select");
  });

  it("draws nothing for a chart with no closes", () => {
    const out = renderToStaticMarkup(
      <Surface messages={surface({ window: "1y", chart: [] })} />,
    );
    expect(out).not.toContain("<svg");
    expect(out).toContain("ag-toggle");
  });
});

describe("the line chart", () => {
  it("rebases several lines to their change, with a legend to tell them apart", () => {
    const out = renderToStaticMarkup(
      <LineChart
        series={[
          eurusd,
          { ...eurusd, symbol: "GC=F", values: [2400, 2600, 2900, 3100, 3600] },
        ]}
        rebased
        label="Change"
      />,
    );
    expect(out.match(/<polyline/g)).toHaveLength(2);
    expect(out).toContain("tk-legend");
    expect(out).toContain(">GC=F<");
    // The axis is in percent, not in either line's own units.
    expect(out).toMatch(/>\+\d+%</);
  });

  it("reads its figures like the answer it sits in, not the account", () => {
    // An English account asked in Spanish: the text says "3.040,11 €".
    const out = renderToStaticMarkup(
      <NumbersIn lang={figuresIn("Tu cartera vale 3.040,11 € (+8,37 %).", "en")}>
        <LineChart
          series={[
            eurusd,
            { ...eurusd, symbol: "GC=F", values: [2400, 2600, 2900, 3100, 3600] },
          ]}
          rebased
          label="Cambio"
        />
      </NumbersIn>,
    );
    // The legend's change carries a decimal comma, never a point.
    expect(out).toMatch(/\+\d+,\d%/);
    expect(out).not.toMatch(/\+\d+\.\d%/);
  });

  it("drops a line too short to draw", () => {
    const out = renderToStaticMarkup(
      <LineChart
        series={[{ ...eurusd, dates: ["2026-10-01"], values: [1.15] }]}
        rebased={false}
        label="Price"
      />,
    );
    expect(out).toBe("");
  });
});

describe("price", () => {
  it("prints a close to the places its size reads at", () => {
    expect(price(1.12345)).toBe("1.1235");
    expect(price(182.5)).toBe("182.50");
    expect(price(95120.4)).toBe("95,120");
  });
});

describe("figuresIn", () => {
  it("reads the decimal mark, not the thousands group", () => {
    expect(figuresIn("vale 3.040,11 € y sube un 5,6 %", "en")).toBe("es");
    expect(figuresIn("worth $3,040.11, up 8.37%", "es")).toBe("en");
    // Groups alone ("3,040", "95.120") and no figures at all say nothing.
    expect(figuresIn("3,040 shares, 95.120 units", "es")).toBe("es");
    expect(figuresIn("¿Bato al S&P?", "en")).toBe("en");
  });
});
