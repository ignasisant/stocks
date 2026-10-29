/**
 * What the ticker page shows for each kind of asset — one table, read by the
 * header, the price card, the chart and the sections below.
 *
 * The page used to draw every symbol as a share: RSI, SMA20 and candles for a
 * money-market fund whose price rises a sliver every day (so its RSI sits in
 * the nineties and the page called cash "overbought"), a position block and an
 * "Analyse" button for an index nobody can buy. Each row here is what that kind
 * is actually read by:
 *
 * - a **share** is read by where its price sits in the year, which way its
 *   trend runs (the 200-day average, 12-1 momentum, its home index), what it
 *   costs against its own history and when it next reports; its RSI and
 *   averages stay on the chart as overlays, where they can be read against
 *   the line rather than as two more figures beside the price;
 * - an **equity fund** by the year's range and its trend — a basket has no
 *   P/E of its own and no results date;
 * - a **coin** by the year's range, its distance from the all-time high and its
 *   trend (no index: a coin has no home market to beat),
 *   and it gets the cycle, positioning and holding cards a share's company
 *   sections would otherwise fill;
 * - a **bond fund** is read by what it pays and how far a rate move pushes it;
 * - a **money-market fund** by its yield against the central bank's rate and
 *   its cost — its chart is a straight line, so no averages and no candles;
 * - a **closed-end fund** by its premium or discount to NAV and its payout;
 * - an **index** by its level in points and its trend; it is followed, not
 *   held.
 *
 * The trend cell is for what has a trend to follow. A bond fund, a
 * money-market fund and a closed-end fund are read by what they pay: a cash
 * fund's line climbs a sliver a day, so it would read "up" forever.
 *
 * `null` — a kind the server did not name — is a share, the page as it was.
 */

import type { AssetKind } from "../../shell/assets";

export type MetricId =
  | "range_52w"
  | "trend"
  | "pe"
  | "next_results"
  | "distribution"
  | "duration"
  | "cash_yield"
  | "policy"
  | "ter"
  | "premium"
  | "cef_distribution"
  | "ath_drawdown";

export type Overlay = "SMA20" | "SMA50" | "SMA200";
export type Marker = "results" | "dividends" | "cycle";

export type Shape = {
  kind: AssetKind;
  /** The cells beside the price, in order. The price itself always leads. */
  metrics: readonly MetricId[];
  overlays: readonly Overlay[];
  /** Whether the line/candles toggle is offered at all. */
  candles: boolean;
  markers: readonly Marker[];
  sections: {
    /** Results, KPI grid, valuation, analysts, moat, insiders, comps, KPI sources. */
    company: boolean;
    /** The fund card (a closed-end fund's is its CEF block). */
    fund: boolean;
    /** The fund card's sector chart and top holdings. */
    fundHoldings: boolean;
    /** A coin's supply, volume and 52-week range. */
    stats: boolean;
    /** Where a coin sits in its cycle: sentiment, Mayer, 200-week, halving. */
    cycle: boolean;
    /** What the perpetual-swap crowd pays to hold it: funding, open interest. */
    positioning: boolean;
    /** The reader's coin against the rest of their crypto and their book. */
    holding: boolean;
  };
  /** Whether a position block and the last-buy line apply. */
  holdable: boolean;
  /** A holding is counted in units, not shares — a coin has no shares. */
  units: boolean;
  /** The analysis question the AI button asks, or null for no button. */
  ai: string | null;
  /** The level is in index points, not money. */
  points: boolean;
  /** Whether the card that overlays it on the indices is offered. */
  compare: boolean;
};

const ALL_AVERAGES: readonly Overlay[] = ["SMA20", "SMA50", "SMA200"];
const SLOW_AVERAGES: readonly Overlay[] = ["SMA50", "SMA200"];
/** Where the price sits, which way it runs, what it costs, when it next reports. */
const MARKET: readonly MetricId[] = ["range_52w", "trend", "pe", "next_results"];
/** A basket or an index: the year's range and which way it runs. */
const FOLLOWED: readonly MetricId[] = ["range_52w", "trend"];

