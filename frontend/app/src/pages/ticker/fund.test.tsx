/**
 * A listed closed-end fund draws the fund card, not blank company tiles.
 *
 * What these pin is the part the feedback was about: every figure says where
 * it was read, an empty one says which sources were asked instead of printing
 * a bare dash, and a filed figure that disagrees with Yahoo's is shown as a
 * disagreement — never resolved silently in favour of either.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { FundSection } from "./Sections";
import type { ClosedEnd, Fund, SourceCheck, SourcedFigure } from "./types";

const figure = (
  value: number | null,
  source: string | null,
  as_of: string | null = "2026-09-28",
  tried: string[] = [],
): SourcedFigure => ({ value, source, as_of, tried });

const base: Fund = {
  ticker: "PDI",
  is_fund: true,
  name: "PIMCO Dynamic Income Fund",
  quote_type: "CEF",
  currency: "USD",
  category: null,
  family: null,
  expense_ratio: 0.0379,
  aum: 7.5e9,
  dividend_yield: 0.189,
  turnover: null,
  description: "",
  legal_type: "Closed-End Fund",
  bond_duration: null,
  is_bond_fund: true,
  holdings: [],
  disclosed_weight: 0,
  sectors: [],
  asset_classes: [["Bonds", 0.9]],
};

const navCheck: SourceCheck = {
  metric: "nav",
  as_of: "2026-08-31",
  official: 15.6,
  official_source: "edgar_xbrl",
  market: 16.4,
  market_source: "yahoo_nav",
  agree: false,
  tolerance: 0.01,
};

const closedEnd: ClosedEnd = {
  nav_symbol: "XPDIX",
  nav: figure(15.0, "yahoo_nav"),
  price: figure(13.9, "yahoo"),
  premium: figure(-0.0733, "yahoo_nav"),
  distribution_rate: figure(0.189, "yahoo"),
  expense_ratio: figure(0.0379, "edgar_xbrl", "2026-09-24"),
  net_assets: figure(null, null, null, ["edgar_nport"]),
  total_assets: figure(null, null, null, ["edgar_nport"]),
  leverage: figure(null, null, null, ["edgar_nport"]),
  holdings_count: null,
  holdings_as_of: null,
  checks: [navCheck],
};

const render = (fund: Fund) => renderToStaticMarkup(<FundSection fund={fund} />);

describe("a closed-end fund", () => {
  it("draws its own tiles and caption, not an ETF's", () => {
    const html = render({ ...base, closed_end: closedEnd });
    expect(html).toContain("ticker.cef_kind");
    expect(html).toContain("ticker.cef_nav");
    expect(html).toContain("ticker.cef_premium");
    expect(html).toContain("ticker.cef_caption");
    expect(html).not.toContain("ticker.fund_turnover");
    expect(html).not.toContain("ticker.fund_caption");
  });

  it("names the source of every figure it has", () => {
    const html = render({ ...base, closed_end: closedEnd });
    expect(html).toContain("ticker.cef_src_yahoo_nav");
    expect(html).toContain("ticker.cef_src_edgar_xbrl");
  });

  it("says which sources were asked for a figure nobody had", () => {
    const html = render({ ...base, closed_end: closedEnd });
    expect(html).toContain("ticker.cef_tried");
  });

  it("flags a disagreement between EDGAR and Yahoo", () => {
    const html = render({ ...base, closed_end: closedEnd });
    expect(html).toContain("tk-banner-warn");
    expect(html).toContain("ticker.cef_check_off");
    expect(html).not.toContain("ticker.cef_check_ok");
  });

  it("tells an agreement from a check nobody could run", () => {
    const agree = render({
      ...base,
      closed_end: {
        ...closedEnd,
        checks: [{ ...navCheck, market: 15.6, agree: true }],
      },
    });
    expect(agree).toContain("ticker.cef_check_ok");
    expect(agree).not.toContain("tk-banner-warn");

    const unchecked = render({
      ...base,
      closed_end: {
        ...closedEnd,
        checks: [{ ...navCheck, market: null, agree: null }],
      },
    });
    expect(unchecked).toContain("ticker.cef_check_none");

    const nothing = render({ ...base, closed_end: { ...closedEnd, checks: [] } });
    expect(nothing).toContain("ticker.cef_check_absent");
  });
});

describe("an ordinary fund", () => {
  it("keeps the ETF tiles", () => {
    const html = render({ ...base, quote_type: "ETF", closed_end: null });
    expect(html).toContain("ticker.fund_turnover");
    expect(html).toContain("ticker.fund_caption");
    expect(html).not.toContain("ticker.cef_");
  });
});

describe("a money-market fund", () => {
  const cash: Fund = {
    ...base,
    ticker: "XEON.DE",
    name: "Xtrackers II EUR Overnight Rate Swap UCITS ETF",
    quote_type: "ETF",
    is_bond_fund: false,
    asset_classes: [["Cash", 1]],
    sectors: [["Financial Services", 1]],
    holdings: [{ symbol: "", name: "Bund 2027", weight: 0.2 }],
    disclosed_weight: 0.2,
    closed_end: null,
  };

  it("leaves out the mix, the sectors and the holdings", () => {
    const html = renderToStaticMarkup(<FundSection fund={cash} holdings={false} />);
    // A swap-backed basket of deposits has no sector story and no top ten.
    expect(html).not.toContain("Bund 2027");
    expect(html).not.toContain("ticker.fund_no_holdings");
    expect(html).toContain("ticker.cash_caption");
    expect(html).not.toContain("ticker.fund_caption");
  });

  it("keeps them for any other fund", () => {
    const html = renderToStaticMarkup(<FundSection fund={cash} />);
    expect(html).toContain("Bund 2027");
    expect(html).toContain("ticker.fund_caption");
  });
});
