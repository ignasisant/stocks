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
  buyRule,
  JournalList,
  MetOn,
  factRows,
  priceMarks,
  settledOn,
  RulesBlock,
  liveRule,
  ruleText,
  rulesSubject,
} from "./Journal";
import { clashWith, closestOf, gapOf, readRule, trackOf } from "./ruleReading";

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

  it("reads a thesis rule as its pillars", () => {
    expect(
      ruleText(
        echo,
        rule({
          snapshot: { rule: "thesis", pillars: ["Capex grows", "Margins hold"] },
        }),
        "en",
      ),
    ).toBe("journal.crit_thesis(Capex grows · Margins hold)");
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
    expect(out).not.toContain("journal.pillar_hit");
  });

  it("names the pillar a thesis rule was met against", () => {
    const out = renderToStaticMarkup(
      <MetOn
        entry={rule({
          state: "hit",
          snapshot: {
            rule: "thesis",
            pillars: ["Capex grows"],
            pillar: "Capex grows",
            quote: "Microsoft cuts its capex plan",
            source: "Reuters",
          },
        })}
      />,
    );
    expect(out).toContain("journal.pillar_hit");
    expect(out).toContain("“Microsoft cuts its capex plan”");
  });
});

describe("the rules block", () => {
  const noop = () => {};
  const zone = (over: Partial<JournalEntry> = {}) =>
    rule({
      id: "b1",
      action: "buy_below",
      subject: "criterion:AMD:buy_below",
      snapshot: { rule: "buy_below", level: 80 },
      ...over,
    });

  it("reads each rule against today, with a named menu", () => {
    const out = renderToStaticMarkup(
      <RulesBlock
        ticker="AMD"
        held
        rules={[rule()]}
        quote={{ price: 100, high: 120 }}
        onChange={noop}
        onAsk={noop}
      />,
    );
    expect(out).toContain("journal.criteria_title");
    expect(out).toContain("journal.crit_below");
    expect(out).toContain("journal.read_today");
    expect(out).toContain('data-kind="far"');
    expect(out).toContain("journal.gap_fall");
    expect(out).toContain('aria-label="journal.rule_options: ');
    expect(out).toContain('aria-expanded="false"');
    expect(out).toContain("ag-jr-track-dot");
    // The actions stay folded until the menu opens.
    expect(out).not.toContain("journal.criteria_retire");
    expect(out).not.toContain("journal.criteria_empty");
  });

  it("calls a price under the line near until the server says met", () => {
    const under = renderToStaticMarkup(
      <RulesBlock
        ticker="AMD"
        rules={[zone()]}
        quote={{ price: 79, high: 120 }}
        onChange={noop}
        onAsk={noop}
      />,
    );
    expect(under).toContain('data-kind="near"');
    expect(under).toContain("journal.read_on_line");
    expect(under).toContain("journal.verdict_none");
    const hit = renderToStaticMarkup(
      <RulesBlock
        ticker="AMD"
        rules={[
          zone({
            state: "hit",
            snapshot: { rule: "buy_below", level: 80, hit_day: "2026-11-20" },
          }),
        ]}
        quote={{ price: 79, high: 120 }}
        onChange={noop}
        onAsk={noop}
      />,
    );
    expect(hit).toContain('data-kind="met"');
    expect(hit).toContain("journal.state_hit");
    expect(hit).toContain("journal.read_hit_on");
    expect(hit).toContain("journal.verdict_all");
  });

  it("never sets another listing's level against this quote", () => {
    const out = renderToStaticMarkup(
      <RulesBlock
        ticker="AMD"
        rules={[zone({ ticker: "AMD.DE" })]}
        quote={{ price: 70, high: 120 }}
        onChange={noop}
        onAsk={noop}
      />,
    );
    expect(out).toContain('data-kind="unread"');
    expect(out).not.toContain("journal.read_today");
  });

  it("puts the buy side first on a name not held, and the exit side in one line", () => {
    expect(buyRule(zone())).toBe(true);
    expect(buyRule(rule())).toBe(false);
    expect(ruleText(echo, zone(), "en")).toBe("journal.crit_buy_below(80.00)");
    const out = renderToStaticMarkup(
      <RulesBlock ticker="AMD" rules={[zone()]} onChange={noop} onAsk={noop} />,
    );
    expect(out).toContain("journal.entry_title");
    expect(out).toContain("journal.criteria_later");
    expect(out).not.toContain("journal.criteria_empty");
    expect(out.indexOf("journal.entry_title")).toBeLessThan(
      out.indexOf("journal.criteria_title"),
    );
  });

  it("puts the exit side first for a holder, offering to write it", () => {
    const out = renderToStaticMarkup(
      <RulesBlock ticker="AMD" held rules={[]} onChange={noop} onAsk={noop} />,
    );
    expect(out).toContain("journal.criteria_empty");
    expect(out).toContain("journal.criteria_propose");
    expect(out).toContain("journal.entry_title_held");
    expect(out.indexOf("journal.criteria_title")).toBeLessThan(
      out.indexOf("journal.entry_title_held"),
    );
  });

  it("shows the checklist and flags a buy rule that asks for less", () => {
    const margin = zone({
      id: "b2",
      action: "buy_operating_margin_above",
      subject: "criterion:AMD:buy_operating_margin_above",
      snapshot: { rule: "buy_operating_margin_above", level: 10 },
    });
    const out = renderToStaticMarkup(
      <RulesBlock
        ticker="AMD"
        rules={[margin]}
        checklist={[
          {
            rule: "op_margin_min",
            level: 15,
            text: "margin at least 15 %",
            shown: "12 %",
            state: "fail",
          },
          {
            rule: "pe_fwd_max",
            level: 30,
            text: "P/E at most 30",
            shown: "22",
            state: "pass",
          },
        ]}
        onChange={noop}
        onAsk={noop}
      />,
    );
    expect(out).toContain("journal.checklist_title");
    expect(out).toContain("journal.checklist_fails");
    expect(out).toContain('data-state="fail"');
    expect(out).toContain("journal.check_fail");
    expect(out).toContain('role="note"');
    expect(out).toContain("journal.clash_fix");
  });
});

