/**
 * The reader's own days: trades and booked payouts off the ledger, and the
 * days the exchanges they trade on are shut.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key — the figures, though, are formatted for real.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Agenda from "./Agenda";
import { BookList, HolidayMark } from "./Book";
import type { CalendarPayment, CalendarTrade, MarketHoliday } from "./data";
import EventDetail from "./EventDetail";
import MonthGrid from "./MonthGrid";

const sell: CalendarTrade = {
  ticker: "MSFT",
  date: "2026-10-07",
  days_until: -9,
  side: "sell",
  quantity: 2,
  price: 410.5,
  amount: 821,
  fee: 1,
  currency: "USD",
  gain: 123.45,
  base_currency: "EUR",
};

const buy: CalendarTrade = {
  ...sell,
  ticker: "NVDA",
  side: "buy",
  date: "2026-10-01",
  days_until: -15,
  gain: null,
};

const paid: CalendarPayment = {
  ticker: "KO",
  date: "2026-10-01",
  days_until: -15,
  gross: 10,
  withheld: 1.5,
  net: 8.5,
  currency: "USD",
  capital: false,
  base_currency: "EUR",
  net_base: 7.3,
};

const thanksgiving: MarketHoliday = {
  venue: "us",
  date: "2026-11-26",
  days_until: 41,
  kind: "closed",
};
const christmasEve: MarketHoliday[] = [
  { venue: "us", date: "2026-12-24", days_until: 69, kind: "early" },
  { venue: "xetra", date: "2026-12-24", days_until: 69, kind: "closed" },
];

function grid(month: number) {
  return renderToStaticMarkup(
    <MonthGrid
      year={2026}
      month={month}
      now="2026-10-16"
      events={[]}
      results={[]}
      deadlines={[]}
      windows={[]}
      banks={[]}
      dividends={[]}
      trades={[sell, buy]}
      payments={[paid]}
      holidays={[thanksgiving, ...christmasEve]}
      onPick={() => {}}
    />,
  );
}

describe("trades and payouts", () => {
  it("draw on the day they happened, a chip each", () => {
    const html = grid(10);
    expect(html.match(/earn-chip trade sell/g)).toHaveLength(1);
    expect(html.match(/earn-chip trade buy/g)).toHaveLength(1);
    expect(html.match(/earn-chip pay/g)).toHaveLength(1);
    expect(grid(11)).not.toContain("earn-chip trade");
  });

  it("list newest first in the list view, a sell with its gain", () => {
    const html = renderToStaticMarkup(
      <BookList trades={[buy, sell]} payments={[paid]} />,
    );
    expect(html).toContain("earnings.book_title");
    expect(html.indexOf("MSFT")).toBeLessThan(html.indexOf("NVDA"));
    expect(html).toContain("123.45");
    expect(html).toContain("8.50");
    expect(renderToStaticMarkup(<BookList trades={[]} payments={[]} />)).toBe("");
  });

  it("open a dialog with the ledger's figures", () => {
    const trade = renderToStaticMarkup(
      <EventDetail pick={{ kind: "trade", item: sell }} onClose={() => {}} />,
    );
    expect(trade).toContain("earnings.trade_sell");
    expect(trade).toContain("821.00");
    expect(trade).toContain("earnings.ev_trade_gain");
    const bought = renderToStaticMarkup(
      <EventDetail pick={{ kind: "trade", item: buy }} onClose={() => {}} />,
    );
    expect(bought).not.toContain("earnings.ev_trade_gain");

    const payout = renderToStaticMarkup(
      <EventDetail pick={{ kind: "payment", item: paid }} onClose={() => {}} />,
    );
    expect(payout).toContain("8.50");
    expect(payout).toContain("1.50");
    expect(payout).toContain("earnings.ev_pay_in_base");
    expect(payout).not.toContain("earnings.ev_pay_capital_note");
  });
});

describe("market holidays", () => {
  it("mark the day beside its number, not as a chip", () => {
    const html = grid(11);
    expect(html.match(/earn-holiday/g)).toHaveLength(1);
    expect(html).toContain("earnings.holiday_mark");
    expect(grid(12)).toContain('class="earn-holiday"');
  });

  it("read as a half day only when every venue is a half day", () => {
    const mixed = renderToStaticMarkup(
      <HolidayMark holidays={christmasEve} onPick={() => {}} />,
    );
    expect(mixed).toContain('class="earn-holiday"');
    const early = renderToStaticMarkup(
      <HolidayMark holidays={christmasEve.slice(0, 1)} onPick={() => {}} />,
    );
    expect(early).toContain("earn-holiday early");
    expect(early).toContain("earnings.holiday_mark_early");
    expect(renderToStaticMarkup(<HolidayMark holidays={[]} onPick={() => {}} />)).toBe(
      "",
    );
  });

  it("show up in the agenda, and name each venue in the dialog", () => {
    const html = renderToStaticMarkup(
      <Agenda
        events={[]}
        deadlines={[]}
        windows={[]}
        banks={[]}
        dividends={[]}
        holidays={[thanksgiving]}
      />,
    );
    expect(html).toContain("earnings.venue_us");
    expect(html).toContain("earnings.holiday_closed");

    const dialog = renderToStaticMarkup(
      <EventDetail pick={{ kind: "holiday", item: christmasEve }} onClose={() => {}} />,
    );
    expect(dialog).toContain("earnings.venue_xetra");
    expect(dialog).toContain("earnings.ev_holiday_early");
    expect(dialog).toContain("earnings.ev_holiday_title<");

    // Only a half session: no "closed" title, no "waits for the next session".
    const half = renderToStaticMarkup(
      <EventDetail
        pick={{ kind: "holiday", item: christmasEve.slice(0, 1) }}
        onClose={() => {}}
      />,
    );
    expect(half).toContain("earnings.ev_holiday_title_early");
    expect(half).not.toContain("earnings.ev_holiday_body");
  });
});
