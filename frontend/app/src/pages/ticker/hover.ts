/**
 * What the price chart's hover box says, row for row the Plotly box it
 * replaces.
 *
 * Streamlit draws the chart with `hovermode="x unified"`: one box per bar,
 * titled with the bar's own stamp, and one row per trace that has a point
 * there — the price (with OHLC under it on candles), each moving average, the
 * reader's fills, and the dividend and results diamonds. Each row wears its
 * trace's swatch, labels are muted and values bold, and the only colour inside
 * a row is the change it reports. This module builds those rows; the chart
 * only draws them.
 *
 * The strings are the catalog's own, which are written for Plotly and carry
 * `<b>`, `<br>` and a `<span style='color:{color}'>` around the one figure a
 * row colours. `markup` reads that small dialect into parts instead of
 * stripping it, so the emphasis lands where Streamlit puts it rather than on
 * the whole line — and no catalog string is ever handed to the DOM as HTML.
 *
 * Pure, and tested, because a return measured against the wrong close or a
 * fill on the wrong bar renders perfectly and means something else.
 */

import type { EventLine } from "./events";
import { sellLine } from "./events";
import { DASH, money, signed, type Translate } from "./format";
import type { Trade } from "./types";

/** A run of text inside a row, and how it is set. */
export type TipPart = { text: string; bold?: boolean; tone?: "up" | "down" | "dim" };

/**
 * One row of the box. `text` is the plain reading (the key, and what a test
 * reads); `parts` is how it is drawn; `swatch` the colour of the trace it
 * belongs to, as Plotly's unified box prefixes every row with one.
 */
export type HoverRow = {
  text: string;
  parts: TipPart[];
  swatch?: string;
};

/** Where the "{color}" slot of a catalog string is filled, and read back. */
const UP = "__up__";
const DOWN = "__down__";

/**
 * The catalog's hover dialect as rows of parts: `<br>` starts a row, `<b>`
 * bolds, a `<span style='color:…'>` colours by the sentinel `colorSlot()` wrote
 * into it. Any other tag is dropped and its text kept.
 */
export function markup(html: string): TipPart[][] {
  const rows: TipPart[][] = [];
  for (const chunk of html.split(/<br\s*\/?>/i)) {
    const parts: TipPart[] = [];
    let bold = 0;
    const tones: (TipPart["tone"] | undefined)[] = [];
    for (const token of chunk.split(/(<[^>]*>)/)) {
      if (!token) continue;
      if (token.startsWith("<")) {
        const tag = token.toLowerCase();
        if (tag === "<b>") bold++;
        else if (tag === "</b>") bold = Math.max(0, bold - 1);
        else if (tag.startsWith("<span")) {
          tones.push(tag.includes(UP) ? "up" : tag.includes(DOWN) ? "down" : undefined);
        } else if (tag === "</span>") tones.pop();
        continue;
      }
      const tone = [...tones].reverse().find(Boolean);
      const part: TipPart = { text: token };
      if (bold) part.bold = true;
      if (tone) part.tone = tone;
      parts.push(part);
    }
    // Plotly collapses the double spaces the catalog uses as a gap; a row
    // that is only whitespace (a leading `<br>`) is no row at all.
    if (parts.some((part) => part.text.trim())) rows.push(parts);
  }
  return rows;
}

/** A value for the `{color}` slot, so `markup` can tell the tone back. */
function colorSlot(value: number | null): string {
  return value === null ? "" : value >= 0 ? UP : DOWN;
}

function toneOf(value: number): "up" | "down" {
  return value >= 0 ? "up" : "down";
}

function row(parts: TipPart[], swatch?: string): HoverRow {
  return {
    text: parts
      .map((part) => part.text)
      .join("")
      .replace(/\s+/g, " ")
      .trim(),
    parts,
    swatch,
  };
}

/**
 * One trace's entry, which may run over several rows: Plotly draws the swatch
 * once, beside the first, and the `<br>` continuations sit under it.
 */
function rows(html: string, swatch?: string): HoverRow[] {
  return markup(html).map((parts, at) => row(parts, at === 0 ? swatch : undefined));
}

/**
 * The box's title: the bar's own stamp — `%Y-%m-%d`, with the clock on an
 * intraday range — as Streamlit pins `hoverformat`. Not the axis label: on a
 * multi-year window that collapses to a month, over a bar that is one day.
 */
