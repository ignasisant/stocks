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
import { TickerCell, useTickerProfile } from "../../shell/tickers";
import { DenseRows, Responsive } from "../../ui/Rows";
import { moneyIn } from "../portfolio/format";
import type { EventPick, RepurchaseWindow } from "./data";
import { days, longDate, plain } from "./format";
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

/** The list view's section, soonest first: the order the API sends. */
export function RepurchaseTable({ windows }: { windows: RepurchaseWindow[] }) {
  const t = useT();
  const lang = useLang();
  if (windows.length === 0) return null;
  const key = (w: RepurchaseWindow) => `${w.ticker}-${w.sell_date}`;
  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.rebuy_windows"))}</h2>
      <Responsive
        wide={
          <table className="earn-table">
            <thead>
              <tr>
                <th className="left">{t("earnings.list_col_ticker")}</th>
                <th className="left">{t("earnings.rebuy_col_sold")}</th>
                <th className="left">{t("earnings.rebuy_col_free")}</th>
                <th>{t("earnings.rebuy_col_loss")}</th>
                <th>{t("earnings.list_col_days_out")}</th>
              </tr>
            </thead>
            <tbody>
              {windows.map((w) => (
                <tr key={key(w)} title={rebuyTitle(w, lang, t)}>
                  <td className="left">
                    <TickerCell className="earn-ticker" ticker={w.ticker}>
                      {w.ticker}
                    </TickerCell>
                  </td>
                  <td className="left">{longDate(w.sell_date, t)}</td>
                  <td className="left">{longDate(w.date, t)}</td>
                  <td className="earn-down">{loss(lang, w)}</td>
                  <td>{days(w.days_until)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        }
        narrow={
          <DenseRows
            rows={windows}
            rowKey={key}
            spec={{
              ticker: (w) => w.ticker,
              value: (w) => days(w.days_until),
              delta: (w) => longDate(w.date, t),
              sub: (w) => [
                `${t("earnings.rebuy_col_sold")} ${longDate(w.sell_date, t)}`,
                `${t("earnings.rebuy_col_loss")} ${loss(lang, w)}`,
              ],
            }}
          />
        }
      />
    </section>
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
