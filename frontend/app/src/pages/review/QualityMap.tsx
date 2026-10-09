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
 * keyboard focus or a tap, and stays inside the map.
 *
 * Fifty dots and a dozen labels make one name slow to find by eye, so a map
 * with as many names as a searchable table gets a search box in its corner
 * (`MapFind`): what does not match fades, every match gets its label, and a
 * picked suggestion is the only dot left lit, its tooltip open.
 */

import { type PointerEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { useTickerProfile } from "../../shell/tickers";
import { useWidth } from "../../shell/useWidth";
import { Chip } from "../../ui/Kpi";
import { percent, pnl, score, verdictTone } from "./format";
import { type Box, type LabelSpot, labelRank, placeLabels } from "./labels";
import { PnlChip } from "./Explain";
import { findRows } from "./filter";
import { MapFind } from "./MapFind";
import { FIND_MIN, useRowWords } from "./Tables";
import type { ReviewRow } from "./types";

/** `stocks.analysis.review.GOOD` and `CHEAP`. */
const GOOD = 60;
const CHEAP = 50;

// The right pad leaves room for a ticker label on a dot at 100.
const PAD = { top: 14, right: 44, bottom: 34, left: 40 };

/** How long the pointer rests on a dot before its tooltip opens, in ms. */
const TIP_DELAY = 300;

/** Gap between a dot's edge and its tooltip, and the box's margin in the map. */
const GAP = 8;

/**
 * Where a `w`×`h` tooltip goes for a dot of radius `r` at (`cx`, `cy`) in a
 * `width`×`height` map: centred over the dot, above it when it fits and below
 * when it does not, slid sideways and clamped so no edge leaves the map.
 */
export function tipPlace(
  dot: { cx: number; cy: number; r: number },
  box: { w: number; h: number },
  map: { width: number; height: number },
): { left: number; top: number } {
  const clamp = (value: number, max: number) => Math.max(GAP, Math.min(value, max));
  const above = dot.cy - dot.r - GAP - box.h;
  const top = above >= GAP ? above : dot.cy + dot.r + GAP;
  return {
    left: clamp(dot.cx - box.w / 2, map.width - box.w - GAP),
    top: clamp(top, map.height - box.h - GAP),
  };
}

type Spot = { row: ReviewRow; cx: number; cy: number; r: number };

export function QualityMap({
  held,
  candidates,
}: {
  held: ReviewRow[];
  candidates: ReviewRow[];
}) {
  const t = useT();
  const [ref, width] = useWidth(640);
  const [tip, setTip] = useState<Spot | null>(null);
  const [needle, setNeedle] = useState("");
  // The suggestion picked, until the field is typed in again.
  const [picked, setPicked] = useState<string | null>(null);
  const words = useRowWords();
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // A tapped tooltip stays until a tap lands somewhere else.
  useEffect(() => {
    if (!tip) return;
    const away = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Element && event.target.closest(".ag-rev-dot")))
        setTip(null);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTip(null);
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [tip]);
  const open = (spot: Spot, wait: boolean) => {
    window.clearTimeout(timer.current);
    if (wait) timer.current = window.setTimeout(() => setTip(spot), TIP_DELAY);
    else setTip(spot);
  };
  const close = () => {
    window.clearTimeout(timer.current);
    setTip(null);
  };
  const rows = [...held, ...candidates];
  const placed = rows.filter((row) => row.quality !== null && row.cheapness !== null);
  const missing = rows.length - placed.length;
  if (placed.length === 0) return null;

  // Wide, a landscape plane; phone-wide, near square — at 0.55 a 340px map is
  // 190px of plot and every name between 40 and 60 lands on one line.
  const tall = width < 560 ? width * 0.95 : width * 0.55;
  const height = Math.round(Math.min(420, Math.max(260, tall)));
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const x = (value: number) => PAD.left + (value / 100) * plotW;
  const y = (value: number) => PAD.top + (1 - value / 100) * plotH;
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
  const matches = !query
    ? placed
    : picked
      ? placed.filter((row) => key(row) === picked)
      : suggested.filter((row) => placed.includes(row));
  const found = new Set(matches.map(key));
  // A match is drawn over the faded names, never under one.
  if (query) ordered.sort((a, b) => +found.has(key(a)) - +found.has(key(b)));
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
    { x0: 16, y0: 0, x1: width, y1: y(0) },
    [...captions, ...ticks],
  );

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
              open(spotOf(row), false);
            }}
          />
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
          <text
            className="ag-rev-map-axis"
            transform={`translate(11 ${y(100)}) rotate(-90)`}
            textAnchor="end"
          >
            {t("review.axis_quality")}
          </text>
          {ordered.map((row) => (
            <Dot
              key={key(row)}
              row={row}
              cx={x(row.cheapness as number)}
              cy={y(row.quality as number)}
              label={labels.get(key(row))}
              dim={!found.has(key(row))}
              on={tip?.row.ticker === row.ticker && tip.row.held === row.held}
              onOpen={open}
              onClose={close}
            />
          ))}
        </svg>
        {tip ? <Tip spot={tip} width={width} height={height} /> : null}
      </div>
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
        <li>{t("review.map_tap")}</li>
        {missing > 0 ? <li>{t("review.map_missing", { count: missing })}</li> : null}
      </ul>
    </section>
  );
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
  on,
  onOpen,
  onClose,
}: {
  row: ReviewRow;
  cx: number;
  cy: number;
  /** Where its ticker goes; none when it would land on another's. */
  label: LabelSpot | undefined;
  /** Left out by the map's search: faded, still there to place the rest. */
  dim: boolean;
  on: boolean;
  onOpen: (spot: Spot, wait: boolean) => void;
  onClose: () => void;
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
    ...row.reasons.map((code) => t(`review.reason_${code}`)),
  ]
    .filter(Boolean)
    .join(". ");
  const spot = { row, cx, cy, r };
  // A mouse waits for the pointer to settle; a finger or a key opens it now.
  const mouse = (event: PointerEvent) => event.pointerType !== "touch";
  return (
    <g
      className={`ag-rev-dot ag-rev-dot-${tone}${row.held ? "" : " ag-rev-dot-out"}${on ? " ag-rev-dot-on" : ""}${dim ? " ag-rev-dot-dim" : ""}`}
      role="img"
      tabIndex={0}
      aria-label={spoken}
      onPointerEnter={(event) => mouse(event) && onOpen(spot, true)}
      onPointerLeave={(event) => mouse(event) && onClose()}
      onPointerUp={(event) => !mouse(event) && (on ? onClose() : onOpen(spot, false))}
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
 * the two scores, the weight and the gain, then the reasons. Measured once drawn and
 * placed by `tipPlace`, hidden until then so it never flashes at the corner.
 */
function Tip({ spot, width, height }: { spot: Spot; width: number; height: number }) {
  const t = useT();
  const lang = useLang();
  const { row } = spot;
  const profile = useTickerProfile(row.ticker);
  const symbol = profile?.symbol || row.symbol || row.ticker;
  const company = profile?.name || "";
  const box = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    setPlace(
      tipPlace(spot, { w: node.offsetWidth, h: node.offsetHeight }, { width, height }),
    );
  }, [spot, width, height, company]);
  const na = t("review.na");
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
      {row.reasons.length > 0 ? (
        <ul className="ag-rev-tip-why">
          {row.reasons.map((code) => (
            <li key={code}>{t(`review.reason_${code}`)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
