/**
 * Quality against price, every judged name on one plane.
 *
 * Up is a better business, right is a cheaper one, so the corner a dot sits in
 * is its verdict before any word is read. Held names are filled and sized by
 * their weight; outside names are rings. The dashed lines are the engine's own
 * bars (`GOOD` quality, `CHEAP` price), not a quartile of whatever is shown.
 *
 * Names with no score — funds, cash, a broken feed — have no place here, and
 * the caption counts them rather than pinning them to a corner.
 *
 * Not every dot is labelled: `placeLabels` prints a ticker only where it reads
 * clear of the others, the names with a move first, so a crowded phone-wide
 * map shows a dozen clean symbols rather than fifty overprinted ones.
 *
 * A dot's details open in the DS tooltip (`Tip`), not the SVG's own `<title>`:
 * the browser waits about a second before drawing that one and draws it in its
 * own chrome. This one opens 300ms after the pointer settles, at once on
 * keyboard focus or a tap, and stays inside the map. Besides the scores it
 * carries a handful of the KPIs behind them (`TIP`); the rest is one press
 * away: a click, Enter, or a second tap on the same dot opens the name's full
 * details (`DetailsDialog`), the dialog the tables' rows open.
 *
 * Fifty dots and a dozen labels make one name slow to find by eye, so a map
 * with as many names as a searchable table gets a search box in its corner
 * (`MapFind`): what does not match fades, every match gets its label, and a
 * picked suggestion is the only dot left lit, its tooltip open.
 *
 * The map shares its focus with the plan and the tables (`focus.tsx`): the
 * dot under the pointer lights its rows below, and a row pointed at below
 * rings its dot here, labels it, fades the rest and opens its tooltip.
 *
 * A window picked over the map (none by default: the map opens on "now"
 * alone, and pressing "now" or the window again clears it) trails each dot
 * from where it sat the day the window opened, through where it sat every
 * half year since (`TRAIL`), into today's dot. Each place is the scores the review recorded
 * that day; else the business as its filings stood then, at that day's price;
 * else, with no filing that old, today's business at that price — so the
 * market's move reads as the dot sliding left (dearer) or right (cheaper),
 * and the business's as it rising or sinking. The map's window is its own, not the tables' (`?ret=`): those
 * always read over one. Beside it the reader can keep only the names the
 * market made dearer, or cheaper (`driftOf`), and only the businesses that
 * got better, or worse (`gainOf`): the rest fade, as the search's misses do.
 */

import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { useTickerProfile } from "../../shell/tickers";
import { useWidth } from "../../shell/useWidth";
import { Chip } from "../../ui/Kpi";
import { Segmented } from "../../ui/Segmented";
import { percent, pnl, score, tipFigures, verdictTone } from "./format";
import { type Box, type LabelSpot, labelRank, placeLabels } from "./labels";
import { DetailsDialog, PnlChip, metricLabel } from "./Explain";
import { useFocus } from "./focus";
import { findRows } from "./filter";
import { MapFind } from "./MapFind";
import { type ReturnWindow, type TrailStep, WINDOWS, useReturns } from "./returns";
import { FIND_MIN, useRowWords } from "./Tables";
import type { ReviewRow, ScorePoint } from "./types";

/** `stocks.analysis.review.GOOD` and `CHEAP`. */
const GOOD = 60;
const CHEAP = 50;

// The right pad leaves room for a ticker label on a dot at 100.
const PAD = { top: 14, right: 44, bottom: 34, left: 40 };
// Phone-wide every pixel is plot: the quality axis is named above it instead
// of turned up its side, and a label at 100 goes left of its dot.
const PAD_NARROW = { top: 24, right: 10, bottom: 34, left: 26 };
const NARROW = 480;

/** A trail shorter than this, in px, is a dot that stayed put: not drawn. */
const TRAIL_MIN = 4;

/**
 * The places a window's trail runs through, oldest first: its own first day,
 * then every half-year step younger than it (`compare.TRAIL_STEPS`), so two
 * years read as a path through four places into today's dot, not one line.
 */
const TRAIL: Record<ReturnWindow, TrailStep[]> = {
  "1m": ["1m"],
  "6m": ["6m"],
  "1y": ["1y", "6m"],
  "2y": ["2y", "18m", "1y", "6m"],
};

/** `since`'s trail as placed points, oldest first; a step not placed is skipped. */
export function trailOf(
  since: ReturnWindow,
  at: (step: TrailStep) => ScorePoint | null,
): (ScorePoint & { step: TrailStep })[] {
  return TRAIL[since].flatMap((step) => {
    const point = at(step);
    return point ? [{ ...point, step }] : [];
  });
}