const NO_SECTIONS = {
  company: false,
  fund: false,
  fundHoldings: false,
  stats: false,
  cycle: false,
  positioning: false,
  holding: false,
};
const FUND = { ...NO_SECTIONS, fund: true, fundHoldings: true };

const SHAPES: Record<AssetKind, Shape> = {
  stock: {
    kind: "stock",
    metrics: MARKET,
    overlays: ALL_AVERAGES,
    candles: true,
    markers: ["results", "dividends"],
    sections: { ...NO_SECTIONS, company: true },
    holdable: true,
    units: false,
    ai: "ticker.ai_prompt",
    points: false,
    compare: true,
  },
  equity_fund: {
    kind: "equity_fund",
    metrics: FOLLOWED,
    overlays: ALL_AVERAGES,
    candles: true,
    markers: ["dividends"],
    sections: FUND,
    holdable: true,
    units: false,
    ai: "ticker.ai_prompt_fund",
    points: false,
    compare: true,
  },
  bond_fund: {
    kind: "bond_fund",
    metrics: ["distribution", "duration"],
    overlays: SLOW_AVERAGES,
    candles: false,
    markers: ["dividends"],
    sections: FUND,
    holdable: true,
    units: false,
    ai: "ticker.ai_prompt_fund",
    points: false,
    compare: true,
  },
  money_market: {
    kind: "money_market",
    metrics: ["cash_yield", "policy", "ter"],
    overlays: [],
    candles: false,
    markers: [],
    sections: { ...NO_SECTIONS, fund: true },
    holdable: true,
    units: false,
    ai: "ticker.ai_prompt_cash",
    points: false,
    // A fund that holds its price: its line is the axis.
    compare: false,
  },
  closed_end: {
    kind: "closed_end",
    metrics: ["premium", "cef_distribution"],
    overlays: SLOW_AVERAGES,
    candles: true,
    markers: ["dividends"],
    sections: FUND,
    holdable: true,
    units: false,
    ai: "ticker.ai_prompt_fund",
    points: false,
    compare: true,
  },
  crypto: {
    kind: "crypto",
    // A coin has no earnings to anchor it, so its peak stands in: how far under
    // the all-time high it trades is the line a crypto reader looks at first,
    // beside the year's range. The averages stay on the chart.
    metrics: ["range_52w", "ath_drawdown", "trend"],
    overlays: ALL_AVERAGES,
    candles: true,
    markers: ["cycle"],
    sections: {
      ...NO_SECTIONS,
      stats: true,
      cycle: true,
      positioning: true,
      holding: true,
    },
    holdable: true,
    units: true,
    ai: "ticker.ai_prompt_crypto",
    points: false,
    compare: true,
  },
  index: {
    kind: "index",
    metrics: FOLLOWED,
    overlays: ALL_AVERAGES,
    candles: true,
    markers: [],
    sections: NO_SECTIONS,
    holdable: false,
    units: false,
    ai: null,
    points: true,
    compare: true,
  },
};

export function layout(kind: AssetKind | null): Shape {
  return SHAPES[kind ?? "stock"];
}

/**
 * The kind the page lays out by.
 *
 * The profile's answer when it has one. Without it — an older server, a
 * failed lookup — the two booleans the page always had: a coin, a fund (drawn
 * as an equity fund, the layout that asks least of the fund's data), else a
 * share. `/fund` finding a basket overrules a "stock" verdict too: a catalog
 * fund Yahoo files oddly must not get a column of empty company cards.
 */
export function resolveKind(
  named: AssetKind | null,
  { crypto, fund }: { crypto: boolean; fund: boolean },
): AssetKind {
  if (named && !(named === "stock" && fund)) return named;
  if (crypto) return "crypto";
  if (fund) return "equity_fund";
  return "stock";
}
