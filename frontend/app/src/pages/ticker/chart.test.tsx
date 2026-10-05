/**
 * The price chart on a phone: drawn at the width it has, its y labels inside
 * the plot, and a legend whose entries switch series off.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { moveBetween, PriceChart } from "./PriceChart";
import { Legend, Tooltip, frame } from "./plot";
import type { Bars } from "./types";

// `chart()` reads the page's custom properties: with none, every one is "".
beforeAll(() => {
  vi.stubGlobal("document", { documentElement: {} });
  vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
});
afterAll(() => vi.unstubAllGlobals());

const dates = Array.from({ length: 60 }, (_, i) => {
  const day = new Date(Date.UTC(2026, 0, 1 + i));
  return day.toISOString().slice(0, 10);
});
const close = dates.map((_, i) => 100 + i);
const sma = (offset: number) => close.map((value) => value + offset);

const bars = {
  ticker: "AAA",
  range: "6mo",
  interval: "1d",
  dates,
  series: {
    Close: close,
    Open: close,
    High: close,
    Low: close,
    SMA20: sma(-2),
    SMA50: sma(-4),
    SMA200: sma(-6),
  },
  dividends: dates.map(() => null),
  rsi_verdict: null,
  rsi_tone: null,
} as unknown as Bars;

const render = (mobile: boolean) =>
  renderToStaticMarkup(
    <PriceChart
      bars={bars}
      events={[]}
      trades={[]}
      avgCost={null}
      candles={false}
      mobile={mobile}
      onWindow={() => {}}
      t={(key) => key}
    />,
  );

describe("PriceChart", () => {
  it("sets the y labels inside the plot on a phone, in a gutter on a desktop", () => {
    expect(render(true)).toContain("tk-grid tk-grid-in");
    expect(render(false)).not.toContain("tk-grid-in");
  });

  it("draws three date labels on a phone and more on a desktop", () => {
    const labels = (html: string) =>
      (html.match(/<g class="tk-xlabels">(.*?)<\/g>/)?.[1] ?? "").split("<text")
        .length - 1;
    expect(labels(render(true))).toBe(3);
    expect(labels(render(false))).toBeGreaterThan(3);
  });

  it("starts with the 200-day average off on a phone only", () => {
    const phone = render(true);
    const desk = render(false);
    expect(phone).toMatch(/aria-pressed="false"[^>]*>(?:(?!<\/button>).)*SMA200/);
    expect(desk).toMatch(/aria-pressed="true"[^>]*>(?:(?!<\/button>).)*SMA200/);
  });
});

describe("moveBetween", () => {
  it("reads the change between the first and last priced bars", () => {
    expect(moveBetween([100, 110, 125], 0, 2)).toEqual({
      a: 0,
      z: 2,
      start: 100,
      end: 125,
      pct: 25,
    });
  });

  it("skips gaps at either end instead of anchoring on them", () => {
    const move = moveBetween([null, 50, null, 40, null], 0, 4);
    expect(move).toMatchObject({ a: 1, z: 3, start: 50, end: 40 });
    expect(move?.pct).toBeCloseTo(-20);
  });

  it("says nothing with one priced bar or a zero start", () => {
    expect(moveBetween([null, 50, null], 0, 2)).toBeNull();
    expect(moveBetween([0, 50], 0, 1)).toBeNull();
  });
});

describe("PriceChart measuring hint", () => {
  it("words the gesture for touch and for a mouse", () => {
    const html = render(false);
    expect(html).toContain("ticker.span_hint_touch");
    expect(html).toContain("ticker.span_hint_mouse");
  });
});

describe("Tooltip", () => {
  const box = frame({ width: 320, height: 260 });
  const lines = [{ text: "Price 100" }];

  it("marks a reading that carries a fill or an event so the strip can grow", () => {
    const rich = renderToStaticMarkup(
      <Tooltip frame={box} x={10} title="d" lines={lines} more />,
    );
    const plain = renderToStaticMarkup(
      <Tooltip frame={box} x={10} title="d" lines={lines} />,
    );
    expect(rich).toContain("tk-tip-more");
    expect(plain).not.toContain("tk-tip-more");
  });
});

describe("Legend", () => {
  const items = [
    { label: "Price", color: "red" },
    { label: "SMA20", color: "blue", key: "SMA20" },
  ];

  it("is a plain list without a toggle", () => {
    const html = renderToStaticMarkup(<Legend items={items} />);
    expect(html).not.toContain("<button");
  });

  it("makes keyed items buttons that say whether they are on", () => {
    const html = renderToStaticMarkup(
      <Legend items={items} onToggle={() => {}} hidden={new Set(["SMA20"])} />,
    );
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain("tk-legend-off");
    expect(html.match(/<button/g)).toHaveLength(1);
  });
});
