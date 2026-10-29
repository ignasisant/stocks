/**
 * The price block: range control, chart, and the figures beside it.
 *
 * The range is state and the zoom window is a slice of the bars.
 *
 * The row beside the price answers a holder's questions in the order they are
 * asked: what the price did today and why (the price tile, and a results
 * line when a report landed this week); where that price sits (the year's
 * range, the P/E against its own average, the next results date — the kind's
 * cells, `layout.ts`); and what it does to the holding (value, gain and
 * weight, in the reader's own money). RSI and the averages stay on the chart,
 * where they can be read against the line rather than as two more figures.
 *
 * Every figure of the holding is priced at the same number the price tile
 * shows — off-session the quote, in session the last bar — so a pre-market
 * drop is not printed beside a value that still stands at last night's close.
 */

import { useState, type ReactNode } from "react";
import { calendarDay } from "../../shell/dates";
import { Loaded } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import type { Query } from "../../shell/useApi";
import {
  DASH,
  barsDayPct,
  currencySymbol,
  earliest,
  known,
  latest,
  money,
  orElse,
  percent,
  shares,
  signed,
  signedPercent,
  type Translate,
} from "./format";
import { layout, type MetricId, type Shape } from "./layout";
import { PriceChart, PriceChartWait, type ChartWindow } from "./PriceChart";
import { Bold, Card, Empty, Metric, Metrics, Segmented, useMobile } from "./ui";
import {
  Chip,
  type ChipSpec,
  Kpi,
  KpiGrid,
  type Tone,
  bandTone,
  chipFor,
} from "../../ui/Kpi";
import type {
  AssetStats,
  Bars,
  CycleEvent,
  EarningsEvent,
  Fund,
  Quote,
  TickerPosition,
  Trade,
  Trend,
  Valuation,
} from "./types";
import { num } from "../../shell/numbers";

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

