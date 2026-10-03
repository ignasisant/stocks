/**
 * The price block: range control, chart, and the figures beside it.
 *
 * The range is state and the zoom window is a slice of the bars.
 *
 * The holding is folded into the hero on a phone and into the price row on
 * desktop — either way beside the price it is valued at.
 *
 * The figures beside the price are the asset kind's (`layout.ts`): momentum
 * and trend for a share, a fund of shares or a coin; payout and duration for
 * a bond fund; yield against the policy rate for a money-market fund; premium
 * to NAV for a closed-end fund.
 */

import { useState } from "react";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import type { Query } from "../../shell/useApi";
import {
  DASH,
  barsDayPct,
  currencySymbol,
  earliest,
  latest,
  money,
  percent,
  shares,
  signed,
  signedPercent,
  type Translate,
} from "./format";
import { layout, type MetricId, type Shape } from "./layout";
import { PriceChart, type Window } from "./PriceChart";
import { Bold, Card, Empty, Metric, Metrics, Segmented, useMobile } from "./ui";
import { Chip, Kpi, KpiGrid, chipFor } from "../../ui/Kpi";
import type { Bars, EarningsEvent, Fund, Quote, TickerPosition, Trade } from "./types";

/** Range labels, in the order the app shows them (`analysis.history.PERIODS`). */
const RANGES = ["1d", "1w", "1m", "3m", "6m", "1y", "2y", "5y", "max"] as const;
export type Range = (typeof RANGES)[number];

export function isRange(value: string): value is Range {
  return (RANGES as readonly string[]).includes(value);
}

/**
 * Nine pills overflow a 360px viewport, so the app drops the two in-between
 * ranges there rather than letting them wrap or scroll.
 */
const PHONE_RANGES = RANGES.filter((one) => one !== "6m" && one !== "2y");

