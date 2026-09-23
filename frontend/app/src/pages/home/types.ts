/**
 * The `/api/v1` payloads this page reads, transcribed from `api/schemas.py`.
 *
 * `null` is load-bearing in every one of these: an unpriced position has no
 * value, a book with no history has no basket move, a name sitting on its
 * 52-week high has no distance from it. The types keep that distinction so the
 * renderer cannot quietly turn one into a zero.
 */

export type DailyCard = {
  day: string | null;
  headline: string | null;
  bullets: string[];
  focus: string[];
  as_of: string | null;
  lang: string | null;
  /** llm | computed — a computed card is built from triggers, not written. */
  source: string | null;
  action_day: string;
  cutoff_hour: number;
  fresh: boolean;
};

type Mover = { ticker: string; pct: number };

export type Movers = {
  window: string;
  /** Currency `amount` is counted in. */
  base: string;
  gainers: Mover[];
  losers: Mover[];
  /** The whole book over the same window; null when the history misses it. */
  basket: number | null;
  /** The same move in money — what the tile leads with. */
  amount: number | null;
  positions: number;
  /** Positions the basket could not measure: no price, or no FX path. */
  unpriced: number;
  /** Which session these figures are from; off-hours, the last completed one. */
  as_of: string | null;
};

/**
 * Whether a day figure on screen is live, and what to say when it is not.
 *
 * `note` is a catalog key stem, so the wording stays each page's own — the
 * server decides the state, the page decides the sentence.
 */
export type MarketStatus = {
  as_of: string;
  us_open: boolean;
  us_extended: string | null;
  note: string | null;
};

export type Extreme = {
  ticker: string;
  price: number;
  edge: string;
  /** Null means at or beyond the edge — not 0% away from it. */
  distance: number | null;
};

export type Extremes = { extremes: Extreme[] };

export type Summary = {
  base: string;
  /** The book is the example one: every figure below it is invented. */
  demo: boolean;
  cost: number;
  value: number;
  pnl: number;
  pnl_pct: number | null;
  positions: number;
  unpriced: number;
  /**
   * All-time result of closed sales, FIFO-matched, in the reporting currency.
   * Null for a book that has never sold: no sale is not a result of zero.
   * NOT the tax report's realised figure — that one replays under the
   * jurisdiction's own currency and matching rule.
   */
  realized: number | null;
  realized_cost: number | null;
};

export type Performance = {
  base: string;
  start: string | null;
  end: string | null;
  injected: number | null;
  value: number | null;
  twr_cumulative: number | null;
  twr_annualised: number | null;
  irr: number | null;
  missing: string[];
};

export type Position = {
  ticker: string;
  shares: number;
  currency: string;
  cost: number;
  value: number | null;
  /** One share, in `currency` — the market's own quote, not the book's. */
  price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  weight: number | null;
};

export type Positions = { base: string; positions: Position[]; unpriced: number };

export type Transaction = {
  id: number | null;
  date: string;
  ticker: string;
  action: string;
  quantity: number;
  price: number;
  currency: string;
  fee: number;
  note: string;
};

export type Transactions = { total: number; transactions: Transaction[] };

export type CalendarEvent = {
  ticker: string;
  date: string | null;
  days_until: number | null;
};

export type CalendarResult = {
  ticker: string;
  date: string;
  eps_estimate: number | null;
  reported_eps: number | null;
  surprise_pct: number | null;
  /** Null when there was nothing to compare — never False. */
  beat: boolean | null;
};

export type EarningsCalendar = {
  upcoming: CalendarEvent[];
  results: CalendarResult[];
  /** portfolio | favorites | one per watchlist tag; empty sets are left out. */
  groups: Record<string, string[]>;
  skipped: string[];
};

export type WatchlistEntry = {
  ticker: string;
  name: string;
  favorite: boolean;
  tags: string[];
  is_crypto: boolean;
};

export type Watchlist = { entries: WatchlistEntry[] };

export type Quote = {
  ticker: string;
  price: number | null;
  pct: number | null;
  session: string | null;
  as_of: string | null;
  market_open: boolean | null;
};

export type Quotes = { quotes: Quote[]; unavailable: string[] };

/**
 * `/portfolio/history` — one point per day. Every figure is nullable and means
 * it: a day with no injected reference is not a day worth zero.
 */
export type History = {
  base: string;
  window: string;
  points: {
    date: string;
    injected: number | null;
    value: number | null;
    pnl_pct: number | null;
    twr: number | null;
  }[];
  missing: string[];
};

/**
 * One stop on the guided tour, as `/onboarding` reports it.
 *
 * The first-run card reads these for one thing only: where a capability is
 * switched on. `path` is the page's URL path — `""` is the default page, and
 * `null` means the target is not a page at all (the assistant is a drawer).
 * No copy crosses the wire; the step names its catalog keys and the client
 * already has the catalog.
 */
export type TourStep = {
  id: string;
  icon: string;
  path: string | null;
  params: Record<string, string>;
  /** Registry-shaped state the step wants on arrival (`profile_tab`, …). */
  session: Record<string, string>;
  gated: boolean;
  /** Null for a step that is nothing to switch on — a page is a page. */
  done: boolean | null;
  title_key: string;
  body_key: string;
  cta_key: string | null;
};

/**
 * `/onboarding` — the registry behind the tour, the what's-new modal and this
 * page's first-run card, in one call because they are one account state.
 *
 * `news` is left out of this transcription on purpose: the cards are the
 * shell's modal (`shell/Tour.tsx`), and a type here would be a second, drifting
 * copy of something this page never draws.
 */
export type Onboarding = {
  version: string;
  seen_version: string | null;
  tour_done: boolean;
  steps: TourStep[];
  /** login | import | ai | telegram — the four connectable capabilities. */
  setup: Record<string, boolean>;
  /** search | ask | watchlist — the three that need no setup at all. */
  explore: Record<string, boolean>;
};
