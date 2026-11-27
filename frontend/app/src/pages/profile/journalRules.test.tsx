/**
 * "Your rules by holding": the tiles count what is left to do, rows keep the
 * server's order (heaviest first), a fund reads "n/a" where a stock reads
 * "missing", and an opened row offers the move a met or stale rule asks for.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Coverage, CoverageRow, CoverageRule } from "../../api.gen";
import { Holding, RulesBoard, draftKey } from "./JournalRules";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

const noop = () => {};

function rule(over: Partial<CoverageRule> = {}): CoverageRule {
  return {
    id: "r1",
    ticker: "AMD",
    rule: "below",
    family: "price",
    side: "exit",
    state: "open",
    since: "2026-10-01",
    level: 95,
    quarters: null,
    pillars: [],
    checked: null,
    last_value: null,
    watch: [],
    flag: null,
    quote: null,
    source: null,
    source_day: null,
    pillar: null,
    verdict: null,
    ...over,
  };
}

const STOCK = ["thesis", "price", "fundamental", "event", "buy"] as const;

function row(over: Partial<CoverageRow> = {}): CoverageRow {
  return {
    ticker: "AMD",
    kind: "stock",
    weight: 0.5,
    status: "ok",
    missing: [],
    applies: [...STOCK],
    rules: [],
    retired: 0,
    ...over,
  };
}

function coverage(rows: CoverageRow[], covered = 0.5): Coverage {
  return {
    rows,
    summary: {
      holdings: rows.length,
      covered,
      hit: 0,
      none: 0,
      gap: 0,
      review: 0,
      ok: 0,
      no_buy: 0,
    },
  };
}

describe("the board", () => {
  const book = coverage([
    row({
      ticker: "NVDA",
      weight: 0.5,
      status: "hit",
      rules: [
        rule({
          id: "a",
          ticker: "NVDA",
          rule: "thesis",
          family: "thesis",
          state: "hit",
        }),
        rule({ id: "b", ticker: "NVDA" }),
      ],
    }),
    row({
      ticker: "AMD",
      weight: 0.3,
      status: "gap",
      missing: ["thesis"],
      rules: [rule({ flag: "drift" })],
    }),
    row({
      ticker: "IWDA.AS",
      kind: "fund",
      weight: 0.2,
      status: "none",
      missing: ["price"],
      applies: ["price", "buy"],
    }),
  ]);

  it("counts what is left to do on tiles that filter", () => {
    const out = renderToStaticMarkup(<RulesBoard coverage={book} reload={noop} />);
    expect(out).toContain("50 %");
    for (const key of ["hit", "none", "gap", "review", "no_buy"]) {
      expect(out).toContain(`journal.cov_${key}`);
    }
    expect(out.match(/aria-pressed="false"/g)).toHaveLength(5);
  });

  it("keeps the heaviest first and drafts the heaviest gap next", () => {
    const out = renderToStaticMarkup(<RulesBoard coverage={book} reload={noop} />);
    const list = out.slice(out.indexOf('class="jc-list"'));
    expect(list.indexOf("NVDA")).toBeLessThan(list.indexOf("AMD"));
    expect(list.indexOf("AMD")).toBeLessThan(list.indexOf("IWDA.AS"));
    expect(list).toContain("journal.cov_lacks");
    expect(out).toContain("journal.cov_next");
    expect(out).toContain('data-cell="miss"');
    expect(out).toContain('data-cell="hit"');
    expect(out).toContain('data-cell="review"');
    // A fund has no thesis to write: not applicable, never missing.
    expect(out).toContain('data-cell="na"');
  });

  it("counts a met rule's missing thesis as a gap, not as done", () => {
    const met = coverage([
      row({
        ticker: "TEP.PA",
        status: "hit",
        missing: ["thesis"],
        rules: [rule({ ticker: "TEP.PA", state: "hit" })],
      }),
    ]);
    const out = renderToStaticMarkup(<RulesBoard coverage={met} reload={noop} />);
    const gap = out.slice(out.indexOf("journal.cov_gap"));
    expect(gap.slice(0, gap.indexOf("</button>"))).toMatch(/>1</);
    expect(out).toContain("journal.cov_next");
  });

  it("says so when nothing is held", () => {
    const out = renderToStaticMarkup(
      <RulesBoard coverage={coverage([])} reload={noop} />,
    );
    expect(out).toContain("journal.cov_empty");
    expect(out).not.toContain("journal.cov_next");
  });
});

describe("an opened row", () => {
  it("offers to sell on a met rule and to adjust a stale one", () => {
    const out = renderToStaticMarkup(
      <Holding
        row={row({
          status: "hit",
          rules: [
            rule({ id: "a", state: "hit" }),
            rule({ id: "b", rule: "weight_above", level: 10, flag: "cap" }),
          ],
        })}
        open
        onToggle={noop}
        onRetire={noop}
      />,
    );
    expect(out).toContain('aria-expanded="true"');
    expect(out).toContain("journal.cov_sell");
    expect(out).toContain("journal.cov_rewrite");
    expect(out).toContain("journal.cov_adjust");
    expect(out).toContain("journal.cov_flag_cap");
    expect(out.match(/journal\.criteria_retire/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("stays folded until asked", () => {
    const out = renderToStaticMarkup(
      <Holding row={row()} open={false} onToggle={noop} onRetire={noop} />,
    );
    expect(out).toContain('aria-expanded="false"');
    expect(out).not.toContain("journal.cov_add_rule");
  });
});

describe("the drafting question", () => {
  it("asks for what is missing, and every exit one opens the rules form", () => {
    expect(draftKey(row({ status: "none", missing: ["thesis", "price"] }))).toBe(
      "journal.criteria_prompt",
    );
    const thesisOnly = rule({ rule: "thesis", family: "thesis" });
    expect(draftKey(row({ status: "gap", missing: ["thesis"], rules: [rule()] }))).toBe(
      "journal.thesis_prompt",
    );
    expect(
      draftKey(row({ status: "gap", missing: ["price"], rules: [thesisOnly] })),
    ).toBe("journal.price_prompt");
    // A buy zone alone is no exit: the whole set is asked for.
    expect(
      draftKey(
        row({ status: "none", missing: ["price"], rules: [rule({ side: "buy" })] }),
      ),
    ).toBe("journal.criteria_prompt");
    expect(draftKey(row({ rules: [rule(), thesisOnly] }))).toBe("journal.entry_prompt");
  });
});
