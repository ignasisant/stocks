/**
 * The book's ex-dates on the calendar: one chip per date, and a list that
 * reads "what's next" before "what just paid".
 *
 * Rendered to static markup with no catalog loaded, so copy comes out as its
 * key — the figures, though, are formatted for real.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CalendarDividend } from "./data";
import { DividendChip, DividendTable } from "./Dividends";
import MonthGrid from "./MonthGrid";

const paid: CalendarDividend = {
  ticker: "MSFT",
  date: "2026-08-20",
  days_until: -43,
  per_share: 0.83,
  shares: 5,
  amount: 4.15,
  currency: "USD",
  projected: false,
  base_currency: "EUR",
  amount_base: 3.74,
  withholding: null,
  withholding_basis: null,
};

const declared: CalendarDividend = {
  ticker: "KO",
  date: "2026-11-28",
  days_until: 57,
  per_share: 0.51,
  shares: 10,
  amount: 5.1,
  currency: "USD",
  projected: false,
  base_currency: "EUR",
  amount_base: 3.74,
  withholding: null,
  withholding_basis: null,
};

const pick = () => {};

const guessed: CalendarDividend = {
  ...declared,
  date: "2027-02-26",
  days_until: 147,
  projected: true,
};

describe("dividends on the calendar", () => {
  it("draws a chip on the ex-date's cell and nowhere else", () => {
    const html = renderToStaticMarkup(
      <MonthGrid
        year={2026}
        month={8}
        now="2026-10-02"
        events={[]}
        results={[]}
        deadlines={[]}
        windows={[]}
        banks={[]}
        dividends={[paid, declared]}
        onPick={() => {}}
      />,
    );
    expect(html.match(/earn-chip div/g)).toHaveLength(1);
  });

  it("opens the payment rather than the name, and calls the upcoming amount a guess", () => {
    const next = renderToStaticMarkup(
      <DividendChip dividend={declared} onPick={pick} />,
    );
    expect(next).toMatch(/^<button type="button"/);
    expect(next).not.toContain("href");
    expect(next).toContain("earnings.div_next_note");
    const past = renderToStaticMarkup(<DividendChip dividend={paid} onPick={pick} />);
    expect(past).not.toContain("earnings.div_next_note");
  });

  it("draws a projected date hollow, marked and called a guess", () => {
    const html = renderToStaticMarkup(
      <DividendChip dividend={guessed} onPick={pick} />,
    );
    expect(html).toContain("earn-chip div projected");
    expect(html).toContain("earnings.tax_approx_mark");
    expect(html).toContain("earnings.div_projected_note");
    expect(html).not.toContain("earnings.div_next_note");
    // A declared one is neither.
    expect(
      renderToStaticMarkup(<DividendChip dividend={declared} onPick={pick} />),
    ).not.toContain("projected");
  });

  it("keeps a projected row in date order, after what is declared", () => {
    const html = renderToStaticMarkup(
      <DividendTable dividends={[paid, declared, guessed]} />,
    );
    expect(html).toContain("earn-div-projected");
    expect(html.indexOf("earn-div-next")).toBeLessThan(
      html.indexOf("earn-div-projected"),
    );
  });

  it("lists the declared date before the ones already behind", () => {
    const html = renderToStaticMarkup(<DividendTable dividends={[paid, declared]} />);
    expect(html.indexOf("KO")).toBeLessThan(html.indexOf("MSFT"));
    expect(html).toContain("4.15");
  });

  it("draws nothing for a book that pays nothing", () => {
    expect(renderToStaticMarkup(<DividendTable dividends={[]} />)).toBe("");
  });
});
