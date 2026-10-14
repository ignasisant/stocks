/**
 * The one segmented control: toggle buttons in a labelled group, one of them
 * pressed, and the thumb that slides under it.
 *
 * Rendered to static markup: the question is what is drawn.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Segmented } from "./Segmented";

const ITEMS = [
  { id: "1m", label: "1M" },
  { id: "1y", label: "1Y" },
  { id: "max", label: "Max" },
] as const;

describe("the segmented control", () => {
  const out = renderToStaticMarkup(
    <Segmented
      items={ITEMS}
      value="1y"
      onPick={() => {}}
      label="Range"
      className="x-place"
    />,
  );

  it("is a labelled group with the picked option pressed", () => {
    expect(out).toContain('role="group"');
    expect(out).toContain('aria-label="Range"');
    expect(out.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(out).toMatch(/aria-pressed="true"[^>]*>1Y/);
    expect(out.match(/aria-pressed="false"/g)).toHaveLength(2);
  });

  it("draws one hidden thumb and lets the page only add a class", () => {
    expect(out.match(/ag-seg-thumb/g)).toHaveLength(1);
    expect(out).toMatch(/class="ag-seg-thumb" aria-hidden="true"/);
    expect(out).toContain('class="ag-seg x-place"');
  });
});
