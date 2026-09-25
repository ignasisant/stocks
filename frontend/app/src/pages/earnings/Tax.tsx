/**
 * The tax residence's filing dates, drawn on the same calendar as the prints.
 *
 * They come in the same `/earnings` response and ignore the ticker filters: a
 * deadline belongs to the reader, not to any name on the watchlist, so
 * narrowing the calendar to Favorites must not hide the renta.
 *
 * Every date here is a statutory default (see `stocks.portfolio.tax.deadlines`)
 * and the legend says so; an `approximate` one — France's by département,
 * Switzerland's by canton — is printed with a "≈" rather than passed off as
 * exact.
 */

import type { TaxDeadline } from "./data";
import { days, longDate, plain } from "./format";
import type { T } from "./format";
import { useT } from "../../shell/i18n";

function taxTitle(deadline: TaxDeadline, t: T): string {
  return t(`earnings.tax_${deadline.key}`, { year: deadline.year });
}

function taxBody(deadline: TaxDeadline, t: T): string {
  return t(`earnings.tax_${deadline.key}_body`, { year: deadline.year });
}

function when(deadline: TaxDeadline, t: T): string {
  const mark = deadline.approximate ? t("earnings.tax_approx_mark") : "";
  return `${mark}${longDate(deadline.date, t)}`;
}

/** The ones inside the 30-day window, said before anything else on the page. */
export function TaxReminders({ deadlines }: { deadlines: TaxDeadline[] }) {
  const t = useT();
  const due = deadlines.filter((deadline) => deadline.remind);
  if (due.length === 0) return null;
  return (
    <div className="earn-tax-warn" role="status">
      {due.map((deadline) => {
        const slots = {
          title: taxTitle(deadline, t),
          date: longDate(deadline.date, t),
          days: deadline.days_until,
        };
        const key =
          deadline.days_until === 0
            ? "earnings.tax_reminder_today"
            : deadline.approximate
              ? "earnings.tax_reminder_approx"
              : "earnings.tax_reminder";
        return (
          <p key={`${deadline.key}-${deadline.year}`}>
            <strong>{t(key, slots)}</strong> {taxBody(deadline, t)}
          </p>
        );
      })}
    </div>
  );
}

export function TaxChip({ deadline }: { deadline: TaxDeadline }) {
  const t = useT();
  return (
    <div
      className="earn-chip tax"
      title={`${taxTitle(deadline, t)} — ${taxBody(deadline, t)}`}
    >
      <span>
        {deadline.approximate ? t("earnings.tax_approx_mark") : ""}
        {taxTitle(deadline, t)}
      </span>
    </div>
  );
}

/** The list view's section: only what is still ahead. */
export function TaxTable({ deadlines }: { deadlines: TaxDeadline[] }) {
  const t = useT();
  const ahead = deadlines.filter((deadline) => deadline.days_until >= 0);
  if (ahead.length === 0) return null;
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.tax_deadlines"))}</h2>
      <table className="earn-table">
        <thead>
          <tr>
            <th className="left">{t("earnings.tax_col_deadline")}</th>
            <th className="left">{t("earnings.list_col_date")}</th>
            <th>{t("earnings.list_col_days_out")}</th>
          </tr>
        </thead>
        <tbody>
          {ahead.map((deadline) => (
            <tr
              key={`${deadline.key}-${deadline.year}`}
              className={deadline.remind ? "earn-tax-soon" : undefined}
            >
              <td className="left" title={taxBody(deadline, t)}>
                {taxTitle(deadline, t)}
              </td>
              <td className="left">{when(deadline, t)}</td>
              <td>{days(deadline.days_until)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** What the amber chips are, and how far to trust their dates. */
export function TaxLegend({ jurisdiction }: { jurisdiction: string | null }) {
  const t = useT();
  if (!jurisdiction) return null;
  const country = t(`profile.tax_residence_${jurisdiction.toLowerCase()}`);
  return <p className="earn-legend">{t("earnings.tax_legend", { country })}</p>;
}