/**
 * Up, down or flat from `past` to `now` as printed: the map's scores are read
 * as whole numbers, so a tenth is not a move. Null with nothing to measure.
 */
function moved(now: number | null, past: number | undefined): -1 | 0 | 1 | null {
  if (now === null || past === undefined) return null;
  return Math.sign(Math.round(now) - Math.round(past)) as -1 | 0 | 1;
}

/** Which way the price score moved since the window opened, as printed. */
export type Drift = "dear" | "cheap" | "flat";

/** "dear" when the price score reads lower than `then`'s, "cheap" higher. */
export function driftOf(now: number | null, then: ScorePoint | null): Drift | null {
  const way = moved(now, then?.cheapness);
  return way === null ? null : way < 0 ? "dear" : way > 0 ? "cheap" : "flat";
}

/** Which way the quality score moved since the window opened, as printed. */
export type Gain = "better" | "worse" | "flat";

/** "better" when the quality score reads higher than `then`'s, "worse" lower. */
export function gainOf(now: number | null, then: ScorePoint | null): Gain | null {
  const way = moved(now, then?.quality);
  return way === null ? null : way > 0 ? "better" : way < 0 ? "worse" : "flat";
}

type DriftPick = "all" | "dear" | "cheap";
type GainPick = "all" | "better" | "worse";

/** How long the pointer rests on a dot before its tooltip opens, in ms. */
const TIP_DELAY = 300;

/** Gap between a dot's edge and its tooltip, and the box's margin in the map. */
const GAP = 8;

/** How far apart, in px, a trail is sampled for a tooltip to steer clear of it. */
const TRAIL_SAMPLE = 6;
/** A named step hidden weighs this many stretches of line. */
export const TRAIL_MARK = 100;
/** Steps a tooltip is slid across the map in, each way, to clear a trail. */
const TIP_SWEEP = 8;

/** Points every `TRAIL_SAMPLE` px along a polyline, its corners included. */
export function sampleTrail(points: [number, number][]): [number, number][] {
  const out: [number, number][] = points.slice(0, 1);
  let last = points[0];
  for (const [x1, y1] of points.slice(1)) {
    if (!last) break;
    const [x0, y0] = last;
    const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / TRAIL_SAMPLE));
    for (let k = 1; k <= n; k += 1) {
      out.push([x0 + ((x1 - x0) * k) / n, y0 + ((y1 - y0) * k) / n]);
    }
    last = [x1, y1];
  }
  return out;
}

/**
 * Where a `w`×`h` tooltip goes for a dot of radius `r` at (`cx`, `cy`) in a
 * `width`×`height` map: centred over the dot, above it when it fits and below
 * when it does not, slid sideways and clamped so no edge leaves the map. A
 * box too tall for either goes beside the dot, on the side with room: clamped
 * over it, it would hide the very name it describes. Only a map with no room
 * on any side (a phone's, for a long tooltip) lets it overlap.
 *
 * Given the dot's trail (`avoid`, sampled), a box over it is the last choice:
 * every spot clear of the dot is tried, beside it, in a corner or swept along
 * the map, and the one hiding the least of the trail wins, the nearest on a
 * tie — a tooltip that covers where the name has been answers the question it
 * was opened for with the answer hidden. A point's third value weighs it: a
 * named step hidden costs more than any stretch of line between two.
 */
