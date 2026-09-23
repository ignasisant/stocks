/**
 * The charts that are not the price: reported vs projected results, the P/E
 * against its own history, a fund's sector sleeves, and insider flow by month.
 *
 * Two of these draw something a reader will act on, so both carry the caveat in
 * the picture rather than beside it: consensus bars are hatched, drawn past a
 * divider and named as consensus, and the P/E chart prints which filing feed
 * reconstructed it. A multiple with no provenance is a number somebody will
 * trade on.
 */

import { useMemo, useState } from "react";
import { useT } from "../../shell/i18n";
import { chart as palette } from "../../shell/theme";
import {
  DASH,
  compact,
  growthLabel,
  known,
  legend as legendOf,
  percent,
  yoy,
} from "./format";
import {
  Chart,
  Legend,
  Tooltip,
  YGrid,
  bounds,
  frame,
  plotWidth,
  scale,
  ticks,
  type TipLine,
} from "./plot";
import {
  Banner,
  Card,
  Empty,
  Kpi,
  Kpis,
  Note,
  Segmented,
  Subhead,
  Tag,
  useMobile,
} from "./ui";
import type { Financials, Fund, Insiders, Valuation } from "./types";

// ------------------------------------------------------------- results chart

/**
 * Reported years as grouped bars, consensus continuing them, EPS on its own
 * axis over the top.
 *
 * EPS lives on a second axis because dollars-per-share beside billions would
 * flatline on the bar scale. The forecast bars are hatched and half-opaque, and
 * the tooltip names each one "consensus" where analysts were polled and
 * "extrapolated" once the path runs past the last published estimate and is
 * only a growth rate carried forward. Drawing those two alike is the whole
 * failure mode here.
 */