export function PriceSection({
  query,
  quote,
  events,
  position,
  range,
  offered,
  onRange,
  candles,
  onCandles,
  shape = layout(null),
  fund = null,
}: {
  /**
   * The bars as a query rather than as data, because the controls do not wait
   * on them: a failed fetch clears only the figures and the chart, and the
   * range pills and the chart toggle stay, so a reader can pick another range
   * instead of facing a lone Retry.
   */
  query: Query<Bars | null>;
  quote: Quote | null;
  events: EarningsEvent[];
  /** Folded into the hero on a phone; into the price row on desktop. */
  position: TickerPosition | null;
  range: Range;
  /**
   * The ranges this listing's history fills, or null until the first bars
   * say. A stock listed last spring gets no "5Y": it would draw exactly what
   * "max" does, under a label that promises three more years.
   */
  offered: readonly Range[] | null;
  onRange: (range: Range) => void;
  candles: boolean;
  onCandles: (candles: boolean) => void;
  /** What this kind of asset is read by: the cells, the averages, the toggle. */
  shape?: Shape;
  /** `/fund`'s answer — where a fund's figures beside the price come from. */
  fund?: Fund | null;
}) {
  const t = useT();
  const mobile = useMobile();
  const [window, setWindow] = useState<Window>(null);
  const bars = query.state === "loaded" ? query.data : null;
  // No figures over bars that have nothing to show: the metric row clears
  // whenever the chart under it cannot draw.
  const drawable = Boolean(bars && bars.dates.length > 0);
  // The quote's move when there is one; the bars' own otherwise, so a
  // throttled quote costs the page its live figure and not the day change.
  const dayPct = quote?.pct ?? barsDayPct(bars);

  const close = bars?.series.Close;
  const last = latest(close);
  const first = earliest(close);
  // Off-session the quote is the honest figure: the last bar is a stale close,
  // and the page dims the day change for exactly that reason.
  const live =
    quote?.market_open === false && quote.price !== null ? quote.price : last;
  const cells = shape.metrics.map((id) =>
    cell(id, { bars, last, fund: fund?.is_fund ? fund : null, t }),
  );
  const extended = quote?.session === "pre" || quote?.session === "post";
  const sessionNote =
    extended && quote?.session ? t(`ticker.session_${quote.session}`) : "";

  // Change over the SELECTED range. `bars` is already trimmed to the display
  // window, so its first close is the period's start.
  const periodPct =
    last !== null && first !== null && first !== 0
      ? ((last - first) / first) * 100
      : null;
  // "+11% in Max" says nothing; the whole history reads as since inception.
  const periodLine =
    periodPct === null
      ? ""
      : range === "max"
        ? t("ticker.period_change_max", { pct: `${signed(periodPct)}%` })
        : t("ticker.period_change", {
            pct: `${signed(periodPct)}%`,
            period: t(`ticker.period_${range}`),
          });
  // Only set once `/quote` found a currency other than the reader's own and a
  // rate to restate it at — a bare number here would read as the reader's
  // money, and a KRW close is not that.
  // Never for an index: its level is points, and points restated in euros are
  // a number that is nobody's money.
  const approxLine =
    !shape.points && quote?.price_base !== null && quote?.price_base !== undefined
      ? approx(quote.price_base, quote.base)
      : "";
  const unit = shape.points ? t("ticker.points") : (quote?.currency ?? null);
  // An index is followed, not held: no position block even if a ledger row
  // somehow names one.
  const held = shape.holdable ? position : null;

  return (
    <Card>
      <div className="tk-controls">
        <Segmented
          label={t("ticker.period")}
          options={(mobile ? PHONE_RANGES : RANGES).filter(
            (one) => !offered || offered.includes(one),
          )}
          value={range}
          onChange={onRange}
          format={(one) => t(`ticker.period_${one}`)}
        />
        {/* A price that barely moves draws a candle as a hairline: the kinds
            read off a line get no toggle, not one that draws nothing. */}
        {shape.candles ? (
          <Segmented
            label={t("ticker.chart_type")}
            options={["line", "candles"] as const}
            value={candles ? "candles" : "line"}
            onChange={(one) => onCandles(one === "candles")}
            format={(one) =>
              t(one === "candles" ? "ticker.chart_candles" : "ticker.chart_line")
            }
          />
        ) : null}
      </div>

      {!drawable ? null : mobile ? (
        <Hero
          price={live}
          dayPct={dayPct}
          dim={quote?.market_open === false}
          sessionNote={sessionNote}
          periodLine={periodLine}
          periodUp={periodPct !== null && periodPct >= 0}
          position={held}
          last={last}
          cells={cells}
          currency={unit}
          approxLine={approxLine}
          units={shape.units}
          t={t}
        />
      ) : (
        // The kind's cells, then the holding's four: the holding sits in the
        // price row, beside the price it is valued at, rather than in a card
        // further down.
        <Metrics>
          <Metric
            // Extended hours are named in the label, the way the page names
            // them: "Price · pre-market". A day move printed without that reads
            // as today's session when it is not.
            label={t("ticker.price") + (sessionNote ? ` · ${sessionNote}` : "")}
            value={live === null ? DASH : `${money(live)}${unit ? ` ${unit}` : ""}`}
            delta={dayPct}
            dim={quote?.market_open === false}
            note={[periodLine, approxLine].filter(Boolean).join(" · ")}
            noteTone={periodPct === null ? null : periodPct >= 0 ? "green" : "red"}
          />
          {cells.map((one) => (
            <Metric
              key={one.id}
              label={one.label}
              value={one.value}
              help={one.help}
              note={one.note}
              noteTone={one.tone}
            />
          ))}
          {held?.held ? (
            <PositionMetrics position={held} last={last} units={shape.units} t={t} />
          ) : null}
        </Metrics>
      )}

      {query.state !== "loaded" ? (
        // Loading, failed or signed out: the chart's slot says so, and the
        // controls above stay where they are.
        <Loaded query={query} skeleton={<Skeleton rows={8} />}>
          {() => null}
        </Loaded>
      ) : bars && bars.dates.length === 0 ? (
        <Empty>{t("ticker.history_empty")}</Empty>
      ) : bars ? (
        <PriceChart
          bars={bars}
          events={events}
          trades={held?.trades ?? []}
          avgCost={held?.avg_cost_native ?? null}
          candles={shape.candles && candles}
          overlays={shape.overlays}
          markers={shape.markers}
          mobile={mobile}
          onWindow={setWindow}
          t={t}
        />
      ) : null}

      {/* Only where a window can be picked: a phone pins both axes so a finger
          drag scrolls the page. */}
      {!mobile && window ? (
        <p className={`tk-readout tk-is-${window.pct >= 0 ? "green" : "red"}`}>
          {t("ticker.range_change", {
            pct: `${signed(window.pct)}%`,
            start: window.from,
            end: window.to,
          })}
        </p>
      ) : null}

      <LastBuy position={held} last={last} units={shape.units} t={t} />
    </Card>
  );
}