/** How many days after a report its line still explains the price. */
const RESULTS_FRESH_DAYS = 7;

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
  stats = null,
  cycle = [],
  valuation = null,
  trend = null,
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
  /** `/crypto`'s answer — where a coin's all-time high and year come from. */
  stats?: AssetStats | null;
  /** A coin's dated cycle events, for the chart's verticals. */
  cycle?: CycleEvent[];
  /** `/valuation`'s answer, which the page fetches anyway: the P/E cell. */
  valuation?: Valuation | null;
  /** `/trend`'s answer: the trend cell. */
  trend?: Trend | null;
}) {
  const t = useT();
  const mobile = useMobile();
  const bars = query.state === "loaded" ? query.data : null;
  // The stretch a drag zoomed the chart into, so the period figure reads what
  // the chart shows; null on the whole range.
  const [zoomed, setZoomed] = useState<ChartWindow | null>(null);
  // No figures over bars that have nothing to show: the metric row clears
  // whenever the chart under it cannot draw.
  const drawable = Boolean(bars && bars.dates.length > 0);
  // The quote's move when there is one; the bars' own otherwise, so a
  // throttled quote costs the page its live figure and not the day change.
  const dayPct = quote?.pct ?? barsDayPct(bars);
  const dim = quote?.market_open === false;

  const close = bars?.series.Close;
  const last = latest(close);
  const first = earliest(close);
  // Off-session the quote is the honest figure: the last bar is a stale close,
  // and the page dims the day change for exactly that reason.
  const live =
    dim && quote?.price !== null && quote?.price !== undefined ? quote.price : last;
  const today = isoToday();
  const cells = shape.metrics.map((id) =>
    cell(id, {
      bars,
      live,
      fund: fund?.is_fund ? fund : null,
      stats,
      quote,
      valuation,
      trend,
      events,
      today,
      t,
    }),
  );
  const extended = quote?.session === "pre" || quote?.session === "post";
  const sessionNote =
    extended && quote?.session ? t(`ticker.session_${quote.session}`) : "";

  // Change over the SELECTED range — or over the stretch the chart is zoomed
  // into, which is what the reader is looking at. `bars` is already trimmed
  // to the display window, so its first close is the period's start.
  const periodPct = zoomed
    ? zoomed.pct
    : last !== null && first !== null && first !== 0
      ? ((last - first) / first) * 100
      : null;
  // "+11% in Max" says nothing; the whole history reads as since inception.
  const periodLine =
    periodPct === null
      ? ""
      : zoomed
        ? t("ticker.range_change", {
            pct: `${signed(periodPct)}%`,
            start: zoomed.start,
            end: zoomed.end,
          })
        : range === "max"
          ? t("ticker.period_change_max", { pct: `${signed(periodPct)}%` })
          : t("ticker.period_change", {
              pct: `${signed(periodPct)}%`,
              period: t(`ticker.period_${range}`),
            });
  const unit = shape.points ? t("ticker.points") : (quote?.currency ?? null);
  // An index is followed, not held: no position block even if a ledger row
  // somehow names one.
  const held = shape.holdable && position?.held ? position : null;
  // The price restated in the reader's own money, for a reader who does not
  // hold the name: a holder reads their euros on the value tile instead, and
  // the same conversion printed twice in one row is noise. Only set once
  // `/quote` found a currency other than the reader's own and a rate to
  // restate it at — a bare number here would read as the reader's money, and
  // a KRW close is not that. Never for an index: its level is points, and
  // points restated in euros are a number that is nobody's money.
  const approxLine =
    !held && !shape.points && known(quote?.price_base)
      ? approx(quote.price_base, quote.base)
      : "";
  const tiles = held
    ? positionTiles(held, live, dayPct, dim, quote, shape.units, t)
    : [];
  // Why the price moved, when a report landed this week.
  const recent = recentResults(events, today);

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
          dim={dim}
          sessionNote={sessionNote}
          periodLine={periodLine}
          periodUp={periodPct !== null && periodPct >= 0}
          tiles={tiles}
          cells={cells}
          currency={unit}
          approxLine={approxLine}
          recent={recent}
          t={t}
        />
      ) : (
        // The price, the kind's cells, then the holding's three: the holding
        // sits in the price row, beside the price it is valued at, rather
        // than in a card further down.
        <>
          <Metrics>
            <Metric
              // Extended hours are named in the label, the way the page names
              // them: "Price · pre-market". A day move printed without that reads
              // as today's session when it is not.
              label={t("ticker.price") + (sessionNote ? ` · ${sessionNote}` : "")}
              value={live === null ? DASH : `${money(live)}${unit ? ` ${unit}` : ""}`}
              delta={dayPct}
              dim={dim}
              note={[periodLine, approxLine].filter(Boolean).join(" · ")}
              noteTone={periodPct === null ? null : periodPct >= 0 ? "green" : "red"}
            />
            {cells.map((one) => (
              <CellTile key={one.id} one={one} />
            ))}
            {tiles.map((one) => (
              <Kpi
                key={one.key}
                label={one.label}
                help={one.help}
                value={one.value}
                chip={one.chip}
                note={one.note}
                noteTone={one.noteTone}
              />
            ))}
          </Metrics>
          {recent ? <ResultsLine event={recent} t={t} /> : null}
        </>
      )}

      {query.state !== "loaded" ? (
        // Loading, failed or signed out: the chart's slot says so, and the
        // controls above stay where they are.
        <Loaded query={query} skeleton={<PriceChartWait mobile={mobile} />}>
          {() => null}
        </Loaded>
      ) : bars && bars.dates.length === 0 ? (
        <Empty>{t("ticker.history_empty")}</Empty>
      ) : bars ? (
        <PriceChart
          bars={bars}
          events={events}
          cycle={cycle}
          trades={held?.trades ?? []}
          avgCost={held?.avg_cost_native ?? null}
          candles={shape.candles && candles}
          overlays={shape.overlays}
          markers={shape.markers}
          mobile={mobile}
          onWindow={setZoomed}
          t={t}
        />
      ) : null}

      <LastBuy position={held} last={live} units={shape.units} t={t} />
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
  /** The price the row above is valued at. */
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
  tiles,
  cells,
  currency,
  approxLine,
  recent,
  t,
}: {
  price: number | null;
  dayPct: number | null;
  dim?: boolean;
  sessionNote: string;
  periodLine: string;
  periodUp: boolean;
  /** The holding's tiles; empty for a reader who does not hold the name. */
  tiles: Tile[];
  /** The kind's figures — the desktop row's cells, read as one line here. */
  cells: Cell[];
  /**
   * The listing's own quote currency — null for a coin pair or a bare guess —
   * or "pts" for an index.
   */
  currency: string | null;
  /** The price restated in the reader's own money; blank with nothing to show. */
  approxLine: string;
  /** This week's report, when there was one. */
  recent: EarningsEvent | null;
  t: Translate;
}) {
  const shown = cells.filter((one) => one.value !== DASH);
  // Not held: no tiles to fold the first figure into, so what the desktop row
  // carries stands on its own line under the price — "52w range 243 – 348 ·
  // −8,2 % off the high · P/E now 31,4 · +12 % vs 5y avg" for a share. Without
  // it a phone reader of a name they do not own gets a price and nothing to
  // read it against.
  const trendLine = shown.map(inline).join(" · ");
  // Held: the first figure folds into the tiles as the fourth of the 2×2 —
  // the year's range with its meter — and the rest keep a line of their own
  // under them, so a coin's distance from its peak is not dropped because
  // the range took the only slot.
  const lead = shown[0] ?? null;
  const restLine = shown.slice(1).map(inline).join(" · ");

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
      {tiles.length > 0 ? (
        <>
          <KpiGrid>
            {tiles.map((one) => (
              <Kpi
                key={one.key}
                label={one.label}
                help={one.help}
                value={one.value}
                chip={one.chip}
                note={one.note}
                noteTone={one.noteTone}
              />
            ))}
            {lead ? <CellTile one={lead} /> : null}
          </KpiGrid>
          {restLine ? <p className="tk-hero-trend">{restLine}</p> : null}
        </>
      ) : trendLine ? (
        <p className="tk-hero-trend">{trendLine}</p>
      ) : null}
      {recent ? <ResultsLine event={recent} t={t} /> : null}
    </div>
  );
}

