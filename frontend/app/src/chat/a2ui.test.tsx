/**
 * The A2UI renderer: what a surface draws, and what it refuses to.
 *
 * Rendered to static markup — the question is what a given list of messages
 * puts on screen. The surfaces here are shaped like the server's
 * (`stocks/chat/a2ui.py`), which its own tests hold to the catalog.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Surface, numeric, tradeImpact, type A2uiMessage } from "./a2ui";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

const surface = (components: object[], data: object = {}): A2uiMessage[] => [
  { version: "v0.9", createSurface: { surfaceId: "s", catalogId: "urn:x" } },
  {
    version: "v0.9",
    updateComponents: { surfaceId: "s", components: components as never },
  },
  { version: "v0.9", updateDataModel: { surfaceId: "s", value: data } },
];

const draw = (messages: A2uiMessage[]) =>
  renderToStaticMarkup(<Surface messages={messages} />);

describe("a surface", () => {
  it("draws its components from the root down, bound to its data", () => {
    const out = draw(
      surface(
        [
          { id: "root", component: "Column", children: ["title", "shares", "go"] },
          { id: "title", component: "Text", text: "Your position", variant: "h3" },
          {
            id: "shares",
            component: "TextField",
            label: "Shares",
            value: { path: "/form/shares" },
            variant: "number",
          },
          {
            id: "go",
            component: "Button",
            text: "Save",
            variant: "primary",
            action: { event: { name: "save" } },
          },
        ],
        { form: { shares: "12" } },
      ),
    );
    expect(out).toContain("Your position");
    expect(out).toContain('value="12"');
    expect(out).toContain('inputMode="decimal"');
    expect(out).toContain("ag-chat-btn-on");
  });

  it("draws a data update over the model it started with", () => {
    const messages = [
      ...surface([{ id: "root", component: "Text", text: { path: "/figure" } }], {
        figure: "1",
      }),
      {
        version: "v0.9",
        updateDataModel: { surfaceId: "s", path: "/figure", value: "2" },
      },
    ];
    expect(draw(messages)).toContain(">2<");
  });

  it("skips a component it does not have, and anything it would have to run", () => {
    const out = draw(
      surface([
        { id: "root", component: "Column", children: ["ok", "evil", "loop"] },
        { id: "ok", component: "Text", text: "<img src=x onerror=alert(1)>" },
        { id: "evil", component: "Script", src: "https://evil.example/x.js" },
        { id: "loop", component: "Column", children: ["loop"] },
      ]),
    );
    expect(out).toContain("&lt;img");
    expect(out).not.toContain("<img");
    expect(out).not.toContain("evil.example");
  });

  it("draws nothing without a root", () => {
    expect(
      draw(surface([{ id: "x", component: "Text", text: "orphan" }])),
    ).not.toContain("orphan");
  });

  it("draws a picker preset to the model's value", () => {
    const out = draw(
      surface(
        [
          {
            id: "root",
            component: "ChoicePicker",
            label: "Date",
            options: [
              { label: "— none —", value: "" },
              { label: "When · 02/01", value: "0" },
            ],
            value: { path: "/mapping/columns/date" },
          },
        ],
        { mapping: { columns: { date: "0" } } },
      ),
    );
    expect(out).toMatch(/<option value="0" selected="">When · 02\/01<\/option>/);
  });

  it("draws a what-if: a slider over the holding and figures toned by the data", () => {
    const out = draw(
      surface(
        [
          { id: "root", component: "Column", children: ["shares", "gain"] },
          {
            id: "shares",
            component: "Slider",
            label: "Shares to sell",
            value: { path: "/shares" },
            min: 0,
            max: 20,
            step: 1,
            action: {
              event: { name: "simulate", context: { shares: { path: "/shares" } } },
            },
          },
          {
            id: "gain",
            component: "Metric",
            label: "Realised gain",
            value: { path: "/view/gain" },
            tone: { path: "/view/gain_tone" },
          },
        ],
        { shares: 10, view: { gain: "+€500", gain_tone: "up" } },
      ),
    );
    expect(out).toContain('type="range"');
    expect(out).toContain('max="20"');
    expect(out).toContain('value="10"');
    expect(out).toContain("+€500");
    expect(out).toContain("ag-tone-up");
  });
});

describe("a number field", () => {
  it("takes digits and one decimal mark, comma or point, and nothing else", () => {
    for (const ok of ["", "12", "26,51", "26.51", "0.", ",5"])
      expect(numeric(ok)).toBe(true);
    for (const no of ["dqwd", "12a", "1,2,3", "1.2.3", "-5", "1e3", "1 000"])
      expect(numeric(no)).toBe(false);
  });
});

describe("a trade being typed", () => {
  const lots: [number, number][] = [
    [60, 20],
    [40, 30],
  ];

  it("sells the oldest parcels first, as the ledger plan does", () => {
    const sale = tradeImpact("sell", 80, 26.51, lots);
    expect(sale?.after).toBe(20);
    // 80 × 26.51 − (60 × 20 + 20 × 30)
    expect(sale?.gain?.amount).toBeCloseTo(320.8);
    expect(sale?.gain?.ratio).toBeCloseTo(320.8 / 1800);
  });

  it("knows the shares left before the price is in", () => {
    const sale = tradeImpact("sell", 100, NaN, lots);
    expect(sale).toEqual({ held: 100, after: 0 });
  });

  it("flags a sale of more than is held, and waits for a side and a count", () => {
    expect(tradeImpact("sell", 101, 26, lots)?.after).toBeNull();
    expect(tradeImpact("", 10, 26, lots)).toBeNull();
    expect(tradeImpact("sell", NaN, 26, lots)).toBeNull();
  });

  it("averages a purchase into what is held", () => {
    const buy = tradeImpact("buy", 100, 35, lots);
    expect(buy?.after).toBe(200);
    expect(buy?.avg).toEqual({ before: 24, after: 29.5 });
    expect(tradeImpact("buy", 10, 35, [])?.avg).toEqual({ before: null, after: 35 });
  });

  it("draws the shares left and the gain under the form", () => {
    const out = draw(
      surface(
        [
          {
            id: "root",
            component: "TradeImpact",
            trade: { path: "/form/trade" },
            quantity: { path: "/form/quantity" },
            price: { path: "/form/price" },
            lots: { path: "/position/lots" },
            currency: "USD",
            labels: {
              held: "Acciones",
              gain: "Ganancia/pérdida",
              over: "Solo tienes {held}",
            },
          },
        ],
        {
          form: { trade: "sell", quantity: "100", price: "26,51" },
          position: { lots },
        },
      ),
    );
    expect(out).toContain("Acciones");
    expect(out).toContain("100 → 0");
    expect(out).toContain("Ganancia/pérdida");
  });
});
