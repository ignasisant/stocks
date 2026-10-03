/**
 * The page's tabular sections: KPIs, moat, insider dealing, fund basket, comps.
 *
 * One rule runs through all of them, and it is the project's rather than a
 * React one: a figure the server could not compute renders as an em dash, and a
 * source that does not cover the name says so in words. Neither ever renders as
 * a zero, because "nothing happened" and "nobody publishes this" look identical
 * once you print them both as 0.
 */

import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { InsiderFlow, FundExposure } from "./Charts";
import {
  DASH,
  compactMoney,
  currencySymbol,
  insiderPrice,
  insiderValue,
  money,
  orElse,
  percent,
  signed,
  signedPercent,
  type Translate,
} from "./format";
import { Banner, Bold, Card, Note, Scroll, Tag, TickerLink, useMobile } from "./ui";
import { Kpi, KpiGrid, bandTone } from "../../ui/Kpi";
import type {
  ClosedEnd,
  Comparables,
  FigureSource,
  Fund,
  Insiders,
  Metrics,
  Moat,
  SourceCheck,
  SourcedFigure,
} from "./types";

// ------------------------------------------------------------------ KPI grid

export function MetricsSection({ metrics }: { metrics: Metrics }) {
  const t = useT();
  const byKey = new Map(metrics.kpis.map((kpi) => [kpi.key, kpi]));

  // Every figure null means the source answered with nothing — a throttled
  // Yahoo, a symbol it does not cover. Said in words, because nine "n/a" tiles
  // look like nine separate gaps rather than one failed fetch.
  if (metrics.grid.length === 0 || metrics.kpis.every((kpi) => kpi.value === null)) {
    return (
      <Card title={t("ticker.fundamentals")}>
        <Note>{t("ticker.fundamentals_failed")}</Note>
      </Card>
    );
  }

  // A dollar company, a base asked for, and no converted figure back: the FX
  // endpoint could not answer. Different from "nothing to convert".
  const fxFailed =
    metrics.base !== null &&
    metrics.currency === "USD" &&
    metrics.base !== "USD" &&
    byKey.get("market_cap")?.value !== null &&
    byKey.get("market_cap")?.value !== undefined &&
    metrics.market_cap_base === null;

  return (
    <Card title={t("ticker.fundamentals")}>
      <KpiGrid>
        {/* The tiles the server says this grid has, in its order, and every one
            of them drawn: a missing figure prints "n/a" rather than vanishing,
            because a grid that changes shape per company cannot be read at a
            glance. */}
        {metrics.grid.map((tile) => {
          const kpi = byKey.get(tile.key);
          if (!kpi) return null;
          // The label is a KEY the API names and a string this page owns; the
          // English one the API also carries is the fallback, never the first
          // choice, or a Spanish reader gets "Net debt/EBITDA".
          const label = orElse(t, tile.label_key, kpi.label);
          const help = tile.help_key ? orElse(t, tile.help_key, kpi.desc) : kpi.desc;
          return (
            <Kpi
              key={tile.key}
              label={label}
              help={help || undefined}
              value={kpi.formatted}
              // Coloured by the tone the domain's band carries, never by the
              // label: the labels grow ("net cash", "heavy dilution") and a
              // client matching on them shows each new one as neutral.
              chip={
                kpi.verdict
                  ? { text: kpi.verdict, tone: bandTone(kpi.verdict_tone) }
                  : null
              }
            />
          );
        })}
      </KpiGrid>
      {fxFailed ? <Note>{t("ticker.fx_unavailable")}</Note> : null}
      {/* The one figure here that is the reader's rather than the company's: a
          dollar market cap restated in the money they keep their book in. */}
      {metrics.market_cap_base_formatted && metrics.base ? (
        <Note>
          {t("ticker.market_cap_fx", {
            usd: byKey.get("market_cap")?.formatted ?? "",
            conv: metrics.market_cap_base_formatted,
            ccy: metrics.base,
            rate: metrics.fx_rate === null ? DASH : metrics.fx_rate.toFixed(4),
            as_of: metrics.fx_as_of ?? DASH,
          })}
        </Note>
      ) : null}
    </Card>
  );
}

// ---------------------------------------------------------------------- moat

