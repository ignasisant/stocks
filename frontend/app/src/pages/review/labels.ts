/**
 * Which dots on the quality map get their ticker printed, and where.
 *
 * Fifty names on a phone-wide plane put a dozen labels on top of each other —
 * "MELI ZBRA CRM DASH UNH" in one smudge — and a smudge says nothing. So the
 * labels are placed one at a time, the names the page asks the reader to act
 * on first, each in the first free spot around its dot (right, left, above,
 * below). A label that fits nowhere is left off: its dot still opens the
 * tooltip, and a clear label on the names that matter beats an unreadable
 * one on every name.
 */

import type { ReviewRow } from "./types";

export type Box = { x0: number; y0: number; x1: number; y1: number };

export type LabelSpot = { x: number; y: number; anchor: "start" | "end" | "middle" };

type Item = { key: string; cx: number; cy: number; r: number; text: string };

/** 11px label text (`--ag-fs-2xs`): a capital is ~7px wide, a line 11px high. */
const CHAR_W = 7;
const LINE_H = 11;
/** Room from a dot's edge to its label, and the breathing space between boxes. */
const GAP = 3;
const PAD = 1;

/** Verdicts that ask the reader to do something come first. */
const ACT = new Set(["sell", "trim", "add", "buy"]);

/** Labelling order: moves before quiet rows, held before outside, heavy first. */
export function labelRank(row: ReviewRow): [number, number, number] {
  return [ACT.has(row.verdict) ? 0 : 1, row.held ? 0 : 1, -(row.weight ?? 0)];
}

const hits = (a: Box, b: Box) =>
  a.x0 < b.x1 + PAD && b.x0 < a.x1 + PAD && a.y0 < b.y1 + PAD && b.y0 < a.y1 + PAD;

const inside = (a: Box, area: Box) =>
  a.x0 >= area.x0 && a.x1 <= area.x1 && a.y0 >= area.y0 && a.y1 <= area.y1;

/** The four places a label can go around its dot, in order of preference. */
function spots(item: Item): [LabelSpot, Box][] {
  const { cx, cy, r } = item;
  const w = item.text.length * CHAR_W;
  const half = LINE_H / 2;
  const base = cy + 4; // text baseline that centres an 11px capital on the dot
  const right = cx + r + GAP;
  const left = cx - r - GAP;
  const top = cy - r - GAP;
  const bottom = cy + r + GAP;
  return [
    [
      { x: right, y: base, anchor: "start" },
      { x0: right, y0: cy - half, x1: right + w, y1: cy + half },
    ],
    [
      { x: left, y: base, anchor: "end" },
      { x0: left - w, y0: cy - half, x1: left, y1: cy + half },
    ],
    [
      { x: cx, y: top - 2, anchor: "middle" },
      { x0: cx - w / 2, y0: top - LINE_H, x1: cx + w / 2, y1: top },
    ],
    [
      { x: cx, y: bottom + LINE_H - 2, anchor: "middle" },
      { x0: cx - w / 2, y0: bottom, x1: cx + w / 2, y1: bottom + LINE_H },
    ],
  ];
}

/**
 * Place the labels of `items` (already in labelling order) inside `area`,
 * clear of every dot but their own, of each other and of `blocked` (the
 * quadrant captions). Returns a spot per key; a key left out gets no label.
 */
export function placeLabels(
  items: Item[],
  area: Box,
  blocked: Box[] = [],
): Map<string, LabelSpot> {
  const dots = items.map((item) => ({
    key: item.key,
    box: {
      x0: item.cx - item.r,
      y0: item.cy - item.r,
      x1: item.cx + item.r,
      y1: item.cy + item.r,
    },
  }));
  const taken: Box[] = [...blocked];
  const out = new Map<string, LabelSpot>();
  for (const item of items) {
    for (const [spot, box] of spots(item)) {
      if (!inside(box, area)) continue;
      if (taken.some((other) => hits(box, other))) continue;
      if (dots.some((dot) => dot.key !== item.key && hits(box, dot.box))) continue;
      taken.push(box);
      out.set(item.key, spot);
      break;
    }
  }
  return out;
}
