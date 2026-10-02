/**
 * Fed and ECB rate-decision days on the same calendar as the prints.
 *
 * Both banks publish the year's schedule in advance (`stocks.data.
 * macro_calendar`), so these are exact dates, not estimates. They belong to no
 * name, so the ticker filters leave them alone — and they are context, not
 * content: a watchlist with no prints does not get a calendar just to show
 * them, and the empty-filter note ignores them.
 */

import { useT } from "../../shell/i18n";
import type { CentralBankDecision, EventPick } from "./data";
import { days, longDate, plain } from "./format";

/** The list shows a quarter ahead: two meetings a bank, give or take. */
const LIST_DAYS = 92;

export function CentralBankChip({
  decision,
  onPick,
}: {
  decision: CentralBankDecision;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  return (
    <button
      type="button"
      className="earn-chip cb"
      title={t(`earnings.cb_${decision.bank}_title`)}
      onClick={() => onPick({ kind: "bank", item: decision })}
    >
      <span>{t(`earnings.cb_${decision.bank}`)}</span>
    </button>
  );
}

/** The list view's section: only what is ahead, and only the next quarter. */
export function CentralBankTable({ decisions }: { decisions: CentralBankDecision[] }) {
  const t = useT();
  const ahead = decisions.filter((d) => d.days_until >= 0 && d.days_until <= LIST_DAYS);
  if (ahead.length === 0) return null;
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.cb_decisions"))}</h2>
      <table className="earn-table">
        <thead>
          <tr>
            <th className="left">{t("earnings.cb_col_bank")}</th>
            <th className="left">{t("earnings.list_col_date")}</th>
            <th>{t("earnings.list_col_days_out")}</th>
          </tr>
        </thead>
        <tbody>
          {ahead.map((d) => (
            <tr key={`${d.bank}-${d.date}`}>
              <td className="left" title={t(`earnings.cb_${d.bank}_title`)}>
                {t(`earnings.cb_${d.bank}`)}
              </td>
              <td className="left">{longDate(d.date, t)}</td>
              <td>{days(d.days_until)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function CentralBankLegend() {
  const t = useT();
  return <p className="earn-legend">{t("earnings.cb_legend")}</p>;
}
