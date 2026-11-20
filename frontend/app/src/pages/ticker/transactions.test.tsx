/**
 * The transactions card lists a holding's ledger rows as the statement printed
 * them, heads them with what went in and came out in the reporting currency,
 * and folds a long history behind its count.
 *
 * Rendered to static markup with the query already landed; copy comes out as
 * its key, slots appended, so a test can read which key and which count.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { Transaction, Transactions } from "../../api.gen";
import {
  averagePrice,
  brokerKey,
  FOLD_ROWS,
  nativeAmount,
  rowReturns,
  totals,
  TransactionsSection,
} from "./Transactions";
import type { TickerPosition } from "./types";

const landed = vi.hoisted(() => ({ data: null as unknown }));
vi.mock("../../shell/useApi", () => ({
  useApi: () => ({ state: "loaded", data: landed.data, reload: () => {} }),
}));

vi.mock("../../shell/i18n", async (original) => ({
  ...(await original<typeof import("../../shell/i18n")>()),
  useT: () => (key: string, slots?: Record<string, string | number>) =>
    slots ? `${key}(${Object.values(slots).join(",")})` : key,
}));

const column = vi.hoisted(() => ({ phone: false }));
vi.mock("../../shell/useMobile", () => ({ useMobile: () => column.phone }));

const row = (over: Partial<Transaction>): Transaction => ({
  id: 1,
  date: "2026-01-02",
  ticker: "0P00006SZ0.F",
  action: "buy",
  quantity: 2,
  price: 400,
  currency: "EUR",
  fee: 1,
  note: "myinvestor aportación",
  amount: 801,
  ...over,
});

const position = {
  custody: [{ broker: "myinvestor", name: "MyInvestor" }],
} as unknown as TickerPosition;

function render(rows: Transaction[], total = rows.length) {
  landed.data = {
    total,
    transactions: rows,
    base: "EUR",
    demo: false,
  } satisfies Transactions;
  return renderToStaticMarkup(
    <TransactionsSection
      ticker="0P00006SZ0.F"
      base="EUR"
      position={position}
      units={false}
      last={{ price: 500, currency: "EUR" }}
    />,
  );
}

describe("transaction figures", () => {
  it("reads the cash each kind of row moved, in its own currency", () => {
    expect(nativeAmount(row({}))).toBe(801);
    expect(nativeAmount(row({ action: "sell" }))).toBe(799);
    expect(nativeAmount(row({ action: "dividend", price: 12.5 }))).toBe(12.5);
    expect(nativeAmount(row({ action: "split", quantity: 4 }))).toBeNull();
  });

  it("sums contributions, sales and income, leaving unconverted rows out", () => {
    const sum = totals([
      row({ amount: 800 }),
      row({ action: "buy", amount: null }),
      row({ action: "sell", amount: 300 }),
      row({ action: "dividend", amount: 10 }),
      row({ action: "capital", amount: 5 }),
      row({ action: "split", amount: null }),
    ]);
    expect(sum).toEqual({ invested: 800, withdrawn: 300, income: 15, unconverted: 1 });
  });

  it("takes the broker from the note's first word", () => {
    expect(brokerKey("  Revolut  buy 3")).toBe("revolut");
    expect(brokerKey("")).toBe("");
  });
});

describe("row returns", () => {
  it("measures a buy against the last price, split-adjusted", () => {
    // Newest first, as the route sends them.
    const rows = [
      row({ date: "2026-02-01", action: "split", quantity: 4, price: 0, fee: 0 }),
      row({ date: "2026-01-02", price: 400, fee: 0 }),
    ];
    const got = rowReturns(rows, { price: 110, currency: "EUR" });
    expect(got.get(1)).toBeCloseTo(0.1);
    expect(got.has(0)).toBe(false);
  });

  it("measures a sale against the average cost it closed", () => {
    const rows = [
      row({ date: "2026-03-01", action: "sell", quantity: 2, price: 150, fee: 0 }),
      row({ date: "2026-02-01", quantity: 2, price: 120, fee: 0 }),
      row({ date: "2026-01-02", quantity: 2, price: 80, fee: 0 }),
    ];
    expect(rowReturns(rows, null).get(0)).toBeCloseTo(0.5);
  });

  it("gives nothing across currencies rather than an exchange rate's gap", () => {
    const rows = [
      row({ date: "2026-03-01", action: "sell", quantity: 1, price: 150, fee: 0 }),
      row({ date: "2026-02-01", currency: "USD", price: 120, fee: 0 }),
      row({ date: "2026-01-02", price: 80, fee: 0 }),
    ];
    const got = rowReturns(rows, { price: 100, currency: "EUR" });
    expect(got.has(0)).toBe(false);
    expect(got.has(1)).toBe(false);
    expect(got.get(2)).toBeCloseTo(0.25);
  });

  it("reads the average price off the position, else off the buys", () => {
    const held = { avg_cost_native: 310, currency: "EUR" } as TickerPosition;
    expect(averagePrice([], held)).toEqual({ price: 310, currency: "EUR" });
    const closed = { avg_cost_native: null, currency: null } as TickerPosition;
    const rows = [
      row({ quantity: 1, price: 100, fee: 0 }),
      row({ quantity: 3, price: 200, fee: 0 }),
    ];
    expect(averagePrice(rows, closed)).toEqual({ price: 175, currency: "EUR" });
  });
});

describe("TransactionsSection", () => {
  it("lists each row with its broker's name and heads the card with the totals", () => {
    column.phone = false;
    const html = render([
      row({
        id: 2,
        date: "2026-03-01",
        action: "sell",
        quantity: 1,
        price: 450,
        fee: 0,
        amount: 450,
      }),
      row({ id: 1, note: "manual" }),
    ]);
    expect(html).toContain("ticker.tx_title");
    expect(html).toContain("ticker.tx_count_n(2)");
    expect(html).toContain("ticker.tx_withdrawn");
    expect(html).not.toContain("ticker.tx_income");
    expect(html).toContain("tk-tx-out");
    expect(html).toContain("tk-tx-in");
    expect(html).toContain("MyInvestor");
    expect(html).toContain("portfolio.broker_manual");
    expect(html).toContain("ticker.tx_col_amount (EUR)");
    // The buy at 400 against the last 500: +25 %, in green.
    expect(html).toMatch(/tk-is-green">\+25[.,]0\s?%/);
    expect(html).not.toContain("tk-show-more");
  });

  it("folds a long history behind its count", () => {
    column.phone = false;
    const rows = Array.from({ length: FOLD_ROWS + 3 }, (_, at) => row({ id: at + 1 }));
    const html = render(rows);
    expect(html.match(/<tr>/g)?.length).toBe(FOLD_ROWS + 1);
    expect(html).toContain(`ticker.tx_show(${FOLD_ROWS + 3})`);
  });

  it("says when the server cut the list", () => {
    column.phone = false;
    expect(render([row({})], 1200)).toContain("ticker.tx_cut(1,1200)");
  });

  it("stacks rows as cards on a phone", () => {
    column.phone = true;
    const html = render([row({})]);
    expect(html).toContain("tk-stack-card");
    expect(html).not.toContain("<table");
  });

  it("says so when the holding has no rows", () => {
    column.phone = false;
    expect(render([])).toContain("ticker.tx_empty");
  });
});
