import { describe, expect, it } from "vitest";

import { cashTotals, daysLeft, renewable, usedPercent } from "./consent";
import type { BankConnection } from "./types";

const NOW = new Date("2026-11-01T12:00:00Z");

function conn(over: Partial<BankConnection>): BankConnection {
  return {
    session_id: "s",
    name: "B",
    country: "ES",
    valid_until: "2027-02-01T00:00:00Z",
    connected_at: "",
    expired: false,
    accounts: [],
    ...over,
  };
}

describe("consent clock", () => {
  it("counts whole days, never below zero", () => {
    expect(daysLeft("2026-11-12T12:00:00Z", NOW)).toBe(11);
    expect(daysLeft("2026-10-01T00:00:00Z", NOW)).toBe(0);
    expect(daysLeft("nonsense", NOW)).toBeNull();
  });
  it("measures the used share of 90 days", () => {
    expect(usedPercent(90)).toBe(0);
    expect(usedPercent(45)).toBe(50);
    expect(usedPercent(0)).toBe(100);
  });
  it("offers renewal from 14 days out, and always once expired", () => {
    expect(renewable(conn({ valid_until: "2026-11-20T00:00:00Z" }), NOW)).toBe(false);
    expect(renewable(conn({ valid_until: "2026-11-14T00:00:00Z" }), NOW)).toBe(true);
    expect(renewable(conn({ expired: true }), NOW)).toBe(true);
  });
});

describe("cashTotals", () => {
  const acc = (balance: number | null, balance_currency: string) => ({
    uid: "u",
    name: "",
    masked_id: "",
    currency: "EUR",
    product: "",
    balance,
    balance_currency,
    fetched_at: null,
  });
  it("sums per currency and skips unread accounts", () => {
    const totals = cashTotals([
      conn({ accounts: [acc(100, "EUR"), acc(null, "EUR")] }),
      conn({ accounts: [acc(50.5, "EUR"), acc(10, "USD")] }),
    ]);
    expect(totals).toEqual([
      { currency: "EUR", amount: 150.5 },
      { currency: "USD", amount: 10 },
    ]);
  });
});
