/**
 * The book's ex-dividend dates, drawn on the same calendar as the prints.
 *
 * They come in the same `/earnings` response, and they obey the ticker
 * filters — unlike the tax dates, a dividend belongs to a name. Funds are in
 * here even though the prints leave them out: an ETF never reports, but a
 * distributing one pays.
 *
 * Every amount is an estimate and the copy says so. A past chip is what the
 * shares were owed from Yahoo's per-share history, booked or not; an upcoming
 * one is the next declared date priced at the LAST payment, because Yahoo
 * publishes the date before the figure. A projected one is not declared at
 * all — last year's date moved a year on — so it is drawn dashed and marked
 * "≈", the way an approximate tax date is.
 *
 * The chip does not lead to the ticker: what a reader wants from an ex-date is
 * the cash, so it opens the dialog that says what lands in the account.
 */

import { useLang, useT } from "../../shell/i18n";
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { DenseRows, Responsive } from "../../ui/Rows";
import { moneyIn, shares as formatShares } from "../portfolio/format";
import type { CalendarDividend, EventPick } from "./data";
import { days, longDate, plain } from "./format";
import type { T } from "./format";

const DASH = "—";

/** Cash in the dividend's own currency; a bare figure when Yahoo named none. */
export function cash(
  lang: string,
  value: number | null,
  currency: string | null,
): string {
  if (value === null) return DASH;
  return currency
    ? (moneyIn(lang, currency)(value, { digits: 2 }) ?? DASH)
    : value.toFixed(2);
}

function breakdown(dividend: CalendarDividend, lang: string, t: T): string {
  return t("earnings.div_breakdown", {
    per_share: cash(lang, dividend.per_share, dividend.currency),
    shares: formatShares(lang, dividend.shares) ?? DASH,
    amount: cash(lang, dividend.amount, dividend.currency),
  });
}

function dividendTitle(
  dividend: CalendarDividend,
  name: string | undefined,
  lang: string,
  t: T,
): string {
  const who = name ? `${dividend.ticker} — ${name}` : dividend.ticker;
  const note = dividend.projected
    ? t("earnings.div_projected_note")
    : dividend.days_until >= 0
      ? t("earnings.div_next_note")
      : "";
  return `${who} · ${t("earnings.div_ex")} · ${breakdown(dividend, lang, t)}${note}`;
}

function mark(dividend: CalendarDividend, t: T): string {
  return dividend.projected ? t("earnings.tax_approx_mark") : "";
}

/** Opens what the payment comes to; the hover carries the same figures. */
export function DividendChip({
  dividend,
  onPick,
}: {
  dividend: CalendarDividend;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useTickerProfile(dividend.ticker);
  return (
    <button
      type="button"
      className={`earn-chip div${dividend.projected ? " projected" : ""}`}
      title={dividendTitle(dividend, profile?.name, lang, t)}
      onClick={() => onPick({ kind: "dividend", item: dividend })}
    >
      {profile?.logo && <img src={profile.logo} alt="" loading="lazy" />}
      <span>
        {mark(dividend, t)}
        {t("earnings.div_chip", { ticker: dividend.ticker })}
      </span>
    </button>
  );
}

/**
 * The list view's section: what is coming, soonest first, then what already
 * went ex, newest first — the order a reader scanning for "what's next, what
 * just paid" reads in. A projected row keeps its place in that order; its "≈"
 * and its hover say it is a guess.
 */
export function DividendTable({ dividends }: { dividends: CalendarDividend[] }) {
  const t = useT();
  const lang = useLang();
  if (dividends.length === 0) return null;
  const ahead = dividends.filter((d) => d.days_until >= 0);
  const behind = dividends.filter((d) => d.days_until < 0).reverse();
  const rows = [...ahead, ...behind];
  const key = (d: CalendarDividend) => `${d.ticker}-${d.date}`;
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.dividends"))}</h2>
      <Responsive
        wide={
          <table className="earn-table">
            <thead>
              <tr>
                <th className="left">{t("earnings.list_col_ticker")}</th>
                <th className="left">{t("earnings.list_col_ex_date")}</th>
                <th>{t("earnings.list_col_per_share")}</th>
                <th>{t("earnings.list_col_amount")}</th>
                <th>{t("earnings.list_col_days_out")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr
                  key={key(d)}
                  className={
                    d.projected
                      ? "earn-div-projected"
                      : d.days_until >= 0
                        ? "earn-div-next"
                        : undefined
                  }
                  title={d.projected ? t("earnings.div_projected_row") : undefined}
                >
                  <td className="left">
                    <TickerCell className="earn-ticker" ticker={d.ticker}>
                      {d.ticker}
                    </TickerCell>
                  </td>
                  <td className="left">
                    {mark(d, t)}
                    {longDate(d.date, t)}
                  </td>
                  <td>{cash(lang, d.per_share, d.currency)}</td>
                  <td title={breakdown(d, lang, t)}>
                    {cash(lang, d.amount, d.currency)}
                  </td>
                  {/* Days are a countdown: a date already behind has none. */}
                  <td>{d.days_until >= 0 ? days(d.days_until) : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
        narrow={
          <DenseRows
            rows={rows}
            rowKey={key}
            spec={{
              ticker: (d) => d.ticker,
              value: (d) => cash(lang, d.amount, d.currency),
              delta: (d) => `${mark(d, t)}${longDate(d.date, t)}`,
              sub: (d) => [breakdown(d, lang, t)],
            }}
          />
        }
      />
    </section>
  );
}

/** What the blue chips are, and how far to trust their amounts. */
export function DividendLegend() {
  const t = useT();
  return <p className="earn-legend">{t("earnings.dividend_legend")}</p>;
}
