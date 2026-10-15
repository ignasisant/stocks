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
  /** Yahoo's country name, English; null when never profiled. */
  country: string | null;
  /** Quote currency (pence folded to pounds); null when never profiled. */
  currency: string | null;
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
  /** What an add would take beyond `delta` that the sales do not pay for. */
  new_money?: number | null;
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
  /** No import of its own (demo rows do not count): nothing was judged, and
   * the page draws `/review/preview` behind the import wall. */
  locked?: boolean;
  total: number | null;
  held: ReviewRow[];
  candidates: ReviewRow[];
  plan: {
    sells: number;
    buys: number;
    tax: number | null;
    tax_currency: string;
    /** The rows' `new_money` added up: adds that wait for new cash. */
    new_money?: number;
  };
  unpriced: number;
  /** Names whose figures missed the server's time budget; read unrated. */
  pending?: number;
  jurisdiction: string;
  /** "chosen" when the reader picked a residence; else how it was assumed. */
  tax_status: string;
  added: string[];
  /** The weights the verdicts were drawn at; some scale with the book. */
  lines?: ReviewLines | null;
  /** What the page says about the book as a whole (`review.note_<key>`). */
  notes: ReviewNote[];
};

export type ReviewLines = {
  /** From here one company is a concentration; null with too few. */
  concentrated: number | null;
  small: number;
  add_to: number;
  sector: number;
};

export type ReviewNote = {
  key:
    | "few_names"
    | "sector_heavy"
    | "country_heavy"
    | "currency_heavy"
    | "fund_core"
    | "cash_heavy"
    | "crypto_heavy"
    | "tax_offset"
    | string;
  count: number | null;
  /** Yahoo's sector name, English. */
  sector: string | null;
  /** Yahoo's country name, English. */
  country: string | null;
  currency: string | null;
  weight: number | null;
  /** Money in `plan.tax_currency` (the saving, for `tax_offset`). */
  amount: number | null;
  tickers: string[];
  /** ISO day a repurchase stops undoing the loss. */
  day: string | null;
};