/**
 * The "≈ €12,345.67" under the native price: the figure in the reporting
 * currency, with its mark ahead of the figure, not the code after it.
 */
function approx(value: number, base: string | null | undefined): string {
  return `≈ ${currencySymbol(base)}${money(value)}`;
}

/** "+€735,26" / "-$12,00": a signed amount with its currency's mark. */
function signedMoney(value: number, currency: string | null | undefined): string {
  return `${value < 0 ? "-" : "+"}${currencySymbol(currency)}${money(Math.abs(value))}`;
}

/** The local calendar day, as the API writes dates. */
function isoToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Whole days from `from` to `to`, both "YYYY-MM-DD"; negative when `to` is earlier. */
function daysBetween(from: string, to: string): number {
  const a = Date.UTC(
    Number(from.slice(0, 4)),
    Number(from.slice(5, 7)) - 1,
    Number(from.slice(8, 10)),
  );
  const b = Date.UTC(
    Number(to.slice(0, 4)),
    Number(to.slice(5, 7)) - 1,
    Number(to.slice(8, 10)),
  );
  return Math.round((b - a) / 86_400_000);
}

/**
 * The report that explains this week's move, or null: the latest reported
 * event dated within `RESULTS_FRESH_DAYS` of today. Older than that it is
 * history the chart's markers already carry; a date still to come is the next
 * results cell's, not this line's.
 */
