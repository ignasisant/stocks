/**
 * The shared chart pieces: one hover box, one set of marks, one scrub.
 *
 * No DOM in this project's tests, so what is checked is what is drawn (the
 * box's rows and classes, its flip past the middle, the sentence a key step
 * speaks) and the numbers the four pages' charts take their marks from.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { keyStep } from "../../shell/useKeyWalk";
import { Tooltip } from "../../pages/ticker/plot";
import { AREA, BASELINE_DASH, DOT, LINE } from "./marks";
import { Tip, TipRows, tipAt, tipSaid } from "./Tip";
import { Spoken } from "./useScrub";

describe("Tip", () => {
  const items = [
    { label: "Value", value: "€1,200", color: "#fff", mark: "line" as const },
    { label: "Put in", value: "€1,000" },
    { text: "Price  187.40", tone: "up" as const },
  ];

  it("draws the title, then one row per item with its swatch and bold figure", () => {
    const html = renderToStaticMarkup(<Tip at={20} title="3 Mar" items={items} />);
    expect(html).toContain('class="ag-tip-title">3 Mar');
    expect(html.match(/class="ag-tip-row/g)).toHaveLength(3);
    expect(html).toContain("ag-tip-sw ag-tip-line");
    expect(html).toContain("<strong>€1,200</strong>");
    expect(html).toContain("ag-is-up");
  });

  it("opens to the pointer's left past the middle, and not before", () => {
    expect(renderToStaticMarkup(<Tip at={54} title="t" />)).not.toContain(
      "ag-tip-flip",
    );
    expect(renderToStaticMarkup(<Tip at={56} title="t" />)).toContain("ag-tip-flip");
  });

  it("anchors by percentage and keeps the page's placement class", () => {
    const html = renderToStaticMarkup(
      <Tip at={tipAt(190, 760)} title="t" className="hm-spark-tip" top={12} up wide />,
    );
    expect(html).toContain("left:25%");
    expect(html).toContain("top:12px");
    expect(html).toContain("hm-spark-tip");
    expect(html).toContain("ag-tip-up");
    expect(html).toContain("ag-tip-wide");
  });

  it("is never a live region: only a key step is spoken", () => {
    expect(renderToStaticMarkup(<Tip at={10} title="t" items={items} />)).not.toContain(
      "role=",
    );
    expect(renderToStaticMarkup(<Spoken text={null} />)).toContain(
      'aria-live="polite"',
    );
  });

  it("serves the ticker's tooltip too, with its strip class", () => {
    const f = { width: 760, height: 320, left: 52, right: 16, top: 12, bottom: 30 };
    const html = renderToStaticMarkup(
      <Tooltip
        frame={f}
        x={380}
        title="t"
        lines={[{ text: "a", swatch: "#fff" }]}
        more
      />,
    );
    expect(html).toContain("ag-tip");
    expect(html).toContain("tk-tip tk-tip-more");
    expect(html).toContain("ag-tip-sw");
  });

  it("says a box as one sentence", () => {
    expect(tipSaid("3 Mar", items)).toBe(
      "3 Mar, Value €1,200, Put in €1,000, Price  187.40",
    );
  });

  it("prints bare rows for a panel", () => {
    expect(
      renderToStaticMarkup(<TipRows items={[{ label: "a", value: "1" }]} />),
    ).toContain("ag-tip-label");
  });
});

describe("marks", () => {
  it("keeps the line hierarchy: primary over secondary over overlay over rule", () => {
    expect(LINE.primary).toBeGreaterThan(LINE.secondary);
    expect(LINE.secondary).toBeGreaterThan(LINE.overlay);
    expect(LINE.overlay).toBeGreaterThan(LINE.rule);
    expect(LINE.compact).toBeLessThan(LINE.primary);
  });

  it("fades an area from a tint to nothing", () => {
    expect(AREA.top).toBe(0.14);
    expect(AREA.bottom).toBe(0);
    expect(DOT.r).toBeGreaterThan(DOT.ring);
    expect(BASELINE_DASH).toBe("4 3");
  });
});

describe("scrub keys", () => {
  it("walks one point, ten with shift, to the edges, and puts the readout away", () => {
    expect(keyStep("ArrowRight", false, 5, 20)).toBe(6);
    expect(keyStep("ArrowLeft", true, 5, 20)).toBe(0);
    expect(keyStep("End", false, 5, 20)).toBe(20);
    expect(keyStep("Home", false, 5, 20)).toBe(0);
    expect(keyStep("Escape", false, 5, 20)).toBe("clear");
    expect(keyStep("a", false, 5, 20)).toBeNull();
  });
});