/**
 * The card's footer: the most recent entry at a glance.
 *
 * Size @ price · date · return to the current price, with the blended average
 * beside it so a single lot can be read against the whole position. Only the
 * return is coloured — a whole line in green reads as a status, not a figure.
 */
function LastBuy({
  position,
  last,
  units,
  t,
}: {
  position: TickerPosition | null;
  last: number | null;
  /** Count the holding in units — a coin — rather than shares. */
  units: boolean;
  t: Translate;
}) {
  // The latest-DATED priced buy, not the last in ledger order: an import
  // appends an older statement's rows.
  const latestBuy = (position?.trades ?? [])
    .filter((fill) => fill.action === "buy" && fill.price)
    .reduce<Trade | undefined>(
      (best, fill) => (!best || fill.date > best.date ? fill : best),
      undefined,
    );
  if (!latestBuy || last === null) return null;
  const pct = latestBuy.price ? (last / latestBuy.price - 1) * 100 : null;
  const reading = pct === null ? DASH : `${signed(pct)}%`;
  const fields = {
    qty: shares(latestBuy.quantity),
    price: money(latestBuy.price),
    date: latestBuy.date,
    pct: reading,
    last: money(last),
  };
  let line = units ? t("ticker.last_buy_units", fields) : t("ticker.last_buy", fields);
  if (position?.avg_cost_native) {
    line += t("ticker.last_buy_avg", { avg: money(position.avg_cost_native) });
  }
  const [head, ...tail] = line.split(reading);
  return (
    <p className="tk-note">
      <Bold text={head ?? ""} />
      <strong
        className={pct === null ? undefined : pct >= 0 ? "tk-is-green" : "tk-is-red"}
      >
        {reading}
      </strong>
      <Bold text={tail.join(reading)} />
    </p>
  );
}

/**
 * The phone summary: a price hero, then the holding as 2×2 tiles.
 *
 * Not a restyle of the desktop metric row — it is the layout the design
 * specifies for a 390px screen.
 */
