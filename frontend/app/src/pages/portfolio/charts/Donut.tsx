/**
 * The allocation donut and its slice hover box.
 */

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { series as seriesHues, seriesOther, token } from "../../../shell/theme";
import { TickerCell } from "../../../shell/tickers";
import { TipRows } from "../../../ui/chart/Tip";
import { type TipRow, ChartTip } from "./frame";

/** The part of one holding inside a slice, in the reporting currency. */
type SliceHolding = { ticker: string; value: number; cost: number };

export type Slice = {
  label: string;
  weight: number;
  /** Market value of the slice's priced holdings; absent where none priced. */
  value?: number | null;
  /** Cost basis of the same rows as `value`, so the P/L is like-for-like. */
  cost?: number | null;
  /** What the slice is made of, largest value first. */
  holdings?: SliceHolding[];
  /** On a folded "Others" slice: the names it swallowed, largest first. */
  includes?: string[];
};

/** What a donut needs to read its slices as money, not only as shares. */
export type SliceDetail = {
  money: (value: number, signed?: boolean) => string;
  /** A signed fraction — a P/L as a percentage. */
  change: (fraction: number) => string;
  labels: {
    value: string;
    invested: string;
    result: string;
    positions: string;
    /** "+3 more" under a hover box's cut list. */
    more: (count: number) => string;
    /** The hint that a click keeps the breakdown open. */
    pin: string;
    close: string;
    /** "Includes: Health, Energy, +3" under a folded slice's breakdown. */
    includes?: (names: string) => string;
    /** Said once under a pinned breakdown: what a slice's figures do not add up to. */
    note?: string;
  };
};

/** Holdings a hover box lists before it says how many more there are. */
const TIP_HOLDINGS = 4;

/**
 * The tail past the palette's hues as the one "Others" slice. Money only from
 * the parts that carried any, and holdings merged by ticker — a fund spread
 * over two tail sectors is still one holding.
 */
export function foldSlices(tail: Slice[], label: string): Slice {
  const priced = tail.filter((slice) => slice.value != null);
  const merged = new Map<string, SliceHolding>();
  for (const slice of tail) {
    for (const one of slice.holdings ?? []) {
      const seen = merged.get(one.ticker);
      merged.set(
        one.ticker,
        seen
          ? {
              ticker: one.ticker,
              value: seen.value + one.value,
              cost: seen.cost + one.cost,
            }
          : { ...one },
      );
    }
  }
  return {
    label,
    weight: tail.reduce((sum, slice) => sum + slice.weight, 0),
    value: priced.length
      ? priced.reduce((sum, slice) => sum + (slice.value ?? 0), 0)
      : null,
    cost: priced.length
      ? priced.reduce((sum, slice) => sum + (slice.cost ?? 0), 0)
      : null,
    holdings: [...merged.values()].sort((a, b) => b.value - a.value),
    includes: [...tail].sort((a, b) => b.weight - a.weight).map((slice) => slice.label),
  };
}

/**
 * A slice's hover box: what it is worth, what went into it and the
 * difference, and how many holdings make it up. Pure, like `bookTip`, so the
 * wording is testable without a pointer. Empty for a slice nothing priced.
 */
export function sliceTip(slice: Slice, detail: SliceDetail): TipRow[] {
  if (slice.value == null) return [];
  const { money, change, labels } = detail;
  const rows: TipRow[] = [{ label: labels.value, value: money(slice.value) }];
  if (slice.cost != null) {
    const pnl = slice.value - slice.cost;
    rows.push(
      { label: labels.invested, value: money(slice.cost), color: token("text-muted") },
      {
        label: labels.result,
        value: `${money(pnl, true)}${slice.cost > 0 ? ` (${change(pnl / slice.cost)})` : ""}`,
        color: pnl >= 0 ? token("up") : token("down"),
      },
    );
  }
  if (slice.holdings?.length) {
    rows.push({ label: labels.positions, value: String(slice.holdings.length) });
  }
  return rows;
}

/** One holding's figures in a slice: its part's value and that part's P/L. */
function HoldingFigures({ one, detail }: { one: SliceHolding; detail: SliceDetail }) {
  const pnl = one.value - one.cost;
  return (
    <>
      <span className="pf-donut-figure">{detail.money(one.value)}</span>
      <span className={`pf-donut-figure ${pnl >= 0 ? "pf-up" : "pf-down"}`}>
        {one.cost > 0 ? detail.change(pnl / one.cost) : "—"}
      </span>
    </>
  );
}

