/**
 * A coin's page past the price: the reader's own coin, where it sits in its
 * cycle, and what the leveraged crowd is paying to hold it.
 *
 * A share has accounts and analysts to anchor it; a coin has neither. What
 * stands in for them here is context, in the order a reader asks for it:
 *
 * - **Your coin** — its share of the reader's crypto and of the whole book,
 *   where it is held, and, held at a loss, what selling it today would save in
 *   tax (the engine's replay, repurchase rule included). Only when it is held.
 * - **Cycle** — the market's mood (Fear & Greed), bitcoin's share of it, and
 *   the coin against its own long averages (Mayer multiple, 200-week), its
 *   volatility, its strength against bitcoin, and the halving clock.
 * - **Derivatives** — perpetual-swap funding and open interest: whether
 *   leverage is crowding one side.
 *
 * Every band is the server's (`analysis.crypto_market`) and coloured as the
 * RSI is: stretched low green, stretched high red. Context, not a call — the
 * card notes say so.
 */

import { useT } from "../../shell/i18n";
import { Kpi, bandTone } from "../../ui/Kpi";
import { DASH, compactMoney, percent, signedPercent, type Translate } from "./format";
import { Banner, Card, Metric, Metrics, Note } from "./ui";
import type { Banded, CryptoCycle, CryptoHolding, CryptoPositioning } from "./types";

// ------------------------------------------------------------------ the bands
// Switches of literal keys, so the catalog scan sees every one; a band this
// page has no words for prints nothing rather than a raw slug.

function fearGreedBand(t: Translate, band: string | null | undefined): string {
  switch (band) {
    case "extreme_fear":
      return t("ticker.fg_extreme_fear");
    case "fear":
      return t("ticker.fg_fear");
    case "neutral":
      return t("ticker.fg_neutral");
    case "greed":
      return t("ticker.fg_greed");
    case "extreme_greed":
      return t("ticker.fg_extreme_greed");
    default:
      return "";
  }
}

function mayerBand(t: Translate, band: string | null | undefined): string {
  switch (band) {
    case "deep":
      return t("ticker.mayer_deep");
    case "below":
      return t("ticker.mayer_below");
    case "normal":
      return t("ticker.mayer_normal");
    case "stretched":
      return t("ticker.mayer_stretched");
    default:
      return "";
  }
}

function ratio200wBand(t: Translate, band: string | null | undefined): string {
  switch (band) {
    case "under":
      return t("ticker.w200_under");
    case "over":
      return t("ticker.w200_over");
    case "far_over":
      return t("ticker.w200_far_over");
    default:
      return "";
  }
}

function fundingBand(t: Translate, band: string | null | undefined): string {
  switch (band) {
    case "negative":
      return t("ticker.funding_negative");
    case "neutral":
      return t("ticker.funding_neutral");
    case "hot":
      return t("ticker.funding_hot");
    case "extreme":
      return t("ticker.funding_extreme");
    default:
      return "";
  }
}

function sizingLine(t: Translate, sizing: CryptoHolding["sizing"]): string {
  switch (sizing) {
    case "under":
      return t("ticker.sleeve_under");
    case "within":
      return t("ticker.sleeve_within");
    case "over":
      return t("ticker.sleeve_over");
    default:
      return "";
  }
}

/** A ratio like the Mayer multiple: "1.42×". */
const times = (value: number | null | undefined) =>
  value === null || value === undefined ? DASH : `${value.toFixed(2)}×`;

/** A funding rate per eight hours: four places, it lives around 0.0100%. */
const rate = (value: number | null | undefined) =>
  value === null || value === undefined ? DASH : `${(value * 100).toFixed(4)}%`;

/** A relative return's tone: beat is green, lagged red — a fact, not a band. */
const signTone = (value: number | null | undefined) =>
  value === null || value === undefined || value === 0
    ? null
    : value > 0
      ? "green"
      : "red";

function present(
  banded: Banded | null | undefined,
): banded is Banded & { value: number } {
  return Boolean(banded) && banded!.value !== null;
}