export function tipPlace(
  dot: { cx: number; cy: number; r: number },
  box: { w: number; h: number },
  map: { width: number; height: number },
  avoid: readonly (readonly [number, number, number?])[] = [],
): { left: number; top: number } {
  const clamp = (value: number, max: number) => Math.max(GAP, Math.min(value, max));
  const centred = clamp(dot.cx - box.w / 2, map.width - box.w - GAP);
  const above = dot.cy - dot.r - GAP - box.h;
  const below = dot.cy + dot.r + GAP;
  const level = clamp(dot.cy - box.h / 2, map.height - box.h - GAP);
  const right = dot.cx + dot.r + GAP;
  const left = dot.cx - dot.r - GAP - box.w;
  const fits = (spot: { left: number; top: number }) =>
    spot.left >= GAP &&
    spot.top >= GAP &&
    spot.left + box.w <= map.width - GAP &&
    spot.top + box.h <= map.height - GAP;
  const preferred = [
    { left: centred, top: above },
    { left: centred, top: below },
    { left: right, top: level },
    { left, top: level },
  ].filter(fits);
  const fallback = { left: centred, top: clamp(below, map.height - box.h - GAP) };
  if (!avoid.length) return preferred[0] ?? fallback;

  const sweep = (room: number) =>
    Array.from({ length: TIP_SWEEP + 1 }, (_, k) => GAP + (room * k) / TIP_SWEEP);
  const lefts = [centred, right, left, ...sweep(map.width - box.w - 2 * GAP)];
  const tops = [above, below, level, ...sweep(map.height - box.h - 2 * GAP)];
  const clear = (spot: { left: number; top: number }) =>
    spot.left > dot.cx + dot.r ||
    spot.left + box.w < dot.cx - dot.r ||
    spot.top > dot.cy + dot.r ||
    spot.top + box.h < dot.cy - dot.r;
  const others = lefts
    .flatMap((x) => tops.map((y) => ({ left: x, top: y })))
    .filter((spot) => fits(spot) && clear(spot));
  const hidden = (spot: { left: number; top: number }) =>
    avoid.reduce(
      (sum, [x, y, weight = 1]) =>
        x >= spot.left - GAP &&
        x <= spot.left + box.w + GAP &&
        y >= spot.top - GAP &&
        y <= spot.top + box.h + GAP
          ? sum + weight
          : sum,
      0,
    );
  const far = (spot: { left: number; top: number }) =>
    Math.hypot(spot.left + box.w / 2 - dot.cx, spot.top + box.h / 2 - dot.cy);
  // The preferred spots first, so a tie keeps the usual place.
  const ranked = [...preferred, ...others].map((spot, at) => ({
    spot,
    cost: hidden(spot),
    far: at < preferred.length ? -1 : far(spot),
  }));
  ranked.sort((a, b) => a.cost - b.cost || a.far - b.far);
  return ranked[0]?.spot ?? fallback;
}

type Spot = { row: ReviewRow; cx: number; cy: number; r: number };

