/**
 * The correlation grid on a diverging ramp, with its pair statistics.
 */

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useT } from "../../../shell/i18n";
import { token } from "../../../shell/theme";
import { TickerCell } from "../../../shell/tickers";
import { useWidth } from "../../../shell/useWidth";
import { NARROW } from "./frame";

/**
 * The diverging ramp for the correlation heatmap: moving apart (blue) through
 * uncorrelated (the card's own border grey) to moving together (red).
 *
 * Lightness rises from the middle outwards on both sides, so the two ends
 * are the most visible cells and a strong pair, either way, stands out from a
 * weak one by lightness as well as hue. The old ramp ended on a pale pink
 * that was lighter than every other stop, which made the diagonal (always 1)
 * the loudest thing in the grid. Blended with `color-mix` rather than parsed,
 * because some tokens are `rgba()` and some are hex.
 */
function correlationColor(value: number): string {
  const mix = (top: string, share: number, base: string) =>
    `color-mix(in srgb, ${top} ${share}%, ${base})`;
  const stops = [
    token("info"),
    mix(token("info"), 60, token("border")),
    token("border"),
    mix(token("critical-fill"), 75, token("border")),
    token("critical-fill"),
  ];
  const clamped = Math.max(-1, Math.min(1, value));
  const position = ((clamped + 1) / 2) * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(position));
  const fraction = position - index;
  const low = stops[index] ?? token("border");
  const high = stops[index + 1] ?? token("border");
  return `color-mix(in srgb, ${high} ${(fraction * 100).toFixed(1)}%, ${low})`;
}

/** How strongly a pair moves together, in five words a reader can act on. */
export type CorrelationBand = "very_high" | "high" | "moderate" | "low" | "negative";

export function correlationBand(value: number): CorrelationBand {
  if (value >= 0.7) return "very_high";
  if (value >= 0.4) return "high";
  if (value >= 0.2) return "moderate";
  if (value > -0.2) return "low";
  return "negative";
}

type Pair = { name: string; value: number };

export type CorrelationPair = {
  a: string;
  b: string;
  value: number;
  /** What the two hold together, as a fraction of the book; 0 when unknown. */
  together: number;
};

/** Below this combined weight a pair is too small to speak for the book. */
export const PAIR_FLOOR = 0.02;

export type CorrelationStats = {
  /** Mean pairwise correlation, each pair weighted by both its weights. */
  average: number | null;
  /** The pair that moves most alike *where the book is*: ranked by the
      correlation times what the two hold together, so two 0.4 % positions
      at 0.98 do not outrank the two largest at 0.8. */
  closest: CorrelationPair | null;
  /** Every measured pair, most linked first by the same ranking. */
  pairs: CorrelationPair[];
  /** The name least like the rest of the book. */
  diversifier: Pair | null;
  /** Per name: its weighted mean correlation with the others, and the other
      it is most and least like. */
  perName: Record<
    string,
    { average: number | null; peer: Pair | null; hedge: Pair | null }
  >;
};

/**
 * What the grid says, summed up: how alike the book is on average, which pair
 * is most alike, and which name diversifies the rest best. Weighted by the
 * book's weights — a pair of 0.5 % positions moving together is not the
 * book's risk — falling back to equal weights where none are known.
 */
export function correlationStats(
  matrix: Record<string, Record<string, number>>,
  weights: Record<string, number> = {},
): CorrelationStats {
  const names = Object.keys(matrix);
  const known = names.some((name) => (weights[name] ?? 0) > 0);
  const weight = (name: string) => (known ? (weights[name] ?? 0) : 1);
  let sum = 0;
  let mass = 0;
  const pairs: CorrelationPair[] = [];
  const perName: CorrelationStats["perName"] = {};
  for (const a of names) {
    let own = 0;
    let ownMass = 0;
    let peer: Pair | null = null;
    let hedge: Pair | null = null;
    for (const b of names) {
      const value = matrix[a]?.[b];
      if (a === b || value === undefined) continue;
      own += weight(b) * value;
      ownMass += weight(b);
      sum += weight(a) * weight(b) * value;
      mass += weight(a) * weight(b);
      if (!peer || value > peer.value) peer = { name: b, value };
      if (!hedge || value < hedge.value) hedge = { name: b, value };
      if (a < b)
        pairs.push({ a, b, value, together: (weights[a] ?? 0) + (weights[b] ?? 0) });
    }
    perName[a] = { average: ownMass ? own / ownMass : null, peer, hedge };
  }
  let diversifier: Pair | null = null;
  for (const name of names) {
    const average = perName[name]?.average;
    if (average == null || (known && !weight(name))) continue;
    if (!diversifier || average < diversifier.value)
      diversifier = { name, value: average };
  }
  // A pair that moves apart weighs nothing here: only the pull together is
  // scaled by size, so the ranking never lifts a negative above a positive.
  const score = (one: CorrelationPair) =>
    known && one.value > 0 ? one.value * one.together : one.value;
  pairs.sort((x, y) => score(y) - score(x));
  return {
    average: mass ? sum / mass : null,
    closest: pairs[0] ?? null,
    pairs,
    diversifier,
    perName,
  };
}