function Hero({
  price,
  dayPct,
  dim,
  sessionNote,
  periodLine,
  periodUp,
  position,
  last,
  cells,
  currency,
  approxLine,
  units,
  t,
}: {
  price: number | null;
  dayPct: number | null;
  dim?: boolean;
  sessionNote: string;
  periodLine: string;
  periodUp: boolean;
  position: TickerPosition | null;
  last: number | null;
  /** The kind's figures — the desktop row's cells, read as one line here. */
  cells: Cell[];
  /**
   * The listing's own quote currency — null for a coin pair or a bare guess —
   * or "pts" for an index.
   */
  currency: string | null;
  /** The price restated in the reader's own money; blank with nothing to show. */
  approxLine: string;
  /** Count the holding in units — a coin — rather than shares. */
  units: boolean;
  t: Translate;
}) {
  const held = position?.held ? position : null;
  const lines = cells.filter((one) => one.value !== DASH).map(inline);
  // Not held: no tiles to fold the first figure into, so what the desktop row
  // carries stands on its own line under the price — "RSI 45.3 · neutral ·
  // SMA20 187.40 · above" for a share. Without it a phone reader of a name
  // they do not own gets a price and nothing to read it against.
  const trendLine = lines.join(" · ");

  return (
    <div className="tk-hero">
      <div className="tk-hero-price">
        <span className="tk-hero-level">{price === null ? DASH : money(price)}</span>
        {currency ? <span className="tk-hero-session">{currency}</span> : null}
        {dayPct !== null ? (
          <Chip chip={chipFor(dayPct, `${signed(dayPct * 100)}%`, dim)} />
        ) : null}
        {sessionNote ? <span className="tk-hero-session">{sessionNote}</span> : null}
        {periodLine ? (
          <span className={`tk-hero-period tk-is-${periodUp ? "green" : "red"}`}>
            {periodLine}
          </span>
        ) : null}
      </div>
      {/* Only when `/quote` converted the native close: a bare number here
          would read as the reader's own money, and often is not. */}
      {approxLine ? <p className="tk-hero-trend">{approxLine}</p> : null}
      {held ? (
        <PositionTiles
          position={held}
          last={last}
          note={lines[0] ?? ""}
          units={units}
          t={t}
        />
      ) : trendLine ? (
        <p className="tk-hero-trend">{trendLine}</p>
      ) : null}
    </div>
  );
}

/**
 * The "≈ €12,345.67" under the native value: the holding in the reporting
 * currency, with its mark ahead of the figure, not the code after it.
 */
function approx(value: number, base: string | null | undefined): string {
  return `≈ ${currencySymbol(base)}${money(value)}`;
}

/**
 * The holding restated in the reader's own money — or nothing when it already
 * is: "1,234.56 EUR" over "≈ €1,234.56" is the same figure twice, and the
 * "≈" claims a conversion that never happened.
 */
function baseNote(position: TickerPosition): string {
  if (position.value === null) return "";
  const own = (position.currency ?? "").toUpperCase();
  if (own && own === (position.base ?? "").toUpperCase()) return "";
  return approx(position.value, position.base);
}

/** One figure beside the price, whichever kind of asset asked for it. */
type Cell = {
  id: MetricId;
  label: string;
  /** How the phone's one-line summary names it, when shorter than `label`. */
  short?: string;
  value: string;
  help?: string;
  note: string;
  tone: string | null;
};

/** "RSI (14) 45.3 · neutral": a cell as a phrase of the phone's summary line. */
function inline(one: Cell): string {
  return [`${one.short ?? one.label} ${one.value}`, one.note]
    .filter(Boolean)
    .join(" · ");
}

/**
 * The server's RSI band in the reader's language. A switch of literal keys, so
 * the catalog scan sees every one; an unknown band prints nothing rather than
 * a raw English word.
 */
function rsiBand(t: Translate, verdict: string | null | undefined): string {
  switch (verdict) {
    case "oversold":
      return t("ticker.rsi_oversold");
    case "neutral":
      return t("ticker.rsi_neutral");
    case "overbought":
      return t("ticker.rsi_overbought");
    default:
      return "";
  }
}

/** Which bank's rate a money-market fund is read against, in words. */
function bankLabel(t: Translate, bank: string | null): string {
  switch (bank) {
    case "ecb":
      return t("ticker.policy_ecb");
    case "fed":
      return t("ticker.policy_fed");
    default:
      return "";
  }
}

/**
 * The figure a cell id stands for, off the payloads the page already holds.
 *
 * A fund figure `/fund` has not answered yet — or does not have — prints a
 * dash in its cell rather than moving the row about: the layout is the kind's,
 * the data fills it in.
 */
