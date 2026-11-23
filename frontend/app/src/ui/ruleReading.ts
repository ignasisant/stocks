/**
 * Where a rule stands today, read from what the panel already has: the live
 * quote for the price rules, and the last quarterly check the night run left
 * on the rule's snapshot for the slow ones (`chat/journal.py`).
 *
 * Met comes only from the server (`state === "hit"`): a close or a run of
 * quarters decides it there. The live figure only says how far the line is,
 * so a price under the line before the close reads "near", never "met".
 */

import type { JournalEntry } from "./Journal";

/** What the page knows today about the name the rules are on. */
export type RuleQuote = {
  /** Last price, in the listing's own unit (what the server's closes are in). */
  price: number | null;
  /** The 52-week high, the peak a drawdown rule is measured from. */
  high: number | null;
};

type RuleKind = "met" | "near" | "far" | "unread" | "watch";
type RuleUnit = "price" | "pct" | "x";
type RuleGroup = "daily" | "quarter" | "news";

export type Reading = {
  kind: RuleKind;
  group: RuleGroup;
  unit: RuleUnit;
  /** Today's figure in the rule's own unit; null when there is none to read. */
  value: number | null;
  level: number | null;
  /** Which side of the level meets the rule. */
  dir: "le" | "ge";
  /** The value is already on the met side, but the rule is not hit yet. */
  onLine: boolean;
  /** Relative distance to the level, for "the closest one". */
  rel: number | null;
  /** The day the slow figure was read, for a fundamental. */
  checked: string | null;
};

const PRICE = new Set(["below", "buy_below"]);
const DRAWDOWN = new Set(["drawdown_high", "buy_drawdown_high"]);
const BOOK = new Set(["drawdown_cost", "weight_above"]);
const NEWS = new Set(["ceo_change", "guidance_cut", "dividend_cut", "thesis"]);
const NEAR = 0.05;

const num = (raw: unknown): number | null =>
  typeof raw === "number" && Number.isFinite(raw) ? raw : null;

export function ruleName(entry: JournalEntry): string {
  return String(entry.snapshot.rule ?? entry.action);
}

/**
 * The rule against today. `sameLine` says the quote is this rule's own line:
 * a journal read by company can carry another listing's rules, and a level
 * in one currency is never set against a price in another.
 */
export function readRule(
  entry: JournalEntry,
  quote: RuleQuote | null,
  sameLine: boolean,
): Reading {
  const rule = ruleName(entry);
  const level = num(entry.snapshot.level);
  const met = entry.state === "hit";
  const base = {
    level,
    onLine: false,
    rel: null,
    checked: null,
  };
  if (NEWS.has(rule) || BOOK.has(rule)) {
    return {
      ...base,
      kind: met ? "met" : "watch",
      group: NEWS.has(rule) ? "news" : "daily",
      unit: "pct",
      value: null,
      dir: "ge",
    };
  }
  let value: number | null = null;
  let unit: RuleUnit = "pct";
  let dir: "le" | "ge" = rule.endsWith("_below") || rule === "below" ? "le" : "ge";
  let group: RuleGroup = "quarter";
  let checked: string | null = null;
  const price = sameLine ? num(quote?.price) : null;
  if (PRICE.has(rule)) {
    group = "daily";
    unit = "price";
    value = price;
  } else if (DRAWDOWN.has(rule)) {
    group = "daily";
    dir = "ge";
    const high = sameLine ? num(quote?.high) : null;
    value = price !== null && high ? Math.max(0, (1 - price / high) * 100) : null;
  } else {
    // A fundamental, or the forward P/E: read once a quarter by the night run.
    checked =
      typeof entry.snapshot.checked === "string" ? entry.snapshot.checked : null;
    value = checked ? num(entry.snapshot.value) : null;
    if (rule === "buy_pe_fwd_below") {
      group = "daily";
      unit = "x";
      // A loss has no P/E to come down: never near, and no line to draw.
      if (value !== null && value <= 0) {
        return { ...base, kind: met ? "met" : "far", group, unit, value, dir, checked };
      }
    }
  }
  if (value === null || level === null) {
    return { ...base, kind: met ? "met" : "unread", group, unit, value, dir, checked };
  }
  const onLine = dir === "le" ? value <= level : value >= level;
  const rel = Math.abs(value - level) / Math.max(Math.abs(level), 1e-9);
  const kind: RuleKind = met ? "met" : onLine || rel <= NEAR ? "near" : "far";
  return { kind, group, unit, value, level, dir, onLine: onLine && !met, rel, checked };
}