/**
 * Allocation as a donut, percentages on the legend rather than the slices.
 *
 * Sliver slices under ~1% printed their labels on top of each other, which is
 * why the original moved them out too. More buckets than the palette has hues
 * folds the tail into one muted "Others" slice, never a cycled colour.
 *
 * The hole names one slice — the largest until the pointer picks another —
 * so the ring carries a label without crowding its slivers. With `detail`, a
 * slice under the pointer opens a box with its money: value, what went in,
 * the P/L between them and the holdings it is made of. A click (a tap, on a
 * phone, where there is no hover) keeps that breakdown open under the legend
 * with every holding as a link, which a box that follows the pointer cannot
 * offer. The legend rows answer the same way, and to the keyboard.
 */
export function Donut({
  title,
  slices,
  otherLabel,
  format,
  detail,
}: {
  title: string;
  slices: Slice[];
  otherLabel: string;
  format: (fraction: number) => string;
  detail?: SliceDetail;
}) {
  const plot = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [pointer, setPointer] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  // A keyboard pin hands focus to the breakdown's close button, so the one
  // thing that changed is where the reader is; a pointer click keeps its own.
  const closeButton = useRef<HTMLButtonElement>(null);
  const focusDetail = useRef(false);
  useEffect(() => {
    if (pinned !== null && focusDetail.current) closeButton.current?.focus();
    focusDetail.current = false;
  }, [pinned]);
  const colors = seriesHues();
  const total = slices.reduce((sum, slice) => sum + slice.weight, 0);
  if (!(total > 0)) return null;

  const sorted = [...slices].sort((a, b) => b.weight - a.weight);
  // Five hues name five slices; the tail folds into one muted "Others", never
  // a sixth hue and never a repeat of the first.
  const shown =
    sorted.length > colors.length
      ? [
          ...sorted.slice(0, colors.length),
          foldSlices(sorted.slice(colors.length), otherLabel),
        ]
      : sorted;
  const palette = [...colors, seriesOther()];

  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  const find = (label: string | null) => shown.find((slice) => slice.label === label);
  const active = find(hover) ?? find(pinned);
  // At rest the hole says what the ring adds up to — the priced market value —
  // not its largest slice, which read as a total it is not. The largest slice
  // stays for a donut with no money to sum.
  const pricedTotal = shown.reduce((sum, slice) => sum + (slice.value ?? 0), 0);
  const restTotal = detail && pricedTotal > 0 ? pricedTotal : null;
  const focus = active ?? (restTotal === null ? shown[0] : undefined);
  const open = detail ? find(pinned) : undefined;
  const toggle = (label: string) => setPinned((now) => (now === label ? null : label));
  const track = (event: PointerEvent<HTMLDivElement>) => {
    // A finger has no hover: a tap pins the breakdown instead, and a box
    // that only lives while the finger is down would flash and vanish.
    if (event.pointerType === "touch") return;
    const box = plot.current?.getBoundingClientRect();
    if (!box) return;
    // Off the ring — in the hole or past its edge — nothing is under the
    // pointer, whichever slice it last crossed. In viewBox units: the stroke
    // spans 32.5…47.5 around the centre, a little more for the lifted one.
    const reach =
      (Math.hypot(
        event.clientX - box.left - box.width / 2,
        event.clientY - box.top - box.height / 2,
      ) /
        (box.width / 2)) *
      50;
    if (reach < 31 || reach > 49.5) setHover(null);
    setPointer({
      x: event.clientX - box.left,
      y: event.clientY - box.top,
      w: box.width,
      h: box.height,
    });
  };
  const tipped = hover !== null ? find(hover) : undefined;
  const tipRows = tipped && detail ? sliceTip(tipped, detail) : [];
  const tipHoldings = tipped?.holdings ?? [];

  return (
    <div className="pf-donut">
      <h3>{title}</h3>
      <div
        ref={plot}
        className="pf-donut-plot"
        onPointerMove={track}
        onPointerLeave={() => {
          setHover(null);
          setPointer(null);
        }}
      >
        <svg viewBox="0 0 100 100" aria-hidden="true">
          {shown.map((slice, index) => {
            const fraction = slice.weight / total;
            const length = fraction * circumference;
            // A 1px surface gap so adjacent fills never touch, dropped when the
            // slice is too thin to spare it.
            const drawn = length > 3 ? length - 1.5 : length;
            const start = offset;
            offset += length;
            const on = active?.label === slice.label;
            return (
              <circle
                key={slice.label}
                className="pf-slice"
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                stroke={palette[index] ?? seriesOther()}
                strokeWidth={on ? 18 : 15}
                strokeOpacity={active && !on ? 0.35 : 1}
                strokeDasharray={`${drawn} ${circumference - drawn}`}
                strokeDashoffset={-start}
                transform="rotate(-90 50 50)"
                onPointerEnter={() => setHover(slice.label)}
                onClick={() => toggle(slice.label)}
              />
            );
          })}
        </svg>
        {restTotal !== null && detail && !active ? (
          <div className="pf-donut-center" aria-hidden="true">
            <span className="pf-donut-center-label">{detail.labels.value}</span>
            <strong>{detail.money(restTotal)}</strong>
          </div>
        ) : focus ? (
          <div className="pf-donut-center" aria-hidden="true">
            <span className="pf-donut-center-label">{focus.label}</span>
            <strong>{format(focus.weight / total)}</strong>
            {detail && focus.value != null ? (
              <span className="pf-donut-center-money">{detail.money(focus.value)}</span>
            ) : null}
          </div>
        ) : null}
        {tipped && pointer ? (
          <ChartTip
            x={pointer.x}
            width={pointer.w}
            top={pointer.y > pointer.h * 0.55 ? pointer.y - 12 : pointer.y + 16}
            up={pointer.y > pointer.h * 0.55}
            wide={Boolean(detail)}
            title={`${tipped.label} · ${format(tipped.weight / total)}`}
            rows={tipRows}
          >
            {detail && tipHoldings.length ? (
              <span className="pf-tip-holdings">
                {tipHoldings.slice(0, TIP_HOLDINGS).map((one) => (
                  <span className="pf-tip-holding" key={one.ticker}>
                    <TickerCell
                      ticker={one.ticker}
                      name={false}
                      className="pf-ticker pf-tip-tick"
                    />
                    <HoldingFigures one={one} detail={detail} />
                  </span>
                ))}
                {tipHoldings.length > TIP_HOLDINGS ? (
                  <span className="pf-muted">
                    {detail.labels.more(tipHoldings.length - TIP_HOLDINGS)}
                  </span>
                ) : null}
                {pinned !== tipped.label ? (
                  <span className="pf-tip-hint">{detail.labels.pin}</span>
                ) : null}
              </span>
            ) : null}
          </ChartTip>
        ) : null}
      </div>
      {open && detail ? (
        <div
          className="pf-donut-detail"
          role="region"
          aria-live="polite"
          aria-label={open.label}
        >
          <div className="pf-donut-detail-head">
            <strong>{open.label}</strong>
            <button
              type="button"
              ref={closeButton}
              className="pf-donut-detail-close"
              aria-label={detail.labels.close}
              onClick={() => setPinned(null)}
            >
              ×
            </button>
          </div>
          <div className="pf-donut-detail-figures">
            <TipRows items={sliceTip(open, detail)} />
          </div>
          {open.includes?.length && detail.labels.includes ? (
            <p className="pf-donut-note">
              {detail.labels.includes(
                open.includes.length > 4
                  ? `${open.includes.slice(0, 3).join(", ")}, +${open.includes.length - 3}`
                  : open.includes.join(", "),
              )}
            </p>
          ) : null}
          {open.holdings?.length ? (
            <ul className="pf-donut-holdings">
              {open.holdings.map((one) => (
                <li key={one.ticker}>
                  <TickerCell ticker={one.ticker} name={false} className="pf-ticker" />
                  <HoldingFigures one={one} detail={detail} />
                </li>
              ))}
            </ul>
          ) : null}
          {detail.labels.note ? (
            <p className="pf-donut-note">{detail.labels.note}</p>
          ) : null}
        </div>
      ) : null}
      <ul className="pf-legend" aria-label={title}>
        {shown.map((slice, index) => (
          <li key={slice.label}>
            <button
              type="button"
              className={
                active?.label === slice.label
                  ? "pf-legend-row pf-legend-btn pf-legend-on"
                  : "pf-legend-row pf-legend-btn"
              }
              aria-pressed={detail ? pinned === slice.label : undefined}
              onPointerEnter={() => setHover(slice.label)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => {
                // No pointer to anchor the box to: the keyboard gets it at the
                // ring's centre, so the holdings are reachable without a mouse.
                const box = plot.current?.getBoundingClientRect();
                if (box)
                  setPointer({
                    x: box.width / 2,
                    y: box.height / 2,
                    w: box.width,
                    h: box.height,
                  });
                setHover(slice.label);
              }}
              onBlur={() => {
                setHover(null);
                setPointer(null);
              }}
              onClick={(event) => {
                focusDetail.current = event.detail === 0;
                toggle(slice.label);
              }}
            >
              <span
                className="pf-swatch"
                style={{ background: palette[index] ?? seriesOther() }}
              />
              <span className="pf-legend-name">
                {slice.label} · {format(slice.weight / total)}
              </span>
              {detail ? (
                <span className="pf-legend-money">
                  {slice.value != null ? detail.money(slice.value) : "—"}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
