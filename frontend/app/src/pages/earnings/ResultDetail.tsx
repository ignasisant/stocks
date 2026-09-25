/**
 * The overview a past chip opens: how the quarter landed, section by section.
 *
 * Same dialog as the Streamlit one (`web.earnings_ui.render_result_body`): the
 * headline first — reported EPS against the estimate, and the price reaction —
 * then the print broken down into revenue, margins, the GAAP result, EPS
 * quality and next quarter's consensus. Each section leads with a visual (bars,
 * gauges, a dispersion range) and parks the numbers in a collapsed "Detail", so
 * the dialog answers "how did it go?" at a glance without becoming a sheet.
 *
 * The headline can paint before the network answers. A caller that already
 * holds the calendar row passes it as `result`, and the three EPS figures show
 * the moment the dialog opens; everything below is one request to
 * `/earnings/{symbol}/result`, which is three Yahoo payloads deep on a cold
 * cache, so it reserves its height with a skeleton instead of pushing the
 * tiles around as it lands.
 *
 * Exported for the Home screen's past-earnings chips as well as this page's
 * calendar: the Streamlit app shares the one dialog between both, so the two
 * cannot drift, and so does this.
 */

import { useEffect } from "react";
import type { ReactNode } from "react";
import { get } from "../../shell/api";
import { Skeleton } from "../../shell/Layout";
import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import type {
  CalendarResult,
  ConsensusPeriod,
  QuarterBreakdown,
  QuarterFigures,
  ResultDetailData,
} from "./data";
import {
  eps,
  longDate,
  money,
  pct,
  plain,
  quarterLabel,
  signedFrac,
  signedNum,
  signedPct,
  tone,
} from "./format";
import type { T } from "./format";

/** Surprise bars shown — two years of prints is the record worth reading. */
const SURPRISE_QUARTERS = 8;

/** The per-period grid's row labels, in the order the API sends them. */
const PERIOD_KEYS: Record<string, string> = {
  "0q": "earnings.period_0q",
  "+1q": "earnings.period_1q",
  "0y": "earnings.period_0y",
  "+1y": "earnings.period_1y",
};

type ResultDetailProps = {
  /** The symbol as the calendar spells it; the API upper-cases it. */
  ticker: string;
  /** The report date, ISO (`YYYY-MM-DD`). */
  date: string;
  /**
   * The calendar row, when the caller already has it: the headline tiles then
   * paint before the request lands. Optional — the response carries it too.
   */
  result?: CalendarResult | null;
  onClose: () => void;
};

// ------------------------------------------------------------------ pieces

type Chip = { text: string; cls: string } | null;

/** A signed change as a verdict chip: green up, red down, grey unknown. */
function chip(text: string, value: number | null | undefined): Chip {
  return { text, cls: tone(value) };
}

type TileSpec = {
  label: string;
  value: string;
  chip?: Chip;
  /** Hover help — the Streamlit tile's `help=`. */
  tip?: string;
};

