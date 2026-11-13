/**
 * The read at the top of a company page: each line says "loading" until its
 * card answers, then takes that card's answer and tone, and links to the
 * section that holds it.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReadingSection } from "./Reading";
import type { Analysts, Insiders, Moat } from "./types";

type Props = Parameters<typeof ReadingSection>[0];

const base: Props = {
  trend: null,
  valuation: null,
  events: [],
  quote: null,
  metrics: undefined,
  analysts: undefined,
  insiders: undefined,
  moat: undefined,
};

const render = (props: Partial<Props> = {}) =>
  renderToStaticMarkup(<ReadingSection {...base} {...props} />);

const moat: Moat = {
  ticker: "AAPL",
  score: 8,
  rating: "wide",
  rating_key: "ticker.moat_rating_wide",
  rating_tone: "green",
  years: 5,
  pillars: [],
};

const analysts = {
  ticker: "AAPL",
  covered: true,
  rating: "buy",
  rating_mean: 1.8,
  targets: { upside_median: 0.12 },
} as unknown as Analysts;

const summary = {
  window_days: 90,
  buy_count: 3,
  sell_count: 0,
  buy_shares: 3000,
  sell_shares: 0,
  buy_value: 500000,
  sell_value: 0,
  buyers: 3,
  sellers: 0,
  net_value: 500000,
  cluster_buy: true,
};

const insiders: Insiders = {
  ticker: "AAPL",
  source: "sec",
  summary,
  trades: [],
  sec_filer: true,
};

describe("ReadingSection", () => {
  it("says loading for every card that has not answered", () => {
    const html = render();
    expect(html.match(/ticker\.read_pending/g)).toHaveLength(3);
  });

  it("links each line to the section that holds it", () => {
    const html = render();
    expect(html).toContain('href="#tk-s-business"');
    expect(html).toContain('href="#tk-s-valuation"');
    expect(html).toContain('href="#tk-s-opinions"');
    expect(html).toContain('href="#tk-s-price"');
  });

  it("takes the moat's band and tone", () => {
    const html = render({ moat });
    expect(html).toContain("ticker.read_moat");
    expect(html).toContain("tk-signal-dot ag-tone-up");
  });

  it("gives the street's rating and the median target", () => {
    const html = render({ analysts });
    expect(html).toContain("ticker.analysts_buy");
    expect(html).toContain("ticker.read_target");
  });

  it("says so when no analyst covers the name", () => {
    const html = render({ analysts: { ...analysts, covered: false } });
    expect(html).toContain("ticker.read_uncovered");
  });

  it("marks a cluster of insider buyers, and only that, as a signal", () => {
    expect(render({ insiders })).toContain("ticker.read_insiders_cluster");
    const selling = render({
      insiders: {
        ...insiders,
        summary: { ...summary, cluster_buy: false, sell_count: 4, net_value: -1 },
      },
    });
    expect(selling).toContain("ticker.read_insiders_selling");
    // Every other line here is flat with no data, so any "up" dot is theirs.
    expect(render({ insiders })).toContain("ag-tone-up");
    expect(selling).not.toContain("ag-tone-up");
  });

  it("tells a market nobody files for from a quiet one", () => {
    expect(render({ insiders: { ...insiders, source: null } })).toContain(
      "ticker.read_insiders_none",
    );
    expect(
      render({
        insiders: {
          ...insiders,
          summary: { ...summary, cluster_buy: false, buy_count: 0, net_value: 0 },
        },
      }),
    ).toContain("ticker.read_insiders_quiet");
  });

  it("draws nothing pending once every card has answered, even with nothing", () => {
    const html = render({ metrics: null, analysts: null, insiders: null, moat: null });
    expect(html).not.toContain("ticker.read_pending");
  });
});