export function QualityMap({
  held,
  candidates,
  taxCurrency,
}: {
  held: ReviewRow[];
  candidates: ReviewRow[];
  /** The plan's, for the sale's tax in a held name's details. */
  taxCurrency: string;
}) {
  const t = useT();
  const [ref, width] = useWidth(640);
  const [tip, setTip] = useState<Spot | null>(null);
  // The name whose details dialog is open.
  const [detail, setDetail] = useState<ReviewRow | null>(null);
  const [needle, setNeedle] = useState("");
  // The suggestion picked, until the field is typed in again.
  const [picked, setPicked] = useState<string | null>(null);
  // Only the names the window made dearer, or cheaper; "all" draws every one.
  const [drift, setDrift] = useState<DriftPick>("all");
  // …and only the businesses that got better, or worse.
  const [gain, setGain] = useState<GainPick>("all");
  const words = useRowWords();
  const { focus, point } = useFocus();
  const returns = useReturns();
  // The window the trails start from; none until one is picked.
  const [since, setSince] = useState<ReturnWindow | null>(null);
  const thenOf = (row: ReviewRow): ScorePoint | null =>
    returns && since ? returns.thenAt(row.symbol, since) : null;
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // A tapped tooltip stays until a tap lands somewhere else.
  useEffect(() => {
    if (!tip) return;
    const away = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Element && event.target.closest(".ag-rev-dot"))) {
        setTip(null);
        point(null);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setTip(null);
      point(null);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [tip, point]);
  // The pointer lands on the plan and the tables at once; only the tooltip
  // waits for it to settle.
  const open = (spot: Spot, wait: boolean) => {
    point({ ticker: spot.row.ticker, from: "map" });
    window.clearTimeout(timer.current);
    if (wait) timer.current = window.setTimeout(() => setTip(spot), TIP_DELAY);
    else setTip(spot);
  };
  const close = () => {
    point(null);
    window.clearTimeout(timer.current);
    setTip(null);
  };
  const expand = (row: ReviewRow) => {
    close();
    setDetail(row);
  };
  const rows = [...held, ...candidates];
  const placed = rows.filter((row) => row.quality !== null && row.cheapness !== null);
  const missing = rows.length - placed.length;
  if (placed.length === 0) return null;

  // Wide, a landscape plane; phone-wide, near square — at 0.55 a 340px map is
  // 190px of plot and every name between 40 and 60 lands on one line.
  const tall = width < 560 ? width * 0.95 : width * 0.55;
  const height = Math.round(Math.min(420, Math.max(260, tall)));
  const narrow = width < NARROW;
  const pad = narrow ? PAD_NARROW : PAD;
  const plotW = Math.max(1, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;
  const x = (value: number) => pad.left + (value / 100) * plotW;
  const y = (value: number) => pad.top + (1 - value / 100) * plotH;
  // Heaviest last so a small dot is never buried under a big one.
  const ordered = [...placed].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  const key = (row: ReviewRow) => `${row.held ? "h" : "c"}-${row.ticker}`;
  const spotOf = (row: ReviewRow): Spot => ({
    row,
    cx: x(row.cheapness as number),
    cy: y(row.quality as number),
    r: radius(row),
  });
  const searchable = placed.length >= FIND_MIN;
  const query = searchable ? needle.trim() : "";
  const symbolOf = (row: ReviewRow) => (row.symbol || row.ticker).toUpperCase();
  // A symbol that starts with what was typed beats a name that contains it.
  const suggested = query
    ? findRows(rows, query, words).sort(
        (a, b) =>
          +!symbolOf(a).startsWith(query.toUpperCase()) -
          +!symbolOf(b).startsWith(query.toUpperCase()),
      )
    : [];
  const drifted = (row: ReviewRow) => driftOf(row.cheapness, thenOf(row));
  const gained = (row: ReviewRow) => gainOf(row.quality, thenOf(row));
  const counts = { dear: 0, cheap: 0, better: 0, worse: 0 };
  for (const row of placed) {
    const way = drifted(row);
    if (way === "dear" || way === "cheap") counts[way] += 1;
    const grew = gained(row);
    if (grew === "better" || grew === "worse") counts[grew] += 1;
  }
  // Nothing to pick from before the window's scores land.
  const driftable = counts.dear + counts.cheap > 0;
  const gainable = counts.better + counts.worse > 0;
  const kept = (row: ReviewRow) =>
    (!driftable || drift === "all" || drifted(row) === drift) &&
    (!gainable || gain === "all" || gained(row) === gain);
  const filtered = (driftable && drift !== "all") || (gainable && gain !== "all");
  const matches = (
    !query
      ? placed
      : picked
        ? placed.filter((row) => key(row) === picked)
        : suggested.filter((row) => placed.includes(row))
  ).filter(kept);
  const found = new Set(matches.map(key));
  // A name pointed at in the plan or a table: ringed, labelled, its tooltip
  // open and every other dot faded, until the pointer leaves it there.
  const pointed =
    focus && focus.from !== "map"
      ? (placed.find((row) => row.ticker === focus.ticker) ?? null)
      : null;
  const lit = (row: ReviewRow) => (pointed ? row === pointed : found.has(key(row)));
  // A match is drawn over the faded names, never under one.
  if (query || pointed || filtered) ordered.sort((a, b) => +lit(a) - +lit(b));
  const quads: { text: string; x: number; y: number; end?: boolean }[] = [
    // Inner corner: the outer one is where the best names crowd.
    { text: t("review.quad_best"), x: x(CHEAP) + 6, y: y(100) + 14 },
    { text: t("review.quad_dear"), x: x(0) + 6, y: y(100) + 14 },
    { text: t("review.quad_cheap"), x: x(100) - 6, y: y(0) - 8, end: true },
    { text: t("review.quad_worst"), x: x(0) + 6, y: y(0) - 8 },
  ];
  // Caption text is lower-case and lighter than a ticker: ~6px a letter.
  const captions: Box[] = quads.map((q) => {
    const w = q.text.length * 6;
    const x0 = q.end ? q.x - w : q.x;
    return { x0, y0: q.y - 10, x1: x0 + w, y1: q.y + 2 };
  });
  // A dot on the left edge may label over the axis gutter, never over a tick.
  const ticks: Box[] = [0, 25, 50, 75, 100].map((tick) => ({
    x0: x(0) - 28,
    y0: y(tick) - 6,
    x1: x(0) - 4,
    y1: y(tick) + 6,
  }));
  const trails = ordered.flatMap((row) => {
    if (!returns || !since) return [];
    const now: [number, number] = [
      x(row.cheapness as number),
      y(row.quality as number),
    ];
    const path = trailOf(since, (step) => returns.thenAt(row.symbol, step));
    const steps = path.map((point): [number, number] => [
      x(point.cheapness),
      y(point.quality),
    ]);
    const still = steps.every(
      ([sx, sy]) => Math.hypot(now[0] - sx, now[1] - sy) < TRAIL_MIN,
    );
    const names = path.map(({ step }) =>
      step === "18m" ? t("review.map_step_18m") : t(`ticker.period_${step}`),
    );
    return still ? [] : [{ row, steps, names, points: [...steps, now] }];
  });
  // One name looked at (its tooltip, a row pointed at below, or the one
  // match the search left): its path alone is drawn, each step named.
  const solo =
    tip?.row ?? pointed ?? (query && matches.length === 1 ? matches[0] : null);
  // By key: the tooltip keeps the row it opened on, a refetch ago.
  const soloKey = solo ? key(solo) : null;
  const shown = soloKey ? trails.filter(({ row }) => key(row) === soloKey) : trails;
  const avoidOf = (row: ReviewRow) => {
    const trail = trails.find((one) => key(one.row) === key(row));
    if (!trail) return [];
    const marks = trail.points.map(([x, y]): [number, number, number] => [
      x,
      y,
      TRAIL_MARK,
    ]);
    return [...sampleTrail(trail.points), ...marks];
  };
  const labels = placeLabels(
    [...matches]
      .sort((a, b) => {
        const [ra, rb] = [labelRank(a), labelRank(b)];
        return ra[0] - rb[0] || ra[1] - rb[1] || ra[2] - rb[2];
      })
      .map((row) => ({
        key: key(row),
        cx: x(row.cheapness as number),
        cy: y(row.quality as number),
        r: radius(row),
        text: row.symbol || row.ticker,
      })),
    { x0: narrow ? 0 : 16, y0: 0, x1: width, y1: y(0) },
    [
      ...captions,
      ...ticks,
      ...(narrow ? [{ x0: 0, y0: 0, x1: width, y1: pad.top - 8 }] : []),
    ],
    // The one path drawn: a label over it reads struck through.
    [
      ...(soloKey
        ? avoidOf(solo as ReviewRow).map(([px, py]) => ({
            x0: px - 1,
            y0: py - 1,
            x1: px + 1,
            y1: py + 1,
          }))
        : []),
    ],
  );

  const sources = new Set(trails.map(({ row }) => thenOf(row)?.source));
  const trailKey = sources.has("price")
    ? "review.map_trail_price"
    : sources.has("filings")
      ? "review.map_trail_filings"
      : "review.map_trail";
  const span = since ? t(`ticker.period_${since}`) : "";

  return (
    <section className="ag-rev-card">
      <div className="ag-rev-map-head">
        <div>
          <h2 className="ag-rev-h2">{t("review.map_title")}</h2>
          <p className="ag-rev-caption">{t("review.map_help")}</p>
        </div>
        {searchable ? (
          <MapFind
            needle={needle}
            matches={suggested}
            placed={(row) => placed.includes(row)}
            onType={(value) => {
              setNeedle(value);
              setPicked(null);
              close();
            }}
            onPick={(row) => {
              setNeedle(row.symbol || row.ticker);
              setPicked(key(row));
              // A phone's tooltip covers the whole map: the path, its steps
              // named, is the answer there; a tap on the dot opens the rest.
              const path = trails.some((one) => key(one.row) === key(row));
              if (!narrow || !path) open(spotOf(row), false);
            }}
          />
        ) : null}
      </div>
      {/* Where from, then the two filters it opens: one row read left to
          right, each group named, rather than three tracks floated right. */}
      <div className="ag-rev-map-tools">
        {returns ? (
          <div className="ag-rev-map-group">
            <span className="ag-rev-map-group-label" aria-hidden="true">
              {t("review.map_group_since")}
            </span>
            <Segmented
              label={t("review.map_since")}
              items={[
                { id: "now" as const, label: t("review.map_since_now") },
                ...WINDOWS.map((id) => ({ id, label: t(`ticker.period_${id}`) })),
              ]}
              value={since ?? "now"}
              onPick={(next) => {
                setSince(next === "now" || next === since ? null : next);
                setDrift("all");
                setGain("all");
                close();
              }}
              className="ag-rev-window"
            />
          </div>
        ) : null}
        {driftable ? (
          <div className="ag-rev-map-group">
            <span className="ag-rev-map-group-label" aria-hidden="true">
              {t("review.map_group_price")}
            </span>
            <Segmented
              label={t("review.map_drift")}
              items={[
                { id: "all", label: t("review.map_drift_all") },
                {
                  id: "dear",
                  label: (
                    <>
                      {t("review.map_drift_dear")}{" "}
                      <span className="ag-rev-drift-n">{counts.dear}</span>
                    </>
                  ),
                },
                {
                  id: "cheap",
                  label: (
                    <>
                      {t("review.map_drift_cheap")}{" "}
                      <span className="ag-rev-drift-n">{counts.cheap}</span>
                    </>
                  ),
                },
              ]}
              value={drift}
              onPick={(next) => {
                setDrift(next);
                close();
              }}
            />
          </div>
        ) : null}
        {gainable ? (
          <div className="ag-rev-map-group">
            <span className="ag-rev-map-group-label" aria-hidden="true">
              {t("review.map_group_quality")}
            </span>
            <Segmented
              label={t("review.map_gain")}
              items={[
                { id: "all", label: t("review.map_drift_all") },
                {
                  id: "better",
                  label: (
                    <>
                      {t("review.map_gain_better")}{" "}
                      <span className="ag-rev-drift-n">{counts.better}</span>
                    </>
                  ),
                },
                {
                  id: "worse",
                  label: (
                    <>
                      {t("review.map_gain_worse")}{" "}
                      <span className="ag-rev-drift-n">{counts.worse}</span>
                    </>
                  ),
                },
              ]}
              value={gain}
              onPick={(next) => {
                setGain(next);
                close();
              }}
            />
          </div>
        ) : null}
      </div>
      <div className="ag-rev-map" ref={ref}>
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-label={t("review.map_title")}
        >
          <rect
            className="ag-rev-map-best"
            x={x(CHEAP)}
            y={y(100)}
            width={x(100) - x(CHEAP)}
            height={y(GOOD) - y(100)}
          />
          {[0, 25, 50, 75, 100].map((tick) => (
            <g key={tick}>
              <line
                className="ag-rev-map-grid"
                x1={x(0)}
                x2={x(100)}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text
                className="ag-rev-map-tick"
                x={x(0) - 6}
                y={y(tick) + 4}
                textAnchor="end"
              >
                {tick}
              </text>
              <text
                className="ag-rev-map-tick"
                x={x(tick)}
                y={y(0) + 16}
                textAnchor="middle"
              >
                {tick}
              </text>
            </g>
          ))}
          <line
            className="ag-rev-map-bar"
            x1={x(CHEAP)}
            x2={x(CHEAP)}
            y1={y(0)}
            y2={y(100)}
          />
          <line
            className="ag-rev-map-bar"
            x1={x(0)}
            x2={x(100)}
            y1={y(GOOD)}
            y2={y(GOOD)}
          />
          {quads.map((q) => (
            <text
              key={q.text}
              className="ag-rev-map-quad"
              x={q.x}
              y={q.y}
              textAnchor={q.end ? "end" : undefined}
            >
              {q.text}
            </text>
          ))}
          <text className="ag-rev-map-axis" x={x(100)} y={height - 2} textAnchor="end">
            {t("review.axis_cheap")}
          </text>
          {narrow ? (
            <text className="ag-rev-map-axis" x={0} y={10}>
              {t("review.axis_quality").replace("→", "↑")}
            </text>
          ) : (
            <text
              className="ag-rev-map-axis"
              transform={`translate(11 ${y(100)}) rotate(-90)`}
              textAnchor="end"
            >
              {t("review.axis_quality")}
            </text>
          )}
          {/* Under every dot: a trail never hides a name. */}
          {/* Two years of paths cross: the one under the pointer is the only
              one left lit, its steps readable. */}
          {shown.map(({ row, steps, names, points }) => (
            <g
              key={`t-${key(row)}`}
              className={`ag-rev-trail ag-rev-trail-${verdictTone(row.verdict)}${
                !lit(row) ? " ag-rev-trail-dim" : ""
              }${key(row) === soloKey ? " ag-rev-trail-on" : ""}`}
              aria-hidden="true"
            >
              <polyline points={points.map((point) => point.join(",")).join(" ")} />
              {/* The oldest place is the trail's open end; each later step a
                  bead on the way to today. */}
              {steps.map(([cx, cy], at) => (
                <circle key={at} cx={cx} cy={cy} r={at === 0 ? 2.5 : 1.75} />
              ))}
              {key(row) === soloKey
                ? steps.map(([cx, cy], at) => (
                    <text
                      key={`n-${at}`}
                      className="ag-rev-trail-step"
                      x={cx}
                      y={cy < pad.top + 14 ? cy + 14 : cy - 7}
                      textAnchor="middle"
                    >
                      {names[at]}
                    </text>
                  ))
                : null}
            </g>
          ))}
          {ordered.map((row) => (
            <Dot
              key={key(row)}
              row={row}
              cx={x(row.cheapness as number)}
              cy={y(row.quality as number)}
              label={
                labels.get(key(row)) ??
                (row === pointed
                  ? besideLabel(spotOf(row), width - pad.right)
                  : undefined)
              }
              dim={!lit(row)}
              then={thenOf(row)}
              span={span}
              on={
                row === pointed ||
                (tip?.row.ticker === row.ticker && tip.row.held === row.held)
              }
              onOpen={open}
              onClose={close}
              onExpand={expand}
            />
          ))}
        </svg>
        {tip ? (
          <Tip
            spot={tip}
            width={width}
            height={height}
            then={thenOf(tip.row)}
            span={span}
            avoid={avoidOf(tip.row)}
          />
        ) : pointed ? (
          <Tip
            spot={spotOf(pointed)}
            width={width}
            height={height}
            then={thenOf(pointed)}
            span={span}
            avoid={avoidOf(pointed)}
          />
        ) : null}
      </div>
      {detail ? (
        <DetailsDialog
          row={detail}
          label={t("review.details_label", { ticker: detail.symbol || detail.ticker })}
          taxCurrency={taxCurrency}
          onClose={() => setDetail(null)}
        />
      ) : null}
      {/* Each key keeps its swatch: wrapped loose, a ring ended one line and
          its words began the next. */}
      <ul className="ag-rev-caption ag-rev-legend">
        <li>
          <span className="ag-rev-key ag-rev-key-held" aria-hidden="true" />
          {t("review.legend_held")}
        </li>
        <li>
          <span className="ag-rev-key ag-rev-key-out" aria-hidden="true" />
          {t("review.legend_outside")}
        </li>
        {trails.length > 0 ? (
          <li>
            <span className="ag-rev-key ag-rev-key-trail" aria-hidden="true" />
            {t(trailKey, { span })}
          </li>
        ) : null}
        {trails.length > 0 && since && TRAIL[since].length > 1 ? (
          <li>{t("review.map_trail_steps")}</li>
        ) : null}
        <li>{t("review.map_tap")}</li>
        {missing > 0 ? <li>{t("review.map_missing", { count: missing })}</li> : null}
      </ul>
    </section>
  );
}

/**
 * A label for a dot `placeLabels` left bare, forced because it is the name
 * pointed at: beside the dot, on the side with room, over whatever is there.
 */
function besideLabel(spot: Spot, edge: number): LabelSpot {
  const right = spot.cx < edge - 8;
  return {
    x: right ? spot.cx + spot.r + 4 : spot.cx - spot.r - 4,
    y: spot.cy + 4,
    anchor: right ? "start" : "end",
  };
}

/** Area, not radius, follows the weight: 1% is a 4px dot, 10% a 12px one. */
const radius = (row: ReviewRow) =>
  row.held ? Math.max(4, Math.min(16, 4 * Math.sqrt((row.weight ?? 0) * 100))) : 5;

function Dot({
  row,
  cx,
  cy,
  label,
  dim,
  then,
  span,
  on,
  onOpen,
  onClose,
  onExpand,
}: {
  row: ReviewRow;
  cx: number;
  cy: number;
  /** Where its ticker goes; none when it would land on another's. */
  label: LabelSpot | undefined;
  /** Left out by the map's search: faded, still there to place the rest. */
  dim: boolean;
  /** Where it sat when the window `span` opened. */
  then: ScorePoint | null;
  span: string;
  on: boolean;
  onOpen: (spot: Spot, wait: boolean) => void;
  onClose: () => void;
  /** Opens the name's full details. */
  onExpand: (row: ReviewRow) => void;
}) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const profile = useTickerProfile(row.ticker);
  const symbol = profile?.symbol || row.symbol || row.ticker;
  const tone = verdictTone(row.verdict);
  const r = radius(row);
  const company = profile?.name || "";
  // The tooltip is drawn for the eye; a screen reader gets the same in words.
  const spoken = [
    company && company.toUpperCase() !== symbol.toUpperCase()
      ? `${symbol} — ${company}`
      : symbol,
    t(`review.verdict_${row.verdict}`),
    `${t("review.col_quality")} ${score(row.quality)}`,
    `${t("review.col_cheapness")} ${score(row.cheapness)}`,
    row.held ? `${t("review.col_weight")} ${percent(row.weight, lang)}` : null,
    row.held
      ? `${t("review.col_pnl")} ${pnl(row, base, lang) ?? t("review.na")}`
      : null,
    then ? thenLine(t, then, span) : null,
    ...row.reasons.map((code) => t(`review.reason_${code}`)),
    ...tipFigures(row.metrics, lang).map(
      ({ key, value }) => `${metricLabel(t, key)} ${value}`,
    ),
  ]
    .filter(Boolean)
    .join(". ");
  const spot = { row, cx, cy, r };
  // The click that follows a press carries no pointer type everywhere, so the
  // press records it: a finger's first tap is the mouse's hover.
  const finger = useRef(false);
  const press = (event: ReactKeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onExpand(row);
  };
  return (
    <g
      className={`ag-rev-dot ag-rev-dot-${tone}${row.held ? "" : " ag-rev-dot-out"}${on ? " ag-rev-dot-on" : ""}${dim ? " ag-rev-dot-dim" : ""}`}
      role="button"
      aria-haspopup="dialog"
      tabIndex={0}
      aria-label={spoken}
      // A mouse waits for the pointer to settle; a finger or a key opens it now.
      onPointerEnter={(event) => event.pointerType !== "touch" && onOpen(spot, true)}
      onPointerLeave={(event) => event.pointerType !== "touch" && onClose()}
      onPointerDown={(event) => {
        finger.current = event.pointerType === "touch";
      }}
      onClick={() => (finger.current && !on ? onOpen(spot, false) : onExpand(row))}
      onKeyDown={press}
      // A tap focuses the dot too; only a keyboard's focus opens it here.
      onFocus={(event) =>
        event.currentTarget.matches(":focus-visible") && onOpen(spot, false)
      }
      onBlur={onClose}
    >
      {/* A finger is wider than a 4px dot: the hit area is at least 22px across. */}
      <circle className="ag-rev-dot-hit" cx={cx} cy={cy} r={Math.max(r, 11)} />
      <circle cx={cx} cy={cy} r={r} />
      {label ? (
        <text x={label.x} y={label.y} textAnchor={label.anchor}>
          {symbol}
        </text>
      ) : null}
    </g>
  );
}

