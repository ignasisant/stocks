/**
 * Projection — where the book's value could be some years out, as a range.
 *
 * Not a forecast, and the page says so: a percentile fan drawn from today's
 * value under assumptions the reader can see and move. The book moves as two
 * sleeves, stocks and crypto, because one blended volatility describes
 * neither: each gets its own growth rate and its own measured volatility,
 * correlated as they have been. Growth is the median compound rate — what
 * "8% a year" means to anyone reading it — and the stock presets are named
 * after the indices they come from. The book's own rate (today's holdings
 * over the volatility's window) is one more option, never the default.
 */

import { useState, type ReactNode } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { chart } from "../../shell/theme";
import {
  CRYPTO_GROWTH,
  CRYPTO_SHARES,
  OWN_GROWTH,
  PROJECTION_YEARS,
  STOCK_PRESETS,
  type Projection as ProjectionData,
} from "./api";
import { compactMoneyIn, moneyIn, percent } from "./format";
import { ReturnLines, type ReturnSeries } from "./charts";
import { Caption, Chip, Empty, Segmented } from "./ui";
import { Help } from "../../ui/Kpi";

type StockPreset = keyof typeof STOCK_PRESETS | typeof OWN_GROWTH;
type CryptoGrowth = (typeof CRYPTO_GROWTH)[number] | typeof OWN_GROWTH;
type CryptoShare = (typeof CRYPTO_SHARES)[number];

