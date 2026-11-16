/**
 * The next seven days, in one strip over the calendar: what lands, when, and
 * how much of the book it is.
 *
 * It replaces the amber "N reports inside a week" line. A count says there is
 * something to look at; this says what, on which day, and what share of the
 * book the reporting names carry, so a reader can tell a quiet week from the
 * one where a fifth of the portfolio prints. Every row is a button that opens
 * the same side panel the grid's chips do.
 *
 * Only what is dated and ahead: the book's own trades and booked payouts are
 * behind it, and a past print has its chip on the grid.
 */

import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { percent } from "../../shell/format";
import { TickerCell } from "../../shell/tickers";
import type {
  CalendarDividend,
  CalendarEvent,
  CentralBankDecision,
  EventPick,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { weighed, weightOf, within } from "./data";
import { shortDay } from "./format";
import { taxTitle } from "./Tax";

type Item = {
  key: string;
  date: string;
  /** Soonest first; same-day items keep the order they were listed in. */
  who: ReactNode;
  what: string;
  weight: number | null;
  pick: EventPick;
};

export function Strip({
  events,
  dividends,
  deadlines,
  windows,
  banks,
  weights,
  onPick,
}: {
  events: CalendarEvent[];
  dividends: CalendarDividend[];
  deadlines: TaxDeadline[];
  windows: RepurchaseWindow[];
  banks: CentralBankDecision[];
  weights: Record<string, number> | undefined;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const prints = events.filter(
    (event) => event.date !== null && within(event.days_until),
  );
  const ex = dividends.filter((dividend) => within(dividend.days_until));

  const name = (ticker: string) => (
    <TickerCell className="earn-strip-tick" ticker={ticker} name={false}>
      {ticker}
    </TickerCell>
  );
  const items: Item[] = [
    ...prints.map((event) => ({
      key: `print-${event.ticker}`,
      date: event.date as string,
      who: name(event.ticker),
      what: t("earnings.kind_earnings"),
      weight: weightOf(weights, event.ticker),
      pick: { kind: "print", item: event } as EventPick,
    })),
    ...ex.map((dividend) => ({
      key: `div-${dividend.ticker}-${dividend.date}`,
      date: dividend.date,
      who: name(dividend.ticker),
      what: t("earnings.strip_exdiv"),
      weight: weightOf(weights, dividend.ticker),
      pick: { kind: "dividend", item: dividend } as EventPick,
    })),
    ...windows
      .filter((window) => within(window.days_until))
      .map((window) => ({
        key: `rebuy-${window.ticker}-${window.sell_date}`,
        date: window.date,
        who: name(window.ticker),
        what: t("earnings.strip_rebuy"),
        weight: null,
        pick: { kind: "rebuy", item: window } as EventPick,
      })),
    ...deadlines
      .filter((deadline) => within(deadline.days_until))
      .map((deadline) => ({
        key: `tax-${deadline.key}-${deadline.year}`,
        date: deadline.date,
        who: <b className="earn-strip-plain">{taxTitle(deadline, t)}</b>,
        what: t("earnings.kind_tax"),
        weight: null,
        pick: { kind: "tax", item: deadline } as EventPick,
      })),
    ...banks
      .filter((decision) => within(decision.days_until))
      .map((decision) => ({
        key: `bank-${decision.bank}-${decision.date}`,
        date: decision.date,
        who: <b className="earn-strip-plain">{t(`earnings.cb_${decision.bank}`)}</b>,
        what: t("earnings.kind_banks"),
        weight: null,
        pick: { kind: "bank", item: decision } as EventPick,
      })),
  ].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  const share = weighed(prints, weights);
  return (
    <section className="earn-strip" aria-labelledby="earn-strip-h">
      <h2 id="earn-strip-h" className="earn-strip-h">
        {t("earnings.strip_title")}
      </h2>
      {items.length === 0 ? (
        <p className="earn-strip-sum">{t("earnings.strip_none")}</p>
      ) : (
        <>
          <p className="earn-strip-sum">
            {prints.length > 0 && (
              <b>
                {t(
                  prints.length === 1
                    ? "earnings.strip_prints_one"
                    : "earnings.strip_prints",
                  { n: prints.length },
                )}
              </b>
            )}
            {prints.length > 0 && share !== null && (
              <>
                {" "}
                {t("earnings.strip_weight", {
                  pct: percent(share, { digits: 1 }) ?? "",
                })}
              </>
            )}
            {ex.length > 0 && (
              <>
                {prints.length > 0 ? " · " : ""}
                {t(ex.length === 1 ? "earnings.strip_ex_one" : "earnings.strip_ex", {
                  n: ex.length,
                })}
              </>
            )}
          </p>
          <ul className="earn-strip-list">
            {items.map((item) => (
              <li key={item.key}>
                <span className="earn-strip-day">
                  <small>{shortDay(item.date, t).weekday}</small>
                  <b>{shortDay(item.date, t).day}</b>
                </span>
                <span className="earn-strip-body">
                  {item.who}
                  <button
                    type="button"
                    className="earn-strip-what"
                    onClick={() => onPick(item.pick)}
                  >
                    {item.what}
                    {item.weight !== null && (
                      <>
                        {" · "}
                        <b>
                          {t("earnings.strip_weighs", {
                            pct: percent(item.weight, { digits: 1 }) ?? "",
                          })}
                        </b>
                      </>
                    )}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
