/**
 * The cards a reader adds from other screens: risk, dividends, the tax year
 * and sector rotation. None is on a new account's Home — each starts in the
 * "add" tray — and each is mounted only while it is on the page, so a card
 * left in the tray costs no request.
 *
 * Each is a compressed cut of a screen that already exists, over the routes
 * that screen already calls, with a link to the full thing. Nothing is
 * computed here that the owning screen does not compute the same way.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { Link } from "../../shell/router";
import { Chip, Kpi, KpiGrid, chipFor } from "../../ui/Kpi";
import type { Dividends, Risk, TaxReport } from "../portfolio/api";
import { useTaxWords } from "../portfolio/taxWords";
import type { EarningsCalendar } from "../earnings/data";
import type { PulseBook, TrendBlock, TrendTables } from "../sentiment/types";
import { maybe, sectorKey } from "../sentiment/format";
import { Card, CardQuery, CardTitle, Note, TickerCell } from "./ui";
import { decimal, money, percent, plain, shortDate } from "./format";

function More({ tab, label }: { tab: string; label: string }) {
  return (
    <Link page="portfolio" params={{ tab }} className="hm-link">
      {label}
    </Link>
  );
}

/* ------------------------------------------------------------------ risk */

/** How the book rides the market: beta and its stance, then the bumps. */
export function RiskCard() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const query = useApi(
    () =>
      Promise.all([
        get<Risk>("/portfolio/risk", { base, period: "1y" }),
        // The beta is the Pulse's; a feed it could not reach costs the
        // headline tile, not the card.
        get<PulseBook>("/pulse/book", { base }).catch(() => null),
      ]),
    [base],
  );
  const na = t("home.na");
  const title = plain(t("home.card_risk"));
  return (
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      title={title}
      skeleton={<Skeleton rows={3} />}
    >
      {([risk, book]) => (
        <Card>
          <CardTitle>{title}</CardTitle>
          <KpiGrid>
            <Kpi
              label={t("sentiment.beta_equity")}
              value={decimal(book?.beta, lang, 2) ?? na}
              note={book?.stance ? t(`sentiment.stance_${book.stance}`) : undefined}
            />
            <Kpi
              label={t("portfolio.annualised_vol")}
              value={percent(risk.volatility, lang, { digits: 1 }) ?? na}
              help={t("portfolio.basket_vol_help")}
            />
            <Kpi
              label={t("portfolio.max_drawdown")}
              value={percent(risk.max_drawdown, lang, { digits: 1 }) ?? na}
              help={t("portfolio.basket_dd_help")}
            />
            <Kpi
              label={t("portfolio.effective_names")}
              value={decimal(risk.effective_names, lang, 1) ?? na}
              help={t("portfolio.effective_names_help")}
            />
          </KpiGrid>
          <More tab="risk" label={t("home.card_more_risk")} />
        </Card>
      )}
    </CardQuery>
  );
}

/* ------------------------------------------------------------- dividends */