export default function Projection() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const money = moneyIn(lang, base);
  const compact = compactMoneyIn(lang, base);
  const [years, setYears] = useState<(typeof PROJECTION_YEARS)[number]>("5");
  const [stocks, setStocks] = useState<StockPreset>("world");
  const [crypto, setCrypto] = useState<CryptoGrowth>("0");
  const [share, setShare] = useState<CryptoShare>("today");
  const [real, setReal] = useState<"nominal" | "real">("nominal");
  const [target, setTarget] = useState<number | null>(null);
  // Zero until the reader types one: the fan opens on what is already in,
  // and the last twelve months' average sits beside the box as a hint.
  const [monthly, setMonthly] = useState(0);

  const query = useApi(
    () =>
      get<ProjectionData>("/portfolio/projection", {
        base,
        years,
        // "own" lets the server read the rate it measures, so it is never a
        // stale number carried over from another currency's answer.
        stock_growth: stocks === OWN_GROWTH ? undefined : STOCK_PRESETS[stocks] / 100,
        stock_own: stocks === OWN_GROWTH ? "true" : undefined,
        crypto_growth: crypto === OWN_GROWTH ? undefined : Number(crypto) / 100,
        crypto_own: crypto === OWN_GROWTH ? "true" : undefined,
        crypto_share: share === "today" ? undefined : Number(share) / 100,
        monthly,
        real: real === "real" ? "true" : undefined,
        target: target ?? undefined,
      }),
    [base, years, stocks, crypto, share, monthly, real, target],
  );
  // Every control refetches. Holding the last answer on screen (dimmed)
  // while the next one draws keeps the panel under the reader's hand instead
  // of swapping the whole view for a skeleton on each click.
  const [last, setLast] = useState<ProjectionData | null>(null);
  if (query.state === "loaded" && query.data !== last) setLast(query.data);
  const data = query.state === "loaded" ? query.data : last;

  const signed = (fraction: number) =>
    percent(lang, fraction, { digits: 1, signed: true }) ?? "";
  const pct = (fraction: number | null | undefined, digits = 0) =>
    percent(lang, fraction ?? null, { digits }) ?? "";
  const date = new Intl.DateTimeFormat(lang, { month: "short", year: "2-digit" });
  const formatDate = (iso: string) => date.format(new Date(`${iso}T00:00:00`));
  const longDate = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric" });

  if (!data || query.state === "failed" || query.state === "signed-out")
    return (
      <Loaded query={query} skeleton={<Skeleton rows={10} />}>
        {() => null}
      </Loaded>
    );

  const stock = data.sleeves.find((one) => one.key === "stocks");
  const coin = data.sleeves.find((one) => one.key === "crypto");
  const contributed = data.contributed.at(-1) ?? null;
  const median = data.p50.at(-1) ?? null;
  const low = data.p10.at(-1) ?? null;
  const high = data.p90.at(-1) ?? null;
  const onIn = (end: number | null) =>
    end === null || !contributed ? null : end / contributed - 1;
  const end = data.dates.at(-1);
  const palette = chart();
  // The book's own rate is offered only once there is a year of it to read.
  const ownOption = <T extends string>(
    options: readonly T[],
    measured?: number | null,
  ): readonly (T | typeof OWN_GROWTH)[] =>
    measured === null || measured === undefined ? options : [...options, OWN_GROWTH];

  const panel = (
    <aside className="pf-proj-panel" aria-label={t("portfolio.projection_assumptions")}>
      <PanelGroup title={t("portfolio.projection_plan")}>
        <AmountField
          label={t("portfolio.projection_monthly")}
          value={data.monthly}
          suffix="€"
          hint={t("portfolio.projection_monthly_hint", {
            amount: money(data.monthly_suggested) ?? "",
          })}
          onCommit={(value) => setMonthly(value ?? 0)}
        />
        {/* The same plan said in total, today's value included, as the
            figure beside the chart reads. Either box sets the monthly
            amount the server draws with; the other is recomputed. */}
        <AmountField
          label={t("portfolio.projection_total_input", { n: data.years })}
          value={data.real ? null : (contributed ?? 0)}
          suffix="€"
          disabled={data.real}
          onCommit={(total) => {
            if (total === null) return;
            const months = data.dates.length - 1;
            const extra = total - (data.start_value ?? 0);
            setMonthly(
              months > 0 ? Math.max(Math.round((extra / months) * 100) / 100, 0) : 0,
            );
          }}
        />
        <AmountField
          label={t("portfolio.projection_target")}
          value={target}
          suffix="€"
          placeholder={t("portfolio.projection_target_placeholder")}
          onCommit={setTarget}
        />
      </PanelGroup>
      <PanelGroup title={t("portfolio.projection_assumptions")}>
        <Segmented
          label={t("portfolio.projection_stocks")}
          options={ownOption(
            Object.keys(STOCK_PRESETS) as (keyof typeof STOCK_PRESETS)[],
            stock?.own_growth,
          )}
          value={stocks}
          onChange={setStocks}
          format={(option) =>
            option === OWN_GROWTH
              ? t("portfolio.projection_preset_own", { rate: pct(stock?.own_growth) })
              : t(`portfolio.projection_preset_${option}`, {
                  rate: STOCK_PRESETS[option],
                })
          }
        />
        {/* Crypto gets its own growth and its own share of each
            contribution, and only when there is crypto to move. */}
        {data.crypto_weight > 0 ? (
          <>
            <Segmented
              label={t("portfolio.projection_crypto", {
                weight: pct(data.crypto_weight),
              })}
              options={ownOption(CRYPTO_GROWTH, coin?.own_growth)}
              value={crypto}
              onChange={setCrypto}
              format={(option) =>
                option === OWN_GROWTH
                  ? t("portfolio.projection_crypto_own", {
                      rate: pct(coin?.own_growth),
                    })
                  : `${option}%`
              }
            />
            <Segmented
              label={t("portfolio.projection_crypto_share")}
              options={CRYPTO_SHARES}
              value={share}
              onChange={setShare}
              format={(option) =>
                option === "today"
                  ? t("portfolio.projection_share_today", {
                      weight: pct(data.crypto_weight),
                    })
                  : `${option}%`
              }
            />
          </>
        ) : null}
        <Segmented
          label={t("portfolio.projection_money")}
          options={["nominal", "real"] as const}
          value={real}
          onChange={setReal}
          format={(option) => t(`portfolio.projection_money_${option}`)}
        />
      </PanelGroup>
    </aside>
  );

  return (
    <>
      <Segmented
        label={t("portfolio.projection_years")}
        options={PROJECTION_YEARS}
        value={years}
        onChange={setYears}
        format={(option) => t("portfolio.projection_years_n", { n: option })}
      />
      {!data.dates.length ? (
        <Empty
          title={t("portfolio.projection_empty")}
          body={t("portfolio.projection_empty_body")}
        />
      ) : (
        <div className="pf-proj-layout">
          <section
            className="pf-card pf-proj-main"
            aria-busy={query.state === "loading"}
          >
            {/* One focal figure: where the typical path ends, and what it is
                on the money it cost. Everything else is a supporting fact. */}
            <div className="pf-proj-hero">
              <div className="pf-proj-focus">
                <span className="pf-proj-eyebrow">
                  {t("portfolio.projection_focus", {
                    date: end ? longDate.format(new Date(`${end}T00:00:00`)) : "",
                  })}
                </span>
                <span className="pf-proj-figure">
                  {money(median) ?? t("portfolio.na")}
                </span>
                <span className="pf-proj-sub">
                  {onIn(median) !== null ? (
                    <Chip value={onIn(median)} text={signed(onIn(median)!)} />
                  ) : null}
                  <span>
                    {t("portfolio.projection_on_contributed", {
                      amount: money(contributed) ?? "",
                    })}
                  </span>
                </span>
              </div>
              <dl className="pf-proj-facts">
                <Fact
                  label={t("portfolio.projection_range")}
                  help={t("portfolio.projection_range_help")}
                  value={`${compact(low) ?? ""} – ${compact(high) ?? ""}`}
                  note={
                    onIn(low) !== null && onIn(high) !== null
                      ? `${signed(onIn(low)!)} / ${signed(onIn(high)!)}`
                      : null
                  }
                />
                <Fact
                  label={t("portfolio.projection_today")}
                  value={money(data.start_value) ?? t("portfolio.na")}
                />
                {data.target !== null && data.target_probability !== null ? (
                  <Fact
                    label={t("portfolio.projection_target_kpi", {
                      target: compact(data.target) ?? "",
                    })}
                    help={t("portfolio.projection_target_help")}
                    value={pct(data.target_probability)}
                  />
                ) : null}
              </dl>
            </div>
            {/* The road so far, then the fan: past month ends carry the
                book's real value and the money put in, the future carries
                the spread. The two meet at "today". */}
            <ReturnLines
              dates={[...data.history_dates, ...data.dates]}
              format={(value) => compact(value) ?? ""}
              formatDate={formatDate}
              marker={
                data.history_dates.length
                  ? {
                      index: data.history_dates.length,
                      label: t("portfolio.projection_now"),
                    }
                  : undefined
              }
              bands={projectionBands(
                data,
                {
                  outer: t("portfolio.projection_band_outer"),
                  inner: t("portfolio.projection_band_inner"),
                },
                palette.accentBand,
              )}
              series={projectionSeries(
                data,
                {
                  actual: t("portfolio.projection_actual"),
                  invested: t("portfolio.projection_invested"),
                  p90: t("portfolio.projection_p90"),
                  p50: t("portfolio.projection_p50"),
                  p10: t("portfolio.projection_p10"),
                  contributed: t("portfolio.projection_contributed"),
                },
                signed,
                {
                  median: palette.brandAccent,
                  actual: palette.textPrimary,
                  money: palette.textMuted,
                },
              )}
            />
            <Caption>
              {t("portfolio.projection_note_stocks", {
                weight: pct(stock?.weight),
                rate: pct(stock?.growth),
                vol: pct(stock?.volatility),
              })}
              {coin
                ? ` ${t("portfolio.projection_note_crypto", {
                    weight: pct(coin.weight),
                    rate: pct(coin.growth),
                    vol: pct(coin.volatility),
                    corr: data.correlation === null ? "—" : data.correlation.toFixed(2),
                  })}`
                : ""}
              {stock?.growth_own || coin?.growth_own
                ? ` ${t("portfolio.projection_note_own")}`
                : ""}
              {` ${t("portfolio.projection_note")}`}
              {data.real
                ? ` ${t("portfolio.projection_note_real", { rate: pct(data.inflation) })}`
                : ""}
            </Caption>
          </section>
          {panel}
        </div>
      )}
    </>
  );
}

function PanelGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="pf-proj-group">
      <legend>{title}</legend>
      {children}
    </fieldset>
  );
}

function Fact({
  label,
  value,
  note,
  help,
}: {
  label: string;
  value: string;
  note?: string | null;
  help?: string;
}) {
  return (
    <div className="pf-proj-fact">
      <dt>
        <span>{label}</span>
        <Help text={help} />
      </dt>
      <dd>
        <span className="pf-proj-fact-value">{value}</span>
        {note ? <span className="pf-proj-fact-note">{note}</span> : null}
      </dd>
    </div>
  );
}

/**
 * The fan's two shaded ranges on the chart's axis: p10–p90 (eight paths in
 * ten) and p25–p75 (half of them), both in the brand's band tint so the
 * overlap reads as the denser middle. Null over the past.
 */
function projectionBands(
  data: ProjectionData,
  labels: { outer: string; inner: string },
  color: string,
) {
  const blank: null[] = Array(data.history_dates.length).fill(null);
  return [
    {
      label: labels.outer,
      low: [...blank, ...data.p10],
      high: [...blank, ...data.p90],
      color,
    },
    {
      label: labels.inner,
      low: [...blank, ...data.p25],
      high: [...blank, ...data.p75],
      color,
    },
  ];
}

/**
 * "1.500,5", "1,500.5", "150.000" and "150000" all as the number they mean.
 * The last separator is the decimal one when both appear; a lone dot followed
 * by groups of three is a thousands dot, as a Spanish reader types it.
 */
