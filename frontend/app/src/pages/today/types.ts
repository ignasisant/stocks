/**
 * `GET/POST /today`, transcribed from `api/schemas.py` (`TodayCard` and the
 * models under it). The personal half is the same `DailyCard` Home's teaser
 * reads; the market half is the read every account shares.
 *
 * As on Home, `null` means "not known" and never zero: a sector whose month
 * could not be computed has no figure, and the page prints none.
 */

import type { Line } from "../../chat/chart";
import type { DailyCard } from "../home/types";

/** One computed line of a Today section. */
export type TodayRow = {
  /** `news:NVDA:1a2b3c4d`, `insider:NVDA`, `compare:NVDA`. */
  key: string;
  /** news | filing | results | insider | compare. */
  kind: string;
  line: string;
  tickers: string[];
  /** yahoo | 8k | sec | bafin | computed — where it was read. */
  source: string;
  /** The article or filing; empty when none. */
  url: string;
  /** ISO day it is from; empty when undated. */
  date: string;
  /** The figures behind the line; for a comparison see `CompareData`. */
  data: Record<string, number | string | boolean | null>;
};

type TodaySectionId = "news" | "insiders" | "compare";

export type TodaySection = {
  id: TodaySectionId;
  title: string;
  rows: TodayRow[];
  /** The model's one remark on the section; empty when none. */
  note: string;
  /** Sources that did not answer: yahoo, edgar, sec, bafin, prices, review. */
  missing: string[];
};

export type MarketLine = {
  topic: "trend" | "sector" | "rates" | "macro" | "crypto";
  line: string;
};

type MarketRate = {
  key: "us10y" | "curve_2s10s" | "hy_spread" | "policy_fed" | "policy_ecb" | string;
  value: number;
  /** Change over a month of sessions, basis points. */
  change_bp: number | null;
};

type MarketBank = {
  bank: "fed" | "ecb";
  rate: number | null;
  last_move_bp: number | null;
  last_date: string | null;
  moved_on: string | null;
  next_date: string | null;
  /** Days to the next decision; 0 is today. */
  days: number | null;
};

export type MarketSector = {
  ticker: string;
  /** English sector name, the `sentiment.sector_*` key's stem. */
  name: string;
  /** 5-session excess over SPY, %. */
  week: number | null;
  /** 21-session excess over SPY, %. */
  month: number | null;
};

export type MarketCard = {
  /** The last US session the figures close on. */
  session: string;
  built_at: number;
  lang: string;
  source: "llm" | "computed";
  headline: string;
  lines: MarketLine[];
  regime: {
    score: number;
    key: string;
    run: number;
    score_month: number | null;
  } | null;
  breadth: {
    indices_hits: number;
    indices_total: number;
    sectors_hits: number;
    sectors_total: number;
  } | null;
  rates: MarketRate[];
  banks: MarketBank[];
  /** Best month first. */
  sectors: MarketSector[];
  inflation: {
    area: string;
    period: string;
    headline: number;
    core: number | null;
    momentum: number | null;
  }[];
  crypto: {
    fear_greed: number | null;
    fear_greed_week: number | null;
    btc_dominance: number | null;
  } | null;
  index: {
    name: string;
    day: number | null;
    week: number | null;
    month: number | null;
  } | null;
  missing: string[];
};

/** The personal card as Today reads it: Home's, plus the computed sections. */
export type PersonalCard = DailyCard & {
  today?: TodaySection[];
  /** empty | fund_only | crypto_only | concentrated | dividend | mixed. */
  shape?: string;
};

export type TodayCard = {
  action_day: string;
  cutoff_hour: number;
  /** Null until the first morning's read exists. */
  market: MarketCard | null;
  /** Older than the last session; a newer read is on its way. */
  market_stale: boolean;
  /** Null for a guest. */
  personal: PersonalCard | null;
};

/** `GET /today/book`: the book against an index over a window, as growth. */
export type BookCompare = {
  range: string;
  index: string;
  chart: Line[];
  /** The first day drawn, when the book is younger than the window. */
  since?: string | null;
};