describe("a rule read against today", () => {
  it("reads a drawdown from the year's high, a fundamental from its last check", () => {
    const drop = readRule(
      rule({ snapshot: { rule: "drawdown_high", level: 25 } }),
      { price: 90, high: 120 },
      true,
    );
    expect(drop.value).toBeCloseTo(25);
    expect(drop.onLine).toBe(true);
    expect(drop.kind).toBe("near");
    const slow = readRule(
      rule({
        snapshot: {
          rule: "buy_operating_margin_above",
          level: 15,
          checked: "2026-11-01",
          value: 12,
        },
      }),
      null,
      true,
    );
    expect(slow.group).toBe("quarter");
    expect(slow.kind).toBe("far");
    expect(gapOf(slow)).toEqual({ key: "journal.gap_points", n: 3 });
    const unchecked = readRule(
      rule({ snapshot: { rule: "buy_operating_margin_above", level: 15, value: 12 } }),
      null,
      true,
    );
    expect(unchecked.kind).toBe("unread");
  });

  it("never calls a loss-making P/E near, and watches news and book rules", () => {
    const pe = readRule(
      rule({
        snapshot: {
          rule: "buy_pe_fwd_below",
          level: 20,
          checked: "2026-11-01",
          value: -4,
        },
      }),
      null,
      true,
    );
    expect(pe.kind).toBe("far");
    expect(trackOf(pe)).toBeNull();
    expect(readRule(rule({ snapshot: { rule: "ceo_change" } }), null, true).kind).toBe(
      "watch",
    );
    expect(
      readRule(rule({ snapshot: { rule: "weight_above", level: 10 } }), null, true)
        .group,
    ).toBe("daily");
  });

  it("says what a price still has to fall, in percent of today", () => {
    const below = readRule(rule(), { price: 100, high: null }, true);
    expect(below.kind).toBe("far");
    expect(gapOf(below)?.key).toBe("journal.gap_fall");
    expect(gapOf(below)?.n).toBeCloseTo(5);
    expect(gapOf(readRule(rule(), { price: 94, high: null }, true))).toBeNull();
  });

  it("names a rule already on its line the closest, whatever its distance", () => {
    const far = {
      id: "far",
      reading: readRule(rule(), { price: 100, high: null }, true),
    };
    const on = {
      id: "on",
      reading: readRule(
        rule({
          snapshot: {
            rule: "buy_pe_fwd_below",
            level: 25,
            checked: "2026-11-01",
            value: 18,
          },
        }),
        null,
        true,
      ),
    };
    const met = { id: "met", reading: readRule(rule({ state: "hit" }), null, true) };
    expect(on.reading.onLine).toBe(true);
    expect(closestOf([far, on, met])?.id).toBe("on");
    expect(closestOf([far, met])?.id).toBe("far");
    expect(closestOf([met])).toBeNull();
  });

  it("places the met side of the line on the track", () => {
    const below = trackOf(readRule(rule(), { price: 100, high: null }, true));
    expect(below?.from).toBe(0);
    expect(below?.to).toBe(below?.level);
    expect(below!.value).toBeGreaterThan(below!.level);
  });

  it("finds the checklist line a buy rule undercuts, and only that one", () => {
    const lines = [{ rule: "pe_fwd_max", level: 25 }];
    const loose = rule({ snapshot: { rule: "buy_pe_fwd_below", level: 30 } });
    const tight = rule({ snapshot: { rule: "buy_pe_fwd_below", level: 20 } });
    expect(clashWith(loose, lines)).toEqual(lines[0]);
    expect(clashWith(tight, lines)).toBeNull();
    expect(clashWith(rule(), lines)).toBeNull();
  });
});

describe("what the assistant is asked to write rules for", () => {
  it("names the company beside a broker code", () => {
    expect(rulesSubject("RCF", "Teleperformance SE")).toBe("RCF (Teleperformance SE)");
  });

  it("keeps the bare ticker when there is no other name", () => {
    expect(rulesSubject("AMD")).toBe("AMD");
    expect(rulesSubject("BTC-EUR", "btc-eur")).toBe("BTC-EUR");
  });
});