export function parseAmount(text: string): number | null {
  let raw = text.replace(/[\s€$£]/g, "");
  if (raw.includes(",") && raw.includes(".")) {
    const decimal = raw.lastIndexOf(",") > raw.lastIndexOf(".") ? "," : ".";
    raw = raw
      .split(decimal === "," ? "." : ",")
      .join("")
      .replace(",", ".");
  } else if (/^\d{1,3}(\.\d{3})+$/.test(raw)) {
    raw = raw.replace(/\./g, "");
  } else {
    raw = raw.replace(",", ".");
  }
  const value = Number(raw);
  return raw !== "" && Number.isFinite(value) && value >= 0 ? value : null;
}

/**
 * A text box with a decimal keyboard, committed on blur or Enter, as the
 * watchlist's numbers are: a number input swallows "1.500,5" into nothing.
 */
function AmountField({
  label,
  value,
  onCommit,
  placeholder,
  disabled,
  suffix,
  hint,
}: {
  label: string;
  value: number | null;
  /** Null when the box was emptied — "no value", not zero. */
  onCommit: (value: number | null) => void;
  placeholder?: string;
  disabled?: boolean;
  suffix?: string;
  hint?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = value === null ? "" : String(Math.round(value));
  return (
    <label className="pf-proj-field">
      <span className="pf-control-label">{label}</span>
      <span className="pf-proj-input-wrap">
        <input
          className="pf-proj-input"
          inputMode="decimal"
          placeholder={placeholder}
          disabled={disabled}
          value={draft ?? shown}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={(event) => {
            setDraft(null);
            const text = event.target.value.trim();
            if (text === "") {
              if (value !== null) onCommit(null);
              return;
            }
            const parsed = parseAmount(text);
            if (parsed !== null && parsed !== value) onCommit(parsed);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
          }}
        />
        {suffix ? <span className="pf-proj-suffix">{suffix}</span> : null}
      </span>
      {hint ? <span className="pf-proj-hint">{hint}</span> : null}
    </label>
  );
}

/**
 * The chart's lines on one axis of past month ends followed by the fan's
 * months. Past lines stop at today (their last point is today's value, so
 * the real line runs into the fan instead of leaving a gap); fan lines are
 * null before it.
 */
export function projectionSeries(
  data: ProjectionData,
  labels: Record<"actual" | "invested" | "p90" | "p50" | "p10" | "contributed", string>,
  pct: (fraction: number) => string | null = () => null,
  colors: { median?: string; actual?: string; money?: string } = {},
): ReturnSeries[] {
  const past = data.history_dates.length;
  const ahead = data.dates.length;
  const blankPast: null[] = Array(past).fill(null);
  const blankAhead: null[] = Array(Math.max(ahead - 1, 0)).fill(null);
  const fan = (points: number[]) => [...blankPast, ...points];
  // Return on the money in by that date: each fan line against what had been
  // contributed by then, the real line against what had been put in.
  const moneyIn = [...data.history_invested, ...data.contributed];
  const onMoneyIn = (index: number, value: number) => {
    const base = moneyIn[index];
    return base ? pct(value / base - 1) : null;
  };
  const lines: ReturnSeries[] = [
    // The edges ride the band: read in the tooltip, not stroked twice.
    { label: labels.p90, points: fan(data.p90), tipNote: onMoneyIn, tipOnly: true },
    {
      label: labels.p50,
      points: fan(data.p50),
      tipNote: onMoneyIn,
      color: colors.median,
    },
    { label: labels.p10, points: fan(data.p10), tipNote: onMoneyIn, tipOnly: true },
    {
      label: labels.contributed,
      points: fan(data.contributed),
      dashed: true,
      color: colors.money,
    },
  ];
  if (!past) return lines;
  return [
    {
      label: labels.actual,
      color: colors.actual,
      points: [...data.history_value, data.start_value, ...blankAhead],
      // Today's point has no "put in" of its own on this axis (the fan's
      // contributed starts at today's value), so it goes without a note.
      tipNote: (index, value) => {
        const base = data.history_invested[index];
        return index < past && base ? pct(value / base - 1) : null;
      },
    },
    {
      label: labels.invested,
      points: [...data.history_invested, null, ...blankAhead],
      dashed: true,
      color: colors.money,
    },
    ...lines,
  ];
}