type HeatFocus = { row: string; column: string; rect: DOMRect };

/** Up to this many names the squares are big enough to print their figure. */
const HEAT_PRINTED = 10;
/**
 * Past this many names a narrow matrix lists one name's row at a time: 47
 * columns on a phone are 7px cells nobody can read or tap.
 */
const HEAT_ROWS_FROM = 6;
const HEAT_FALLBACK = 720;
/** A long row opens on its strongest links; the rest wait behind a button. */
const HEAT_ROWS_SHOWN = 10;

/**
 * Pairwise return correlation as a grid of squares.
 *
 * A pair the API had no overlap for is absent from the matrix rather than 0 —
 * an uncorrelated pair and an unmeasurable one are not the same reading — so
 * those cells are drawn as a dashed outline, not painted at the neutral stop.
 * A name against itself is always 1 and says nothing, so it is drawn in the
 * surface grey with a dot rather than at the loud end of the ramp.
 *
 * It is an ARIA grid with one tab stop: arrows walk the cells, Home / End
 * jump along the row (with Ctrl, along the whole grid), Escape puts the
 * reading away. A focused cell opens the same reading a hover does, and its
 * own label says the pair, the figure and the band, so a screen reader hears
 * the content without needing the box.
 *
 * Hovering a cell (tapping, on a phone) lights its row and column and opens
 * `explain`'s reading of that pair beside it. The box is portalled to the
 * body: the grid scrolls sideways inside its card, which would clip it, and
 * the main column is a size container, which would anchor a fixed box to it.
 */