function recentResults(events: EarningsEvent[], today: string): EarningsEvent | null {
  let best: EarningsEvent | null = null;
  for (const one of events) {
    if (one.reported_eps === null || one.date > today) continue;
    if (daysBetween(one.date, today) > RESULTS_FRESH_DAYS) continue;
    if (!best || one.date > best.date) best = one;
  }
  return best;
}

/**
 * "**Results 21 Oct 2026**  EPS 3,83 vs 5,46 est. · −29,9 % surprise": the
 * reason for the week's move, under the tiles and above the chart. Only the
 * surprise is coloured, and it carries its sign and the word beside it, so
 * the colour is never the only thing saying which way it went.
 */
function ResultsLine({ event, t }: { event: EarningsEvent; t: Translate }) {
  const fields = {
    date: calendarDay(event.date),
    eps: money(event.reported_eps),
    est: money(event.eps_estimate),
  };
  const line = known(event.eps_estimate)
    ? t("ticker.results_recent", fields)
    : t("ticker.results_recent_bare", fields);
  const surprise = event.surprise_pct;
  return (
    <p className="tk-results">
      <Bold text={line} />
      {known(surprise) ? (
        <>
          {" · "}
          <strong className={surprise >= 0 ? "tk-is-green" : "tk-is-red"}>
            {signed(surprise, 1)}%
          </strong>{" "}
          {t("ticker.hover_surprise")}
        </>
      ) : null}
    </p>
  );
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
  /** Anything drawn under the figure: the range meter. */
  extra?: ReactNode;
};

/** A cell as the app-wide tile. */
function CellTile({ one }: { one: Cell }) {
  return (
    <Kpi
      label={one.label}
      value={one.value}
      help={one.help}
      note={one.note}
      noteTone={one.tone ? bandTone(one.tone) : null}
    >
      {one.extra}
    </Kpi>
  );
}