function Tiles({ tiles }: { tiles: TileSpec[] }) {
  return (
    <div className="earn-tiles">
      {tiles.map((tile) => (
        <div className="earn-tile" key={tile.label} title={tile.tip}>
          <div className={`earn-tile-label${tile.tip ? " tip" : ""}`}>{tile.label}</div>
          <div className="earn-tile-value">{tile.value}</div>
          {tile.chip && (
            <span className={`earn-verdict ${tile.chip.cls}`}>{tile.chip.text}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function Section({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children: ReactNode;
}) {
  return (
    <section className="earn-sec">
      <div className="earn-sec-title">{title}</div>
      {sub && <div className="earn-sec-sub">{sub}</div>}
      {children}
    </section>
  );
}

type BarRow = { label: string; value: number | null; text: string; fill: string };

/**
 * A horizontal bar stack, widths relative to the largest magnitude in the set.
 *
 * No axis on purpose: the question is the shape of the trend, and the figure
 * is printed at the end of every bar anyway. A non-null value never shrinks
 * below a sliver, so a small quarter still reads as "there, and small".
 */
function Bars({ rows }: { rows: BarRow[] }) {
  const magnitudes = rows.flatMap((row) =>
    row.value === null ? [] : [Math.abs(row.value)],
  );
  const top = magnitudes.length ? Math.max(...magnitudes) : 0;
  return (
    <div className="earn-bars">
      {rows.map((row) => {
        const width =
          !top || row.value === null
            ? 0
            : Math.max(2, (Math.abs(row.value) / top) * 100);
        return (
          <div className="earn-bar-row" key={row.label}>
            <span className="earn-bar-label">{row.label}</span>
            <span className="earn-track">
              <span
                className={`earn-fill ${row.fill}`}
                style={{ width: `${width.toFixed(1)}%` }}
              />
            </span>
            <span className="earn-bar-value">{row.text}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Margin gauges. A margin is a share of one denominator, so each gets a filled
 * track out of 100% rather than a bar scaled against its neighbours: 75% gross
 * next to 30% operating then reads as two levels of the same whole.
 */
function Meters({
  items,
}: {
  items: { label: string; fraction: number | null; chip: Chip }[];
}) {
  return (
    <div className="earn-meters">
      {items.map((item) => {
        const width =
          item.fraction === null ? 0 : Math.min(Math.max(item.fraction * 100, 0), 100);
        return (
          <div className="earn-meter" key={item.label}>
            <div className="earn-tile-label">{item.label}</div>
            <div className="earn-meter-head">
              <span className="earn-meter-value">{pct(item.fraction)}</span>
              {item.chip && (
                <span className={`earn-verdict ${item.chip.cls}`}>
                  {item.chip.text}
                </span>
              )}
            </div>
            <span className="earn-meter-track">
              <span
                className="earn-meter-fill"
                style={{ width: `${width.toFixed(1)}%` }}
              />
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Consensus dispersion: the analysts' low–high band with the mean marked. */
function Range({
  label,
  low,
  avg,
  high,
  fmt,
  note,
}: {
  label: string;
  low: number | null;
  avg: number | null;
  high: number | null;
  fmt: (value: number | null) => string;
  note: string;
}) {
  const span = low === null || high === null ? null : high - low;
  const position =
    avg === null || low === null || span === null || span <= 0
      ? 50
      : Math.min(Math.max(((avg - low) / span) * 100, 4), 96);
  return (
    <div className="earn-range">
      <div className="earn-range-head">
        <span className="earn-tile-label">{label}</span>
        {note && <span className="earn-range-note">{note}</span>}
      </div>
      <div className="earn-meter-value">{fmt(avg)}</div>
      <span className="earn-range-band">
        <span className="earn-range-mark" style={{ left: `${position.toFixed(1)}%` }} />
      </span>
      <div className="earn-range-ends">
        <span>{fmt(low)}</span>
        <span>{fmt(high)}</span>
      </div>
    </div>
  );
}

/** The collapsed numbers under a section's visual. */
function Detail({
  head,
  rows,
  caption,
}: {
  head: string[];
  rows: { key: string; cells: ReactNode[]; classes?: string[] }[];
  caption?: string;
}) {
  const t = useT();
  return (
    <details className="earn-detail">
      <summary>{t("earnings.detail")}</summary>
      <div className="earn-detail-scroll">
        <table className="earn-table">
          <thead>
            <tr>
              {head.map((label, i) => (
                <th key={label} className={i === 0 ? "left" : undefined}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                {row.cells.map((cell, i) => (
                  <td
                    key={i}
                    className={
                      [i === 0 ? "left" : "", row.classes?.[i] ?? ""]
                        .join(" ")
                        .trim() || undefined
                    }
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && <p className="earn-caption">{caption}</p>}
    </details>
  );
}

// ----------------------------------------------------------------- sections

function RevenueSection({
  breakdown,
  trend,
  prefix,
}: {
  breakdown: QuarterBreakdown;
  trend: QuarterFigures[];
  prefix: string;
}) {
  const t = useT();
  const q = breakdown.quarter;
  return (
    <Section title={t("earnings.sec_revenue")} sub={t("earnings.sub_revenue")}>
      <Tiles
        tiles={[
          {
            label: t("earnings.tile_revenue"),
            value: money(q.revenue, prefix),
            chip: chip(
              t("earnings.chip_yoy", { pct: signedFrac(q.revenue_yoy) }),
              q.revenue_yoy,
            ),
          },
          { label: t("earnings.tile_qoq"), value: signedFrac(q.revenue_qoq) },
          {
            label: t("earnings.tile_ttm_revenue"),
            value: money(breakdown.revenue_ttm, prefix),
            tip: t("earnings.tip_ttm"),
          },
        ]}
      />
      <Bars
        rows={trend.map((x) => ({
          label: quarterLabel(x.end, t),
          value: x.revenue,
          text: money(x.revenue, prefix),
          // The reported quarter in the brand colour, its neighbours muted.
          fill: x.end === q.end ? "now" : "past",
        }))}
      />
      <Detail
        head={[
          t("earnings.col_quarter"),
          t("earnings.col_revenue"),
          t("earnings.col_yoy"),
          t("earnings.col_qoq"),
          t("earnings.col_gross_profit"),
        ]}
        rows={trend.map((x) => ({
          key: x.end,
          cells: [
            quarterLabel(x.end, t),
            money(x.revenue, prefix),
            signedFrac(x.revenue_yoy),
            signedFrac(x.revenue_qoq),
            money(x.gross_profit, prefix),
          ],
        }))}
      />
    </Section>
  );
}

function MarginSection({
  breakdown,
  trend,
}: {
  breakdown: QuarterBreakdown;
  trend: QuarterFigures[];
}) {
  const t = useT();
  const q = breakdown.quarter;
  const gauge = (key: string, fraction: number | null, bps: number | null) => ({
    label: t(key),
    fraction,
    chip:
      bps === null
        ? null
        : chip(t("earnings.chip_bps", { bps: signedNum(bps, 0) }), bps),
  });
  return (
    <Section title={t("earnings.sec_margins")} sub={t("earnings.sub_margins")}>
      <Meters
        items={[
          gauge(
            "earnings.tile_gross_margin",
            q.gross_margin,
            breakdown.gross_margin_bps,
          ),
          gauge(
            "earnings.tile_operating_margin",
            q.operating_margin,
            breakdown.operating_margin_bps,
          ),
          gauge("earnings.tile_net_margin", q.net_margin, breakdown.net_margin_bps),
        ]}
      />
      <Detail
        head={[
          t("earnings.col_quarter"),
          t("earnings.col_gross"),
          t("earnings.col_operating"),
          t("earnings.col_net"),
          t("earnings.col_rnd"),
        ]}
        rows={trend.map((x) => ({
          key: x.end,
          cells: [
            quarterLabel(x.end, t),
            pct(x.gross_margin),
            pct(x.operating_margin),
            pct(x.net_margin),
            pct(x.rnd_intensity),
          ],
        }))}
        caption={t("earnings.margins_caption")}
      />
    </Section>
  );
}

function GaapSection({
  breakdown,
  trend,
  prefix,
}: {
  breakdown: QuarterBreakdown;
  trend: QuarterFigures[];
  prefix: string;
}) {
  const t = useT();
  const q = breakdown.quarter;
  const shares = breakdown.shares_yoy;
  return (
    <Section title={t("earnings.sec_gaap")} sub={t("earnings.sub_gaap")}>
      <Tiles
        tiles={[
          {
            label: t("earnings.tile_net_income"),
            value: money(q.net_income, prefix),
            chip: chip(
              t("earnings.chip_yoy", { pct: signedFrac(breakdown.net_income_yoy) }),
              breakdown.net_income_yoy,
            ),
          },
          { label: t("earnings.tile_pretax"), value: money(q.pretax_income, prefix) },
          {
            label: t("earnings.tile_tax_rate"),
            value: pct(q.tax_rate),
            tip: t("earnings.tip_tax_rate"),
          },
          {
            label: t("earnings.tile_shares"),
            // A count, not money: the same compact form with no currency.
            value: money(q.diluted_shares),
            // Dilution is the bad direction here: fewer shares (buybacks)
            // lift per-share value, more shares thin it — so the tone flips.
            chip: chip(
              t("earnings.chip_yoy", { pct: signedFrac(shares) }),
              shares === null ? null : -shares,
            ),
            tip: t("earnings.tip_shares"),
          },
        ]}
      />
      {/* Quarters down the rows and line items across, the way the Streamlit
          table reads once its phone cards transpose it — here it is simply
          the orientation that scrolls sideways least. */}
      <Detail
        head={[
          t("earnings.col_quarter"),
          t("earnings.col_revenue"),
          t("earnings.col_gross_profit"),
          t("earnings.col_operating_income"),
          t("earnings.col_pretax"),
          t("earnings.col_tax"),
          t("earnings.col_net_income"),
          t("earnings.col_gaap_eps"),
        ]}
        rows={trend.map((x) => ({
          key: x.end,
          cells: [
            quarterLabel(x.end, t),
            money(x.revenue, prefix),
            money(x.gross_profit, prefix),
            money(x.operating_income, prefix),
            money(x.pretax_income, prefix),
            money(x.tax_provision, prefix),
            money(x.net_income, prefix),
            eps(x.diluted_eps),
          ],
        }))}
      />
    </Section>
  );
}

function EpsSection({
  printed,
  gaap,
  gap,
  history,
}: {
  printed: CalendarResult;
  gaap: number | null;
  gap: number | null;
  history: CalendarResult[];
}) {
  const t = useT();
  const surprises = history
    .filter((x) => x.surprise_pct !== null)
    .slice(0, SURPRISE_QUARTERS);
  return (
    <Section title={t("earnings.sec_eps")} sub={t("earnings.sub_eps")}>
      <Tiles
        tiles={[
          {
            label: t("earnings.reported_eps"),
            value: eps(printed.reported_eps),
            chip:
              printed.surprise_pct === null
                ? null
                : chip(
                    t("earnings.surprise_vs_est", {
                      pct: signedNum(printed.surprise_pct),
                    }),
                    printed.surprise_pct,
                  ),
            tip: t("earnings.tip_headline_eps"),
          },
          {
            label: t("earnings.tile_gaap_eps"),
            value: eps(gaap),
            // The gap is the adjustment, not a verdict — grey either way.
            chip:
              gap === null
                ? null
                : {
                    text: t("earnings.chip_vs_gaap", { delta: signedNum(gap) }),
                    cls: "earn-flat",
                  },
            tip: t("earnings.tip_gaap_eps"),
          },
          { label: t("earnings.eps_estimate"), value: eps(printed.eps_estimate) },
        ]}
      />
      {surprises.length > 0 && (
        <>
          <p className="earn-caption">{t("earnings.eps_surprise_trend")}</p>
          <Bars
            rows={surprises.map((x) => ({
              label: quarterLabel(x.date, t),
              value: x.surprise_pct,
              text: signedPct(x.surprise_pct),
              fill: (x.surprise_pct ?? 0) >= 0 ? "beat" : "miss",
            }))}
          />
        </>
      )}
      {history.length > 1 && (
        <Detail
          head={[
            t("earnings.col_date"),
            t("earnings.col_eps_est"),
            t("earnings.col_reported"),
            t("earnings.col_surprise"),
          ]}
          rows={history.map((x) => ({
            key: x.date,
            cells: [
              longDate(x.date, t),
              eps(x.eps_estimate),
              eps(x.reported_eps),
              signedPct(x.surprise_pct),
            ],
            classes: ["", "", "", tone(x.surprise_pct)],
          }))}
        />
      )}
    </Section>
  );
}

/** "+12.0% YoY · 28 analysts", skipping whichever half is unknown. */
function consensusNote(t: T, growth: number | null, analysts: number | null): string {
  return [
    growth === null ? "" : t("earnings.chip_yoy", { pct: signedFrac(growth) }),
    analysts ? t("earnings.chip_analysts", { n: analysts }) : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function OutlookSection({
  outlook,
  periods,
}: {
  outlook: ConsensusPeriod;
  periods: ConsensusPeriod[];
}) {
  const t = useT();
  const prefix = outlook.currency_prefix;
  return (
    <Section title={t("earnings.sec_outlook")} sub={t("earnings.sub_outlook")}>
      {outlook.rev_avg !== null && (
        <Range
          label={t("earnings.outlook_revenue")}
          low={outlook.rev_low}
          avg={outlook.rev_avg}
          high={outlook.rev_high}
          fmt={(value) => money(value, prefix)}
          note={consensusNote(t, outlook.rev_growth, outlook.rev_analysts)}
        />
      )}
      {outlook.eps_avg !== null && (
        <Range
          label={t("earnings.outlook_eps")}
          low={outlook.eps_low}
          avg={outlook.eps_avg}
          high={outlook.eps_high}
          fmt={eps}
          note={consensusNote(t, outlook.eps_growth, outlook.eps_analysts)}
        />
      )}
      <Detail
        head={[
          t("earnings.col_period"),
          t("earnings.col_eps_avg"),
          t("earnings.col_eps_range"),
          t("earnings.col_rev_avg"),
          t("earnings.col_rev_range"),
          t("earnings.col_yoy"),
        ]}
        rows={periods.map((view) => {
          const key = PERIOD_KEYS[view.period];
          return {
            key: view.period,
            cells: [
              key ? t(key) : view.period,
              eps(view.eps_avg),
              `${eps(view.eps_low)} – ${eps(view.eps_high)}`,
              money(view.rev_avg, view.currency_prefix),
              `${money(view.rev_low, view.currency_prefix)} – ${money(view.rev_high, view.currency_prefix)}`,
              signedFrac(view.rev_growth),
            ],
          };
        })}
        caption={t("earnings.outlook_caption")}
      />
    </Section>
  );
}

/**
 * Everything under the headline, once the request has answered. Exported for
 * the tests, which render it from a fixed payload with no fetch in the way.
 */
export function Breakdown({
  data,
  printed,
}: {
  data: ResultDetailData;
  printed: CalendarResult;
}) {
  const t = useT();
  const { breakdown, trend, currency_prefix: prefix } = data;
  return (
    <>
      {breakdown && (
        <>
          <RevenueSection breakdown={breakdown} trend={trend} prefix={prefix} />
          <MarginSection breakdown={breakdown} trend={trend} />
          <GaapSection breakdown={breakdown} trend={trend} prefix={prefix} />
        </>
      )}
      <EpsSection
        printed={printed}
        gaap={breakdown?.quarter.diluted_eps ?? null}
        gap={data.eps_gaap_gap}
        history={data.history}
      />
      {data.outlook && (
        <OutlookSection outlook={data.outlook} periods={data.outlook_periods} />
      )}
      {data.unavailable ? (
        <p className="earn-caption">{t("common.data_unavailable")}</p>
      ) : (
        data.quarter_state !== "matched" && (
          <p className="earn-caption">
            {t(
              data.quarter_state === "pending"
                ? "earnings.quarter_pending"
                : "earnings.no_quarter_data",
            )}
          </p>
        )
      )}
    </>
  );
}

// ------------------------------------------------------------------ dialog

function ResultDetail({ ticker, date, result, onClose }: ResultDetailProps) {
  const t = useT();
  const profile = useTickerProfile(ticker);
  const query = useApi(
    () =>
      get<ResultDetailData>(`/earnings/${encodeURIComponent(ticker)}/result`, { date }),
    [ticker, date],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const data = query.state === "loaded" ? query.data : null;
  // The response is the authority once it lands; until then, the row the
  // caller handed over. After it lands a null means the feed has no figures
  // for that day — unless the caller's own row says otherwise, in which case
  // the calendar knew something a throttled per-ticker fetch did not.
  const printed = data?.result ?? result ?? null;
  const name = profile?.name || data?.name || "";
  const logo = profile?.logo ?? data?.logo ?? null;
  const settled = query.state !== "loading";

  return (
    <div
      className="earn-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="earn-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label={t("earnings.dialog_title")}
      >
        <div className="earn-modal-head">
          <div className="earn-modal-id">
            {logo && (
              <img className="earn-modal-logo" src={logo} alt="" loading="lazy" />
            )}
            <div>
              <div className="earn-modal-name">
                <Link className="earn-ticker" page="ticker" params={{ ticker }}>
                  {ticker}
                </Link>
                {name && <span>{` — ${name}`}</span>}
              </div>
              <div className="earn-modal-date">
                {plain(t("earnings.reported_on", { date: longDate(date, t) }))}
              </div>
            </div>
          </div>
          <button type="button" className="earn-close" onClick={onClose}>
            {t("earnings.close")}
          </button>
        </div>

        {printed === null ? (
          settled ? (
            <p className="ag-note">{t("earnings.no_figures")}</p>
          ) : (
            <Skeleton rows={4} />
          )
        ) : (
          <>
            <Tiles
              tiles={[
                {
                  label: t("earnings.reported_eps"),
                  value: eps(printed.reported_eps),
                  chip:
                    printed.surprise_pct === null
                      ? null
                      : chip(
                          t("earnings.surprise_vs_est", {
                            pct: signedNum(printed.surprise_pct),
                          }),
                          printed.surprise_pct,
                        ),
                },
                { label: t("earnings.eps_estimate"), value: eps(printed.eps_estimate) },
                {
                  label: t("earnings.price_reaction"),
                  value: data ? signedPct(data.price_reaction, 2) : "…",
                  tip: t("earnings.price_reaction_caption"),
                },
              ]}
            />
            {query.state === "loading" ? (
              <Skeleton rows={6} />
            ) : query.state === "failed" ? (
              <div className="ag-note">
                <p>{t("common.data_unavailable")}</p>
                <button type="button" className="ag-btn" onClick={query.retry}>
                  {t("common.retry")}
                </button>
              </div>
            ) : data ? (
              <Breakdown data={data} printed={printed} />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

export default ResultDetail;
