/**
 * The plan tab: which parts it draws for a given stored plan.
 *
 * Rendered with no catalog loaded, so every string is its key — the question
 * is what the form shows, not its wording.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { checkFigure, PlanForm, type InvestorPlan } from "./Plan";

const EMPTY: InvestorPlan = {
  mix: null,
  limits: { max_position_pct: null, max_sector_pct: null, max_speculative_pct: null },
  contribution: null,
  reserve: null,
  cash: null,
  set: false,
  actual: {},
  currency: "EUR",
  next_contribution: null,
  cash_stale_days: null,
};

const draw = (over: Partial<InvestorPlan> = {}) =>
  renderToStaticMarkup(<PlanForm stored={{ ...EMPTY, ...over }} />);

const MIX = {
  targets: { stocks: 60, equity_funds: 30, bonds: 0, cash: 10, crypto: 0 },
  band_pp: 5,
};

describe("the plan tab", () => {
  it("offers every bucket and says no mix is set before one is", () => {
    const html = draw();
    for (const bucket of ["stocks", "equity_funds", "bonds", "cash", "crypto"])
      expect(html).toContain(`profile.plan_bucket_${bucket}`);
    expect(html).toContain("profile.plan_mix_none");
    expect(html).not.toContain("pl-bar");
  });

  it("shows the app's own line where a limit is blank", () => {
    const html = draw();
    expect(html).toContain('placeholder="profile.plan_app_line"');
    expect(html).toContain('placeholder="40"');
    expect(html).toContain('placeholder="3"');
  });

  it("draws today's share beside each target once the book is priced", () => {
    const html = draw({
      mix: MIX,
      set: true,
      actual: { stocks: 75, equity_funds: 20, bonds: 0, cash: 5, crypto: 0 },
    });
    expect(html.match(/class="pl-bar"/g)).toHaveLength(5);
    expect(html).toContain("profile.plan_mix_whole");
    // Stocks 75 against 60 and funds 20 against 30 are past the 5-point band;
    // cash 5 against 10 is on it.
    expect(html).toContain("pl-warn");
    expect(html).not.toContain("profile.plan_sum_inside");
  });

  it("calls a book on its targets inside the band", () => {
    const html = draw({
      mix: MIX,
      set: true,
      actual: { stocks: 62, equity_funds: 28, bonds: 0, cash: 10, crypto: 0 },
    });
    expect(html).toContain("profile.plan_sum_inside");
    expect(html).not.toContain("pl-warn");
  });

  it("keeps the schedule fields shut until there is an amount", () => {
    expect(draw()).toMatch(/aria-label="profile.plan_every"[^>]*disabled/);
    const html = draw({
      contribution: { amount: 500, every: "monthly", day: 5 },
      next_contribution: "2026-11-05",
    });
    expect(html).not.toMatch(/aria-label="profile.plan_every"[^>]*disabled/);
    expect(html).toContain('value="500"');
  });

  it("dates the stated cash and asks again once it is old", () => {
    expect(draw()).toMatch(/aria-label="profile.plan_rate"[^>]*disabled/);
    expect(draw()).not.toContain("profile.plan_cash_as_of");
    const cash = { investable: 4000, cushion: 9000, rate_pct: 2, as_of: "2026-10-01" };
    const fresh = draw({ cash });
    expect(fresh).toContain('value="4000"');
    expect(fresh).toContain('value="9000"');
    expect(fresh).toContain("profile.plan_cash_as_of");
    expect(fresh).not.toContain("pl-warn");
    const old = draw({ cash: { ...cash, as_of: "2026-07-01" }, cash_stale_days: 121 });
    expect(old).toContain("profile.plan_cash_stale");
    expect(old).toContain("pl-sum-off");
    expect(old).toContain("pl-warn");
  });
});

describe("a figure field's text", () => {
  it("is blank, a figure, or the reason it is neither", () => {
    expect(checkFigure("  ", { max: 100 })).toEqual({ ok: true, value: null });
    expect(checkFigure("12,5", { max: 100 })).toEqual({ ok: true, value: 12.5 });
    expect(checkFigure("dqwdq", { max: 100 })).toEqual({ ok: false, error: "number" });
    expect(checkFigure("12abc", { max: 100 })).toEqual({ ok: false, error: "number" });
    expect(checkFigure("1e3", { max: 100 })).toEqual({ ok: false, error: "number" });
    expect(checkFigure("140", { max: 100 })).toEqual({ ok: false, error: "range" });
    expect(checkFigure("-3", { max: 100 })).toEqual({ ok: false, error: "range" });
  });

  it("holds a day to whole numbers and a cap to more than nothing", () => {
    const day = { min: 1, max: 28, whole: true };
    expect(checkFigure("15", day)).toEqual({ ok: true, value: 15 });
    expect(checkFigure("2.5", day)).toEqual({ ok: false, error: "whole" });
    expect(checkFigure("31", day)).toEqual({ ok: false, error: "range" });
    expect(checkFigure("0", { max: 100, above: true })).toEqual({
      ok: false,
      error: "above",
    });
    expect(checkFigure("0.5", { max: 100, above: true })).toEqual({
      ok: true,
      value: 0.5,
    });
  });

  it("leaves the day without a percent sign", () => {
    const html = draw({
      contribution: { amount: 300, every: "monthly", day: 5 },
      set: true,
    });
    expect(html).toMatch(/aria-label="profile.plan_day"[^>]*\/><\/span>/);
  });
});