function Annual({ data }: { data: Financials }) {
  const t = useT();
  const mobile = useMobile();
  const colors = palette();
  const [hover, setHover] = useState<number | null>(null);

  const years = data.annual.map((row) => row.year);
  const projection = data.projection.filter(
    (row) => row.revenue !== null || row.eps !== null,
  );
  const periods = [...years, ...projection.map((row) => row.period)];

  const hasRevenue = data.annual.some((row) => row.revenue !== null);
  const hasIncome = data.annual.some((row) => row.net_income !== null);
  const revenue = [
    ...data.annual.map((row) => row.revenue),
    ...projection.map((row) => (hasRevenue ? row.revenue : null)),
  ];
  const income = [
    ...data.annual.map((row) => row.net_income),
    ...projection.map(() => null),
  ];
  const epsPoints = data.annual.filter((row) => row.eps !== null);
  const eps = [
    ...data.annual.map((row) => row.eps),
    ...projection.map((row) => (epsPoints.length ? row.eps : null)),
  ];
  const epsLow = [
    ...data.annual.map(() => null),
    ...projection.map((row) => (epsPoints.length ? row.eps_low : null)),
  ];
  const epsHigh = [
    ...data.annual.map(() => null),
    ...projection.map((row) => (epsPoints.length ? row.eps_high : null)),
  ];

  const bars = [
    ...(hasRevenue
      ? [
          {
            key: "revenue",
            values: revenue,
            color: colors.info,
            label: t("ticker.revenue"),
          },
        ]
      : []),
    ...(hasIncome
      ? [
          {
            key: "income",
            values: income,
            color: colors.candleUp,
            label: t("ticker.net_income"),
          },
        ]
      : []),
  ];

  const box = frame({
    height: mobile ? 260 : 320,
    left: 52,
    right: epsPoints.length ? 46 : 16,
    bottom: 30,
    top: 24,
  });
  const money_ = bounds(
    bars.map((one) => one.values),
    { zero: true, pad: 0.12 },
  );
  const epsRange = bounds([eps, epsLow, epsHigh], { zero: true, pad: 0.12 });
  if (!money_ && !epsRange) return null;
  const left = money_ ?? { lo: 0, hi: 1 };
  const y = scale(left.lo, left.hi, box.height - box.bottom, box.top);
  const yEps = epsRange
    ? scale(epsRange.lo, epsRange.hi, box.height - box.bottom, box.top)
    : null;

  const band = plotWidth(box) / Math.max(1, periods.length);
  const xOf = (index: number) => box.left + (index + 0.5) * band;
  const width = Math.min(34, (band * 0.7) / Math.max(1, bars.length));

  const kindOf = (index: number): string => {
    const row = projection[index - years.length];
    if (!row) return t("ticker.k_reported");
    return row.revenue_extrapolated || row.eps_extrapolated
      ? t("ticker.k_extrapolated")
      : t("ticker.k_consensus");
  };

  const lines: TipLine[] = [];
  if (hover !== null) {
    for (const series of bars) {
      const value = series.values[hover];
      const before = hover > 0 ? (series.values[hover - 1] ?? null) : null;
      lines.push({
        text: `${series.label} ${compact(value)} ${growthLabel(yoy(value ?? null, before))}`.trim(),
      });
    }
    const point = eps[hover];
    if (known(point)) lines.push({ text: `EPS ${point.toFixed(2)}` });
    lines.push({ text: kindOf(hover) });
  }

  return (
    <div className="tk-plot">
      <Chart
        frame={box}
        label={t("ticker.chart_annual_title")}
        onPointer={(x) =>
          setHover(
            Math.max(
              0,
              Math.min(periods.length - 1, Math.floor((x - box.left) / band)),
            ),
          )
        }
        onLeave={() => setHover(null)}
      >
        <defs>
          {/* Hatched, so a forecast bar cannot be mistaken for a filed one even
              in a screenshot with no legend under it. */}
          <pattern
            id="tk-forecast"
            width="6"
            height="6"
            patternTransform="rotate(45)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="6" height="6" fill={colors.surfaceCard} />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="6"
              stroke={colors.textMuted}
              strokeWidth="2"
            />
          </pattern>
        </defs>

        <YGrid frame={box} lo={left.lo} hi={left.hi} format={(v) => compact(v)} />
        {/* The zero rule: a loss below the axis has to be visibly below it. */}
        <line
          x1={box.left}
          x2={box.width - box.right}
          y1={y(0)}
          y2={y(0)}
          stroke={colors.border}
        />

        {bars.map((series, slot) =>
          series.values.map((value, index) => {
            if (!known(value)) return null;
            const forecast = index >= years.length;
            const x = xOf(index) - (width * bars.length) / 2 + slot * width;
            return (
              <rect
                key={`${series.key}-${index}`}
                x={x}
                y={Math.min(y(value), y(0))}
                width={Math.max(1, width - 2)}
                height={Math.max(1, Math.abs(y(value) - y(0)))}
                fill={forecast ? "url(#tk-forecast)" : series.color}
                opacity={forecast ? 0.75 : 1}
                stroke={forecast ? series.color : "none"}
              />
            );
          }),
        )}

        {/* The analyst range around the EPS path, anchored at the last reported
            point so it fans out of it rather than floating beside it. */}
        {yEps && epsHigh.some((one) => one !== null) ? (
          <path
            d={bandPath(epsHigh, epsLow, eps, years.length, xOf, yEps)}
            fill={colors.accentBand}
          />
        ) : null}

        {yEps
          ? runs(eps).map((run) => (
              <polyline
                key={`eps-${run[0]}`}
                className="tk-line"
                points={run.map((i) => `${xOf(i)},${yEps(eps[i] as number)}`).join(" ")}
                stroke={colors.brandAccent}
                strokeWidth={2}
                strokeDasharray={
                  (run[run.length - 1] ?? 0) >= years.length ? "5 4" : undefined
                }
              />
            ))
          : null}

        {/* Where reported stops and consensus starts, said in the picture. */}
        {projection.length ? (
          <line
            className="tk-event"
            x1={box.left + years.length * band}
            x2={box.left + years.length * band}
            y1={box.top}
            y2={box.height - box.bottom}
            stroke={colors.textMuted}
          />
        ) : null}

        {/* The EPS scale, on the right and without gridlines of its own: two
            grids over one plot is two readings of every horizontal line. A
            second axis that is drawn but never labelled is a line whose level
            nobody can read, which is the thing Plotly's `yaxis2` was doing. */}
        {yEps && epsRange ? (
          <g className="tk-grid tk-grid-right">
            {ticks(epsRange.lo, epsRange.hi, 3).map((value) => (
              <text
                key={`eps-${value}`}
                x={box.width - box.right + 8}
                y={yEps(value) + 4}
                textAnchor="start"
              >
                {value.toFixed(value >= 10 || value <= -10 ? 0 : 1)}
              </text>
            ))}
            <text x={box.width - box.right + 8} y={box.top - 2} textAnchor="start">
              EPS
            </text>
          </g>
        ) : null}

        <g className="tk-xlabels">
          {periods.map((period, index) => (
            <text key={period} x={xOf(index)} y={box.height - 8} textAnchor="middle">
              {period}
            </text>
          ))}
        </g>
      </Chart>

      {hover !== null && periods[hover] ? (
        <Tooltip
          frame={box}
          x={xOf(hover)}
          title={periods[hover] as string}
          lines={lines}
        />
      ) : null}

      <Legend
        items={[
          ...bars.map((series) => ({
            label: legendOf(series.label, series.values, t),
            color: series.color,
          })),
          ...(epsPoints.length
            ? [{ label: t("ticker.eps_reported"), color: colors.brandAccent }]
            : []),
          ...(projection.length
            ? [
                {
                  label: t("ticker.eps_consensus"),
                  color: colors.brandAccent,
                  dashed: true,
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}

/** A series' contiguous runs of known values, so a gap stays a gap. */
function runs(values: (number | null)[]): number[][] {
  const out: number[][] = [];
  let run: number[] = [];
  values.forEach((value, index) => {
    if (known(value)) run.push(index);
    else {
      if (run.length > 1) out.push(run);
      run = [];
    }
  });
  if (run.length > 1) out.push(run);
  return out;
}

/** The high/low ribbon, closed back along the low and anchored at the last
 *  reported point. */
function bandPath(
  high: (number | null)[],
  low: (number | null)[],
  centre: (number | null)[],
  anchor: number,
  xOf: (index: number) => number,
  y: (value: number) => number,
): string {
  const at = anchor - 1;
  const start = centre[at];
  const top: string[] = [];
  const bottom: string[] = [];
  if (known(start)) {
    top.push(`${xOf(at)},${y(start)}`);
    bottom.push(`${xOf(at)},${y(start)}`);
  }
  high.forEach((value, index) => {
    const floor = low[index];
    if (!known(value) || !known(floor)) return;
    top.push(`${xOf(index)},${y(value)}`);
    bottom.push(`${xOf(index)},${y(floor)}`);
  });
  if (top.length < 2) return "";
  return `M ${top.join(" L ")} L ${bottom.reverse().join(" L ")} Z`;
}

function Quarterly({ data }: { data: Financials }) {
  const t = useT();
  const mobile = useMobile();
  const colors = palette();
  const [hover, setHover] = useState<number | null>(null);
  const rows = data.quarterly_eps;
  const values = rows.map((row) => row.eps);
  const box = frame({ height: mobile ? 240 : 280, bottom: 30 });
  const range = bounds([values], { zero: true });
  if (!range) return null;
  const y = scale(range.lo, range.hi, box.height - box.bottom, box.top);
  const band = plotWidth(box) / Math.max(1, rows.length);
  const xOf = (index: number) => box.left + (index + 0.5) * band;
  const point = hover === null ? null : values[hover];

  return (
    <div className="tk-plot">
      <Chart
        frame={box}
        label={t("ticker.chart_quarterly_title")}
        onPointer={(x) =>
          setHover(
            Math.max(0, Math.min(rows.length - 1, Math.floor((x - box.left) / band))),
          )
        }
        onLeave={() => setHover(null)}
      >
        <YGrid frame={box} lo={range.lo} hi={range.hi} format={(v) => v.toFixed(2)} />
        {runs(values).map((run) => (
          <polyline
            key={`q-${run[0]}`}
            className="tk-line"
            points={run.map((i) => `${xOf(i)},${y(values[i] as number)}`).join(" ")}
            stroke={colors.brandAccent}
            strokeWidth={2}
            strokeDasharray="3 3"
          />
        ))}
        <g className="tk-xlabels">
          {rows.map((row, index) =>
            index % Math.max(1, Math.ceil(rows.length / (mobile ? 4 : 8))) === 0 ? (
              <text
                key={row.period}
                x={xOf(index)}
                y={box.height - 8}
                textAnchor="middle"
              >
                {row.period}
              </text>
            ) : null,
          )}
        </g>
      </Chart>
      {hover !== null && rows[hover] ? (
        <Tooltip
          frame={box}
          x={xOf(hover)}
          title={rows[hover]?.period ?? ""}
          lines={[{ text: `EPS ${known(point) ? point.toFixed(2) : DASH}` }]}
        />
      ) : null}
    </div>
  );
}

export function FinancialsChart({ data }: { data: Financials }) {
  const t = useT();
  const hasAnnual = data.annual.some(
    (row) => row.revenue !== null || row.net_income !== null || row.eps !== null,
  );
  const hasQuarterly = data.quarterly_eps.length > 0;
  const [view, setView] = useState<"annual" | "quarterly">(
    hasAnnual ? "annual" : "quarterly",
  );
  const showing = view === "annual" && hasAnnual ? "annual" : "quarterly";
  if (!hasAnnual && !hasQuarterly) return null;

  return (
    <Card
      title={t(
        showing === "annual"
          ? "ticker.chart_annual_title"
          : "ticker.chart_quarterly_title",
      )}
    >
      {/* Only offered when there are two views. One view with a control that
          does nothing is worse than no control. */}
      {hasAnnual && hasQuarterly ? (
        <div className="tk-controls">
          <Segmented
            label={t("ticker.financials_view")}
            options={["annual", "quarterly"] as const}
            value={showing}
            onChange={setView}
            format={(one) => t(`ticker.view_${one}`)}
          />
        </div>
      ) : null}
      {showing === "annual" ? <Annual data={data} /> : <Quarterly data={data} />}
      {showing === "annual" && data.projection.length > 0 ? (
        <Note>{t("ticker.annual_caption")}</Note>
      ) : null}
    </Card>
  );
}

// ------------------------------------------------------------ P/E vs history

export function ValuationChart({
  data,
  fundamentalPe,
}: {
  data: Valuation;
  /** The KPI grid's P/E (TTM), for the divergence warning below. */
  fundamentalPe: number | null;
}) {
  const t = useT();
  const mobile = useMobile();
  const colors = palette();
  const [range, setRange] = useState("5y");
  const [hover, setHover] = useState<number | null>(null);

  const window =
    data.windows.find((one) => one.window === range) ??
    data.windows.find((one) => one.window === "5y") ??
    data.windows[0];

  const kept = useMemo(() => {
    const last = data.dates[data.dates.length - 1];
    if (!window || last === undefined) return [];
    const floor = Date.parse(last) - window.days * 86_400_000;
    return data.dates
      .map((day, index) => ({ day, value: data.pe[index] ?? null }))
      .filter((row) => Date.parse(row.day) >= floor);
  }, [data, window]);

  // No feed had the quarters. Said outright rather than left as an empty panel,
  // which would read as a P/E that never moved.
  if (!data.source) {
    return (
      <Card title={t("ticker.valuation_history")}>
        <Empty>{t("ticker.pe_insufficient")}</Empty>
      </Card>
    );
  }
  if (!window) return null;

  // Where today's multiple sits inside its own distribution, on the app's
  // 80/20 bands. The reading rides the tooltip: the pill has to stay short
  // enough for a tile.
  const percentile = window.percentile;
  const band =
    percentile === null
      ? null
      : percentile >= 80
        ? { tone: "red", tip: "ticker.pe_above_avg" }
        : percentile <= 20
          ? { tone: "green", tip: "ticker.pe_below_avg" }
          : { tone: "gray", tip: "ticker.pe_inline_avg" };

  // Around earnings the two P/Es legitimately diverge: Yahoo's TTM EPS picks up
  // a press-released quarter weeks before the filing lands in EDGAR, and this
  // series only steps on filing dates. Flagged so the gap reads as vintage.
  const divergence =
    fundamentalPe && fundamentalPe > 0 && data.current && data.current > 0
      ? Math.abs(data.current - fundamentalPe) / fundamentalPe
      : 0;

  const values = kept.map((row) => row.value);
  const box = frame({ height: mobile ? 220 : 260, bottom: 30 });
  const span = bounds([values, window.mean === null ? [] : [window.mean]]);
  const y = span ? scale(span.lo, span.hi, box.height - box.bottom, box.top) : null;
  const band_ = plotWidth(box) / Math.max(1, kept.length);
  const xOf = (index: number) => box.left + (index + 0.5) * band_;

  return (
    <Card title={t("ticker.valuation_history")}>
      <div className="tk-controls">
        <Segmented
          label={t("ticker.pe_range")}
          options={data.windows.map((one) => one.window)}
          value={window.window}
          onChange={setRange}
        />
      </div>

      <Kpis>
        <Kpi
          label={t("ticker.kpi_pe_current")}
          help={t("ticker.kpi_pe_current_help")}
          value={data.current === null ? DASH : data.current.toFixed(1)}
        />
        <Kpi
          label={t("ticker.kpi_pe_avg", { rng: window.window })}
          help={t("ticker.kpi_pe_avg_help")}
          value={window.mean === null ? DASH : window.mean.toFixed(1)}
        />
        <Kpi
          label={t("ticker.kpi_pe_premium")}
          help={t("ticker.kpi_pe_premium_help") + (band ? ` — ${t(band.tip)}` : "")}
          value={
            window.premium === null
              ? DASH
              : `${window.premium >= 0 ? "+" : ""}${(window.premium * 100).toFixed(1)}%`
          }
          meta={
            band && percentile !== null ? (
              <Tag tone={band.tone}>
                {t("ticker.pe_percentile", { p: percentile.toFixed(0) })}
              </Tag>
            ) : null
          }
        />
      </Kpis>

      {divergence > 0.2 ? (
        <Banner tone="warn">
          {t("ticker.pe_divergence", {
            cur: (data.current ?? 0).toFixed(1),
            fund: (fundamentalPe ?? 0).toFixed(1),
            diff: (divergence * 100).toFixed(0),
          })}
        </Banner>
      ) : null}

      <Subhead>{t("ticker.chart_pe_title")}</Subhead>
      {span && y && kept.length > 1 ? (
        <div className="tk-plot">
          <Chart
            frame={box}
            label={t("ticker.chart_pe_title")}
            onPointer={(x) =>
              setHover(
                Math.max(
                  0,
                  Math.min(kept.length - 1, Math.floor((x - box.left) / band_)),
                ),
              )
            }
            onLeave={() => setHover(null)}
          >
            <YGrid frame={box} lo={span.lo} hi={span.hi} format={(v) => v.toFixed(0)} />
            {window.mean !== null ? (
              <line
                className="tk-event"
                x1={box.left}
                x2={box.width - box.right}
                y1={y(window.mean)}
                y2={y(window.mean)}
                stroke={colors.textMuted}
              />
            ) : null}
            {runs(values).map((run) => (
              <polyline
                key={`pe-${run[0]}`}
                className="tk-line"
                points={run.map((i) => `${xOf(i)},${y(values[i] as number)}`).join(" ")}
                stroke={colors.brandAccent}
                strokeWidth={1.8}
              />
            ))}
            {hover !== null ? (
              <line
                className="tk-cross"
                x1={xOf(hover)}
                x2={xOf(hover)}
                y1={box.top}
                y2={box.height - box.bottom}
              />
            ) : null}
            <g className="tk-xlabels">
              {[0, Math.floor(kept.length / 2), kept.length - 1].map((index) => {
                const row = kept[index];
                if (!row) return null;
                return (
                  <text
                    key={`x-${index}`}
                    x={Math.min(
                      box.width - box.right - 24,
                      Math.max(box.left + 24, xOf(index)),
                    )}
                    y={box.height - 8}
                    textAnchor="middle"
                  >
                    {row.day.slice(0, 7)}
                  </text>
                );
              })}
            </g>
          </Chart>
          {hover !== null && kept[hover] ? (
            <Tooltip
              frame={box}
              x={xOf(hover)}
              title={kept[hover]?.day.slice(0, 10) ?? ""}
              lines={[
                {
                  text: `P/E ${known(values[hover]) ? (values[hover] as number).toFixed(1) : DASH}`,
                },
                ...(window.mean === null
                  ? []
                  : [
                      {
                        text: t("ticker.pe_avg_line", { avg: window.mean.toFixed(1) }),
                      },
                    ]),
              ]}
            />
          ) : null}
        </div>
      ) : (
        <Empty>{t("ticker.pe_insufficient")}</Empty>
      )}
      {/* Which filing feed backed the reconstruction. Not a footnote. */}
      <Note>{t("ticker.pe_caption", { source: data.source })}</Note>
    </Card>
  );
}

// ------------------------------------------------------------- fund exposure

/**
 * A fund's sector weights as horizontal bars.
 *
 * Bars and not a donut, for the page's own reason: the question here is "how
 * big is the tech sleeve", which is a length comparison, and sector names are
 * too long to ride slices.
 */
export function FundExposure({ fund }: { fund: Fund }) {
  const t = useT();
  if (fund.sectors.length === 0) return null;
  const top = Math.max(...fund.sectors.map(([, weight]) => weight), 0) || 1;
  return (
    <>
      <Subhead>{t("ticker.fund_sectors")}</Subhead>
      <div className="tk-hbars">
        {fund.sectors.map(([label, weight]) => (
          <div className="tk-hbar" key={label}>
            <span className="tk-hbar-l">{label}</span>
            <span className="tk-hbar-track">
              <span
                className="tk-hbar-fill"
                style={{ width: `${(weight / top) * 100}%` }}
              />
            </span>
            <span className="tk-hbar-v">{percent(weight, 1)}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// --------------------------------------------------------------- insider flow

/**
 * Open-market buy vs sell value by month — the balance over time, which a
 * single trailing-window net cannot show: three months of steady selling and
 * one large purchase net out to roughly nothing.
 *
 * Open-market rows only. A grant is not a decision to buy, and counting it as
 * one turns every vesting date into insider conviction.
 */
export function InsiderFlow({ insiders }: { insiders: Insiders }) {
  const t = useT();
  const mobile = useMobile();
  const colors = palette();
  const [hover, setHover] = useState<number | null>(null);

  const months = useMemo(() => {
    const cells = new Map<string, { buy: number; sell: number }>();
    for (const trade of insiders.trades) {
      if (!trade.is_open_market || !trade.date || !trade.value) continue;
      const month = trade.date.slice(0, 7);
      const cell = cells.get(month) ?? { buy: 0, sell: 0 };
      // The value is signed; the two series are magnitudes, drawn side by side.
      if (trade.value >= 0) cell.buy += trade.value;
      else cell.sell += -trade.value;
      cells.set(month, cell);
    }
    return [...cells.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [insiders.trades]);

  if (months.length === 0) return null;
  const ccy = insiders.trades[0]?.currency ?? "";
  const box = frame({ height: mobile ? 200 : 230, bottom: 28, top: 14 });
  const range = bounds([months.map(([, cell]) => Math.max(cell.buy, cell.sell))], {
    zero: true,
    pad: 0.08,
  });
  if (!range) return null;
  const y = scale(range.lo, range.hi, box.height - box.bottom, box.top);
  const band = plotWidth(box) / months.length;
  const xOf = (index: number) => box.left + (index + 0.5) * band;
  const width = Math.min(18, (band * 0.7) / 2);
  const row = hover === null ? null : months[hover];

  return (
    <>
      <Subhead>{t("ticker.chart_insider_title", { ccy })}</Subhead>
      <div className="tk-plot">
        <Chart
          frame={box}
          label={t("ticker.chart_insider_title", { ccy })}
          onPointer={(x) =>
            setHover(
              Math.max(
                0,
                Math.min(months.length - 1, Math.floor((x - box.left) / band)),
              ),
            )
          }
          onLeave={() => setHover(null)}
        >
          <YGrid
            frame={box}
            lo={range.lo}
            hi={range.hi}
            format={(v) => compact(v)}
            count={3}
          />
          {months.map(([month, cell], index) => (
            <g key={month}>
              <rect
                x={xOf(index) - width}
                y={y(cell.buy)}
                width={width - 1}
                height={Math.max(0, y(0) - y(cell.buy))}
                fill={colors.up}
              />
              <rect
                x={xOf(index) + 1}
                y={y(cell.sell)}
                width={width - 1}
                height={Math.max(0, y(0) - y(cell.sell))}
                fill={colors.down}
              />
            </g>
          ))}
          <g className="tk-xlabels">
            {months.map(([month], index) =>
              index % Math.max(1, Math.ceil(months.length / (mobile ? 3 : 8))) === 0 ? (
                <text key={month} x={xOf(index)} y={box.height - 8} textAnchor="middle">
                  {month}
                </text>
              ) : null,
            )}
          </g>
        </Chart>
        {row ? (
          <Tooltip
            frame={box}
            x={xOf(hover as number)}
            title={row[0]}
            lines={[
              { text: `${t("ticker.buy")} ${compact(row[1].buy, ccy)}`, tone: "up" },
              {
                text: `${t("ticker.sell")} ${compact(row[1].sell, ccy)}`,
                tone: "down",
              },
            ]}
          />
        ) : null}
        <Legend
          items={[
            { label: t("ticker.buy"), color: colors.up },
            { label: t("ticker.sell"), color: colors.down },
          ]}
        />
      </div>
    </>
  );
}
