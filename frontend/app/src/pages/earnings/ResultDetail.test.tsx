/**
 * The result dialog draws what the Streamlit one draws, from the same payload.
 *
 * Two things go wrong silently here. A section that should be there is not —
 * the React dialog shipped for months with only the EPS tiles — and a figure
 * prints in the wrong unit, because the API sends ratios as fractions and the
 * surprise as a percentage. So these render the breakdown from a fixed payload
 * and look for each section and for a few figures in their printed form.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key: the assertions name the keys the Streamlit dialog uses.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CalendarResult, QuarterFigures, ResultDetailData } from "./data";
import { money, pct, quarterLabel, signedFrac } from "./format";
import { Breakdown } from "./ResultDetail";

const t = (key: string) => key;

const printed: CalendarResult = {
  ticker: "MSFT",
  date: "2026-07-30",
  eps_estimate: 2.2,
  reported_eps: 2.4,
  surprise_pct: 9.09,
  beat: true,
};

const quarter = (end: string, revenue: number): QuarterFigures => ({
  end,
  revenue,
  gross_profit: revenue * 0.7,
  operating_income: revenue * 0.4,
  net_income: revenue * 0.25,
  pretax_income: revenue * 0.3,
  tax_provision: revenue * 0.05,
  rnd: revenue * 0.1,
  diluted_eps: 2.0,
  diluted_shares: 7.4e9,
  gross_margin: 0.7,
  operating_margin: 0.4,
  net_margin: 0.25,
  rnd_intensity: 0.1,
  tax_rate: 0.1667,
  revenue_yoy: 0.2,
  revenue_qoq: 0.05,
});

const payload = (over: Partial<ResultDetailData> = {}): ResultDetailData => ({
  ticker: "MSFT",
  name: "Microsoft",
  logo: null,
  date: "2026-07-30",
  result: printed,
  price_reaction: 4.5,
  quarter_state: "matched",
  currency: "USD",
  currency_prefix: "$",
  breakdown: {
    quarter: quarter("2026-06-30", 76.4e9),
    revenue_ttm: 281.7e9,
    net_income_yoy: 0.24,
    shares_yoy: -0.01,
    gross_margin_bps: 120,
    operating_margin_bps: -35,
    net_margin_bps: null,
  },
  trend: [quarter("2026-06-30", 76.4e9), quarter("2026-03-31", 70.1e9)],
  eps_gaap_gap: 0.4,
  history: [
    printed,
    { ...printed, date: "2026-04-28", surprise_pct: -3.1, beat: false },
  ],
  outlook: {
    period: "+1q",
    eps_avg: 3.1,
    eps_low: 2.9,
    eps_high: 3.3,
    eps_growth: 0.12,
    eps_analysts: 28,
    rev_avg: 80e9,
    rev_low: 78e9,
    rev_high: 82e9,
    rev_growth: 0.15,
    rev_analysts: 30,
    currency: "USD",
    currency_prefix: "$",
  },
  outlook_periods: [],
  unavailable: false,
  ...over,
});

const draw = (data: ResultDetailData) =>
  renderToStaticMarkup(<Breakdown data={data} printed={printed} />);

describe("the breakdown", () => {
  it("draws all five sections for a filed quarter", () => {
    const html = draw(payload());
    for (const key of [
      "earnings.sec_revenue",
      "earnings.sec_margins",
      "earnings.sec_gaap",
      "earnings.sec_eps",
      "earnings.sec_outlook",
    ]) {
      expect(html).toContain(key);
    }
    expect(html).not.toContain("earnings.quarter_pending");
  });

  it("prints money compact and behind the statement's currency", () => {
    const html = draw(payload());
    expect(html).toContain("$76.40B");
    expect(html).toContain("$281.70B");
  });

  it("colours the share count the other way round: fewer shares is good", () => {
    const html = draw(payload());
    // -1.0% YoY on shares is a buyback, so it wears the green class.
    expect(html).toMatch(/earn-verdict earn-up">earnings\.chip_yoy/);
  });

  it("keeps the EPS record and says why the rest is missing when pending", () => {
    const html = draw(payload({ quarter_state: "pending", breakdown: null }));
    expect(html).not.toContain("earnings.sec_revenue");
    expect(html).toContain("earnings.sec_eps");
    expect(html).toContain("earnings.quarter_pending");
  });

  it("tells no statements apart from not-yet-filed", () => {
    const html = draw(payload({ quarter_state: "none", breakdown: null }));
    expect(html).toContain("earnings.no_quarter_data");
  });

  it("says the data is unavailable rather than claiming there is none", () => {
    const html = draw(
      payload({ unavailable: true, breakdown: null, quarter_state: "none" }),
    );
    expect(html).toContain("common.data_unavailable");
    expect(html).not.toContain("earnings.no_quarter_data");
  });

  it("drops the outlook when nobody covers the name", () => {
    expect(draw(payload({ outlook: null }))).not.toContain("earnings.sec_outlook");
  });
});

describe("the formatters", () => {
  it("compacts money the way earnings_ui._money does", () => {
    expect(money(81.6e9, "$")).toBe("$81.60B");
    expect(money(1.24e12, "€")).toBe("€1.24T");
    expect(money(950, "")).toBe("950");
    expect(money(null, "$")).toBe("—");
  });

  it("reads ratios as fractions", () => {
    expect(pct(0.183)).toBe("18.3%");
    expect(signedFrac(0.052)).toBe("+5.2%");
    expect(signedFrac(-0.02)).toBe("-2.0%");
  });

  it("tags a quarter by its end month", () => {
    expect(quarterLabel("2026-06-30", t)).toBe("earnings.mon_6 26");
  });
});
