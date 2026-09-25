/**
 * A ticker on screen is a logo, a symbol, a name and a link.
 *
 * Rendered to static markup: the cell's job is the HTML it produces, and the
 * profile cache is seeded directly because the effect that would ask the
 * server never runs outside a browser.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { seed, TickerCell } from "./tickers";

seed([
  { ticker: "ASML", symbol: "ASML.AS", name: "ASML Holding", logo: "/logo/asml.png" },
  {
    ticker: "IE00B4L5Y983",
    symbol: "IWDA.AS",
    name: "iShares Core MSCI World",
    logo: null,
  },
]);

const html = (node: React.ReactElement) => renderToStaticMarkup(node);

describe("TickerCell", () => {
  it("prints the resolved symbol and the company, as ticker_cell does", () => {
    const out = html(<TickerCell ticker="ASML" />);
    expect(out).toContain("ASML.AS");
    expect(out).toContain("— ASML Holding");
    expect(out).toContain('src="/logo/asml.png"');
  });

  it("links the stored label, not the resolved symbol", () => {
    const out = html(<TickerCell ticker="IE00B4L5Y983" />);
    expect(out).toContain("IWDA.AS");
    expect(out).toContain('href="/ticker?ticker=IE00B4L5Y983"');
  });

  it("drops the name in a compact context, keeping it as hover text", () => {
    const out = html(<TickerCell ticker="ASML" name={false} />);
    expect(out).not.toContain("— ASML Holding");
    expect(out).toContain('title="ASML Holding"');
  });

  it("still lets a caller replace the label", () => {
    const out = html(<TickerCell ticker="ASML">custom</TickerCell>);
    expect(out).toContain("custom");
    expect(out).not.toContain("ASML.AS");
  });

  it("prints the bare ticker for a symbol nobody knows", () => {
    const out = html(<TickerCell ticker="ZZZZ" />);
    expect(out).toContain(">ZZZZ<");
  });
});
