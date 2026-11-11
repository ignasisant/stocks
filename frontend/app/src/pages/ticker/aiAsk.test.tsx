/**
 * "Analyse with AI" as a split button: the press, and the chevron that
 * offers the other angles — on a share only, named for a screen reader —
 * in one pill, worded at every width.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiAsk } from "./AiAsk";

const html = (over: Partial<Parameters<typeof AiAsk>[0]> = {}) =>
  renderToStaticMarkup(
    <AiAsk ticker="LEU" name="Centrus" prompt="ticker.ai_prompt" angles {...over} />,
  );

describe("AiAsk", () => {
  it("draws the press and a closed menu toggle on a share", () => {
    const out = html();
    expect(out).toContain('class="ag-ai tk-ai-pill tk-ai-split"');
    expect(out).toContain("ticker.ai_analyze<");
    expect(out).toContain('aria-haspopup="menu"');
    expect(out).toContain('aria-expanded="false"');
    expect(out).toContain('aria-label="ticker.ai_more"');
    // Closed: no menu in the page until it is asked for.
    expect(out).not.toContain('role="menu"');
  });

  it("offers no angles on a fund or a coin", () => {
    const out = html({ angles: false });
    expect(out).toContain('class="ag-ai tk-ai-pill"');
    expect(out).not.toContain("tk-ai-more");
  });

  it("keeps its words beside the sparkle, so the press says what it does", () => {
    const out = html();
    expect(out).toContain("ag-chat-glyph");
    expect(out).toContain("<span>ticker.ai_analyze</span>");
    expect(out).not.toContain("✨");
  });
});