export function hoverTitle(stamp: string, intraday: boolean): string {
  const clean = stamp.replace("T", " ");
  return intraday ? clean.slice(0, 16) : clean.slice(0, 10);
}

/**
 * A fill on the chart: the bar it is drawn on, and the fill.
 *
 * Streamlit draws every buy and every sell dated on or after the window's
 * first bar, and nothing older — a 2022 entry on a one-year chart is off the
 * left edge, not piled onto its first candle. A fill on a closed day lands on
 * the next bar, where Plotly's range breaks would have folded it too.
 */
export type Fill = { index: number; trade: Trade };

export function placeFills(trades: Trade[], days: string[]): Fill[] {
  const first = days[0];
  if (first === undefined) return [];
  const out: Fill[] = [];
  for (const trade of trades) {
    if (trade.action !== "buy" && trade.action !== "sell") continue;
    const day = trade.date.slice(0, 10);
    if (day < first.slice(0, 10)) continue;
    const index = days.findIndex((stamp) => stamp.slice(0, 10) >= day);
    out.push({ index: index === -1 ? days.length - 1 : index, trade });
  }
  return out;
}

/**
 * The price row, and the open/high/low under it on candles: "Price  187.40
 * +1.23%", the change being the bar's move on the previous close.
 */
export function priceRows(
  args: {
    close: number | null;
    prev: number | null;
    ohlc: { open: number | null; high: number | null; low: number | null } | null;
    swatch: string;
  },
  t: Translate,
): HoverRow[] {
  const { close, prev, ohlc, swatch } = args;
  const move = close !== null && prev ? (close / prev - 1) * 100 : null;
  const parts: TipPart[] = [
    { text: t("ticker.price"), tone: "dim" },
    { text: "  " },
    { text: close === null ? DASH : money(close), bold: true },
  ];
  if (move !== null) {
    parts.push(
      { text: "  " },
      { text: `${signed(move)}%`, bold: true, tone: toneOf(move) },
    );
  }
  const out = [row(parts, swatch)];
  if (ohlc) {
    const detail = t("ticker.hover_ohlc", {
      open: money(ohlc.open),
      high: money(ohlc.high),
      low: money(ohlc.low),
    });
    out.push(row([{ text: detail, tone: "dim" }]));
  }
  return out;
}

/** "SMA50  201.33" — muted name, bold value; nothing where it is still warming up. */
export function averageRow(name: string, value: number | null, swatch: string) {
  if (value === null || value === undefined) return null;
  return row(
    [{ text: name, tone: "dim" }, { text: "  " }, { text: money(value), bold: true }],
    swatch,
  );
}

/**
 * A fill's rows. A buy: size @ price · date, then its return to the LAST CLOSE
 * OF THE RANGE (Streamlit's `last`, not the end of a zoom), then the blended
 * average so the lot can be read against the whole position. A sell: size @
 * price · date and nothing else — Streamlit prices no return on a sale.
 */
export function fillRows(
  fill: Trade,
  args: { last: number | null; avgCost: number | null; swatch: string },
  t: Translate,
): HoverRow[] {
  const { last, avgCost, swatch } = args;
  const qty = fill.quantity.toFixed(4);
  if (fill.action === "sell") {
    return rows(sellLine(qty, money(fill.price), fill.date, t), swatch);
  }
  const pct = last !== null && fill.price ? (last / fill.price - 1) * 100 : 0;
  let html = t("ticker.hover_buy", {
    qty,
    price: money(fill.price),
    date: fill.date,
    color: colorSlot(pct),
    pct: signed(pct),
    last: money(last),
  });
  if (avgCost) html += t("ticker.hover_avg_buy", { avg: money(avgCost) });
  return rows(html, swatch);
}

/**
 * A dividend or results diamond's rows. The event line's `emphasis` is the one
 * figure Streamlit colours inside it (the surprise), in the line's tone; the
 * rest of the row stays neutral.
 */
export function eventRows(lines: EventLine[], swatch: string): HoverRow[] {
  const out: HoverRow[] = [];
  for (const line of lines) {
    let html = line.text;
    if (line.emphasis && line.tone) {
      const mark = line.tone === "up" ? UP : DOWN;
      html = html.replace(
        line.emphasis,
        `<span style='color:${mark}'><b>${line.emphasis}</b></span>`,
      );
    }
    // Every event is its own diamond, so each one's first row carries it.
    out.push(...rows(html, swatch));
  }
  return out;
}
