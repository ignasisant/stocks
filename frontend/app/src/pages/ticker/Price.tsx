/**
 * The price block: range control, chart, and the figures beside it.
 *
 * This is the part of the page the rebuild is actually meant to improve. In
 * Streamlit it is an `@st.fragment` that reruns the whole block to change a
 * range, and the zoom readout is hand-written JS that has to survive `newPlot`
 * purging its handlers off the div. Here the range is state and the window is
 * a slice.
 *
 * The holding is folded into the hero on a phone and gets its own card on
 * desktop — the design's layout for a 390px screen, not a narrowed card.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { DASH, earliest, latest, money, signed, type Translate } from "./format";
import { PriceChart, type Window } from "./PriceChart";
import { Bold, Card, Empty, Metric, Metrics, Segmented, useMobile } from "./ui";
import type { Bars, EarningsEvent, Quote, TickerPosition } from "./types";

/** Range labels, in the order the app shows them (`analysis.history.PERIODS`). */
const RANGES = ["1d", "1w", "1m", "3m", "6m", "1y", "2y", "5y"] as const;
export type Range = (typeof RANGES)[number];

export function isRange(value: string): value is Range {
  return (RANGES as readonly string[]).includes(value);
}

/**
 * Eight pills overflow a 360px viewport, so the app drops the two in-between
 * ranges there rather than letting them wrap or scroll.
 */
const PHONE_RANGES = RANGES.filter((one) => one !== "6m" && one !== "2y");