export function Heatmap({
  matrix,
  format,
  explain,
  describe,
  scale,
}: {
  matrix: Record<string, Record<string, number>>;
  format: (value: number) => string;
  /** The reading of one cell; a name against itself when row = column. */
  explain?: (row: string, column: string) => ReactNode;
  /** What a screen reader hears on a cell; defaults to "row × column value". */
  describe?: (row: string, column: string, value: number | undefined) => string;
  /** Words under the colour ramp's two ends and its middle. */
  scale?: { low: string; mid: string; high: string };
}) {
  const t = useT();
  const [focus, setFocus] = useState<HeatFocus | null>(null);
  // The one cell in the tab order; arrows move it.
  const [cursor, setCursor] = useState<[number, number]>([0, 0]);
  const grid = useRef<HTMLDivElement>(null);
  const [frame, width] = useWidth(HEAT_FALLBACK);
  // The name whose row the narrow rendering lists.
  const [pick, setPick] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  // A tapped cell stays read until the page scrolls under it.
  useEffect(() => {
    if (!focus) return;
    const clear = () => setFocus(null);
    window.addEventListener("scroll", clear, { capture: true, passive: true });
    return () => window.removeEventListener("scroll", clear, { capture: true });
  }, [focus]);
  const names = Object.keys(matrix);
  if (!names.length) return null;
  // The grid is summed up for a screen reader by its two extremes — the pair
  // that moves most together and the one that moves most apart.
  const pairs = names.flatMap((row, i) =>
    names.slice(i + 1).flatMap((column) => {
      const value = matrix[row]?.[column];
      return value === undefined ? [] : [{ row, column, value }];
    }),
  );
  const said = (one: { row: string; column: string; value: number }) =>
    `${one.row} × ${one.column} ${format(one.value)}`;
  const top = pairs.reduce<(typeof pairs)[number] | null>(
    (best, one) => (best === null || one.value > best.value ? one : best),
    null,
  );
  const bottom = pairs.reduce<(typeof pairs)[number] | null>(
    (best, one) => (best === null || one.value < best.value ? one : best),
    null,
  );
  if (width < NARROW && names.length > HEAT_ROWS_FROM) {
    const row = pick && names.includes(pick) ? pick : (top?.row ?? names[0]!);
    const others = names
      .filter((name) => name !== row)
      .map((name) => ({ name, value: matrix[row]?.[name] }))
      .sort((x, y) => (y.value ?? -2) - (x.value ?? -2));
    const half = (value: number) => `${(Math.abs(value) / 2) * 100}%`;
    return (
      <div className="pf-heat-rows" ref={frame}>
        <label className="pf-heat-pick">
          <span>{t("portfolio.heat_row_pick")}</span>
          <select value={row} onChange={(event) => setPick(event.target.value)}>
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <ol aria-label={t("portfolio.heat_row_label", { name: row })}>
          {(all ? others : others.slice(0, HEAT_ROWS_SHOWN)).map(({ name, value }) => (
            <li
              key={name}
              className="ag-row-reach"
              aria-label={describe ? describe(row, name, value) : undefined}
            >
              <TickerCell ticker={name} name={false} className="pf-ticker" />
              <span className="pf-heat-track" aria-hidden="true">
                {value === undefined ? null : (
                  <i
                    style={{
                      [value < 0 ? "right" : "left"]: "50%",
                      width: half(value),
                      background: correlationColor(value),
                    }}
                  />
                )}
              </span>
              <span className="pf-heat-value">
                {value === undefined ? "·" : format(value)}
              </span>
            </li>
          ))}
        </ol>
        {!all && others.length > HEAT_ROWS_SHOWN ? (
          <button
            type="button"
            className="ag-btn pf-heat-all"
            onClick={() => setAll(true)}
          >
            {t("portfolio.heat_row_all", { n: others.length })}
          </button>
        ) : null}
        <HeatLegend format={format} scale={scale} />
      </div>
    );
  }
  const open = (row: string, column: string, target: Element) =>
    setFocus({ row, column, rect: target.getBoundingClientRect() });
  const lit = (name: string) => focus?.row === name || focus?.column === name;
  const last = names.length - 1;
  const printed = names.length <= HEAT_PRINTED;
  const go = (r: number, c: number) => {
    const next: [number, number] = [
      Math.max(0, Math.min(last, r)),
      Math.max(0, Math.min(last, c)),
    ];
    setCursor(next);
    grid.current
      ?.querySelector<HTMLElement>(`[data-pos="${next[0]}-${next[1]}"]`)
      ?.focus();
  };
  const walk = (event: KeyboardEvent<Element>, r: number, c: number) => {
    const far = event.ctrlKey || event.metaKey;
    const to: Record<string, [number, number]> = {
      ArrowUp: [r - 1, c],
      ArrowDown: [r + 1, c],
      ArrowLeft: [r, c - 1],
      ArrowRight: [r, c + 1],
      Home: [far ? 0 : r, 0],
      End: [far ? last : r, last],
    };
    if (event.key === "Escape") {
      setFocus(null);
      return;
    }
    const next = to[event.key];
    if (!next) return;
    event.preventDefault();
    go(next[0], next[1]);
  };
  return (
    <div className="pf-scroll" ref={frame}>
      <div
        ref={grid}
        className={focus ? "pf-heat pf-heat-focus" : "pf-heat"}
        role="grid"
        aria-label={
          top && bottom
            ? t("portfolio.heat_summary", { high: said(top), low: said(bottom) })
            : t("portfolio.heat_label")
        }
        aria-rowcount={names.length + 1}
        aria-colcount={names.length + 1}
        style={
          {
            gridTemplateColumns: `auto repeat(${names.length}, minmax(${
              printed ? "2.75rem" : "1.5rem"
            }, 1fr))`,
            "--heat-n": names.length,
          } as CSSProperties
        }
        onPointerLeave={(event) => {
          if (event.pointerType !== "touch") setFocus(null);
        }}
        onBlur={(event) => {
          // Focus leaving the grid puts the reading away; moving between
          // cells keeps it (the next focus reopens it at once).
          if (!event.currentTarget.contains(event.relatedTarget as Node | null))
            setFocus(null);
        }}
      >
        <div className="pf-heat-row" role="row">
          <span role="presentation" />
          {names.map((name) => (
            <span
              className={lit(name) ? "pf-heat-col pf-heat-lit" : "pf-heat-col"}
              key={`head-${name}`}
              role="columnheader"
            >
              {name}
            </span>
          ))}
        </div>
        {names.map((row, r) => (
          <div className="pf-heat-row" role="row" key={row}>
            <span
              className={lit(row) ? "pf-heat-label pf-heat-lit" : "pf-heat-label"}
              role="rowheader"
            >
              <TickerCell ticker={row} name={false} className="pf-ticker" />
            </span>
            {names.map((column, c) => {
              const value = matrix[row]?.[column];
              const self = row === column;
              const on = focus?.row === row || focus?.column === column;
              const classes = [
                "pf-heat-cell",
                on ? "pf-heat-on" : "",
                self ? "pf-heat-self" : "",
                value === undefined ? "pf-heat-gap" : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <span
                  className={classes}
                  key={`${row}-${column}`}
                  role="gridcell"
                  data-pos={`${r}-${c}`}
                  tabIndex={cursor[0] === r && cursor[1] === c ? 0 : -1}
                  aria-label={
                    describe
                      ? describe(row, column, value)
                      : value === undefined
                        ? `${row} × ${column}`
                        : `${row} × ${column} ${format(value)}`
                  }
                  style={
                    self || value === undefined
                      ? undefined
                      : { background: correlationColor(value) }
                  }
                  onPointerEnter={(event) => {
                    if (event.pointerType !== "touch")
                      open(row, column, event.currentTarget);
                  }}
                  onClick={(event) => {
                    setCursor([r, c]);
                    const same = focus?.row === row && focus?.column === column;
                    if (same) setFocus(null);
                    else open(row, column, event.currentTarget);
                  }}
                  onFocus={(event) => {
                    setCursor([r, c]);
                    // A click's focus is the pointer's: it opens the box
                    // itself. Only a key's focus opens it here.
                    if (event.currentTarget.matches(":focus-visible"))
                      open(row, column, event.currentTarget);
                  }}
                  onKeyDown={(event) => walk(event, r, c)}
                >
                  {self
                    ? "·"
                    : value === undefined
                      ? "·"
                      : printed
                        ? format(value)
                        : null}
                </span>
              );
            })}
          </div>
        ))}
      </div>
      <HeatLegend format={format} scale={scale} />
      {focus && explain ? (
        <HeatTip rect={focus.rect}>{explain(focus.row, focus.column)}</HeatTip>
      ) : null}
    </div>
  );
}

