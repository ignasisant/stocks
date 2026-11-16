/**
 * The valuation read in one frame, and the multiples read as bars.
 *
 * Pure, over what the page already receives: the DCF's base case, the
 * street's price targets and the rivals' median multiple. Nothing is
 * estimated here; a method with no figure is left out rather than filled in.
 *
 * Everything is a distance from the price (a fraction), not an amount: the
 * DCF is in the filing currency, the targets in the listing's, the peer
 * multiple in neither, and a fraction is the one thing they share.
 */

import type { Analysts, Comparables, Dcf } from "./types";

/** A formatted figure ("14.2x", "-3.1%", "1.20T") as a number; null for "n/a". */
export function figure(text: string | undefined): number | null {
  if (!text) return null;
  const value = Number.parseFloat(text.replace(/,/g, ""));
  if (!Number.isFinite(value)) return null;
  const suffix = /([TBM])$/.exec(text.trim())?.[1];
  return suffix
    ? value * { T: 1e12, B: 1e9, M: 1e6 }[suffix as "T" | "B" | "M"]
    : value;
}

export type PeerBar = {
  key: string;
  label: string;
  mine: number;
  median: number;
  mineText: string;
  medianText: string;
  /** The name's own figure is on the right side of the rivals' middle. */
  better: boolean;
  /** The share of the row's track each figure fills. */
  mineWidth: number;
  medianAt: number;
};

/**
 * The rows the rivals' band exists for, the subject's figure against their
 * median. A multiple at or under zero is a loss, not a cheap reading, and is
 * left out the way the ranking leaves it out.
 */
export function peerBars(comps: Comparables | null): PeerBar[] {
  const subject = comps?.tickers[0];
  if (!comps || !subject || !comps.keys || !comps.lower_better) return [];
  const out: PeerBar[] = [];
  comps.labels.forEach((label, row) => {
    const key = comps.keys?.[row];
    const medianText = comps.peer_median[row];
    const mineText = comps.rows[subject]?.[row];
    const lower = comps.lower_better?.[row];
    if (!key || !medianText || lower === undefined) return;
    const mine = figure(mineText);
    const median = figure(medianText);
    if (mine === null || median === null || !mineText) return;
    if (lower && key !== "net_debt_ebitda" && key !== "share_dilution" && mine <= 0) {
      return;
    }
    const top = Math.max(Math.abs(mine), Math.abs(median)) * 1.1 || 1;
    out.push({
      key,
      label,
      mine,
      median,
      mineText,
      medianText,
      better: lower ? mine < median : mine > median,
      mineWidth: Math.abs(mine) / top,
      medianAt: Math.abs(median) / top,
    });
  });
  return out;
}

export type WorthRow = {
  id: "dcf" | "analysts" | "peers";
  /** Distance from the price, as a fraction: -0.36 is 36% under it. */
  at: number;
  /** The street's low and high targets, as the same distance. */
  low?: number;
  high?: number;
  /** The figure itself, in its own currency, when it has one. */
  value: number | null;
  currency: string | null;
};

/**
 * One row per method that has a figure. The DCF is the base case the card
 * below it opens on; the street is the median target, ranged by its lowest
 * and highest; the peers' row re-prices the name's own earnings at the
 * rivals' median P/E (`price x median / own`), which needs both.
 */
export function worthRows(
  dcf: Dcf | null,
  analysts: Analysts | null,
  comps: Comparables | null,
): WorthRow[] {
  const rows: WorthRow[] = [];
  if (dcf && !dcf.reason && dcf.value !== null && dcf.price) {
    rows.push({
      id: "dcf",
      at: dcf.value / dcf.price - 1,
      value: dcf.value,
      currency: dcf.currency,
    });
  }
  const targets = analysts?.covered ? analysts.targets : null;
  if (analysts && targets && targets.median !== null && analysts.price) {
    const away = (target: number | null) =>
      target === null ? undefined : target / (analysts.price as number) - 1;
    rows.push({
      id: "analysts",
      at: targets.median / analysts.price - 1,
      low: away(targets.low),
      high: away(targets.high),
      value: targets.median,
      currency: analysts.currency,
    });
  }
  const subject = comps?.tickers[0];
  if (comps && subject && comps.keys) {
    const row = comps.keys.indexOf("pe_ttm");
    const mine = figure(comps.rows[subject]?.[row]);
    const median = figure(comps.peer_median[row]);
    if (mine !== null && median !== null && mine > 0 && median > 0) {
      rows.push({ id: "peers", at: median / mine - 1, value: null, currency: null });
    }
  }
  return rows;
}

/** The axis the rows are laid on: the price at zero, a little room each side. */
export function worthAxis(rows: WorthRow[]): { lo: number; hi: number } {
  const all = rows.flatMap((one) =>
    [one.at, one.low, one.high].filter((v): v is number => v !== undefined),
  );
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const pad = (hi - lo) * 0.12 || 0.1;
  return { lo: lo - pad, hi: hi + pad };
}
