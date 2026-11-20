import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { EditPlan } from "../../api.gen";
import {
  type Draft,
  TradeForm,
  TradePlan,
  amount,
  count,
  localDay,
  majorUnit,
  tradeRow,
} from "./AddTrade";

const draft = (over: Partial<Draft> = {}): Draft => ({
  side: "buy",
  date: "2026-11-18",
  quantity: "16,16135",
  price: "309,4",
  fee: "",
  currency: "EUR",
  ...over,
});

describe("majorUnit", () => {
  it("turns a pence quote into pounds", () => {
    expect(majorUnit("GBp", 1234)).toEqual({ currency: "GBP", price: 12.34 });
  });
  it("keeps a major currency as it is", () => {
    expect(majorUnit("EUR", 422.62)).toEqual({ currency: "EUR", price: 422.62 });
    expect(majorUnit("GBP", 12)).toEqual({ currency: "GBP", price: 12 });
  });
  it("has no currency when the quote had none", () => {
    expect(majorUnit(null, 5)).toEqual({ currency: null, price: 5 });
  });
});

describe("amount", () => {
  it("reads a comma or a point as the decimal mark", () => {
    expect(amount("26,51")).toBe(26.51);
    expect(amount("26.51")).toBe(26.51);
  });
  it("is NaN for anything that is not a number", () => {
    expect(amount("")).toBeNaN();
    expect(amount("1,2,3")).toBeNaN();
    expect(amount("abc")).toBeNaN();
  });
});

describe("tradeRow", () => {
  const today = "2026-11-19";

  it("builds the add row the ledger takes", () => {
    expect(tradeRow("0P00006SZ0.F", draft({ fee: "1,5" }), today)).toEqual({
      date: "2026-11-18",
      ticker: "0P00006SZ0.F",
      action: "buy",
      quantity: 16.16135,
      price: 309.4,
      currency: "EUR",
      fee: 1.5,
      note: "",
    });
  });

  it("reads an empty fee as zero", () => {
    expect(tradeRow("X", draft(), today)?.fee).toBe(0);
  });

  it("refuses what the ledger would refuse", () => {
    expect(tradeRow("X", draft({ quantity: "0" }), today)).toBeNull();
    expect(tradeRow("X", draft({ quantity: "" }), today)).toBeNull();
    expect(tradeRow("X", draft({ price: "" }), today)).toBeNull();
    expect(tradeRow("X", draft({ currency: "EU" }), today)).toBeNull();
    expect(tradeRow("X", draft({ date: "" }), today)).toBeNull();
  });

  it("refuses a day after today", () => {
    expect(tradeRow("X", draft({ date: "2026-11-20" }), today)).toBeNull();
    expect(tradeRow("X", draft({ date: today }), today)).not.toBeNull();
  });
});

describe("count and localDay", () => {
  it("keeps the decimals a count has, six at most", () => {
    expect(count(16.16135)).toMatch(/16[.,]16135/);
    expect(count(22)).toBe("22");
    expect(count(0.123456789)).toMatch(/0[.,]123457/);
  });
  it("is the local calendar day", () => {
    expect(localDay(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
  });
});

describe("TradeForm", () => {
  const form = (over: Partial<Draft> = {}, ready = true) =>
    renderToStaticMarkup(
      <TradeForm
        draft={draft(over)}
        today="2026-11-19"
        ready={ready}
        onDraft={() => undefined}
        onReview={() => undefined}
        onCancel={() => undefined}
      />,
    );

  it("shows the total so an amount typed as a price stands out", () => {
    expect(form()).toContain("ticker.trade_total");
  });

  it("caps the date at today and disables review until the row is valid", () => {
    expect(form()).toContain('max="2026-11-19"');
    expect(form({}, false)).toMatch(/<button type="submit"[^>]*disabled/);
  });
});

describe("TradePlan", () => {
  const plan = (ok: boolean): EditPlan => ({
    ops: [],
    changes: [],
    effects: [
      {
        ticker: "X",
        currency: "EUR",
        held_before: 0,
        held_after: 10,
        cost_before: 0,
        cost_after: 100,
        realized_before: {},
        realized_after: {},
      },
    ],
    positions_before: 0,
    positions_after: 1,
    problems: ok ? [] : ["sells 10 X but only 0 are held"],
    token: "t",
    ok,
  });

  const draw = (ok: boolean) =>
    renderToStaticMarkup(
      <TradePlan
        plan={plan(ok)}
        busy={false}
        onConfirm={() => undefined}
        onBack={() => undefined}
      />,
    );

  it("offers confirm only for a plan that can go ahead", () => {
    expect(draw(true)).toContain("ticker.trade_confirm");
    expect(draw(false)).not.toContain("ticker.trade_confirm");
    expect(draw(false)).toContain("only 0 are held");
  });
});