// ------------------------------------------------------------------ your coin

export function HoldingSection({
  holding,
  coin,
}: {
  holding: CryptoHolding;
  coin: string;
}) {
  const t = useT();
  if (!holding.held) return null;
  const harvest = holding.harvest;
  return (
    <Card title={t("ticker.your_coin", { coin })}>
      <Metrics>
        <Metric
          label={t("ticker.coin_weight")}
          value={percent(holding.crypto_weight, 1)}
          help={t("ticker.coin_weight_help")}
        />
        <Metric
          label={t("ticker.sleeve_share")}
          value={percent(holding.crypto_share, 1)}
          help={t("ticker.sleeve_help")}
          note={sizingLine(t, holding.sizing)}
          noteTone={holding.sizing === "over" ? "orange" : null}
        />
        {holding.custody.length ? (
          <Metric label={t("ticker.custody")} value={holding.custody.join(" · ")} />
        ) : null}
      </Metrics>
      {harvest ? (
        <Banner tone={harvest.blocked ? "warn" : "good"}>
          {harvest.blocked
            ? t("ticker.harvest_blocked", {
                loss: compactMoney(harvest.loss, harvest.currency),
              })
            : t("ticker.harvest_line", {
                loss: compactMoney(harvest.loss, harvest.currency),
                saving: compactMoney(harvest.saving, harvest.currency),
              })}
          {!harvest.blocked && harvest.clear_on
            ? ` ${t("ticker.harvest_window", { date: harvest.clear_on })}`
            : ""}
        </Banner>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------- cycle

/**
 * Ninety days of Fear & Greed as a line on its 0–100 scale, with the 25 and 75
 * edges of the extreme bands dotted in — where the line sits against them is
 * the whole reading at this size.
 */
function FearGreedSpark({ history }: { history: [string, number][] }) {
  if (history.length < 2) return null;
  const width = 160;
  const height = 32;
  const x = (i: number) => (i / (history.length - 1)) * width;
  const y = (v: number) => height - (v / 100) * height;
  const points = history.map(([, v], i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  return (
    <svg
      className="tk-fg-spark"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <line className="tk-fg-edge" x1={0} x2={width} y1={y(25)} y2={y(25)} />
      <line className="tk-fg-edge" x1={0} x2={width} y1={y(75)} y2={y(75)} />
      <polyline className="tk-fg-line" points={points.join(" ")} />
    </svg>
  );
}

export function CycleSection({ cycle, coin }: { cycle: CryptoCycle; coin: string }) {
  const t = useT();
  const fg = cycle.fear_greed;
  const halving = cycle.halving;
  const vsBtc = cycle.vs_btc_90d;
  const vsNdx = cycle.vs_nasdaq_90d;
  const anything =
    present(fg) ||
    cycle.btc_dominance !== null ||
    present(cycle.mayer) ||
    cycle.vol30 !== null ||
    halving !== null;
  if (!anything) return null;
  return (
    <Card
      title={t("ticker.cycle_title")}
      note={
        cycle.scan_date ? t("ticker.cycle_as_of", { date: cycle.scan_date }) : undefined
      }
    >
      <Metrics>
        {present(fg) ? (
          <Kpi
            label={t("ticker.fear_greed")}
            help={t("ticker.fear_greed_help")}
            value={String(Math.round(fg.value))}
            note={[
              fearGreedBand(t, fg.band),
              cycle.fear_greed_week !== null
                ? t("ticker.fg_week", { n: Math.round(cycle.fear_greed_week) })
                : "",
            ]
              .filter(Boolean)
              .join(" · ")}
            noteTone={bandTone(fg.tone)}
          >
            <FearGreedSpark history={cycle.fear_greed_history} />
          </Kpi>
        ) : null}
        {cycle.btc_dominance !== null ? (
          <Metric
            label={t("ticker.btc_dominance")}
            help={t("ticker.btc_dominance_help")}
            value={percent(cycle.btc_dominance / 100, 1)}
            note={
              cycle.total_mcap !== null
                ? t("ticker.total_mcap", {
                    value: compactMoney(cycle.total_mcap, cycle.quote),
                  })
                : ""
            }
          />
        ) : null}
        {present(cycle.mayer) ? (
          <Metric
            label={t("ticker.mayer")}
            help={t("ticker.mayer_help")}
            value={times(cycle.mayer.value)}
            note={mayerBand(t, cycle.mayer.band)}
            noteTone={cycle.mayer.tone}
          />
        ) : null}
        {present(cycle.ratio_200w) ? (
          <Metric
            label={t("ticker.w200")}
            help={t("ticker.w200_help")}
            value={times(cycle.ratio_200w.value)}
            note={ratio200wBand(t, cycle.ratio_200w.band)}
            noteTone={cycle.ratio_200w.tone}
          />
        ) : null}
        {cycle.vol30 !== null ? (
          <Metric
            label={t("ticker.vol30")}
            help={t("ticker.vol30_help")}
            value={percent(cycle.vol30, 0)}
          />
        ) : null}
        {vsBtc !== null ? (
          <Metric
            label={t("ticker.vs_btc")}
            help={t("ticker.vs_btc_help", { coin })}
            value={signedPercent(vsBtc, 1)}
            note={t(vsBtc >= 0 ? "ticker.vs_beat" : "ticker.vs_lagged")}
            noteTone={signTone(vsBtc)}
          />
        ) : null}
        {vsNdx !== null ? (
          <Metric
            label={t("ticker.vs_nasdaq")}
            help={t("ticker.vs_nasdaq_help")}
            value={signedPercent(vsNdx, 1)}
            note={t(vsNdx >= 0 ? "ticker.vs_beat" : "ticker.vs_lagged")}
            noteTone={signTone(vsNdx)}
          />
        ) : null}
        {halving ? (
          <Kpi
            label={t("ticker.halving")}
            help={t("ticker.halving_help")}
            value={t("ticker.halving_since", { n: halving.days_since })}
            note={t("ticker.halving_next", { date: halving.next_est })}
          >
            <span className="tk-meter" aria-hidden="true">
              <span style={{ width: `${Math.round(halving.progress * 100)}%` }} />
            </span>
          </Kpi>
        ) : null}
      </Metrics>
      <Note>{t("ticker.cycle_caption")}</Note>
    </Card>
  );
}

// ---------------------------------------------------------------- derivatives

/** The venue as people write it, not as the API slugs it. */
function venueName(venue: string): string {
  switch (venue) {
    case "bybit":
      return "Bybit";
    case "binance":
      return "Binance";
    case "okx":
      return "OKX";
    default:
      return venue;
  }
}

export function PositioningSection({ data }: { data: CryptoPositioning }) {
  const t = useT();
  const now = data.funding_8h;
  const week = data.funding_7d_8h;
  return (
    <Card
      title={t("ticker.positioning_title")}
      note={`${venueName(data.venue)} · ${data.symbol}`}
    >
      <Metrics>
        <Metric
          label={t("ticker.funding_now")}
          help={t("ticker.funding_help")}
          value={rate(now?.value)}
          note={fundingBand(t, now?.band)}
          noteTone={now?.tone ?? null}
        />
        <Metric
          label={t("ticker.funding_week")}
          value={rate(week?.value)}
          note={
            data.annualized !== null
              ? t("ticker.funding_annual", { pct: signedPercent(data.annualized, 1) })
              : ""
          }
          noteTone={week?.tone ?? null}
        />
        <Metric
          label={t("ticker.open_interest")}
          help={t("ticker.open_interest_help")}
          value={compactMoney(data.oi_usd, "USD")}
          note={
            data.oi_change_7d !== null
              ? t("ticker.oi_week", { pct: signedPercent(data.oi_change_7d, 1) })
              : ""
          }
        />
      </Metrics>
      <Note>{t("ticker.positioning_caption")}</Note>
    </Card>
  );
}
