import { describe, expect, it } from "vitest";
import type { JournalEntry } from "../../ui/Journal";
import { marks } from "./Yours";

function rule(
  action: string,
  level: number | string,
  state: JournalEntry["state"] = "open",
  ticker = "ASML",
): JournalEntry {
  return {
    type: "criterion",
    action,
    state,
    ticker,
    snapshot: { rule: action, level },
  } as unknown as JournalEntry;
}

describe("marks", () => {
  it("names nothing for a reader who set nothing", () => {
    expect(marks([], [], 100, true)).toEqual([]);
  });

  it("takes the price alert nearest the price, with the distance to it", () => {
    const out = marks(
      [
        { type: "below", price: 80 },
        { type: "above", price: 110 },
        { type: "rsi_below", level: 30 },
      ],
      [],
      100,
      false,
    );
    expect(out).toHaveLength(1);
    expect(out[0]?.key).toBe("ticker.mine_alert_above");
    expect(out[0]?.gap).toBeCloseTo(0.1);
  });

  it("counts the alerts when none of them is a price", () => {
    const out = marks([{ type: "pct_move", pct: 5 }], [], 100, false);
    expect(out[0]?.key).toBe("ticker.mine_alerts_one");
  });

  it("says the price is in the buy zone once it is under the level", () => {
    const [zone] = marks([], [rule("buy_below", 120)], 100, false);
    expect(zone?.key).toBe("ticker.mine_buy_in");
    expect(zone?.gap).toBeNull();
    const [above] = marks([], [rule("buy_below", 80)], 100, false);
    expect(above?.key).toBe("ticker.mine_buy");
    expect(above?.gap).toBeCloseTo(-0.2);
  });

  it("reads exit rules only while the name is held", () => {
    const entries = [rule("below", 90), rule("thesis", "")];
    expect(marks([], entries, 100, false)).toEqual([]);
    const [exit] = marks([], entries, 100, true);
    expect(exit?.key).toBe("ticker.mine_exit");
    expect(exit?.gap).toBeCloseTo(-0.1);
  });

  it("puts a hit exit rule ahead of the levels", () => {
    const [exit] = marks([], [rule("below", 90), rule("thesis", "", "hit")], 100, true);
    expect(exit?.key).toBe("ticker.mine_exit_hit");
    expect(exit?.tone).toBe("down");
  });

  it("never measures a level drawn on another listing against this price", () => {
    // 600 on ASML.AS is euros; this page's 100 is the dollar line's price.
    const [zone] = marks(
      [],
      [rule("buy_below", 600, "open", "ASML.AS")],
      100,
      false,
      "ASML",
    );
    expect(zone?.key).toBe("ticker.mine_buy_on");
    expect(zone?.vars).toMatchObject({ listing: "ASML.AS" });
    expect(zone?.gap).toBeNull();
    expect(zone?.tone).toBeNull();
  });

  it("prefers this listing's level and still trusts another's hit", () => {
    const both = [rule("buy_below", 600, "open", "ASML.AS"), rule("buy_below", 80)];
    const [zone] = marks([], both, 100, false, "asml");
    expect(zone?.key).toBe("ticker.mine_buy");
    expect(zone?.gap).toBeCloseTo(-0.2);
    const [hit] = marks(
      [],
      [rule("buy_below", 600, "hit", "ASML.AS")],
      100,
      false,
      "ASML",
    );
    expect(hit?.key).toBe("ticker.mine_buy_in");
  });

  it("names the listing of an exit floor drawn elsewhere", () => {
    const [exit] = marks(
      [],
      [rule("below", 500, "open", "ASML.AS")],
      100,
      true,
      "ASML",
    );
    expect(exit?.key).toBe("ticker.mine_exit_on");
    expect(exit?.gap).toBeNull();
  });

  it("leaves retired rules out", () => {
    expect(marks([], [rule("buy_below", 80, "retired")], 100, true)).toEqual([]);
  });
});