/**
 * The reading beside a cell: right of it, else left, kept on screen. Where
 * nothing hovers a finger covers the cell and what is beside it, so the box
 * sits above the cell instead (below when there is no room), as the other
 * charts lift theirs.
 */
function HeatTip({ rect, children }: { rect: DOMRect; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const tip = box.current;
    if (!tip) return;
    const { width, height } = tip.getBoundingClientRect();
    const gap = 10;
    const room = window.innerWidth;
    const touch = !!window.matchMedia?.("(hover: none)").matches;
    let left = rect.right + gap;
    if (touch) left = rect.left + rect.width / 2 - width / 2;
    else if (left + width > room - 8) left = rect.left - gap - width;
    left = Math.max(8, Math.min(left, room - width - 8));
    let top = rect.top + rect.height / 2 - height / 2;
    if (touch) {
      top = rect.top - gap - height;
      if (top < 8) top = rect.bottom + gap;
    }
    top = Math.max(8, Math.min(top, window.innerHeight - height - 8));
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
    tip.style.visibility = "visible";
  });
  return createPortal(
    <div ref={box} className="ag-tip pf-heat-tip">
      {children}
    </div>,
    document.body,
  );
}

/**
 * The colour scale under the grid, −1 to +1 — Plotly's colorbar, flattened.
 *
 * Without it the ramp is a guess: nothing on the grid says whether the deep
 * end is "moves together" or "moves apart". Drawn from the same
 * `correlationColor` the cells use, so the two cannot disagree. With `scale`
 * the ends and the middle are also said in words.
 */
function HeatLegend({
  format,
  scale,
}: {
  format: (value: number) => string;
  scale?: { low: string; mid: string; high: string };
}) {
  const stops = [-1, -0.5, 0, 0.5, 1];
  return (
    <div className="pf-heat-legend-wrap" aria-hidden="true">
      <div className="pf-heat-legend">
        <span>{format(-1)}</span>
        <span
          className="pf-heat-ramp"
          style={{
            background: `linear-gradient(to right, ${stops
              .map((v) => correlationColor(v))
              .join(", ")})`,
          }}
        />
        <span>{format(1)}</span>
      </div>
      {scale ? (
        <div className="pf-heat-words">
          <span>{scale.low}</span>
          <span>{scale.mid}</span>
          <span>{scale.high}</span>
        </div>
      ) : null}
    </div>
  );
}