/** What the year paid, what the next twelve months should, and who is next. */
export function DividendsCard() {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const query = useApi(
    () =>
      Promise.all([
        get<Dividends>("/portfolio/dividends", { base }),
        // The upcoming dates are the calendar's; without it the totals stand.
        get<EarningsCalendar>("/earnings").catch(() => null),
      ]),
    [base],
  );
  const na = t("home.na");
  const title = plain(t("home.card_dividends"));
  return (
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      title={title}
      skeleton={<Skeleton rows={3} />}
    >
      {([dividends, calendar]) => {
        const next = (calendar?.dividends ?? [])
          .filter((row) => row.days_until >= 0)
          .slice(0, 3);
        return (
          <Card>
            <CardTitle>{title}</CardTitle>
            <KpiGrid>
              <Kpi
                label={t("portfolio.div_kpi_ytd")}
                value={money(dividends.booked_ytd, dividends.base || base, lang) ?? na}
                help={t("portfolio.div_kpi_ytd_help")}
              />
              <Kpi
                label={t("portfolio.div_kpi_next")}
                value={
                  money(dividends.forward_annual, dividends.base || base, lang) ?? na
                }
                help={t("portfolio.div_kpi_next_help")}
              />
            </KpiGrid>
            {next.length > 0 ? (
              <ul className="hm-extra-list">
                {next.map((row) => (
                  <li key={`${row.ticker}-${row.date}`}>
                    <TickerCell ticker={row.ticker} name={false} />
                    <span className="hm-muted">
                      {t("home.card_ex_date", { date: shortDate(row.date, lang) })}
                    </span>
                    <span className="hm-num">
                      {money(
                        row.amount_base,
                        row.base_currency || dividends.base || base,
                        lang,
                      ) ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Note>{t("home.card_no_ex_dates")}</Note>
            )}
            <More tab="dividends" label={t("home.card_more_dividends")} />
          </Card>
        );
      }}
    </CardQuery>
  );
}

/* ------------------------------------------------------------------- tax */

/** This tax year's headline figures, any reporting line crossed, the next date. */
export function TaxCard() {
  const t = useT();
  const query = useApi(
    () =>
      Promise.all([
        get<TaxReport>("/portfolio/tax"),
        get<EarningsCalendar>("/earnings").catch(() => null),
      ]),
    [],
  );
  const title = plain(t("home.card_tax"));
  return (
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      title={title}
      skeleton={<Skeleton rows={3} />}
    >
      {([report, calendar]) => (
        <TaxBody report={report} calendar={calendar} title={title} />
      )}
    </CardQuery>
  );
}

function TaxBody({
  report,
  calendar,
  title,
}: {
  report: TaxReport;
  calendar: EarningsCalendar | null;
  title: string;
}) {
  const t = useT();
  const lang = useLang();
  // The same words the Tax tab uses: `portfolio.<code>_<name>`, else the
  // neutral `portfolio.<name>` — the API ships names, not sentences.
  const words = useTaxWords(report.jurisdiction);
  const na = t("home.na");
  const cash = (value: number) => money(value, report.currency, lang) ?? na;
  // The newest year the engine replayed: the current one once anything
  // in it was sold, otherwise the last one that had a sale.
  const year = report.years[report.years.length - 1] ?? null;
  const crossed = report.flags.filter((flag) => flag.reportable);
  const due = (calendar?.tax_deadlines ?? []).find((row) => row.days_until >= 0);
  return (
    <Card>
      <div className="hm-card-head">
        <CardTitle>{title}</CardTitle>
        {year ? (
          <span className="hm-caption">{year.year_label || year.period}</span>
        ) : null}
      </div>
      {year ? (
        <KpiGrid>
          {year.kpis.slice(0, 3).map((kpi) => (
            <Kpi
              key={kpi.name}
              label={words.say(kpi.name)}
              value={cash(kpi.value)}
              help={words.say(kpi.help)}
            />
          ))}
        </KpiGrid>
      ) : (
        <Note>{t("home.card_tax_no_sales")}</Note>
      )}
      {crossed.map((flag) => (
        <p key={flag.name} className="hm-callout hm-callout-warn">
          {t("home.card_tax_flag", {
            val: cash(flag.total_value),
            threshold: cash(flag.threshold),
          })}
        </p>
      ))}
      {due ? (
        <Note>
          {t(dueKey(due.days_until, due.approximate), {
            title: t(`earnings.tax_${due.key}`, { year: due.year }),
            date: shortDate(due.date, lang),
            days: due.days_until,
          })}
        </Note>
      ) : null}
      <More tab="tax" label={t("home.card_more_tax")} />
    </Card>
  );
}

function dueKey(days: number, approximate: boolean): string {
  if (days === 0) return "home.card_tax_due_today";
  if (approximate) return "home.card_tax_due_approx";
  return days === 1 ? "home.card_tax_due_tomorrow" : "home.card_tax_due";
}

/* -------------------------------------------------------------- rotation */

const ROTATION_SHOWN = 3;

/**
 * The sectors beating and trailing the S&P 500 this month, with the reader's
 * own weight in each. The figure is already the excess return over the index
 * (`/pulse/tables` rotation block), so the sign is the whole verdict — and
 * which side a sector lands on: a month where only one sector beat the index
 * shows one, not the two least-bad losers beside it.
 */
export function RotationCard() {
  const t = useT();
  const query = useApi(
    () => get<TrendTables>("/pulse/tables", { blocks: "rotation" }),
    [],
  );
  const title = plain(t("home.card_rotation"));
  return (
    <CardQuery
      query={query}
      note={t("home.data_unavailable")}
      title={title}
      skeleton={<Skeleton rows={3} />}
    >
      {(tables) => {
        const block = tables.blocks.find((b) => b.block === "rotation") ?? null;
        return (
          <Card>
            <CardTitle>{title}</CardTitle>
            <Rotation block={block} />
            <Link page="sentiment" className="hm-link">
              {t("home.card_more_rotation")}
            </Link>
          </Card>
        );
      }}
    </CardQuery>
  );
}

function Rotation({ block }: { block: TrendBlock | null }) {
  const t = useT();
  const lang = useLang();
  const rows = (block?.rows ?? []).filter((row) => row.changes.month !== undefined);
  if (rows.length === 0) return <Note>{t("home.market_unavailable")}</Note>;
  const sorted = [...rows].sort(
    (a, b) => (b.changes.month ?? 0) - (a.changes.month ?? 0),
  );
  const leaders = sorted
    .filter((row) => (row.changes.month ?? 0) > 0)
    .slice(0, ROTATION_SHOWN);
  const laggards = sorted
    .filter((row) => (row.changes.month ?? 0) < 0)
    .slice(-ROTATION_SHOWN)
    .reverse();
  const side = (heading: string, list: typeof rows, none: string) => (
    <div>
      <p className="hm-caption">{heading}</p>
      {list.length === 0 ? (
        <Note>{none}</Note>
      ) : (
        <ul className="hm-extra-list">
          {list.map((row) => {
            const move = row.changes.month ?? null;
            return (
              <li key={row.key}>
                <Link page="ticker" params={{ ticker: row.key }} title={row.key}>
                  {maybe(t, `sentiment.sector_${sectorKey(row.name)}`) ?? row.name}
                </Link>
                {row.weight ? (
                  <span className="hm-muted">
                    {t("home.card_rotation_weight", {
                      weight: percent(row.weight, lang, { digits: 0 }) ?? "",
                    })}
                  </span>
                ) : null}
                <Chip
                  chip={chipFor(move, percent(move, lang, { signed: true, digits: 1 }))}
                />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
  return (
    <div className="hm-split">
      {side(
        t("home.card_rotation_leading"),
        leaders,
        t("home.card_rotation_no_leaders"),
      )}
      {side(
        t("home.card_rotation_lagging"),
        laggards,
        t("home.card_rotation_no_laggards"),
      )}
    </div>
  );
}
