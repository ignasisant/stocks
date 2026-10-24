/**
 * "Analyse with AI" as a split button: the press, and the chevron that
 * offers the other angles — on a share only, named for a screen reader,
 * and the sparkle alone at phone width.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiAsk } from "./AiAsk";

const html = (over: Partial<Parameters<typeof AiAsk>[0]> = {}) =>
  renderToStaticMarkup(
    <AiAsk
      ticker="LEU"
      name="Centrus"
      prompt="ticker.ai_prompt"
      angles
      compact={false}
      {...over}
    />,
  );

describe("AiAsk", () => {
  it("draws the press and a closed menu toggle on a share", () => {
    const out = html();
    expect(out).toContain('class="ag-ai tk-ai"');
    expect(out).toContain("ticker.ai_analyze<");
    expect(out).toContain('aria-haspopup="menu"');
    expect(out).toContain('aria-expanded="false"');
    expect(out).toContain('aria-label="ticker.ai_more"');
    // Closed: no menu in the page until it is asked for.
    expect(out).not.toContain('role="menu"');
  });

  it("offers no angles on a fund or a coin", () => {
    const out = html({ angles: false });
    expect(out).toContain("tk-ai");
    expect(out).not.toContain("tk-ai-more");
  });

  it("is the sparkle alone at phone width, still named", () => {
    const out = html({ compact: true });
    expect(out).toContain("✨");
    expect(out).toContain('aria-label="ticker.ai_analyze"');
  });
});
