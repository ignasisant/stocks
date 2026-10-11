/**
 * The journal's rows: what a folded entry shows, which figures it prints and
 * in which units, and that the ticker panel's rows leave the ticker out.
 *
 * Units are the trap. The Review page writes P&L and weights as fractions; a
 * card signal writes its `*_pct` already in percent. Read with one rule, a
 * 50 % gain prints as 0.5 % or a 12 % drawdown as 1 200 %.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type JournalEntry, JournalList, factRows } from "./Journal";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

function entry(over: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: "e1",
    type: "proposal",
    source: "review",
    action: "sell",
    subject: "review:AMD",
    ticker: "AMD",
    line: "",
    reasons: ["weak_quality"],
    snapshot: {},
    evidence: "",
    state: "open",
    day: "2026-10-01",
    last: "2026-10-03",
    times: 2,
    links: [],
    updated: "2026-10-03T09:00:00",
    ...over,
  };
}

describe("the figures", () => {
  it("reads a Review P&L and weight as fractions", () => {
    const rows = factRows(
      entry({ snapshot: { pnl_pct: 0.5, weight: 0.15, quality: 41.6, held: true } }),
      "en",
      "EUR",
    );
    expect(rows).toEqual([
      ["quality", "42"],
      ["weight", "15 %"],
      ["pnl_pct", "50 %"],
    ]);
  });

  it("reads a card signal's percent as already percent, in its own currency", () => {
    const rows = factRows(
      entry({
        source: "daily",
        action: "harvest",
        snapshot: { pnl_pct: -12.3, loss: -500, currency: "USD", kind: "harvest" },
      }),
      "en",
      "EUR",
    );
    expect(rows).toEqual([
      ["pnl_pct", "-12.3 %"],
      ["loss", "-$500"],
    ]);
  });
});

describe("a folded row", () => {
  it("carries its anchor, its move, its state and how often it was shown", () => {
    const out = renderToStaticMarkup(<JournalList entries={[entry()]} />);
    expect(out).toContain('id="jr-e1"');
    expect(out).toContain("journal.action_sell");
    expect(out).toContain("journal.state_open");
    expect(out).toContain('aria-expanded="false"');
    // No line of its own: the reasons stand in, in the Review page's words.
    expect(out).toContain("review.reason_weak_quality");
    expect(out).toContain("journal.shown");
    expect(out).toContain("ag-tick");
  });

  it("names its fold button after the entry, not just 'more'", () => {
    const out = renderToStaticMarkup(
      <JournalList entries={[entry(), entry({ id: "e2", ticker: "SNAP" })]} />,
    );
    expect(out).toContain(
      'aria-label="journal.more: journal.action_sell AMD 2026-10-01"',
    );
    expect(out).toContain(
      'aria-label="journal.more: journal.action_sell SNAP 2026-10-01"',
    );
    expect(out).toContain('aria-controls="jr-e1-detail"');
  });

  it("leaves the ticker out where the panel already names it", () => {
    const out = renderToStaticMarkup(
      <JournalList entries={[entry()]} showTicker={false} />,
    );
    expect(out).not.toContain("ag-tick");
  });
});
