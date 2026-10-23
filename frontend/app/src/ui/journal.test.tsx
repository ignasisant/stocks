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

import {
  type JournalEntry,
  JournalList,
  MetOn,
  factRows,
  priceMarks,
  settledOn,
  RulesBlock,
  liveRule,
  ruleText,
} from "./Journal";

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

describe("how it was settled", () => {
  it("names the trade day when the book settled it", () => {
    expect(settledOn(entry({ state: "followed", settled: "ledger:2026-10-04" }))).toBe(
      "2026-10-04",
    );
  });

  it("names nothing for a button press or an older entry", () => {
    expect(settledOn(entry({ state: "declined", settled: "chat" }))).toBeNull();
    expect(settledOn(entry())).toBeNull();
  });
});

describe("the price since", () => {
  it("prints each mark read, signed, in day order", () => {
    const marked = entry({ outcome: { then: 100, d90: 20, d30: -12 } });
    expect(priceMarks(marked, "en")).toEqual([
      { days: 30, shown: "-12 %" },
      { days: 90, shown: "+20 %" },
    ]);
    expect(priceMarks(entry({ outcome: { then: 100, d30: 3.25 } }), "es")).toEqual([
      { days: 30, shown: "+3,3 %" },
    ]);
  });

  it("prints nothing before the first mark", () => {
    expect(priceMarks(entry(), "en")).toEqual([]);
    expect(priceMarks(entry({ outcome: { then: 100 } }), "en")).toEqual([]);
  });
});

function rule(over: Partial<JournalEntry> = {}): JournalEntry {
  return entry({
    id: "c1",
    type: "criterion",
    source: "chat",
    action: "below",
    subject: "criterion:AMD:below",
    reasons: [],
    snapshot: { rule: "below", level: 95 },
    evidence: "Data-centre share gains",
    ...over,
  });
}

const echo = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}(${Object.values(vars).join(",")})` : key;

describe("an exit rule", () => {
  it("reads in words, a price with cents and a percent as given", () => {
    expect(ruleText(echo, rule(), "en")).toBe("journal.crit_below(95.00)");
    expect(
      ruleText(echo, rule({ snapshot: { rule: "drawdown_cost", level: 30 } }), "en"),
    ).toBe("journal.crit_drawdown_cost(30)");
    expect(
      ruleText(echo, rule({ snapshot: { rule: "weight_above", level: 12.5 } }), "es"),
    ).toBe("journal.crit_weight_above(12,5)");
  });

  it("names an event without a level and a quarters run when there is one", () => {
    expect(ruleText(echo, rule({ snapshot: { rule: "ceo_change" } }), "en")).toBe(
      "journal.crit_ceo_change()",
    );
    expect(
      ruleText(
        echo,
        rule({ snapshot: { rule: "operating_margin_below", level: 15, quarters: 2 } }),
        "en",
      ),
    ).toBe("journal.crit_run(journal.crit_operating_margin_below(15),2)");
    expect(
      ruleText(
        echo,
        rule({ snapshot: { rule: "gross_margin_below", level: 40, quarters: 1 } }),
        "en",
      ),
    ).toBe("journal.crit_gross_margin_below(40)");
  });

  it("is live while open or met, not once retired or for a proposal", () => {
    expect(liveRule(rule())).toBe(true);
    expect(liveRule(rule({ state: "hit" }))).toBe(true);
    expect(liveRule(rule({ state: "retired" }))).toBe(false);
    expect(liveRule(entry())).toBe(false);
  });

  it("prints only where its measure stood the day it was met", () => {
    expect(factRows(rule(), "en", "USD")).toEqual([]);
    expect(
      factRows(
        rule({ snapshot: { rule: "below", level: 95, hit_value: 90 } }),
        "en",
        "USD",
      ),
    ).toEqual([["hit_value", "90"]]); // the quote's own currency, not the book's
    expect(
      factRows(
        rule({ snapshot: { rule: "drawdown_cost", level: 30, hit_value: -32 } }),
        "en",
        "USD",
      ),
    ).toEqual([["hit_value", "-32 %"]]);
  });

  it("prints the last quarter a fundamental rule read while still open", () => {
    expect(
      factRows(
        rule({ snapshot: { rule: "gross_margin_below", level: 40, value: 43.5 } }),
        "en",
        "USD",
      ),
    ).toEqual([["last_value", "43.5 %"]]);
  });

  it("quotes the passage an event rule was met on", () => {
    const out = renderToStaticMarkup(
      <MetOn
        entry={rule({
          state: "hit",
          snapshot: {
            rule: "ceo_change",
            quote: "Lisa Su will step down as CEO",
            source: "8-K (5.02)",
            source_day: "2026-10-20",
          },
        })}
      />,
    );
    expect(out).toContain("journal.met_on");
    expect(out).toContain("“Lisa Su will step down as CEO”");
    expect(out).toContain("8-K (5.02) · 2026-10-20");
  });
});

describe("the rules block", () => {
  const noop = () => {};

  it("lists each rule with its state and a named retire button", () => {
    const out = renderToStaticMarkup(
      <RulesBlock ticker="AMD" rules={[rule()]} onChange={noop} onAsk={noop} />,
    );
    expect(out).toContain("journal.criteria_title");
    expect(out).toContain("journal.crit_below");
    expect(out).toContain("journal.state_open");
    expect(out).toContain('aria-label="journal.criteria_retire: ');
    expect(out).toContain("journal.criteria_edit");
    expect(out).not.toContain("journal.criteria_empty");
  });

  it("offers to write them with the assistant when there are none", () => {
    const out = renderToStaticMarkup(
      <RulesBlock ticker="AMD" rules={[]} onChange={noop} onAsk={noop} />,
    );
    expect(out).toContain("journal.criteria_empty");
    expect(out).toContain("journal.criteria_propose");
    expect(out).not.toContain("ag-jr-retire");
  });
});
