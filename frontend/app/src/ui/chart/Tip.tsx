/**
 * The one hover box every chart draws.
 *
 * Portfolio, ticker, Hoy and Home each grew their own: same palette, four
 * boxes. This is the box — a title, then one row per series with its swatch,
 * a muted name and a bold figure — and the pages only say where it sits (a
 * `className` for their placement rules: a readout strip on a phone, a lift
 * above a sparkline).
 *
 * A div rather than SVG text: it has to wrap, stay legible at every width and
 * not scale with the chart. Anchored as a percentage of the plot so it lands
 * with the pointer whatever the rendered size, flipped to the pointer's left
 * past the middle, then nudged back inside the plot where it would still
 * overhang it. Never a live region: it is rewritten on every pointer move;
 * what a screen reader hears is `Spoken`, and only when a key moved the
 * readout (`useScrub`).
 */

import type { ReactNode } from "react";
import { useLayoutEffect, useRef } from "react";
import "./chart.css";

/** One piece of a pre-set row: a muted run, a bold figure, a toned figure. */
type TipPart = { text: string; bold?: boolean; tone?: "up" | "down" | "dim" };

/**
 * One row. Either `label` + `value` (muted name, bold figure at the far end)
 * or `text` / `parts` for a row a caller has already set as a sentence.
 * `color` is the series' swatch; `mark` keys a line by a short stroke.
 */
export type TipItem = {
  label?: string;
  value?: string;
  text?: string;
  parts?: TipPart[];
  color?: string;
  mark?: "line" | "dashed";
  tone?: "up" | "down" | null;
};

/** A box with the swatch a series is keyed by. */
function TipSwatch({ color, mark }: { color: string; mark?: "line" | "dashed" }) {
  const kind =
    mark === "dashed" ? " ag-tip-dashed" : mark === "line" ? " ag-tip-line" : "";
  return <span className={`ag-tip-sw${kind}`} style={{ background: color }} />;
}

/** The rows alone, for a panel that prints what the box would (donut detail). */
export function TipRows({ items }: { items: TipItem[] }) {
  return (
    <>
      {items.map((item, index) => (
        <span
          key={`${item.label ?? item.text ?? ""}-${index}`}
          className={item.tone ? `ag-tip-row ag-is-${item.tone}` : "ag-tip-row"}
        >
          {item.color ? <TipSwatch color={item.color} mark={item.mark} /> : null}
          {item.label !== undefined ? (
            <>
              <span className="ag-tip-label">{item.label}</span>
              <strong>{item.value}</strong>
            </>
          ) : (
            <span className="ag-tip-text">
              {item.parts
                ? item.parts.map((part, at) => (
                    <span
                      key={at}
                      className={
                        [
                          part.bold ? "ag-tip-b" : "",
                          part.tone ? `ag-is-${part.tone}` : "",
                        ]
                          .filter(Boolean)
                          .join(" ") || undefined
                      }
                    >
                      {part.text}
                    </span>
                  ))
                : item.text}
            </span>
          )}
        </span>
      ))}
    </>
  );
}

/** The one sentence a box says, for the live region a key step speaks. */
export function tipSaid(title: string, items: TipItem[]): string {
  const rows = items.map((item) =>
    item.label !== undefined
      ? `${item.label} ${item.value ?? ""}`.trim()
      : (item.text ?? item.parts?.map((part) => part.text).join("") ?? ""),
  );
  return [title, ...rows].filter(Boolean).join(", ");
}

/** Past this share of the plot the box opens to the pointer's left. */
const TIP_FLIP = 55;

/** An anchor in viewBox units as the percentage `Tip` positions by. */
export const tipAt = (x: number, width: number) => (x / width) * 100;

export function Tip({
  at,
  title,
  items = [],
  top,
  up = false,
  wide = false,
  className,
  children,
}: {
  /** Anchor, as a percentage of the plot's width (`tipAt`). */
  at: number;
  title: string;
  items?: TipItem[];
  /** Pixels down the plot, for a box that follows the pointer both ways. */
  top?: number;
  /** Opens above `top` rather than below it, for a pointer low in the plot. */
  up?: boolean;
  /** Allowed the plot's whole width, for a box with more than a figure a row. */
  wide?: boolean;
  /** The page's placement classes (strip on touch, lift over a sparkline). */
  className?: string;
  /** Anything past the rows — a donut slice's holdings. */
  children?: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  // Measured after every render, since the pointer moved it: set on the
  // element rather than through state, so the measurement is never of its own
  // nudge. On `left` rather than a transform, which would still leave the
  // untouched box counted in the page's width.
  useLayoutEffect(() => {
    const tip = box.current;
    const plot = tip?.parentElement;
    if (!tip || !plot) return;
    tip.style.left = `${at}%`;
    const rect = tip.getBoundingClientRect();
    const frame = plot.getBoundingClientRect();
    const over = rect.right - frame.right;
    const under = frame.left - rect.left;
    const nudge = over > 0 ? -over : under > 0 ? under : 0;
    if (nudge) tip.style.left = `calc(${at}% + ${nudge}px)`;
  });
  const classes = ["ag-tip"];
  if (at > TIP_FLIP) classes.push("ag-tip-flip");
  if (up) classes.push("ag-tip-up");
  if (wide) classes.push("ag-tip-wide");
  if (className) classes.push(className);
  return (
    <div
      ref={box}
      className={classes.join(" ")}
      style={{ left: `${at}%`, ...(top === undefined ? {} : { top }) }}
    >
      <span className="ag-tip-title">{title}</span>
      <TipRows items={items} />
      {children}
    </div>
  );
}