function cell(
  id: MetricId,
  {
    bars,
    last,
    fund,
    t,
  }: { bars: Bars | null; last: number | null; fund: Fund | null; t: Translate },
): Cell {
  switch (id) {
    case "rsi": {
      const rsi = latest(bars?.series.RSI14);
      return {
        id,
        label: t("ticker.rsi_label"),
        value: rsi === null ? DASH : rsi.toFixed(1),
        help: t("ticker.rsi_help"),
        // The band is the server's, not a threshold picked here.
        note: rsiBand(t, bars?.rsi_verdict),
        tone: bars?.rsi_tone ?? null,
      };
    }
    case "sma20": {
      const sma20 = latest(bars?.series.SMA20);
      const known = last !== null && sma20 !== null;
      return {
        id,
        label: t("ticker.sma20_label"),
        short: "SMA20",
        value: sma20 === null ? DASH : money(sma20),
        help: t("ticker.sma20_help"),
        // Price against its 20-day average: a trend read beside the level.
        note: known
          ? t(last >= sma20 ? "ticker.price_above" : "ticker.price_below")
          : "",
        tone: known ? (last >= sma20 ? "green" : "red") : null,
      };
    }
    case "distribution":
      return {
        id,
        label: t("ticker.fund_yield"),
        value: percent(fund?.dividend_yield, 2),
        help: t("ticker.fund_yield_help"),
        note: "",
        tone: null,
      };
    case "duration": {
      const years = fund?.bond_duration ?? null;
      return {
        id,
        label: t("ticker.fund_duration"),
        value: years === null ? DASH : t("ticker.years", { n: years.toFixed(1) }),
        help: t("ticker.fund_duration_help"),
        note: "",
        tone: null,
      };
    }
    case "cash_yield": {
      const cash = fund?.cash ?? null;
      // A pinned-NAV fund has no price to read: a year of payouts is its
      // figure, and the note says that is what it is.
      const paid = cash?.source === "distribution";
      const headline = paid ? (cash?.yield_1y ?? null) : (cash?.yield_3m ?? null);
      return {
        id,
        label: t("ticker.cash_yield"),
        value: percent(headline, 2),
        help: t("ticker.cash_yield_help"),
        note: paid
          ? t("ticker.cash_yield_paid")
          : cash?.yield_1y !== null && cash?.yield_1y !== undefined
            ? t("ticker.cash_yield_1y", { pct: percent(cash.yield_1y, 2) })
            : "",
        tone: null,
      };
    }
    case "policy": {
      const cash = fund?.cash ?? null;
      const policy = cash?.policy_rate ?? null;
      const earned =
        cash?.source === "distribution" ? cash.yield_1y : (cash?.yield_3m ?? null);
      // The gap is the fund's cost and its lag behind a rate move, in
      // percentage points — a shortfall is the normal reading, not an alarm.
      const gap =
        policy !== null && earned !== null && earned !== undefined
          ? t("ticker.policy_gap", { pp: signed((earned - policy) * 100, 2) })
          : "";
      return {
        id,
        label: t("ticker.policy_rate"),
        value: percent(policy, 2),
        help: t("ticker.policy_rate_help"),
        note: [bankLabel(t, cash?.bank ?? null), gap].filter(Boolean).join(" · "),
        tone: null,
      };
    }
    case "ter":
      return {
        id,
        label: t("ticker.fund_ter"),
        value: percent(fund?.expense_ratio, 2),
        help: t("ticker.fund_ter_help"),
        note: "",
        tone: null,
      };
    case "premium":
      return {
        id,
        label: t("ticker.cef_premium"),
        value: signedPercent(fund?.closed_end?.premium.value),
        help: t("ticker.cef_premium_help"),
        note: "",
        tone: null,
      };
    case "cef_distribution":
      return {
        id,
        label: t("ticker.cef_distribution"),
        value: percent(fund?.closed_end?.distribution_rate.value, 2),
        help: t("ticker.cef_distribution_help"),
        note: "",
        tone: null,
      };
  }
}

/**
 * The holding's four figures: value, unrealised P/L, weight, average cost.
 *
 * One function for both layouts — the phone tiles and the desktop price row —
 * because the arithmetic is the part that must not differ, and it is
 * arithmetic the server deliberately does not do: `/position` reports cost in
 * the position's own currency and prices nothing, so value and P/L are the last
 * close against that basis.
 */
