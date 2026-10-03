/**
 * The MCP App: the conversation with the host, and what each result draws.
 *
 * The host is a fake port that records what it is sent; the views are static
 * markup, and `t` hands keys back so the assertions name the parts drawn
 * rather than their wording.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Bridge, PROTOCOL_VERSION, type HostContext, type ToolResult } from "./bridge";
import { money, percent, shortDay } from "./format";
import { slices } from "./Overview";
import { bounds, path } from "./Performance";
import { initials } from "./TickerLabel";
import type { Overview, Performance, Position, Words } from "./types";
import { View } from "./View";
import { applyTheme, language, readConfig, translator } from "./words";

type Sent = {
  jsonrpc: string;
  id?: number;
  method?: string;
  params?: unknown;
  result?: unknown;
};

function host() {
  const sent: Sent[] = [];
  return { sent, postMessage: (message: unknown) => sent.push(message as Sent) };
}

function rig() {
  const port = host();
  const seen: { context: HostContext[]; result: ToolResult[] } = {
    context: [],
    result: [],
  };
  const bridge = new Bridge(port, {
    context: (c) => seen.context.push(c),
    result: (r) => seen.result.push(r),
  });
  const from = (data: unknown, source: unknown = port) =>
    bridge.receive({ data, source } as never);
  return { port, seen, bridge, from };
}

// A key, and its slots as `name=value` — no quotes for the markup to escape.
const words: Words = {
  t: (key, slots) =>
    slots
      ? `${key}(${Object.entries(slots)
          .map(([name, value]) => `${name}=${value}`)
          .join(";")})`
      : key,
  locale: "en",
  open: () => undefined,
};

const position = (over: Partial<Position> = {}): Position => ({
  ticker: "AAPL",
  value: 6000,
  cost: 5000,
  pnl_pct: 0.2,
  weight: 0.6,
  logo: "https://topstocks.example/app/static/logos/AAPL.png",
  ...over,
});

const overview = (over: Partial<Overview> = {}): Overview => ({
  kind: "overview",
  summary: {
    base: "EUR",
    value: 10000,
    cost: 8000,
    pnl: 2000,
    pnl_pct: 0.25,
    positions: 2,
    unpriced: 0,
    realized: 150,
  },
  positions: [
    position(),
    position({ ticker: "MSFT", weight: 0.4, pnl_pct: -0.05, logo: null }),
  ],
  positions_total: 2,
  unpriced: 0,
  ...over,
});

const performance = (over: Partial<Performance> = {}): Performance => ({
  kind: "performance",
  performance: {
    base: "EUR",
    window: "1y",
    start: "2025-10-03",
    end: "2026-10-03",
    injected: 9000,
    value: 10000,
    twr_cumulative: 0.12,
    twr_annualised: 0.12,
    twr_max_drawdown: -0.08,
    irr: 0.1,
  },
  history: {
    start: "2025-10-03",
    end: "2026-10-03",
    points: [
      { date: "2025-10-03", injected: 8000, value: 8000 },
      { date: "2026-04-03", injected: 9000, value: 9500 },
      { date: "2026-10-03", injected: 9000, value: 10000 },
    ],
    missing: [],
  },
  ...over,
});

const draw = (result: ToolResult | null) =>
  renderToStaticMarkup(<View result={result} words={words} />);

describe("the bridge", () => {
  it("asks for the host's context, hands it over, then says it is ready", async () => {
    const { port, seen, bridge, from } = rig();
    const started = bridge.start();
    const ask = port.sent[0];
    expect(ask?.method).toBe("ui/initialize");
    expect(ask?.params).toMatchObject({ protocolVersion: PROTOCOL_VERSION });
    from({ jsonrpc: "2.0", id: ask?.id, result: { hostContext: { theme: "light" } } });
    await started;
    expect(seen.context).toEqual([{ theme: "light" }]);
    expect(port.sent[1]?.method).toBe("ui/notifications/initialized");
  });

  it("draws the tool result the host sends, and follows its context", () => {
    const { seen, from } = rig();
    from({
      jsonrpc: "2.0",
      method: "ui/notifications/tool-result",
      params: { structuredContent: { kind: "overview" } },
    });
    from({
      jsonrpc: "2.0",
      method: "ui/notifications/host-context-changed",
      params: { locale: "es-ES" },
    });
    expect(seen.result).toEqual([{ structuredContent: { kind: "overview" } }]);
    expect(seen.context).toEqual([{ locale: "es-ES" }]);
  });

  it("ignores every window but the host", () => {
    const { port, seen, from } = rig();
    from({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: {} }, {});
    from({ jsonrpc: "2.0", id: 7, method: "ui/resource-teardown" }, null);
    expect(seen.result).toEqual([]);
    expect(port.sent).toEqual([]);
  });

  it("answers a request it does not know, so the host never waits on it", () => {
    const { port, from } = rig();
    from({ jsonrpc: "2.0", id: 7, method: "ui/resource-teardown", params: {} });
    expect(port.sent).toEqual([{ jsonrpc: "2.0", id: 7, result: {} }]);
  });

  it("ignores what is not JSON-RPC", () => {
    const { port, seen, from } = rig();
    from("hello");
    from({ method: "ui/notifications/tool-result" });
    expect(seen.result).toEqual([]);
    expect(port.sent).toEqual([]);
  });

  it("opens links through the host and survives a refusal", async () => {
    const { port, bridge, from } = rig();
    bridge.open("https://topstocks.example/ticker?ticker=AAPL");
    const ask = port.sent[0];
    expect(ask).toMatchObject({
      method: "ui/open-link",
      params: { url: "https://topstocks.example/ticker?ticker=AAPL" },
    });
    from({ jsonrpc: "2.0", id: ask?.id, error: { message: "no" } });
    await Promise.resolve();
  });
});

describe("the overview", () => {
  it("draws the figures, the ring and each holding as a logo and a link", () => {
    const html = draw({ structuredContent: overview() });
    expect(html).toContain("connector.view_overview_title");
    expect(html).toContain("connector.view_realized");
    expect(html).toContain('href="/ticker?ticker=AAPL"');
    expect(html).toContain('src="https://topstocks.example/app/static/logos/AAPL.png"');
    // No mirrored logo: initials, never an image from elsewhere.
    expect(html).toContain(
      '<span class="v-logo v-logo-i" aria-hidden="true">MS</span>',
    );
    expect(html).toContain('class="v-ring"');
    expect(html).toContain('href="/portfolio"');
  });

  it("says how many positions are unpriced and how many are not shown", () => {
    const html = draw({
      structuredContent: overview({
        positions: [position({ value: null, weight: null, pnl_pct: null })],
        positions_total: 30,
        unpriced: 1,
      }),
    });
    expect(html).toContain("connector.view_no_price");
    expect(html).toContain("connector.view_unpriced_note");
    expect(html).toContain("connector.view_more(shown=1;total=30)");
  });

  it("is an empty state for an empty book", () => {
    const html = draw({
      structuredContent: overview({ positions: [], positions_total: 0 }),
    });
    expect(html).toContain("connector.view_empty");
    expect(html).not.toContain("v-table");
  });

  it("leaves out realised when the book has none to report", () => {
    const data = overview();
    data.summary.realized = null;
    expect(draw({ structuredContent: data })).not.toContain("connector.view_realized");
  });

  it("escapes a ticker rather than drawing it as markup", () => {
    const html = draw({
      structuredContent: overview({ positions: [position({ ticker: "<b>X</b>" })] }),
    });
    expect(html).not.toContain("<b>X</b>");
  });
});

describe("the ring", () => {
  it("draws the largest weights and the rest of the book as one slice", () => {
    const many = Array.from({ length: 8 }, (_, i) =>
      position({ ticker: `T${i}`, weight: 0.1 }),
    );
    const parts = slices(many, "Other");
    expect(parts).toHaveLength(7);
    expect(parts.at(-1)).toMatchObject({ label: "Other" });
    expect(parts.at(-1)?.weight).toBeCloseTo(0.4);
  });

  it("has no slice for an unpriced holding, and no rest when nothing is left", () => {
    const parts = slices(
      [position({ weight: 1 }), position({ ticker: "X", weight: null })],
      "O",
    );
    expect(parts.map((p) => p.label)).toEqual(["AAPL"]);
  });
});

describe("the performance view", () => {
  it("puts both returns side by side with the window it covers", () => {
    const html = draw({ structuredContent: performance() });
    expect(html).toContain("connector.view_window_1y");
    expect(html).toContain("connector.view_twr");
    expect(html).toContain("connector.view_irr");
    expect(html).toContain("connector.view_drawdown");
    // The site's own tile, signed by colour like on every page.
    expect(html).toContain('class="ag-kpi-value ag-tone-down"');
    expect(html).toContain('class="v-line v-line-val"');
    expect(html).toContain('href="/portfolio?tab=risk"');
  });

  it("names the holdings it has no history for", () => {
    const data = performance();
    data.history.missing = ["XYZ", "ABC"];
    expect(draw({ structuredContent: data })).toContain(
      "connector.view_missing_note(names=XYZ, ABC)",
    );
  });

  it("has no chart with fewer than two points", () => {
    const data = performance();
    data.history.points = data.history.points.slice(0, 1);
    expect(draw({ structuredContent: data })).not.toContain("v-chart");
  });

  it("lifts the pen over a gap rather than drawing through it", () => {
    const d = path(
      [
        { date: "a", injected: 1, value: 1 },
        { date: "b", injected: 1, value: null },
        { date: "c", injected: 1, value: 2 },
      ],
      (p) => p.value,
      0,
      2,
    );
    expect(d.match(/M/g)).toHaveLength(2);
    expect(d).not.toContain("L");
  });

  it("scales both lines to one axis", () => {
    const [lo, hi] = bounds(performance().history.points) ?? [0, 0];
    expect(lo).toBeLessThan(8000);
    expect(hi).toBeGreaterThan(10000);
    expect(bounds([{ date: "a", injected: null, value: null }])).toBeNull();
  });
});

describe("the frame around a result", () => {
  it("waits for the host before there is a result", () => {
    expect(draw(null)).toContain("connector.view_waiting");
  });

  it("shows an error's words and nothing else", () => {
    const html = draw({
      isError: true,
      content: [{ type: "text", text: "Too many requests" }],
    });
    expect(html).toContain("Too many requests");
    expect(html).not.toContain("v-card");
  });

  it("leaves a kind with no view to the text Claude already has", () => {
    expect(draw({ structuredContent: { kind: "tax" } })).toContain(
      "connector.view_unknown",
    );
  });

  it("says when prices are stale", () => {
    const html = draw({
      structuredContent: { ...overview(), stale_since: "2026-10-02T09:00:00+00:00" },
    });
    expect(html).toContain("connector.view_stale");
  });
});

describe("words and theme", () => {
  it("reads the config the server wrote in, and survives a missing one", () => {
    const doc = (text: string | null) =>
      ({
        getElementById: () => (text === null ? null : { textContent: text }),
      }) as never;
    expect(
      readConfig(doc('{"origin":"https://x","strings":{"en":{"a":"b"}}}')),
    ).toEqual({
      origin: "https://x",
      strings: { en: { a: "b" } },
    });
    expect(readConfig(doc(null))).toEqual({ origin: "", strings: {} });
    expect(readConfig(doc("<!--TS-CONFIG-->"))).toEqual({ origin: "", strings: {} });
  });

  it("picks the host's language when shipped, English otherwise", () => {
    expect(language("es-ES", ["en", "es"])).toBe("es");
    expect(language("fr", ["en", "es"])).toBe("en");
    expect(language(undefined, ["en", "es"])).toBe("en");
  });

  it("fills slots and keeps a key with no string", () => {
    const t = translator({ hi: "Hi {name}, {name}" });
    expect(t("hi", { name: "Ana" })).toBe("Hi Ana, Ana");
    expect(t("hi")).toBe("Hi {name}, {name}");
    expect(t("nope")).toBe("nope");
  });

  it("takes the host's theme and only its CSS variables", () => {
    const set: Record<string, string> = {};
    const root = {
      dataset: {} as Record<string, string>,
      style: { setProperty: (k: string, v: string) => (set[k] = v) },
    };
    applyTheme(root as never, {
      theme: "light",
      styles: { variables: { "--color-text-primary": "#111", color: "red" } },
    });
    expect(root.dataset.theme).toBe("light");
    expect(set).toEqual({ "--color-text-primary": "#111" });
  });
});

describe("formats", () => {
  it("formats money, with a code Intl does not know", () => {
    expect(money(1234.5, "EUR", "en")).toBe("€1,235");
    expect(money(12.345, "EUR", "en")).toBe("€12.35");
    expect(money(null, "EUR", "en")).toBe("—");
    expect(money(5, "NOTACODE", "en")).toBe("5.00 NOTACODE");
  });

  it("signs a move but not a share", () => {
    expect(percent(0.123, "en")).toBe("+12.3%");
    expect(percent(0.123, "en", false)).toBe("12.3%");
    expect(percent(null, "en")).toBe("—");
  });

  it("dates a day without shifting it", () => {
    expect(shortDay("2026-10-03", "en")).toBe("Oct 3, 2026");
    expect(shortDay(null, "en")).toBe("");
  });

  it("makes initials of what a ticker has", () => {
    expect(initials("BRK.B")).toBe("BR");
    expect(initials("^^")).toBe("?");
  });
});
