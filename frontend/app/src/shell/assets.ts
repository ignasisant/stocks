/**
 * What kind of thing a symbol is, in words — `stocks.data.asset_kind`.
 *
 * The search box finds shares, funds, coins and indices alike, and a money-market
 * fund read as a share is how a cash account came to be called "overbought".
 * The server names the kind; this table is what the page and the search box
 * say about it: a short label, and one line on what it is and what to read.
 *
 * `fund` is the search box's answer for a fund nobody has opened yet — it
 * knows it is a fund, not yet which kind, and a vague pill beats a wrong one.
 * It has a label and no line: the ticker page always knows the exact kind.
 */

export type AssetKind =
  | "stock"
  | "equity_fund"
  | "bond_fund"
  | "money_market"
  | "closed_end"
  | "crypto"
  | "index";

export const ASSET_KINDS: readonly AssetKind[] = [
  "stock",
  "equity_fund",
  "bond_fund",
  "money_market",
  "closed_end",
  "crypto",
  "index",
];

/** Literal keys, so the catalog scan (`test_frontend_i18n_keys.py`) sees every one. */
export const ASSETS: Record<AssetKind | "fund", { label: string; help?: string }> = {
  stock: { label: "ticker.asset_stock", help: "ticker.asset_stock_line" },
  equity_fund: {
    label: "ticker.asset_equity_fund",
    help: "ticker.asset_equity_fund_line",
  },
  bond_fund: { label: "ticker.asset_bond_fund", help: "ticker.asset_bond_fund_line" },
  money_market: {
    label: "ticker.asset_money_market",
    help: "ticker.asset_money_market_line",
  },
  closed_end: {
    label: "ticker.asset_closed_end",
    help: "ticker.asset_closed_end_line",
  },
  crypto: { label: "ticker.asset_crypto", help: "ticker.asset_crypto_line" },
  index: { label: "ticker.asset_index", help: "ticker.asset_index_line" },
  fund: { label: "watchlist.kind_fund" },
};

/** A kind the server named, or null for anything this build has no entry for. */
export function assetKind(value: string | null | undefined): AssetKind | null {
  return value && (ASSET_KINDS as readonly string[]).includes(value)
    ? (value as AssetKind)
    : null;
}

/** The label key for a search row or a header, or null to draw no label. */
export function assetLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return value in ASSETS ? ASSETS[value as keyof typeof ASSETS].label : null;
}