/**
 * Where the level and today's figure sit on one line, as fractions of its
 * width, and which part of it meets the rule. Null when there is nothing to
 * place.
 */
export function trackOf(
  reading: Reading,
): { level: number; value: number; from: number; to: number } | null {
  const { value, level } = reading;
  if (value === null || level === null) return null;
  if (reading.unit === "x" && value <= 0) return null;
  let lo = Math.min(level, value);
  let hi = Math.max(level, value);
  const pad = (hi - lo) * 0.35 || Math.abs(hi) * 0.2 || 1;
  lo -= pad;
  hi += pad;
  if (Math.min(level, value) >= 0) lo = Math.max(lo, 0);
  const at = (x: number) => (x - lo) / (hi - lo);
  const mark = at(level);
  return reading.dir === "le"
    ? { level: mark, value: at(value), from: 0, to: mark }
    : { level: mark, value: at(value), from: mark, to: 1 };
}

/**
 * How far today is from the line, in the rule's terms: the fall a price
 * still needs, in percent; the points a margin or a drawdown still has to
 * move; the cut a P/E still needs. Null when met, unread or already there.
 */
export function gapOf(reading: Reading): { key: string; n: number } | null {
  const { value, level } = reading;
  if (reading.kind === "met" || reading.onLine || value === null || level === null) {
    return null;
  }
  if (reading.unit === "pct")
    return { key: "journal.gap_points", n: Math.abs(level - value) };
  if (value <= 0) return null;
  // Every price-like rule is a ceiling (`below`, `buy_below`, the P/E cap):
  // what is left is the fall to it.
  const move = (1 - level / value) * 100;
  return move > 0
    ? { key: reading.unit === "x" ? "journal.gap_cut" : "journal.gap_fall", n: move }
    : null;
}

/**
 * The rule not met yet that stands nearest its line: one already on the
 * line first (it waits only for the close or the quarter), then the smallest
 * relative distance. Rules with nothing to measure are left out.
 */
export function closestOf<T extends { reading: Reading }>(
  rows: readonly T[],
): T | null {
  const rank = (reading: Reading) => (reading.onLine ? -1 : (reading.rel ?? 0));
  return (
    rows
      .filter(({ reading }) => reading.kind !== "met" && reading.rel !== null)
      .sort((a, b) => rank(a.reading) - rank(b.reading))[0] ?? null
  );
}

/**
 * The checklist line a buy rule answers to, when the rule asks for less than
 * the list does: a margin rule under the list's floor, a P/E rule over its cap.
 * Met, the rule would still leave the list saying no.
 */
const CLASH: Record<
  string,
  { rule: string; looser: (rule: number, check: number) => boolean }
> = {
  buy_operating_margin_above: { rule: "op_margin_min", looser: (r, c) => r < c },
  buy_revenue_growth_above: { rule: "revenue_growth_min", looser: (r, c) => r < c },
  buy_pe_fwd_below: { rule: "pe_fwd_max", looser: (r, c) => r > c },
};

export function clashWith<L extends { rule: string; level: number }>(
  entry: JournalEntry,
  lines: readonly L[],
): L | null {
  const pair = CLASH[ruleName(entry)];
  const level = num(entry.snapshot.level);
  if (!pair || level === null) return null;
  const line = lines.find((one) => one.rule === pair.rule);
  return line && pair.looser(level, line.level) ? line : null;
}
