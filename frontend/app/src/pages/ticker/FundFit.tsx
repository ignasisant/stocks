/**
 * A fund set against the reader's own book: what it repeats, what it adds,
 * and what it costs them.
 *
 * A world ETF bought beside Apple, Microsoft and Nvidia is not the
 * diversification it reads as on its own card, so this card answers the
 * question the fund profile cannot: the fund's top holdings the book already
 * owns, the book's sectors with and without it against the plan's cap, and
 * the fund's running cost beside the spread and commission the reader's own
 * fills paid.
 */

import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { DASH, percent } from "../../shell/format";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { maybe, sectorKey } from "../sentiment/format";
import { Card, Note, Scroll, Subhead } from "./ui";
import type { Fund, FundFit } from "./types";

const pct = (value: number | null | undefined, digits = 1) =>
  percent(value ?? null, { digits, tight: true }) ?? DASH;

export function FundFitSection({ fund, fit }: { fund: Fund; fit: FundFit }) {
  const t = useT();
  const cap = fit.sector_cap;
  const over = cap !== null && fit.sectors.some((row) => row.book > cap);
  return (
    <Card
      title={t("ticker.fit_title")}
      note={
        fit.held
          ? t("ticker.fit_held", { pct: pct(fit.fund_share) })
          : t("ticker.fit_unheld")
      }
    >
      <Subhead>{t("ticker.fit_overlap")}</Subhead>
      {fit.overlap.length ? (
        <>
          <Scroll>
            <table className="tk-table tk-holdings">
              <thead>
                <tr>
                  <th>{t("ticker.fund_holding")}</th>
                  <th>{t("ticker.fit_in_fund")}</th>
                  <th>{t("ticker.fit_in_book")}</th>
                </tr>
              </thead>
              <tbody>
                {fit.overlap.map((row) => (
                  <tr key={row.symbol}>
                    <td>
                      <TickerCell ticker={row.symbol} />
                    </td>
                    <td>{pct(row.fund_weight, 2)}</td>
                    <td>{pct(row.book_weight)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <Note>
            {t("ticker.fit_overlap_line", {
              n: fit.overlap.length,
              pct: pct(fit.overlap_weight),
              disclosed: pct(fit.disclosed_weight),
            })}
          </Note>
        </>
      ) : (
        <Note>
          {fit.disclosed_weight > 0
            ? t("ticker.fit_overlap_none")
            : t("ticker.fund_no_holdings")}
        </Note>
      )}

      {fit.sectors.length ? (
        <>
          <Subhead>{t("ticker.fit_sectors")}</Subhead>
          <Scroll>
            <table className="tk-table">
              <thead>
                <tr>
                  <th>{t("ticker.fit_sector")}</th>
                  <th>{t("ticker.fit_in_book")}</th>
                  <th>{t("ticker.fit_in_fund")}</th>
                  {fit.held ? <th>{t("ticker.fit_without")}</th> : null}
                </tr>
              </thead>
              <tbody>
                {fit.sectors.map((row) => (
                  <tr key={row.label}>
                    <td>
                      {maybe(t, `sentiment.sector_${sectorKey(row.label)}`) ??
                        row.label}
                    </td>
                    {/* Weight as well as colour: red alone is no signal to
                        a reader who cannot tell it apart. */}
                    {cap !== null && row.book > cap ? (
                      <td className="tk-is-red">
                        <strong>{pct(row.book)}</strong>
                      </td>
                    ) : (
                      <td>{pct(row.book)}</td>
                    )}
                    <td>{pct(row.fund)}</td>
                    {fit.held ? <td>{pct(row.without)}</td> : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroll>
          <Note>
            {over
              ? `${t("ticker.fit_sectors_caption")} ${t("ticker.fit_over_cap", { cap: pct(cap, 0) })}`
              : t("ticker.fit_sectors_caption")}
          </Note>
        </>
      ) : null}

      <Subhead>{t("ticker.fit_cost")}</Subhead>
      <KpiGrid>
        <Kpi
          label={t("ticker.fund_ter")}
          value={
            fund.expense_ratio === null ? t("ticker.na") : pct(fund.expense_ratio, 2)
          }
          help={t("ticker.fit_ter_help")}
        />
        {fit.trades ? (
          <>
            <Kpi
              label={t("ticker.fit_spread")}
              value={fit.spread === null ? t("ticker.na") : pct(fit.spread, 2)}
              help={t("ticker.fit_spread_help")}
            />
            <Kpi
              label={t("ticker.fit_commission")}
              value={fit.commission === null ? t("ticker.na") : pct(fit.commission, 2)}
              help={t("ticker.fit_commission_help")}
            />
          </>
        ) : null}
      </KpiGrid>
      <Note>
        {fit.trades === 1
          ? t("ticker.fit_cost_caption_one")
          : fit.trades
            ? t("ticker.fit_cost_caption_n", { n: fit.trades })
            : t("ticker.fit_cost_unheld")}
      </Note>
      {/* A Spanish index fund moves to another tax-free; a listed ETF cannot,
          which is the trade-off a Spanish reader weighs before buying one. */}
      {fit.jurisdiction === "ES" && fund.quote_type === "ETF" ? (
        <Note>{t("ticker.fit_es_transfer")}</Note>
      ) : null}
    </Card>
  );
}
