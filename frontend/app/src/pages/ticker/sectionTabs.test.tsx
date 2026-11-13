/**
 * The page's index: links to every section, the first marked current, and
 * nothing at all for a page too short to need one.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SectionTabs, type SectionKey } from "./SectionTabs";

const render = (keys: SectionKey[]) =>
  renderToStaticMarkup(
    <SectionTabs
      sections={keys.map((key) => ({ key, label: `tab:${key}` }))}
      head={{ current: null }}
      mini={<b>AAPL</b>}
    />,
  );

describe("SectionTabs", () => {
  it("links every section and marks the first as where the reader is", () => {
    const html = render(["summary", "price", "valuation", "compare"]);
    expect(html).toContain('href="#tk-s-summary"');
    expect(html).toContain('href="#tk-s-compare"');
    expect(html.match(/aria-current="location"/g)).toHaveLength(1);
    expect(html).toMatch(/aria-current="location"[^>]*>tab:summary/);
  });

  it("draws no index for a page of two sections", () => {
    expect(render(["price", "compare"])).toBe("");
  });

  it("keeps the symbol out of the strip until the header has gone", () => {
    expect(render(["summary", "price", "compare"])).not.toContain("tk-tabs-mini");
  });
});