function holding(position: TickerPosition, last: number | null) {
  const count = position.shares ?? null;
  const valueNative = count !== null && last !== null ? count * last : null;
  const pnlNative =
    valueNative !== null &&
    position.cost_native !== null &&
    position.cost_native !== undefined
      ? valueNative - position.cost_native
      : null;
  const pnlPct =
    last !== null && position.avg_cost_native
      ? (last / position.avg_cost_native - 1) * 100
      : null;
  return { count, valueNative, pnlNative, pnlPct, ccy: position.currency ?? "" };
}

/**
 * The holding as four cells of the desktop price row, in this order: value,
 * weight, P/L, average cost.
 */
/** "67 shares", or "0.0773 units" for a coin, which has no shares. */
function countNote(t: Translate, count: number, units: boolean): string {
  return units
    ? t("ticker.n_units", { n: shares(count) })
    : t("ticker.n_shares", { n: shares(count) });
}

function PositionMetrics({
  position,
  last,
  units,
  t,
}: {
  position: TickerPosition;
  last: number | null;
  /** Count the holding in units — a coin — rather than shares. */
  units: boolean;
  t: Translate;
}) {
  const { count, valueNative, pnlNative, pnlPct, ccy } = holding(position, last);
  return (
    <>
      <Metric
        label={t("ticker.position_value")}
        value={valueNative === null ? DASH : `${money(valueNative)} ${ccy}`.trim()}
        note={baseNote(position)}
      />
      <Metric
        label={t("ticker.pct_portfolio")}
        help={t("ticker.pct_portfolio_help")}
        value={
          position.weight === null ? DASH : `${(position.weight * 100).toFixed(1)}%`
        }
      />
      <Metric
        label={t("ticker.unrealised_pl")}
        help={t("ticker.unrealised_pl_help")}
        value={pnlNative === null ? DASH : `${signed(pnlNative)} ${ccy}`.trim()}
        // A fraction, as `delta` takes it: the same pill the price's day move
        // wears, which is what `st.metric`'s delta draws there.
        delta={pnlPct === null ? null : pnlPct / 100}
      />
      <Metric
        label={t("ticker.avg_buy_price")}
        value={
          position.avg_cost_native === null
            ? DASH
            : `${money(position.avg_cost_native)} ${ccy}`.trim()
        }
        note={count === null ? "" : countNote(t, count, units)}
      />
    </>
  );
}

/** The holding as 2×2 tiles, for the phone hero. */
function PositionTiles({
  position,
  last,
  note,
  units,
  t,
}: {
  position: TickerPosition;
  /** The last close the chart drew — what the holding is valued at. */
  last: number | null;
  /** The line under the weight tile: the RSI read. */
  note?: string;
  /** Count the holding in units — a coin — rather than shares. */
  units: boolean;
  t: Translate;
}) {
  const { count, valueNative, pnlNative, pnlPct, ccy } = holding(position, last);

  return (
    <KpiGrid>
      <Kpi
        label={t("ticker.position_value")}
        value={valueNative === null ? DASH : `${money(valueNative)} ${ccy}`.trim()}
        note={baseNote(position)}
      />
      <Kpi
        label={t("ticker.unrealised_pl")}
        help={t("ticker.unrealised_pl_help")}
        value={pnlNative === null ? DASH : `${signed(pnlNative)} ${ccy}`.trim()}
        chip={chipFor(pnlPct, pnlPct === null ? null : `${signed(pnlPct)}%`)}
      />
      <Kpi
        label={t("ticker.pct_portfolio")}
        help={t("ticker.pct_portfolio_help")}
        value={
          position.weight === null ? DASH : `${(position.weight * 100).toFixed(1)}%`
        }
        note={note ?? ""}
      />
      <Kpi
        label={t("ticker.avg_buy_price")}
        value={
          position.avg_cost_native === null
            ? DASH
            : `${money(position.avg_cost_native)} ${ccy}`.trim()
        }
        note={count === null ? "" : countNote(t, count, units)}
      />
    </KpiGrid>
  );
}