export function PriceSection({
  bars,
  quote,
  events,
  position,
  range,
  onRange,
  candles,
  onCandles,
}: {
  bars: Bars | null;
  quote: Quote | null;
  events: EarningsEvent[];
  /** Folded into the hero on a phone; its own card on desktop. */
  position: TickerPosition | null;
  range: Range;
  onRange: (range: Range) => void;
  candles: boolean;
  onCandles: (candles: boolean) => void;
}) {
  const t = useT();
  const mobile = useMobile();
  const [window, setWindow] = useState<Window>(null);

  const close = bars?.series.Close;
  const last = latest(close);
  const first = earliest(close);
  // Off-session the quote is the honest figure: the last bar is a stale close,
  // and the page dims the day change for exactly that reason.
  const live =
    quote?.market_open === false && quote.price !== null ? quote.price : last;
  const rsi = latest(bars?.series.RSI14);
  const sma20 = latest(bars?.series.SMA20);
  const extended = quote?.session === "pre" || quote?.session === "post";
  const sessionNote =
    extended && quote?.session ? t(`ticker.session_${quote.session}`) : "";

  // Change over the SELECTED range. `bars` is already trimmed to the display
  // window, so its first close is the period's start.
  const periodPct =
    last !== null && first !== null && first !== 0
      ? ((last - first) / first) * 100
      : null;
  const periodLine =
    periodPct === null
      ? ""
      : t("ticker.period_change", {
          pct: `${signed(periodPct)}%`,
          period: t(`ticker.period_${range}`),
        });

  return (
    <Card>
      <div className="tk-controls">
        <Segmented
          label={t("ticker.period")}
          options={mobile ? PHONE_RANGES : RANGES}
          value={range}
          onChange={onRange}
          format={(one) => t(`ticker.period_${one}`)}
        />
        <Segmented
          label={t("ticker.chart_type")}
          options={["line", "candles"] as const}
          value={candles ? "candles" : "line"}
          onChange={(one) => onCandles(one === "candles")}
          format={(one) =>
            t(one === "candles" ? "ticker.chart_candles" : "ticker.chart_line")
          }
        />
      </div>

      {mobile ? (
        <Hero
          price={live}
          dayPct={quote?.pct ?? null}
          dim={quote?.market_open === false}
          sessionNote={sessionNote}
          periodLine={periodLine}
          periodUp={periodPct !== null && periodPct >= 0}
          position={position}
          last={last}
          rsi={rsi}
          rsiVerdict={bars?.rsi_verdict ?? null}
          t={t}
        />
      ) : (
        <Metrics>
          <Metric
            // Extended hours are named in the label, the way the page names
            // them: "Price · pre-market". A day move printed without that reads
            // as today's session when it is not.
            label={t("ticker.price") + (sessionNote ? ` · ${sessionNote}` : "")}
            value={live === null ? DASH : money(live)}
            delta={quote?.pct ?? null}
            dim={quote?.market_open === false}
            note={periodLine}
            noteTone={periodPct === null ? null : periodPct >= 0 ? "green" : "red"}
          />
          <Metric
            label={t("ticker.rsi_label")}
            value={rsi === null ? DASH : rsi.toFixed(1)}
            help={t("ticker.rsi_help")}
            // The band is the server's, not a threshold picked here.
            note={bars?.rsi_verdict ?? ""}
            noteTone={bars?.rsi_tone ?? null}
          />
          <Metric
            label={t("ticker.sma20_label")}
            value={sma20 === null ? DASH : money(sma20)}
            help={t("ticker.sma20_help")}
            // Price against its 20-day average: a trend read beside the level.
            note={
              last === null || sma20 === null
                ? ""
                : t(last >= sma20 ? "ticker.price_above" : "ticker.price_below")
            }
            noteTone={
              last === null || sma20 === null ? null : last >= sma20 ? "green" : "red"
            }
          />
        </Metrics>
      )}

      {bars && bars.dates.length === 0 ? (
        <Empty>{t("ticker.history_empty")}</Empty>
      ) : bars ? (
        <PriceChart
          bars={bars}
          events={events}
          trades={position?.trades ?? []}
          avgCost={position?.avg_cost_native ?? null}
          candles={candles}
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

      <LastBuy position={position} last={last} t={t} />
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
  t,
}: {
  position: TickerPosition | null;
  last: number | null;
  t: Translate;
}) {
  const buys = (position?.trades ?? []).filter((fill) => fill.action === "buy");
  const latestBuy = buys[buys.length - 1];
  if (!latestBuy || last === null) return null;
  const pct = latestBuy.price ? (last / latestBuy.price - 1) * 100 : null;
  const reading = pct === null ? DASH : `${signed(pct)}%`;
  let line = t("ticker.last_buy", {
    qty: latestBuy.quantity.toFixed(4),
    price: money(latestBuy.price),
    date: latestBuy.date,
    pct: reading,
    last: money(last),
  });
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
 * specifies for a 390px screen, and the Streamlit page builds the same one.
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
  rsi,
  rsiVerdict,
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
  rsi: number | null;
  rsiVerdict: string | null;
  t: Translate;
}) {
  const held = position?.held ? position : null;
  const rsiLine =
    rsi === null
      ? ""
      : `${t("ticker.rsi_label")} ${rsi.toFixed(1)}${rsiVerdict ? ` · ${rsiVerdict}` : ""}`;

  return (
    <div className="tk-hero">
      <div className="tk-hero-price">
        <span className="tk-hero-level">{price === null ? DASH : money(price)}</span>
        {dayPct !== null ? (
          <span
            className={`tk-pill tk-pill-${dayPct >= 0 ? "up" : "down"}${dim ? " tk-pill-dim" : ""}`}
          >
            {signed(dayPct * 100)}%
          </span>
        ) : null}
        {sessionNote ? <span className="tk-hero-session">{sessionNote}</span> : null}
        {periodLine ? (
          <span className={`tk-hero-period tk-is-${periodUp ? "green" : "red"}`}>
            {periodLine}
          </span>
        ) : null}
      </div>
      {held ? <PositionTiles position={held} last={last} note={rsiLine} t={t} /> : null}
    </div>
  );
}

/**
 * The holding as four tiles: value, unrealised P/L, weight, average cost.
 *
 * One component for both layouts — the phone hero and the desktop card under
 * the chart — because the arithmetic is the part that must not differ, and it
 * is arithmetic the server deliberately does not do: `/position` reports cost
 * in the position's own currency and prices nothing, so value and P/L are the
 * last close against that basis.
 */
export function PositionTiles({
  position,
  last,
  note,
  t,
}: {
  position: TickerPosition;
  /** The last close the chart drew — what the holding is valued at. */
  last: number | null;
  /** The line under the weight tile: RSI on a phone, nothing on desktop. */
  note?: string;
  t: Translate;
}) {
  const shares = position.shares ?? null;
  const valueNative = shares !== null && last !== null ? shares * last : null;
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
  const ccy = position.currency ?? "";

  return (
    <div className="tk-tiles">
      <Tile
        label={t("ticker.position_value")}
        value={valueNative === null ? DASH : `${money(valueNative)} ${ccy}`.trim()}
        note={
          position.value === null
            ? ""
            : `≈ ${money(position.value)} ${position.base ?? ""}`.trim()
        }
      />
      <Tile
        label={t("ticker.unrealised_pl")}
        help={t("ticker.unrealised_pl_help")}
        value={pnlNative === null ? DASH : `${signed(pnlNative)} ${ccy}`.trim()}
        valueTone={pnlNative === null ? null : pnlNative >= 0 ? "green" : "red"}
        note={pnlPct === null ? "" : `${signed(pnlPct)}%`}
        noteTone={pnlPct === null ? null : pnlPct >= 0 ? "green" : "red"}
      />
      <Tile
        label={t("ticker.pct_portfolio")}
        help={t("ticker.pct_portfolio_help")}
        value={
          position.weight === null ? DASH : `${(position.weight * 100).toFixed(1)}%`
        }
        note={note ?? ""}
      />
      <Tile
        label={t("ticker.avg_buy_price")}
        value={
          position.avg_cost_native === null
            ? DASH
            : `${money(position.avg_cost_native)} ${ccy}`.trim()
        }
        note={shares === null ? "" : t("ticker.n_shares", { n: money(shares, 4) })}
      />
    </div>
  );
}

function Tile({
  label,
  value,
  valueTone,
  note,
  noteTone,
  help,
}: {
  label: string;
  value: string;
  valueTone?: string | null;
  note?: string;
  noteTone?: string | null;
  help?: string;
}) {
  return (
    <div className="tk-tile">
      <span className="tk-tile-label" title={help}>
        {label}
        {help ? <span className="tk-q">?</span> : null}
      </span>
      <span
        className={valueTone ? `tk-tile-value tk-is-${valueTone}` : "tk-tile-value"}
      >
        {value}
      </span>
      {note ? (
        <span className={noteTone ? `tk-tile-note tk-is-${noteTone}` : "tk-tile-note"}>
          {note}
        </span>
      ) : null}
    </div>
  );
}