/** "52w range 243 – 348 · −8,2 % off the high": a cell as a phrase of the phone's summary line. */
function inline(one: Cell): string {
  return [`${one.short ?? one.label} ${one.value}`, one.note]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Where today's price sits between the year's low and high, as a track with
 * a dot. Decoration for a sighted reader: the cell's note says the same in
 * words ("−8,2 % off the high"), so the meter is hidden from a screen reader
 * rather than read out as an empty span.
 */
function RangeMeter({ at }: { at: number }) {
  return (
    <span className="tk-range" aria-hidden="true">
      <span className="tk-range-dot" style={{ left: `${at * 100}%` }} />
    </span>
  );
}

/**
 * The year's low and high, from whichever source has them: a coin's `/crypto`
 * stats, the quote's own row (Yahoo's, in the listing's currency), or the
 * bars on screen when they reach back a full year — a Finnhub quote has no
 * year, and a reader on the 5y range still gets the cell.
 */
function yearRange(
  quote: Quote | null,
  stats: AssetStats | null,
  bars: Bars | null,
): { low: number; high: number } | null {
  if (known(stats?.high_52w) && known(stats?.low_52w)) {
    return { low: stats.low_52w, high: stats.high_52w };
  }
  if (known(quote?.high_52w) && known(quote?.low_52w)) {
    return { low: quote.low_52w, high: quote.high_52w };
  }
  if (!bars || bars.dates.length < 2) return null;
  const lastDay = (bars.dates[bars.dates.length - 1] ?? "").slice(0, 10);
  const firstDay = (bars.dates[0] ?? "").slice(0, 10);
  if (!firstDay || !lastDay || daysBetween(firstDay, lastDay) < 365) return null;
  const since = daysBetween(firstDay, lastDay) - 365;
  let low = Infinity;
  let high = -Infinity;
  (bars.series.Close ?? []).forEach((one, i) => {
    if (!known(one)) return;
    const day = (bars.dates[i] ?? "").slice(0, 10);
    if (daysBetween(firstDay, day) < since) return;
    low = Math.min(low, one);
    high = Math.max(high, one);
  });
  return Number.isFinite(low) && Number.isFinite(high) ? { low, high } : null;
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
 * A figure its feed has not answered yet — or does not have — prints a dash
 * in its cell rather than moving the row about: the layout is the kind's,
 * the data fills it in.
 */
function cell(
  id: MetricId,
  {
    bars,
    live,
    fund,
    stats,
    quote,
    valuation,
    trend,
    events,
    today,
    t,
  }: {
    bars: Bars | null;
    /** The price the row is read at — the tile's, not always the last bar. */
    live: number | null;
    fund: Fund | null;
    stats: AssetStats | null;
    quote: Quote | null;
    valuation: Valuation | null;
    trend: Trend | null;
    events: EarningsEvent[];
    today: string;
    t: Translate;
  },
): Cell {
  switch (id) {
    case "range_52w": {
      const year = yearRange(quote, stats, bars);
      const label = t("ticker.range_52w");
      const help = t("ticker.range_52w_help");
      if (!year || live === null || year.high <= 0) {
        return { id, label, value: DASH, help, note: "", tone: null };
      }
      // A share over 100 reads whole — "243 – 348" — and a penny stock keeps
      // its cents: the range is a frame for the price, not a quote.
      const digits = year.high >= 100 ? 0 : 2;
      const span = year.high - year.low;
      const at = span > 0 ? Math.min(1, Math.max(0, (live - year.low) / span)) : 1;
      const offHigh = live / year.high - 1;
      return {
        id,
        label,
        value: `${money(year.low, digits)} – ${money(year.high, digits)}`,
        help,
        // Within half a tenth of the high is at it: a pre-market print a cent
        // over last year's intraday peak is not "+0,0 % off the high".
        note:
          offHigh >= -0.0005
            ? t("ticker.at_high")
            : t("ticker.off_high", { pct: signedPercent(offHigh, 1) }),
        tone: null,
        extra: <RangeMeter at={at} />,
      };
    }
    case "trend": {
      const label = t("ticker.trend");
      const help = t("ticker.trend_help");
      // Under ~11 months of bars there is no 200-day average with a slope to
      // read: the cell says the history is short rather than guess a side.
      if (!trend?.state) {
        const short = trend !== null && trend.price !== null;
        return {
          id,
          label,
          value: DASH,
          help,
          note: short ? t("ticker.trend_short") : "",
          tone: null,
        };
      }
      // The distance from the high is the range cell's; this one adds what
      // the range cannot say: the year's momentum and the home index.
      const note = [
        known(trend.mom_12_1)
          ? t("ticker.trend_momentum", { pct: signedPercent(trend.mom_12_1, 0) })
          : "",
        known(trend.rs_12m) && trend.bench_name
          ? t("ticker.trend_vs", {
              pct: signedPercent(trend.rs_12m, 0),
              index: trend.bench_name,
            })
          : "",
      ]
        .filter(Boolean)
        .join(" · ");
      // The colour lands on the note, so it goes only where the momentum agrees
      // with the average: a coin back above a rising line after a crash reads
      // "up" with a -24 % year, and a green -24 % says the opposite of itself.
      const side = trend.state === "up" ? 1 : trend.state === "down" ? -1 : 0;
      const agrees = !known(trend.mom_12_1) || side * trend.mom_12_1 >= 0;
      return {
        id,
        label,
        value: t(`ticker.trend_${trend.state}`),
        help,
        note,
        // Spelled out in the figure as well, so the colour is never the only
        // carrier of which way it runs.
        tone: side && agrees ? (side > 0 ? "green" : "red") : null,
      };
    }
    case "pe": {
      const current = valuation?.current ?? null;
      // Five years is the frame the valuation card opens on; the first window
      // stands in for a company younger than that.
      const window =
        valuation?.windows.find((one) => one.window === "5y") ??
        valuation?.windows[0] ??
        null;
      const premium = window?.premium ?? null;
      const percentile = window?.percentile ?? null;
      const label = t("ticker.kpi_pe_current");
      const help = t("ticker.kpi_pe_current_help");
      if (current === null) {
        return { id, label, value: DASH, help, note: "", tone: null };
      }
      return {
        id,
        label,
        value: num(current, 1),
        help,
        // Against its own average when there is one; the grid's band when
        // the history is too short to have one.
        note:
          window && known(premium)
            ? t("ticker.pe_vs_avg", {
                pct: signedPercent(premium, 0),
                rng: window.window,
              })
            : orElse(t, `ticker.verdict_${valuation?.current_verdict ?? ""}`, ""),
        // The same thresholds the valuation card bands on: the top fifth of
        // its own history is rich, the bottom fifth cheap, the rest unsaid.
        tone:
          percentile === null
            ? (valuation?.current_tone ?? null)
            : percentile >= 80
              ? "red"
              : percentile <= 20
                ? "green"
                : null,
      };
    }
    case "next_results": {
      const label = t("ticker.next_results");
      const help = t("ticker.next_results_help");
      let next: EarningsEvent | null = null;
      let lastReported: EarningsEvent | null = null;
      for (const one of events) {
        if (one.reported_eps === null && one.date >= today) {
          if (!next || one.date < next.date) next = one;
        } else if (one.reported_eps !== null) {
          if (!lastReported || one.date > lastReported.date) lastReported = one;
        }
      }
      if (!next) {
        return {
          id,
          label,
          value: DASH,
          help,
          note: lastReported
            ? t("ticker.last_results", { date: calendarDay(lastReported.date) })
            : "",
          tone: null,
        };
      }
      const days = daysBetween(today, next.date);
      return {
        id,
        label,
        value: calendarDay(next.date),
        help,
        note:
          days === 0
            ? t("ticker.results_today")
            : days === 1
              ? t("ticker.in_one_day")
              : t("ticker.in_days", { n: days }),
        tone: null,
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
        value: years === null ? DASH : t("ticker.years", { n: num(years, 1) }),
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
    case "ath_drawdown": {
      const peak = stats?.ath ?? null;
      // Measured against the price on the tile, not a night-old peak's own
      // price: a coin past last night's high is at its peak, never above it.
      const drop = live !== null && peak ? Math.min(0, live / peak - 1) : null;
      return {
        id,
        label: t("ticker.ath_label"),
        short: t("ticker.ath_short"),
        value: drop === null ? DASH : signedPercent(drop, 1),
        help: t("ticker.ath_help"),
        // A peak read off a year of bars is not an all-time high, and the
        // cell says which one it is measured from.
        note:
          drop === null
            ? ""
            : stats?.ath_source === "52w"
              ? t("ticker.ath_52w")
              : stats?.ath_date
                ? t("ticker.ath_on", { date: stats.ath_date })
                : "",
        tone: null,
      };
    }
  }
}

/** "67 shares", or "0.0773 units" for a coin, which has no shares. */
function countNote(t: Translate, count: number, units: boolean): string {
  return units
    ? t("ticker.n_units", { n: shares(count) })
    : t("ticker.n_shares", { n: shares(count) });
}

/** One of the holding's tiles, ready for `Kpi` in either layout. */
type Tile = {
  key: "value" | "gain" | "weight";
  label: string;
  help?: string;
  value: string;
  chip?: ChipSpec | null;
  note?: string;
  noteTone?: Tone | null;
};

/**
 * The holding's three figures: value, gain and weight, in this order and in
 * the reader's own money.
 *
 * One function for both layouts — the phone tiles and the desktop price row —
 * because the arithmetic is the part that must not differ. The native value
 * is the count times the price on the tile; it is restated through the same
 * rate `/quote` restated the price with (which also absorbs a minor-unit
 * listing — pence against pounds), and falls back to `/position`'s own pass,
 * a close older than the tile, marked "≈". The gain is that value less the
 * basis `/position` carries in the reader's money at each trade's rate, so
 * it is the gain the Portfolio page prints, FX moves included; without that
 * basis it is the native gain, which says less and is labelled as such by
 * its currency.
 */
function positionTiles(
  position: TickerPosition,
  live: number | null,
  dayPct: number | null,
  dim: boolean,
  quote: Quote | null,
  units: boolean,
  t: Translate,
): Tile[] {
  const count = position.shares ?? null;
  const native = position.currency ?? "";
  const base = position.base ?? null;
  const valueNative = count !== null && live !== null ? count * live : null;
  // Case-sensitive on purpose: "GBp" is not "GBP", and a pence value printed
  // as pounds is a hundredfold.
  const sameMoney = Boolean(native && base && native === base);
  const rate =
    quote && known(quote.price_base) && known(quote.price) && quote.price !== 0
      ? quote.price_base / quote.price
      : null;
  let valueBase: number | null = null;
  let approxValue = false;
  if (valueNative !== null && sameMoney) {
    valueBase = valueNative;
  } else if (valueNative !== null && rate !== null) {
    valueBase = valueNative * rate;
  } else if (known(position.value)) {
    valueBase = position.value;
    approxValue = true;
  }
  const money_ = (value: number) => `${currencySymbol(base)}${money(value)}`;

  // Today's move in the reader's money: the value now against the value
  // before the day's change, off the same percentage the price tile shows.
  const todayBase =
    valueBase !== null && dayPct !== null && dayPct > -1
      ? valueBase - valueBase / (1 + dayPct)
      : null;
  const value: Tile = {
    key: "value",
    label: t("ticker.position_value"),
    help: t("ticker.position_value_help"),
    value:
      valueBase === null
        ? valueNative === null
          ? DASH
          : `${money(valueNative)} ${native}`.trim()
        : `${approxValue ? "≈ " : ""}${money_(valueBase)}`,
    chip:
      todayBase === null
        ? null
        : chipFor(
            dayPct,
            t("ticker.today_chip", { amt: signedMoney(todayBase, base) }),
            dim,
          ),
    note:
      valueBase !== null && valueNative !== null && !sameMoney
        ? `${money(valueNative)} ${native}`.trim()
        : "",
  };

  const basis = position.cost_base ?? null;
  let gainBase: number | null = null;
  let gainNative: number | null = null;
  if (valueBase !== null && known(basis)) {
    gainBase = valueBase - basis;
  } else if (valueNative !== null && known(position.cost_native)) {
    gainNative = valueNative - position.cost_native;
  }
  const gainPct =
    gainBase !== null && known(basis) && basis !== 0
      ? gainBase / basis
      : gainNative !== null && known(position.cost_native) && position.cost_native !== 0
        ? gainNative / position.cost_native
        : null;
  const gain: Tile = {
    key: "gain",
    label: t("ticker.unrealised_pl"),
    help: t("ticker.unrealised_pl_help"),
    value:
      gainBase !== null
        ? signedMoney(gainBase, base)
        : gainNative !== null
          ? `${signed(gainNative)} ${native}`.trim()
          : DASH,
    chip: chipFor(gainPct, gainPct === null ? null : signedPercent(gainPct, 2)),
    note: known(position.avg_cost_native)
      ? t("ticker.avg_cost_note", {
          avg: `${money(position.avg_cost_native)} ${native}`.trim(),
        })
      : "",
  };

  const weight: Tile = {
    key: "weight",
    label: t("ticker.pct_portfolio"),
    help: t("ticker.pct_portfolio_help"),
    value: known(position.weight) ? `${num(position.weight * 100, 1)}%` : DASH,
    note: count === null ? "" : countNote(t, count, units),
  };

  return [value, gain, weight];
}