/**
 * The DS tooltip box (`.tk-tip` / `.pf-tip` in the charts): name, verdict,
 * the two scores, the weight and the gain, the KPIs in `TIP` the feed had,
 * then the reasons and how to open the rest. Measured once drawn and
 * placed by `tipPlace`, hidden until then so it never flashes at the corner.
 */
function Tip({
  spot,
  width,
  height,
  then,
  span,
  avoid,
}: {
  spot: Spot;
  width: number;
  height: number;
  then: ScorePoint | null;
  span: string;
  /** The name's trail, sampled, its steps weighed: what the box should not hide. */
  avoid: (readonly [number, number, number?])[];
}) {
  const t = useT();
  const lang = useLang();
  const { row } = spot;
  const profile = useTickerProfile(row.ticker);
  const symbol = profile?.symbol || row.symbol || row.ticker;
  const company = profile?.name || "";
  const box = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);
  // By value: the spot of a name pointed at elsewhere is rebuilt each render.
  const { cx, cy, r } = spot;
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    setPlace(
      tipPlace(
        { cx, cy, r },
        { w: node.offsetWidth, h: node.offsetHeight },
        { width, height },
        avoid,
      ),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a fresh array each render
  }, [cx, cy, r, row.ticker, width, height, company, then, avoid.join(";")]);
  const na = t("review.na");
  const figures = tipFigures(row.metrics, lang);
  return (
    <div
      ref={box}
      className="ag-rev-tip"
      aria-hidden="true"
      style={place ?? { visibility: "hidden" }}
    >
      <div className="ag-rev-tip-head">
        <span className="ag-rev-tip-sym">{symbol}</span>
        <Chip
          chip={{
            text: t(`review.verdict_${row.verdict}`),
            tone: verdictTone(row.verdict),
          }}
        />
      </div>
      {company && company.toUpperCase() !== symbol.toUpperCase() ? (
        <div className="ag-rev-tip-name">{company}</div>
      ) : null}
      <div className="ag-rev-tip-figs">
        <span>
          {t("review.col_quality")} <b>{score(row.quality) ?? na}</b>
        </span>
        <span>
          {t("review.col_cheapness")} <b>{score(row.cheapness) ?? na}</b>
        </span>
        {row.held ? (
          <span>
            {t("review.col_weight")} <b>{percent(row.weight, lang) ?? na}</b>
          </span>
        ) : null}
        {row.held ? (
          <span>
            {t("review.col_pnl")} <PnlChip row={row} />
          </span>
        ) : null}
      </div>
      {then ? <div className="ag-rev-tip-then">{thenLine(t, then, span)}</div> : null}
      {figures.length > 0 ? (
        <dl className="ag-rev-tip-kpis">
          {figures.map(({ key, value }) => (
            <div key={key}>
              <dt>{metricLabel(t, key)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {row.reasons.length > 0 ? (
        <ul className="ag-rev-tip-why">
          {row.reasons.map((code) => (
            <li key={code}>{t(`review.reason_${code}`)}</li>
          ))}
        </ul>
      ) : null}
      <div className="ag-rev-tip-more">{t("review.tip_more")}</div>
    </div>
  );
}

/** "6M ago: quality 62 · price 35", and how it was placed when not recorded. */
function thenLine(t: ReturnType<typeof useT>, then: ScorePoint, span: string): string {
  const line = t("review.tip_then", {
    span,
    quality: score(then.quality) ?? "",
    cheapness: score(then.cheapness) ?? "",
  });
  return then.source === "record"
    ? line
    : `${line} ${t(`review.tip_then_${then.source}`)}`;
}
