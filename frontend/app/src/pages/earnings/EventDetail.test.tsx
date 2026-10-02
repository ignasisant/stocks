/**
 * The dialog a chip opens: one card per kind, and for a dividend the cash.
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key — the figures, though, are formatted for real.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  CalendarDividend,
  CalendarEvent,
  CentralBankDecision,
  EventPick,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import EventDetail, { relative } from "./EventDetail";
import type { T } from "./format";

const close = () => {};

function open(pick: EventPick, held: string[] = []) {
  return renderToStaticMarkup(<EventDetail pick={pick} held={held} onClose={close} />);
}

const ahead: CalendarDividend = {
  ticker: "MSFT",
  date: "2026-11-19",
  days_until: 48,
  per_share: 0.91,
  shares: 5,
  amount: 4.55,
  currency: "USD",
  projected: false,
  base_currency: "EUR",
  amount_base: 4.0,
  withholding: 0.15,
  withholding_basis: "ticker",
};

describe("a dividend", () => {
  it("leads with what lands, net of the book's own withholding", () => {
    const html = open({ kind: "dividend", item: ahead });
    expect(html).toContain("earnings.ev_div_will_get");
    expect(html).toContain("3.87"); // 4.55 less 15%
    expect(html).toContain("earnings.ev_div_net");
    expect(html).toContain("earnings.ev_div_basis_ticker");
    // In the reader's currency too, at today's rate: 4.00 € less 15%.
    expect(html).toContain("earnings.ev_div_in_base_today");
    expect(html).toContain("earnings.ev_div_rule_ahead");
  });

  it("says gross, not 0%, when no statement ever printed a withholding", () => {
    const html = open({
      kind: "dividend",
      item: { ...ahead, withholding: null, withholding_basis: null },
    });
    expect(html).toContain("4.55");
    expect(html).toContain("earnings.ev_div_gross");
    expect(html).toContain("earnings.ev_div_basis_none");
    expect(html).not.toContain("earnings.ev_div_net");
  });

  it("says where a borrowed rate came from", () => {
    const html = open({
      kind: "dividend",
      item: { ...ahead, withholding_basis: "currency" },
    });
    expect(html).toContain("earnings.ev_div_basis_currency");
  });

  it("reads a past ex-date as owed, at the rate of that day", () => {
    const html = open({ kind: "dividend", item: { ...ahead, days_until: -10 } });
    expect(html).toContain("earnings.ev_div_got");
    expect(html).toContain("earnings.ev_div_in_base_ex");
    expect(html).toContain("earnings.ev_div_rule_past");
    expect(html).toContain("earnings.ev_div_past");
  });

  it("prints no second figure when the payment is already in the base currency", () => {
    const html = open({
      kind: "dividend",
      item: { ...ahead, currency: "EUR", amount_base: 4.55 },
    });
    expect(html).not.toContain("earnings.ev_div_in_base");
  });

  it("sends the reader to their dividends, never to the ticker as its action", () => {
    const html = open({ kind: "dividend", item: ahead });
    expect(html).toContain("tab=dividends");
    expect(html).not.toMatch(/class="ag-btn"[^>]*ticker=/);
  });

  it("calls a projected date a guess", () => {
    const html = open({ kind: "dividend", item: { ...ahead, projected: true } });
    expect(html).toContain("earnings.ev_div_projected");
  });
});

describe("the other kinds", () => {
  const print: CalendarEvent = { ticker: "NVDA", date: "2026-10-07", days_until: 5 };

  it("explains a print, warns inside a week and leads on to the ticker", () => {
    const html = open({ kind: "print", item: print }, ["NVDA"]);
    expect(html).toContain("earnings.ev_print_body");
    expect(html).toContain("earnings.ev_print_soon");
    expect(html).toContain("earnings.ev_held");
    expect(html).toContain("earnings.ev_open");
    expect(html).toContain("NVDA");
    const later = open({ kind: "print", item: { ...print, days_until: 30 } });
    expect(later).not.toContain("earnings.ev_print_soon");
    expect(later).not.toContain("earnings.ev_held");
  });

  it("explains a tax deadline and links to the tax tab", () => {
    const deadline: TaxDeadline = {
      key: "es_renta",
      date: "2027-06-30",
      days_until: 271,
      year: "2026",
      approximate: true,
      remind: false,
    };
    const html = open({ kind: "tax", item: deadline });
    expect(html).toContain("earnings.tax_es_renta_body");
    expect(html).toContain("earnings.ev_tax_approx");
    expect(html).toContain("tab=tax");
  });

  it("explains a buy-back day with the loss at stake", () => {
    const window: RepurchaseWindow = {
      ticker: "NVDA",
      sell_date: "2026-09-22",
      date: "2026-11-23",
      days_until: 52,
      loss: 101.4,
      currency: "EUR",
      window: "2m",
    };
    const html = open({ kind: "rebuy", item: window });
    expect(html).toContain("earnings.ev_rebuy_body");
    expect(html).toContain("101.40");
    expect(html).toContain("earnings.rebuy_rule_2m");
  });

  it("explains a rate decision and what it moves", () => {
    const fed: CentralBankDecision = {
      bank: "fed",
      date: "2026-10-28",
      days_until: 26,
    };
    const html = open({ kind: "bank", item: fed });
    expect(html).toContain("earnings.ev_bank_fed");
    expect(html).toContain("earnings.cb_fed_title");
    expect(html).toContain("earnings.ev_bank_body");
  });
});

describe("how far away", () => {
  const t: T = (key, slots) => (slots ? `${key}:${slots.n}` : key);

  it("names the near days and counts the rest", () => {
    expect(relative(0, t)).toBe("earnings.ev_today");
    expect(relative(1, t)).toBe("earnings.ev_tomorrow");
    expect(relative(-1, t)).toBe("earnings.ev_yesterday");
    expect(relative(9, t)).toBe("earnings.ev_in_days:9");
    expect(relative(-3, t)).toBe("earnings.ev_days_ago:3");
    expect(relative(null, t)).toBe("—");
  });
});
