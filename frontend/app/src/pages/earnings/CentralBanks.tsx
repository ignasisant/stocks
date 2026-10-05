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

export function CentralBankLegend() {
  const t = useT();
  return <p className="earn-legend">{t("earnings.cb_legend")}</p>;
}
