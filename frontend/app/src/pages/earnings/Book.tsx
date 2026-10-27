/**
 * The reader's own days on the calendar: what they bought and sold, what
 * landed in the account, and when the exchanges they trade on are shut.
 *
 * Trades and payouts come off the ledger, not Yahoo, so unlike the ex-date
 * chips they are facts rather than estimates. They obey the ticker filters,
 * since each belongs to a name. A trade is drawn hollow: it is something the
 * reader did, not something that will happen to them, and a reporting week
 * with three prints and a sell should still read as a reporting week. A
 * payout is the ex-date's blue, filled — the cash the ex-date promised.
 *
 * A market holiday belongs to no name, so it is not a chip at all but a quiet
 * mark beside the day number: it says when an order would wait, without
 * taking a chip's room on the one day a print also lands.
 */

import { useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { DenseRows } from "../../ui/Rows";
import { Fold } from "../../ui/Fold";
import { moneyIn, shares as formatShares } from "../portfolio/format";
import type { CalendarPayment, CalendarTrade, EventPick, MarketHoliday } from "./data";
import { cash } from "./Dividends";
import { longDate, plain, tone } from "./format";
import type { T } from "./format";

const DASH = "—";

/** "+1.234,56 €": a realised gain in the reporting currency, signed. */
export function gainText(lang: string, trade: CalendarTrade): string {
  if (trade.gain === null || !trade.base_currency) return DASH;
  return (
    moneyIn(lang, trade.base_currency)(trade.gain, { digits: 2, signed: true }) ?? DASH
  );
}

function tradeTitle(
  trade: CalendarTrade,
  name: string | undefined,
  lang: string,
  t: T,
): string {
  const who = name ? `${trade.ticker} — ${name}` : trade.ticker;
  const bits = [
    who,
    t(`earnings.trade_${trade.side}`),
    t("earnings.trade_breakdown", {
      shares: formatShares(lang, trade.quantity) ?? DASH,
      price: cash(lang, trade.price, trade.currency),
    }),
  ];
  if (trade.gain !== null) bits.push(gainText(lang, trade));
  return bits.join(" · ");
}

export function TradeChip({
  trade,
  onPick,
}: {
  trade: CalendarTrade;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useTickerProfile(trade.ticker);
  return (
    <button
      type="button"
      className={`earn-chip trade ${trade.side}`}
      title={tradeTitle(trade, profile?.name, lang, t)}
      onClick={() => onPick({ kind: "trade", item: trade })}
    >
      {profile?.logo && <img src={profile.logo} alt="" loading="lazy" />}
      <span>{t(`earnings.trade_chip_${trade.side}`, { ticker: trade.ticker })}</span>
    </button>
  );
}

export function PaymentChip({
  payment,
  onPick,
}: {
  payment: CalendarPayment;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const lang = useLang();
  const profile = useTickerProfile(payment.ticker);
  const who = profile?.name ? `${payment.ticker} — ${profile.name}` : payment.ticker;
  return (
    <button
      type="button"
      className="earn-chip pay"
      title={`${who} · ${t(payment.capital ? "earnings.pay_capital" : "earnings.pay_kind")} · ${cash(lang, payment.net, payment.currency)}`}
      onClick={() => onPick({ kind: "payment", item: payment })}
    >
      {profile?.logo && <img src={profile.logo} alt="" loading="lazy" />}
      <span>{t("earnings.pay_chip", { ticker: payment.ticker })}</span>
    </button>
  );
}

/** "US", "Xetra" — the exchange, in the reader's words. */
export function venueName(venue: MarketHoliday["venue"], t: T): string {
  return t(`earnings.venue_${venue}`);
}

/**
 * "US holiday", "US, London half day": every venue shut that day in one
 * mark. Closures lead; a day that is both reads as closed, the half sessions
 * named in the dialog.
 */
function holidayLabel(holidays: MarketHoliday[], t: T): string {
  const closed = holidays.filter((h) => h.kind === "closed");
  const shown = closed.length > 0 ? closed : holidays;
  const names = shown.map((h) => venueName(h.venue, t)).join(", ");
  return t(
    closed.length > 0 ? "earnings.holiday_mark" : "earnings.holiday_mark_early",
    {
      venues: names,
    },
  );
}

export function HolidayMark({
  holidays,
  onPick,
}: {
  holidays: MarketHoliday[];
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  if (holidays.length === 0) return null;
  const early = holidays.every((h) => h.kind === "early");
  const label = holidayLabel(holidays, t);
  return (
    <button
      type="button"
      className={`earn-holiday${early ? " early" : ""}`}
      title={label}
      onClick={() => onPick({ kind: "holiday", item: holidays })}
    >
      {label}
    </button>
  );
}

/** Past trades and payouts shown before "show more" in the list view. */
const BOOK_ROWS = 8;

type BookRow =
  | { kind: "trade"; date: string; item: CalendarTrade }
  | { kind: "payment"; date: string; item: CalendarPayment };

/**
 * The list view's section: the reader's own trades and payouts, newest first.
 * The phone default is the list, so without this a phone would never see them.
 * Each row is the ticker's link, like every dense row; the figures a dialog
 * would add (amount, gain, net) are already on it.
 */
export function BookList({
  trades,
  payments,
}: {
  trades: CalendarTrade[];
  payments: CalendarPayment[];
}) {
  const t = useT();
  const lang = useLang();
  const [cap, setCap] = useState(BOOK_ROWS);
  const all: BookRow[] = [
    ...trades.map((item) => ({ kind: "trade" as const, date: item.date, item })),
    ...payments.map((item) => ({ kind: "payment" as const, date: item.date, item })),
  ].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  if (all.length === 0) return null;
  const rows = all.slice(0, cap);
  const key = (row: BookRow) =>
    `${row.kind}-${row.item.ticker}-${row.date}-${row.kind === "trade" ? row.item.side : ""}`;
  return (
    <section className="earn-block">
      <Fold
        id="earn-book"
        head={<h2 className="earn-h2">{plain(t("earnings.book_title"))}</h2>}
      >
        <DenseRows
          rows={rows}
          rowKey={key}
          spec={{
            ticker: (row) => row.item.ticker,
            value: (row) =>
              row.kind === "trade"
                ? cash(lang, row.item.amount, row.item.currency)
                : cash(lang, row.item.net, row.item.currency),
            delta: (row) =>
              row.kind === "trade" && row.item.gain !== null ? (
                <span className={tone(row.item.gain)}>{gainText(lang, row.item)}</span>
              ) : (
                longDate(row.date, t)
              ),
            sub: (row) =>
              row.kind === "trade"
                ? [
                    t(`earnings.trade_${row.item.side}`),
                    ...(row.item.gain !== null ? [longDate(row.date, t)] : []),
                  ]
                : [t(row.item.capital ? "earnings.pay_capital" : "earnings.pay_kind")],
          }}
        />
        {all.length > cap && (
          <button
            type="button"
            className="ag-btn earn-show-more"
            onClick={() => setCap(cap + BOOK_ROWS)}
          >
            {t("earnings.show_more_results")}
          </button>
        )}
      </Fold>
    </section>
  );
}

export function BookLegend() {
  const t = useT();
  return <p className="earn-legend">{t("earnings.book_legend")}</p>;
}

export function HolidayLegend() {
  const t = useT();
  return <p className="earn-legend">{t("earnings.holiday_legend")}</p>;
}
