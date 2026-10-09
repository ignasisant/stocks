/**
 * Numbers and verdicts as this page prints them. A null in is the caller's
 * "n/a" out — never a zero.
 */

import { type ChipSpec, type Tone, toneOf } from "../../ui/Kpi";
import type { Verdict } from "./types";

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
    return new Intl.NumberFormat(lang, {
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
  return new Intl.NumberFormat(lang, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** The KPIs a row carries, in display order (`stocks.analysis.review.SHOWN`). */
export const SHOWN = [
  "pe_fwd",
  "fcf_yield",
  "owner_fcf_yield",
  "ev_ebitda",
  "roic",
  "op_margin",
  "moat",
  "revenue_cagr",
  "share_dilution",
  "net_debt_ebitda",
  "ev_sales",
  "revenue_growth",
  "fcf_margin",
  "runway_years",
] as const;

/** The ones the KPI catalog lacks; their words are `review.metric_<key>`. */
export const OWN_LABEL = new Set<string>([
  "owner_fcf_yield",
  "revenue_growth",
  "fcf_margin",
  "runway_years",
]);

/** The KPIs a row carries, each in its own unit. */
const UNITS: Record<string, "pct" | "x" | "score" | "years"> = {
  pe_fwd: "x",
  ev_ebitda: "x",
  ev_sales: "x",
  net_debt_ebitda: "x",
  fcf_yield: "pct",
  owner_fcf_yield: "pct",
  roic: "pct",
  op_margin: "pct",
  revenue_cagr: "pct",
  share_dilution: "pct",
  revenue_growth: "pct",
  fcf_margin: "pct",
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
      return new Intl.NumberFormat(lang, { maximumFractionDigits: 1 }).format(value);
    default:
      return `${value.toFixed(1)}x`;
  }
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
