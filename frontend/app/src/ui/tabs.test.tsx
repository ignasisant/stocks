/**
 * The one tab strip: a single stop in the page's tab order, the arrows to move
 * along it, a count only where there is something to count.
 *
 * Rendered to static markup: the question is what is drawn.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Tabs, stepTo } from "./Tabs";

const ITEMS = [
  { id: "a", label: "Overview" },
  { id: "b", label: "Positions", count: 12 },
  { id: "c", label: "Tax", count: 0 },
] as const;

describe("the tab strip", () => {
  const out = renderToStaticMarkup(
    <Tabs items={ITEMS} active="b" onPick={() => {}} label="Portfolio" />,
  );

  it("is a labelled tablist with the open tab selected", () => {
    expect(out).toContain('role="tablist"');
    expect(out).toContain('aria-label="Portfolio"');
    expect(out.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(out).toMatch(/aria-selected="true"[^>]*>Positions/);
  });

  it("is one stop in the tab order, on the open tab", () => {
    expect(out.match(/tabindex="0"/g)).toHaveLength(1);
    expect(out.match(/tabindex="-1"/g)).toHaveLength(2);
  });

  it("counts only what has something to count", () => {
    expect(out).toContain('<span class="ag-tab-n">12</span>');
    expect(out.match(/ag-tab-n/g)).toHaveLength(1);
  });

  it("draws one underline, hidden from a screen reader", () => {
    expect(out).toMatch(/<span class="ag-tabs-ink" aria-hidden="true">/);
  });
});

describe("the arrows", () => {
  it("move one tab along and wrap round the ends", () => {
    expect(stepTo("ArrowRight", 0, 3)).toBe(1);
    expect(stepTo("ArrowRight", 2, 3)).toBe(0);
    expect(stepTo("ArrowLeft", 0, 3)).toBe(2);
  });

  it("jump to the ends on Home and End, and ignore every other key", () => {
    expect(stepTo("Home", 2, 3)).toBe(0);
    expect(stepTo("End", 0, 3)).toBe(2);
    expect(stepTo("Enter", 1, 3)).toBeNull();
  });
});
