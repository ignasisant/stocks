/**
 * What the price chart's corporate-event markers say.
 *
 * The page puts a dotted vertical on every dividend and every results date and
 * writes a line into that date's tooltip. The lines are the point: a spike next
 * to an earnings print is a different fact from a spike next to nothing, and a
 * chart that draws the vertical without saying what it was leaves the reader to
 * guess which.
 *
 * Pure, and returning text rather than markup, because the wording is the part
 * that goes wrong silently — a yield computed against the wrong close, a
 * surprise sign flipped — and none of that shows up in a screenshot.
 */

import type { Translate } from "./format";
import type { EarningsEvent } from "./types";

/**
 * A tooltip line, and whether it reads as good or bad news. `emphasis` is the
 * figure inside it that carries the tone — Streamlit colours the surprise, not
 * the whole EPS line — so a renderer can set only that part.
 */
export type EventLine = { text: string; tone?: "up" | "down"; emphasis?: string };

/**
 * A sell marker's line.
 *
 * The catalogs only have this one as a Plotly hovertemplate — three positional
 * `%{…}` slots the library fills from the trace — because that is what the
 * Streamlit chart needs. This page draws its own tooltip, so it prefers a
 * `ticker.hover_sell` written with named slots like its buy twin, and fills the
 * template's three slots in their published order until that key exists.
 * Getting that order wrong prints the quantity as a price, which is why the
 * fallback is here and not inline.
 */
export function sellLine(
  qty: string,
  price: string,
  date: string,
  t: Translate,
): string {
  const written = t("ticker.hover_sell", { qty, price, date });
  if (written !== "ticker.hover_sell") return written;
  const slots = [qty, price, date];
  let at = 0;
  return t("ticker.hover_sell_tmpl")
    .replace("<extra></extra>", "")
    .replace(/%\{[^}]*\}/g, () => slots[at++] ?? "");
}

/**
 * Index of the first bar on or after `day`; the last bar when it is past the
 * end. A report filed on a non-trading day — or after the close — belongs on
 * the next bar, which is where the gap it caused shows up.
 */
export function snap(days: string[], day: string): number {
  const at = days.findIndex((stamp) => stamp.slice(0, 10) >= day);
  return at === -1 ? days.length - 1 : at;
}

/** "Dividend 0.24/sh · ex-date 2024-05-10 · ≈0.52% of price" */
export function dividendLine(
  value: number,
  close: number | null,
  date: string,
  t: Translate,
): EventLine {
  let text = t("ticker.hover_dividend", {
    amt: String(Number(value.toPrecision(4))),
    date: date.slice(0, 10),
  });
  // The yield is against THAT day's close, not today's: a 2019 dividend told
  // as a percentage of the 2026 price is a different number entirely.
  if (close) {
    text += t("ticker.hover_div_yield", { pct: ((value / close) * 100).toFixed(2) });
  }
  return { text };
}

/**
 * The results marker, as lines: the date, the EPS against consensus with the
 * surprise, and how far the price moved across the print.
 *
 * The move spans the session before to the session after, because whether the
 * company reported before the open or after the close is not in the data.
 */
export function resultsLines(
  event: EarningsEvent,
  closes: (number | null)[],
  at: number,
  daily: boolean,
  t: Translate,
): EventLine[] {
  const lines: EventLine[] = [
    { text: t("ticker.hover_results", { date: event.date.slice(0, 10) }) },
  ];
  if (event.reported_eps !== null) {
    let text = `EPS ${event.reported_eps.toFixed(2)}`;
    if (event.eps_estimate !== null) {
      text += t("ticker.hover_vs_est", { est: event.eps_estimate.toFixed(2) });
    }
    if (event.surprise_pct !== null) {
      const sign = event.surprise_pct >= 0 ? "+" : "";
      const emphasis = `${sign}${event.surprise_pct.toFixed(1)}%`;
      text += ` · ${emphasis} ${t("ticker.hover_surprise")}`;
      lines.push({ text, tone: event.surprise_pct >= 0 ? "up" : "down", emphasis });
    } else {
      lines.push({ text });
    }
  }
  const before = closes[at - 1];
  const after = closes[at + 1];
  if (daily && at > 0 && before && after !== null && after !== undefined) {
    // Uncoloured, as Streamlit prints it: the move is context for the
    // surprise above it, not a second verdict.
    const move = after / before - 1;
    lines.push({
      text: t("ticker.hover_move", {
        pct: `${move >= 0 ? "+" : ""}${(move * 100).toFixed(1)}`,
      }),
    });
  }
  return lines;
}
