/**
 * What `/api/v1/review` answers with. Mirrors `Review` / `ReviewRow` in
 * `src/stocks/api/schemas.py`.
 *
 * Verdicts and reasons are keys: the words are the catalog's
 * (`review.verdict_<key>`, `review.reason_<code>`). Every figure that could not
 * be measured is `null` — a name with no fundamentals has no quality score,
 * which is not a score of zero.
 */

export type Verdict =
  | "sell"
  | "trim"
  | "hold"
  | "add"
  | "bet"
  | "core"
  | "cash"
  | "buy"
  | "watch"
  | "pass"
  | "unrated";

export type ReviewRow = {
  ticker: string;
  symbol: string;
  kind: string | null;
  /** Yahoo's sector name, English; null for a fund or a name never profiled. */
  sector: string | null;
  held: boolean;
  verdict: Verdict;
  reasons: string[];
  quality: number | null;
  cheapness: number | null;
  metrics: Record<string, number | null>;
  value: number | null;
  weight: number | null;
  risk_share: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  target_weight: number | null;
  /** Base-currency money to buy (+) or sell (-) to reach the target. */
  delta: number | null;
  /** Extra tax this year if the sale is made, in `plan.tax_currency`. */
  tax: number | null;
  /** First day a buy no longer undoes a loss sold inside the window. */
  buy_after: string | null;
  /** On the watchlist (held or not), starred, and the groups it is filed in. */
  watched: boolean;
  favorite: boolean;
  lists: string[];
};

export type Review = {
  base: string;
  as_of: string;
  total: number | null;
  held: ReviewRow[];
  candidates: ReviewRow[];
  plan: { sells: number; buys: number; tax: number | null; tax_currency: string };
  unpriced: number;
  jurisdiction: string;
  added: string[];
};
