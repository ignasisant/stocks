import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { EditPlan, RowChange, Transaction } from "../../api.gen";
import { RemovalPlan, realizedShifts, span } from "./Removal";

const row = (id: number, date: string, action = "buy"): RowChange => {
  const before: Transaction = {
    id,
    date,
    ticker: "GRF.MC",
    action,
    quantity: 10,
    price: 8,
    currency: "EUR",
    fee: 0,
    note: "ibkr",
    amount: null,
  };
  return { id, kind: "deleted", before, after: null };
};

const plan = (overrides: Partial<EditPlan>): EditPlan => ({
  ops: [],
  changes: [],
  effects: [],
  positions_before: 1,
  positions_after: 0,
  problems: [],
  token: "t",
  ok: true,
  ...overrides,
});

describe("removing a holding", () => {
  it("lists only the years whose realized gain moves, oldest first", () => {
    const shifts = realizedShifts(
      plan({
        effects: [
          {
            ticker: "GRF.MC",
            currency: "EUR",
            held_before: 0,
            held_after: 0,
            cost_before: 0,
            cost_after: 0,
            realized_before: { "2026": 398, "2024": 12, "2025": 5 },
            realized_after: { "2025": 5 },
          },
        ],
      }),
    );
    expect(shifts).toEqual([
      { year: "2024", currency: "EUR", before: 12, after: 0 },
      { year: "2026", currency: "EUR", before: 398, after: 0 },
    ]);
  });

  it("sums one currency's year across effects into one line", () => {
    const effect = (ticker: string, gain: number) => ({
      ticker,
      currency: "EUR",
      held_before: 0,
      held_after: 0,
      cost_before: 0,
      cost_after: 0,
      realized_before: { "2026": gain },
      realized_after: {},
    });
    const shifts = realizedShifts(
      plan({ effects: [effect("ES0171996087", 398), effect("GRF.MC", 2)] }),
    );
    expect(shifts).toEqual([{ year: "2026", currency: "EUR", before: 400, after: 0 }]);
  });

  it("spans the rows it deletes whatever order they come in", () => {
    const changes = [
      row(3, "2026-09-01", "dividend"),
      row(1, "2024-03-01"),
      row(2, "2025-01-02"),
    ];
    expect(span(plan({ changes }))).toEqual({
      first: "2024-03-01",
      last: "2026-09-01",
    });
    expect(span(plan({}))).toBeNull();
  });
});

describe("the removal panel", () => {
  const draw = (overrides: Partial<EditPlan>) =>
    renderToStaticMarkup(
      <RemovalPlan
        ticker="GRF.MC"
        plan={plan({
          changes: [row(1, "2024-03-01"), row(2, "2026-08-21")],
          ...overrides,
        })}
        busy={false}
        onRemove={() => undefined}
        onCancel={() => undefined}
      />,
    );

  it("offers the destructive button when the plan can be committed", () => {
    expect(draw({})).toContain("tk-btn-danger");
  });

  it("names the problems and offers no way to commit when it cannot", () => {
    const html = draw({ ok: false, problems: ["sell of 5 exceeds held 0"] });
    expect(html).toContain("sell of 5 exceeds held 0");
    expect(html).not.toContain("tk-btn-danger");
  });
});
