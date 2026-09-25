/**
 * The shapes `/pulse`, `/pulse/book` and `/pulse/tables` actually send.
 *
 * Mirrors `src/stocks/api/schemas.py`. Every figure the server could not
 * compute arrives as `null` rather than as a zero, and that difference is the
 * whole reason these are `| null` and not optional: a book the market cannot
 * move and a book nobody could measure are different claims.
 */

type PulseComponent = {
  /** momentum | breadth | volatility | term | credit | haven | junk | global_risk */
  key: string;
  /** This input's own 0-100 score. */
  score: number | null;
  /** What it actually read, in its own units — which differ per input. */
  raw: number | null;
  /**
   * `raw` already formatted in its own units (+4.2%, 15.2, 1.19…) by the
   * Python registry that knows them. Null exactly when `raw` is.
   */
  text: string | null;
  /** The same score 21 sessions ago; null when history is short. */
  then: number | null;
};

type PulsePoint = { date: string; score: number };

/**
 * How many of a set are in an uptrend, and how many could be read at all.
 *
 * Both numbers, never a percentage: three of four and thirty of forty are the
 * same fraction and not the same statement, and a denominator that shrank
 * because a source failed has to stay visible.
 */
type Breadth = {
  hits: number;
  total: number;
  /** Sessions in the moving average — the note says which one this counted. */
  window: number;
};

export type Pulse = {
  score: number | null;
  /** A band KEY, not prose: stress | caution | neutral | appetite | euphoria | unknown. */
  regime: string;
  as_of: string | null;
  /** Consecutive sessions the score has held this band. */
  run: number;
  components: PulseComponent[];
  /** Inputs that could not be built — named so the page can say what is absent. */
  missing: string[];
  history: PulsePoint[];
  /**
   * Three readings the composite does not contain, which the page states
   * beside it. Market-wide, all of them: the stock/bond correlation here is
   * SPY against TLT, and `/pulse/book`'s `bond_correlation` is the reader's
   * own basket against the same bond — a different pair, answering a different
   * question, and neither is inferable from the other.
   */
  breadth_indices: Breadth | null;
  breadth_sectors: Breadth | null;
  stock_bond_correlation: number | null;
  /** The same correlation a quarter ago; null when history is short. */
  stock_bond_correlation_then: number | null;
  /** Server clock at answer time, `YYYY-MM-DD HH:MM UTC` — the "loaded" caption. */
  loaded_at: string | null;
  /**
   * rate_limited | offline | no_data — set when the composite could not be
   * built at all. The server answers 200 with this rather than an error, so
   * every block keeps its heading and says which source died.
   */
  unavailable?: string | null;
};

/** One secondary beta: duration (TLT), credit (HYG) or emerging markets (EEM). */
type BookBeta = {
  /** duration | credit | em — the suffix of `sentiment.beta_<key>`. */
  key: string;
  ticker: string;
  beta: number | null;
  rolling: number | null;
  rolling_then: number | null;
};

export type PulseBook = {
  base: string;
  /** Beta over the whole window — the headline. */
  beta: number | null;
  /** The 60-session rolling beta, latest value. */
  beta_rolling: number | null;
  /** The same rolling beta a quarter ago. Compares with `beta_rolling`, never with `beta`. */
  beta_rolling_then: number | null;
  /** amplify | track | cushion */
  stance: string | null;
  bond_correlation: number | null;
  bond_correlation_then: number | null;
  usd_share: number | null;
  fx_drag: number | null;
  currency_weights: Record<string, number>;
  rotation_capture: number | null;
  sector_tilt: Record<string, number>;
  /** The three betas beside the equity one, on the same EUR-rebased returns. */
  betas: BookBeta[];
  /**
   * The book's whole sector split, largest first — including buckets no sector
   * ETF tracks. What "your three largest sectors" is chosen from.
   */
  sector_weights?: Record<string, number>;
  /**
   * rate_limited | offline | no_data — why the price-derived figures are null.
   * The weights need no feed and still arrive, so this is a partial card, not
   * an empty one.
   */
  unavailable?: string | null;
};

export type TrendRow = {
  /** Series id: a ticker, a FRED id, or an area code. What a label is looked up by. */
  key: string;
  /** The source's own name, unlocalized. */
  name: string;
  value: number | null;
  /**
   * Change per horizon (week | month | quarter | year), in the block's `unit`.
   * A horizon the series is too short for is ABSENT, not null — that is "no
   * data", which is a different claim from "no change".
   */
  changes: Record<string, number>;
  /** Last 90 observations, oldest first. */
  spark: number[];
  /** up | turning_up | turning_down | down | unknown | stale, or null for no label. */
  state: string | null;
  percentile: number | null;
  percentile_then: number | null;
  /**
   * Which direction is the good news: +1 a rise, -1 a fall, 0 neither. NOT the
   * sign of the change — a widening spread and a falling index are both bad.
   */
  welcome: number;
  /** The publisher dropped this one: dim the row, keep it visible. */
  stale: boolean;
  /** Share of the reader's own book this row stands for, where that means something. */
  weight: number | null;
  /** The index's own share of the same sector, so the two can be compared. */
  spy_weight: number | null;
  /** Inflation with food and energy taken out: a second level, not a change. */
  core: number | null;
  /** Date of the row's last observation; what a stale gauge's note quotes. */
  as_of?: string | null;
};

export type TrendBlock = {
  /** indices | gauges | rates | inflation | rotation | cross */
  block: string;
  /** How to read `changes`: percent (a fraction), basis_points, or points. */
  unit: string;
  rows: TrendRow[];
  /** rate_limited | offline | no_data — why the block is empty. */
  unavailable: string | null;
  /** Rows the block is configured to carry: the tab badge, even while it is down. */
  expected?: number | null;
};

export type TrendTables = { blocks: TrendBlock[] };
