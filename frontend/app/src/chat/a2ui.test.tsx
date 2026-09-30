/**
 * The A2UI renderer: what a surface draws, and what it refuses to.
 *
 * Rendered to static markup — the question is what a given list of messages
 * puts on screen. The surfaces here are shaped like the server's
 * (`stocks/chat/a2ui.py`), which its own tests hold to the catalog.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Surface, type A2uiMessage } from "./a2ui";

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
