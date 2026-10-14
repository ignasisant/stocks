/**
 * Numbers and verdicts as this page prints them. A null in is the caller's
 * "n/a" out — never a zero.
 */

import { type ChipSpec, type Tone, toneOf } from "../../ui/Kpi";
import { parseDay } from "../home/format";
import type { Review, Verdict } from "./types";
import { formatter } from "../../shell/numbers";

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function money(
  value: number | null | undefined,
  currency: string,
  lang: string,
  signed = false,
): string | null {
  if (!finite(value)) return null;
  try {
    return formatter(lang, {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
      signDisplay: signed ? "exceptZero" : "auto",
    }).format(value);
  } catch {
    return `${Math.round(value)} ${currency}`;
  }
}

export function percent(
  value: number | null | undefined,
  lang: string,
  digits = 1,
): string | null {
  if (!finite(value)) return null;
  return formatter(lang, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** A line the copy quotes: as few decimals as it needs (5 %, 0,25 %). */
export function line(value: number, lang: string): string {
  return formatter(lang, { style: "percent", maximumFractionDigits: 2 }).format(value);
}

/** The row's quote currency when it is not the page's; null when it is or is unknown. */
export function foreign(row: { currency: string | null }, base: string): string | null {
  return row.currency && row.currency !== base ? row.currency : null;
}

/** The KPIs a row carries, in display order (`stocks.analysis.review.SHOWN`). */
export const SHOWN = [
  "pe_fwd",
  "growth_pe",
  "fcf_yield",
  "owner_fcf_yield",
  "ev_ebitda",
  "roic",
  "roic_ex_goodwill",
  "op_margin",
  "moat",
  "revenue_cagr",
  "share_dilution",
  "net_debt_ebitda",
  "ev_sales",
  "revenue_growth",
  "fcf_margin",
  "runway_years",
  "pe_ttm",
  "pb",
  "roe",
  "dividend_yield",
  "payout_ratio",
] as const;

/** The few a map dot's tooltip carries: price, price for growth, cash, returns. */
const TIP = [
  "pe_fwd",
  "growth_pe",
  "fcf_yield",
  "roic",
  "op_margin",
  "revenue_growth",
] as const;

/** The tooltip's figures, printed, the ones the feed lacked left out. */
export function tipFigures(
  metrics: Record<string, number | null>,
  lang: string,
): { key: string; value: string }[] {
  return TIP.flatMap((key) => {
    const value = metric(key, metrics[key], lang);
    return value === null ? [] : [{ key, value }];
  });
}

/** The ones the KPI catalog lacks; their words are `review.metric_<key>`. */
export const OWN_LABEL = new Set<string>([
  "growth_pe",
  "owner_fcf_yield",
  "roic_ex_goodwill",
  "revenue_growth",
  "fcf_margin",
  "runway_years",
  "dividend_yield",
  "payout_ratio",
]);

/** The KPIs a row carries, each in its own unit. */
const UNITS: Record<string, "pct" | "x" | "score" | "years"> = {
  pe_fwd: "x",
  pe_ttm: "x",
  pb: "x",
  growth_pe: "x",
  ev_ebitda: "x",
  ev_sales: "x",
  net_debt_ebitda: "x",
  fcf_yield: "pct",
  owner_fcf_yield: "pct",
  roic: "pct",
  roic_ex_goodwill: "pct",
  op_margin: "pct",
  revenue_cagr: "pct",
  share_dilution: "pct",
  revenue_growth: "pct",
  fcf_margin: "pct",
  roe: "pct",
  dividend_yield: "pct",
  payout_ratio: "pct",
  moat: "score",
  runway_years: "years",
};

/** Whether `metric` printed a bare count of years, for the caller to word. */
export const inYears = (key: string) => UNITS[key] === "years";

export function metric(key: string, value: number | null | undefined, lang: string) {
  if (!finite(value)) return null;
  switch (UNITS[key]) {
    case "pct":
      return percent(value, lang);
    case "score":
      return Math.round(value).toString();
    case "years":
      return formatter(lang, { maximumFractionDigits: 1 }).format(value);
    default:
      return `${value.toFixed(1)}x`;
  }
}

/** "9 Oct 2026" — an API calendar day in the reader's locale; junk comes back as is. */
export function longDay(iso: string, lang: string): string {
  const date = parseDay(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat(lang, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function score(value: number | null | undefined): string | null {
  return finite(value) ? Math.round(value).toString() : null;
}

/** The colour a verdict reads in: action to take, or nothing to do. */
export function verdictTone(verdict: Verdict): Tone {
  switch (verdict) {
    case "sell":
    case "pass":
      return "down";
    case "trim":
    case "watch":
    case "bet":
      return "warn";
    case "add":
    case "buy":
      return "up";
    default:
      return "flat";
  }
}

/** The verdicts that ask the reader to do something. */
export const ACTIONS: Verdict[] = ["sell", "trim", "add"];

/** `?add=` as a list, upper-cased, de-duplicated, empties dropped. */
export function parseAdded(raw: string | null): string[] {
  const out: string[] = [];
  for (const part of (raw ?? "").split(",")) {
    const symbol = part.trim().toUpperCase();
    if (symbol && !out.includes(symbol)) out.push(symbol);
  }
  return out;
}

/** What the server accepts in `add`, checked before asking it. */
export const SYMBOL = /^[A-Z0-9][A-Z0-9.\-=^]{0,19}$/;
export const MAX_ADDED = 10;

/** A held name's gain or loss: "+152 € (6,7 %)", the money alone without a
 * cost, the share alone without a price; null when neither is known. */
export function pnl(
  row: { pnl: number | null; pnl_pct: number | null },
  base: string,
  lang: string,
): string | null {
  const amount = money(row.pnl, base, lang, true);
  const share = percent(row.pnl_pct, lang);
  if (amount && share) return `${amount} (${share})`;
  return amount ?? share;
}

/** The gain as a DS chip, green up, red down; null when nothing is known. */
export function pnlChip(
  row: { pnl: number | null; pnl_pct: number | null },
  base: string,
  lang: string,
): ChipSpec | null {
  const text = pnl(row, base, lang);
  return text ? { text, tone: toneOf(row.pnl ?? row.pnl_pct) } : null;
}

/**
 * Whether a read that left names loading on the server is worth asking for
 * again: once per question (`asked` = base and added tickers), never in a loop.
 */
export function askAgain(read: Review, retried: string | null, asked: string): boolean {
  return (read.pending ?? 0) > 0 && retried !== asked;
}
