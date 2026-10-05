/**
 * The day each loss sold this season can be bought back without deferring it.
 *
 * Spain blocks a loss when the same security is bought back within two months
 * of the sale, the US and Canada within 30 days, Ireland within 28 (see
 * `stocks.portfolio.tax.base.window_end`). The engine already knows which
 * sales are exposed; this draws the first free day, so a reader who sold to
 * harvest a loss knows when the name can come back into the book.
 *
 * Like the tax deadlines, these ignore the ticker filters: the name was sold,
 * so it has usually left the Portfolio group the filter would match it by.
 * The chip opens the dialog that explains the rule; the dialog links on to
 * the ticker, since buying back is a decision taken on that page.
 */

import { useLang, useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { moneyIn } from "../portfolio/format";
import type { EventPick, RepurchaseWindow } from "./data";
import { longDate } from "./format";
import type { T } from "./format";

const DASH = "—";

export function loss(lang: string, window: RepurchaseWindow): string {
  return moneyIn(lang, window.currency)(window.loss, { digits: 2 }) ?? DASH;
}

/** "two months", "30 days" — the rule, in words, for the hover and legend. */
export function rule(window: string, t: T): string {
  return t(`earnings.rebuy_rule_${window}`);
}

function rebuyTitle(window: RepurchaseWindow, lang: string, t: T): string {
  return t("earnings.rebuy_title", {
    ticker: window.ticker,
    sold: longDate(window.sell_date, t),
    loss: loss(lang, window),
    rule: rule(window.window, t),
  });
}

export function RepurchaseChip({
  window,
  onPick,
}: {
  window: RepurchaseWindow;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useTickerProfile(window.ticker);
  return (
    <button
      type="button"
      className="earn-chip rebuy"
      title={rebuyTitle(window, lang, t)}
      onClick={() => onPick({ kind: "rebuy", item: window })}
    >
      {profile?.logo && <img src={profile.logo} alt="" loading="lazy" />}
      <span>{t("earnings.rebuy_chip", { ticker: window.ticker })}</span>
    </button>
  );
}

/** What the outlined amber chips are. One rule per residence, so one legend. */
export function RepurchaseLegend({ windows }: { windows: RepurchaseWindow[] }) {
  const t = useT();
  const first = windows[0];
  if (first === undefined) return null;
  return (
    <p className="earn-legend">
      {t("earnings.rebuy_legend", { rule: rule(first.window, t) })}
    </p>
  );
}