export function MoatSection({ moat }: { moat: Moat }) {
  const t = useT();
  // Under three scored pillars there is no score, and the card says why rather
  // than disappearing: a company whose filings are too short to judge is a
  // finding, and a section that vanishes reads as one that failed to load.
  if (moat.score === null || moat.pillars.length === 0) {
    return (
      <Card title={t("ticker.moat")}>
        <Note>{t("ticker.moat_insufficient")}</Note>
      </Card>
    );
  }
  return (
    <Card
      title={t("ticker.moat")}
      note={t("ticker.moat_caption", { years: moat.years })}
    >
      <KpiGrid>
        {/* The band's tone from the server and the KPI's own description on
            the tooltip, which is where the reader learns ≥70 is "wide". */}
        <Kpi
          label={t("ticker.moat_score")}
          help={orElse(t, "kpi.moat.desc", "") || undefined}
          value={moat.score.toFixed(0)}
          chip={
            moat.rating ? { text: moat.rating, tone: bandTone(moat.rating_tone) } : null
          }
        />
      </KpiGrid>
      <ul className="tk-pillars">
        {moat.pillars.map((pillar) => (
          <li key={pillar.key}>
            <div className="tk-pillar-head">
              <span>{pillar.label}</span>
              {/* How much of the score this pillar decides. Without it the five
                  read as equal, and they are not. */}
              {pillar.score !== null ? (
                <Tag>{t("ticker.weight", { pct: percent(pillar.weight, 0) })}</Tag>
              ) : null}
              <span className="tk-pillar-score">
                {pillar.score === null ? DASH : pillar.score.toFixed(0)}
              </span>
            </div>
            {/* An unscored pillar gets no bar rather than an empty one: a bar
                at zero reads as a pillar that scored nothing. */}
            {pillar.score === null ? null : (
              <div className="tk-bar" aria-hidden="true">
                <div className="tk-bar-fill" style={{ width: `${pillar.score}%` }} />
              </div>
            )}
            <span className="tk-pillar-detail">{pillar.detail}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ------------------------------------------------------------------ insiders

export function InsidersSection({ insiders }: { insiders: Insiders }) {
  const t = useT();
  const mobile = useMobile();
  const summary = insiders.summary;

  // No source is two different findings, worded differently: a US filer whose
  // insiders have not traded, or an issuer that files no Form 4 at all. Saying
  // nothing would read as neither.
  if (!insiders.source) {
    return (
      <Card title={t("ticker.insider_activity")}>
        <Note>
          {t(
            insiders.sec_filer === false ? "ticker.no_form4_non_us" : "ticker.no_form4",
          )}
        </Note>
      </Card>
    );
  }

  const ccy = insiders.trades[0]?.currency ?? null;
  const rows = insiders.trades.slice(0, 30);

  return (
    <Card
      title={t("ticker.insider_activity")}
      note={t(
        insiders.source === "BaFin"
          ? "ticker.insider_caption_bafin"
          : "ticker.insider_caption",
      )}
    >
      {summary ? (
        <KpiGrid>
          {/* Counts on the value line, money on the chip. The count is how many
              trades, which is not how many people: those are the fourth tile,
              and swapping them overstates one insider trading five times. */}
          <Kpi
            label={t("ticker.buys_open_market")}
            value={String(summary.buy_count)}
            chip={
              summary.buy_value
                ? {
                    text: `+${compactMoney(summary.buy_value, ccy ?? "USD")}`,
                    tone: "up",
                  }
                : null
            }
          />
          <Kpi
            label={t("ticker.sells_open_market")}
            value={String(summary.sell_count)}
            chip={
              summary.sell_value
                ? {
                    text: `-${compactMoney(summary.sell_value, ccy ?? "USD")}`,
                    tone: "down",
                  }
                : null
            }
          />
          <Kpi
            label={t("ticker.net_window", { days: summary.window_days })}
            value={compactMoney(summary.net_value, ccy ?? "USD")}
          />
          <Kpi
            label={t("ticker.distinct_buyers_sellers")}
            value={`${summary.buyers} / ${summary.sellers}`}
          />
        </KpiGrid>
      ) : null}

      {/* The one reading the page offers on this data, in the app's words. */}
      {summary?.cluster_buy ? (
        <Banner tone="good">{t("ticker.cluster_buying")}</Banner>
      ) : summary &&
        summary.sell_value > summary.buy_value * 3 &&
        summary.sell_count ? (
        <Banner tone="warn">{t("ticker.selling_dominates")}</Banner>
      ) : null}

      <InsiderFlow insiders={insiders} />

      {mobile ? (
        <div className="tk-stack">
          {rows.map((trade, index) => (
            <div
              className="tk-stack-card"
              key={`${trade.date}-${trade.insider}-${index}`}
            >
              <p className="tk-stack-title">{trade.insider}</p>
              <Line label={t("ticker.col_date")} value={trade.date ?? DASH} />
              {/* Untranslated: the catalog labels only Date/Shares/Price/Value,
                  and Role is the filer's own words. */}
              <Line label="Role" value={trade.role} />
              <Line label={t("ticker.col_type")} value={codeLabel(t, trade)} />
              <Line
                label={t("ticker.col_shares")}
                value={signed(trade.shares, 0)}
                tone={trade.shares >= 0 ? "green" : "red"}
              />
              {trade.price !== null ? (
                <Line
                  label={t("ticker.col_price")}
                  value={insiderPrice(trade.price, trade.currency)}
                />
              ) : null}
              {trade.value !== null ? (
                <Line
                  label={t("ticker.col_value")}
                  value={insiderValue(trade.value, trade.currency)}
                  tone={trade.value >= 0 ? "green" : "red"}
                />
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <Scroll>
          <table className="tk-table">
            <thead>
              <tr>
                <th>{t("ticker.col_date")}</th>
                <th>Insider</th>
                <th>Role</th>
                <th>{t("ticker.col_type")}</th>
                <th>{t("ticker.col_shares")}</th>
                <th>{t("ticker.col_price")}</th>
                <th>{t("ticker.col_value")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((trade, index) => (
                <tr key={`${trade.date}-${trade.insider}-${index}`}>
                  <td>{trade.date ?? DASH}</td>
                  <td>{trade.insider}</td>
                  <td className="tk-muted">{trade.role}</td>
                  <td>{codeLabel(t, trade)}</td>
                  <td className={trade.shares >= 0 ? "tk-is-green" : "tk-is-red"}>
                    {signed(trade.shares, 0)}
                  </td>
                  <td>{insiderPrice(trade.price, trade.currency)}</td>
                  <td
                    className={
                      trade.value === null
                        ? undefined
                        : trade.value >= 0
                          ? "tk-is-green"
                          : "tk-is-red"
                    }
                  >
                    {insiderValue(trade.value, trade.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Scroll>
      )}
      <Note>{t("ticker.signed_caption")}</Note>
    </Card>
  );
}

/**
 * What kind of transaction a row is, in the reader's language: the catalog's
 * word for the Form 4 code, then the English one the API sends, so a code this
 * catalog has not heard of still reads as a word rather than a lone letter.
 */
function codeLabel(t: Translate, trade: Insiders["trades"][number]): string {
  return orElse(t, `ticker.insider_code_${trade.code}`, trade.label || trade.code);
}

function Line({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "green" | "red";
}) {
  return (
    <p className="tk-stack-line">
      <span>{label}</span>
      <span className={tone ? `tk-is-${tone}` : undefined}>{value}</span>
    </p>
  );
}

// ---------------------------------------------------------------------- fund

export function FundSection({
  fund,
  holdings = true,
}: {
  fund: Fund;
  /**
   * The asset mix, sector chart and top holdings. Off for a money-market fund:
   * its basket is deposits, bills and repos rolled weekly — a pie of "Other
   * 100%" and a list of repo lines tell the reader nothing the yield does not,
   * so the card closes on what that kind of fund is instead.
   */
  holdings?: boolean;
}) {
  const t = useT();
  if (!fund.is_fund) return null;
  const cef = fund.closed_end ?? null;
  // What kind of wrapper it is, who runs it, what it is classified as — the
  // three facts that decide whether the rest of the card is worth reading.
  const meta = [
    cef ? t("ticker.cef_kind") : fund.legal_type,
    fund.category,
    fund.family,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card title={t("ticker.fund_profile")} note={meta || fund.name}>
      {cef ? (
        <>
          <CefTiles fund={fund} cef={cef} />
          <CefChecks fund={fund} cef={cef} />
        </>
      ) : (
        <FundTiles fund={fund} />
      )}
      {/* Stocks / bonds / cash, which is what says whether the sector chart
          below is the whole story or a third of it. */}
      {holdings && fund.asset_classes.length > 0 ? (
        <Note>
          {`${t("ticker.fund_assets")} ${fund.asset_classes
            .map(([label, weight]) => `${label} ${percent(weight, 1)}`)
            .join(" · ")}`}
        </Note>
      ) : null}
      {holdings ? (
        <>
          <FundExposure fund={fund} />
          <FundHoldings fund={fund} />
        </>
      ) : null}
      <Note>
        {cef
          ? t("ticker.cef_caption")
          : holdings
            ? t("ticker.fund_caption")
            : t("ticker.cash_caption")}
      </Note>
    </Card>
  );
}

/**
 * Cost, size and income — a fund's answer to the KPI grid.
 *
 * Every tile stands on its own and prints "n/a" rather than the section hiding:
 * Yahoo's coverage of UCITS lines is thin (often no AUM, no category, no yield)
 * and the profile is still worth showing. A bond sleeve swaps the top-ten
 * concentration tile — meaningless when Yahoo publishes no basket for it — for
 * effective duration, which is what a rate move acts on.
 */
function FundTiles({ fund }: { fund: Fund }) {
  const t = useT();
  const na = t("ticker.na");
  const bonds =
    fund.is_bond_fund || (fund.bond_duration !== null && !fund.holdings.length);
  const cell = (value: string) => (value === DASH ? na : value);
  const tiles: [string, string, string][] = [
    ["ticker.fund_ter", cell(percent(fund.expense_ratio, 2)), "ticker.fund_ter_help"],
    [
      "ticker.fund_aum",
      cell(compactMoney(fund.aum, fund.currency)),
      "ticker.fund_aum_help",
    ],
    [
      "ticker.fund_yield",
      cell(percent(fund.dividend_yield, 2)),
      "ticker.fund_yield_help",
    ],
    [
      "ticker.fund_turnover",
      cell(percent(fund.turnover, 1)),
      "ticker.fund_turnover_help",
    ],
    bonds
      ? [
          "ticker.fund_duration",
          fund.bond_duration === null ? na : fund.bond_duration.toFixed(2),
          "ticker.fund_duration_help",
        ]
      : [
          "ticker.fund_top10",
          fund.holdings.length ? cell(percent(fund.disclosed_weight, 1)) : na,
          "ticker.fund_top10_help",
        ],
  ];
  return (
    <KpiGrid>
      {tiles.map(([label, value, help]) => (
        <Kpi key={label} label={t(label)} value={value} help={t(help)} />
      ))}
    </KpiGrid>
  );
}

/**
 * Where a closed-end fund figure came from, in words. A switch of literal
 * keys, so the parity scan sees every one.
 */
function sourceLabel(t: Translate, source: FigureSource, navSymbol: string): string {
  switch (source) {
    case "yahoo":
      return t("ticker.cef_src_yahoo");
    case "yahoo_nav":
      return t("ticker.cef_src_yahoo_nav", { symbol: navSymbol });
    case "edgar_xbrl":
      return t("ticker.cef_src_edgar_xbrl");
    case "edgar_nport":
      return t("ticker.cef_src_edgar_nport");
    default:
      return source;
  }
}

function metricLabel(t: Translate, metric: string): string {
  return metric === "premium"
    ? t("ticker.cef_metric_premium")
    : t("ticker.cef_metric_nav");
}

/**
 * The line under a tile: which source, as of when — or, with no figure, which
 * sources were asked. Never blank: an empty tile that does not say who was
 * asked reads as "nobody looked".
 */
function provenance(
  t: Translate,
  figure: SourcedFigure,
  navSymbol: string,
  lead?: string,
): string {
  const named = (list: FigureSource[]) =>
    list.map((source) => sourceLabel(t, source, navSymbol)).join(", ");
  if (figure.value === null || figure.source === null) {
    return figure.tried.length
      ? t("ticker.cef_tried", { sources: named(figure.tried) })
      : t("ticker.na");
  }
  return [lead, sourceLabel(t, figure.source, navSymbol), figure.as_of]
    .filter(Boolean)
    .join(" · ");
}

/**
 * A closed-end fund's own tiles. It trades at a price of its own against the
 * value of its holdings, so NAV and the premium lead; cost, income, size and
 * leverage follow, each from the filing or feed that publishes it.
 */
function CefTiles({ fund, cef }: { fund: Fund; cef: ClosedEnd }) {
  const t = useT();
  const na = t("ticker.na");
  const sym = currencySymbol(fund.currency);
  const cell = (value: string) => (value === DASH ? na : value);
  const priced = (value: number | null) =>
    value === null ? na : `${sym}${money(value, 2)}`;
  const premiumLead =
    cef.premium.source === "yahoo_nav" && cef.price.value !== null
      ? t("ticker.cef_premium_lead", {
          price: priced(cef.price.value),
          nav: cef.price.as_of === cef.premium.as_of ? priced(navOn(cef)) : na,
        })
      : undefined;
  const tiles: [string, string, string, string][] = [
    [
      t("ticker.cef_nav"),
      priced(cef.nav.value),
      t("ticker.cef_nav_help"),
      provenance(t, cef.nav, cef.nav_symbol),
    ],
    [
      t("ticker.cef_premium"),
      cell(signedPercent(cef.premium.value)),
      t("ticker.cef_premium_help"),
      provenance(t, cef.premium, cef.nav_symbol, premiumLead),
    ],
    [
      t("ticker.cef_distribution"),
      cell(percent(cef.distribution_rate.value, 2)),
      t("ticker.cef_distribution_help"),
      provenance(t, cef.distribution_rate, cef.nav_symbol),
    ],
    [
      t("ticker.fund_ter"),
      cell(percent(cef.expense_ratio.value, 2)),
      t("ticker.cef_ter_help"),
      provenance(t, cef.expense_ratio, cef.nav_symbol),
    ],
    [
      t("ticker.cef_net_assets"),
      cell(compactMoney(cef.net_assets.value, fund.currency)),
      t("ticker.cef_net_assets_help"),
      provenance(t, cef.net_assets, cef.nav_symbol),
    ],
    [
      t("ticker.cef_leverage"),
      cell(percent(cef.leverage.value, 1)),
      t("ticker.cef_leverage_help"),
      provenance(t, cef.leverage, cef.nav_symbol),
    ],
  ];
  return (
    <KpiGrid>
      {tiles.map(([label, value, help, note]) => (
        <Kpi key={label} label={label} value={value} help={help} note={note} />
      ))}
    </KpiGrid>
  );
}

/**
 * The NAV the premium was computed against: the price and premium share a
 * session, so NAV = price ÷ (1 + premium) is that session's, not the latest.
 */
function navOn(cef: ClosedEnd): number | null {
  const { price, premium } = cef;
  if (price.value === null || premium.value === null || premium.value === -1)
    return null;
  return price.value / (1 + premium.value);
}

/**
 * EDGAR against Yahoo, on EDGAR's date. A disagreement is a warning with both
 * numbers in it — the page does not pick one — and a comparison that could
 * not be made says so rather than passing for agreement.
 */
function CefChecks({ fund, cef }: { fund: Fund; cef: ClosedEnd }) {
  const t = useT();
  const sym = currencySymbol(fund.currency);
  const shown = (check: SourceCheck, value: number | null) =>
    value === null
      ? t("ticker.na")
      : check.metric === "premium"
        ? signedPercent(value)
        : `${sym}${money(value, 2)}`;
  if (cef.checks.length === 0) return <Note>{t("ticker.cef_check_absent")}</Note>;
  return (
    <>
      {cef.checks.map((check) => {
        const slots = {
          metric: metricLabel(t, check.metric),
          date: check.as_of,
          official: shown(check, check.official),
          official_source: sourceLabel(t, check.official_source, cef.nav_symbol),
          market: shown(check, check.market),
          market_source: sourceLabel(t, check.market_source, cef.nav_symbol),
        };
        if (check.agree === false) {
          return (
            <Banner key={check.metric} tone="warn">
              <Bold text={t("ticker.cef_check_off", slots)} />
            </Banner>
          );
        }
        return (
          <Note key={check.metric}>
            {check.agree
              ? t("ticker.cef_check_ok", slots)
              : t("ticker.cef_check_none", slots)}
          </Note>
        );
      })}
    </>
  );
}

/**
 * The disclosed basket. Yahoo publishes the top ten only, so the caption says
 * what the rows add up to: a reader who sees ten names must not read them as
 * the whole fund.
 */
function FundHoldings({ fund }: { fund: Fund }) {
  const t = useT();
  if (fund.holdings.length === 0) return <Note>{t("ticker.fund_no_holdings")}</Note>;
  return (
    <>
      <Scroll>
        <table className="tk-table tk-holdings">
          <thead>
            <tr>
              <th>{t("ticker.fund_holding")}</th>
              <th>{t("ticker.fund_weight")}</th>
            </tr>
          </thead>
          <tbody>
            {fund.holdings.map((holding) => (
              <tr key={holding.symbol || holding.name}>
                <td>
                  {/* House rule: every symbol on screen opens its analysis, and
                      reads under the app's own name for it ("Nvidia"), not
                      Yahoo's "NVIDIA Corp", which would name one company two
                      ways across two screens. A line Yahoo gives no symbol for
                      has no page to open, so its own name is all there is. */}
                  {holding.symbol ? (
                    <TickerCell ticker={holding.symbol} />
                  ) : (
                    <span className="tk-muted">{holding.name || DASH}</span>
                  )}
                </td>
                {/* Weights arrive as fractions; scaling once, here. */}
                <td>{percent(holding.weight, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      <Note>
        {fund.closed_end
          ? t("ticker.cef_holdings_caption", {
              n: fund.holdings.length,
              count: fund.closed_end.holdings_count ?? DASH,
              date: fund.closed_end.holdings_as_of ?? DASH,
              pct: percent(fund.disclosed_weight, 1),
            })
          : t("ticker.fund_holdings_caption", {
              n: fund.holdings.length,
              pct: percent(fund.disclosed_weight, 1),
            })}
      </Note>
    </>
  );
}

// --------------------------------------------------------------- comparables

export function ComparablesSection({
  comps,
  children,
}: {
  /** null until a peer is picked — nothing is compared before that. */
  comps: Comparables | null;
  /** The picker, which sits inside the card above the table. */
  children?: ReactNode;
}) {
  const t = useT();
  const mobile = useMobile();
  return (
    <Card
      title={t("ticker.comparables")}
      note={
        comps && Object.keys(comps.medals).length
          ? t("ticker.medals_caption")
          : undefined
      }
    >
      {children}
      {!comps ? <Note>{t("ticker.pick_peers")}</Note> : null}
      {comps ? (
        mobile ? (
          <CompsCards comps={comps} />
        ) : (
          <CompsGrid comps={comps} />
        )
      ) : null}
    </Card>
  );
}

/** Peers across the columns: reads at a glance on a desktop. */
function CompsGrid({ comps }: { comps: Comparables }) {
  return (
    <Scroll>
      <table className="tk-table tk-comps">
        <thead>
          <tr>
            <th />
            {comps.tickers.map((ticker) => (
              <th key={ticker}>
                {comps.medals[ticker] ? `${comps.medals[ticker]} ` : ""}
                <TickerLink ticker={ticker} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comps.labels.map((label, row) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              {comps.tickers.map((ticker) => (
                <td key={ticker}>{comps.rows[ticker]?.[row] ?? DASH}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Scroll>
  );
}

/**
 * The same grid transposed: one card per peer, one KPI per line.
 *
 * A wide table on a 390px screen either pans sideways or squeezes every column
 * to three characters, and a short card beats a complete one there.
 */
function CompsCards({ comps }: { comps: Comparables }) {
  return (
    <div className="tk-stack">
      {comps.tickers.map((ticker) => (
        <div className="tk-stack-card" key={ticker}>
          <p className="tk-stack-title">
            {comps.medals[ticker] ? `${comps.medals[ticker]} ` : ""}
            <TickerLink ticker={ticker} />
          </p>
          {comps.labels.map((label, row) => {
            const cell = comps.rows[ticker]?.[row];
            if (!cell || cell === "n/a") return null;
            return <Line key={label} label={label} value={cell} />;
          })}
        </div>
      ))}
    </div>
  );
}
