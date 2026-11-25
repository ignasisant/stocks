/**
 * The watchlist card: favourites open first, «Ahora» reads the whole list in
 * its order of urgency, sorting keeps unpriced names last, and a column with
 * nothing to say for the open group is not drawn.
 */

import { describe, expect, it } from "vitest";

import type { CloseRow, WatchlistEntry } from "./types";
import {
  columns,
  earningsByTicker,
  groups,
  inGroup,
  nowItems,
  openGroup,
  sortRows,
  tally,
  type WatchRow,
} from "./watch";

const entry = (
  ticker: string,
  favorite = false,
  tags: string[] = [],
): WatchlistEntry => ({
  ticker,
  name: ticker,
  favorite,
  tags,
  shares: null,
  cost: null,
  is_crypto: false,
});

const close = (pct: number | null, extra: Partial<CloseRow> = {}): CloseRow => ({
  ticker: "",
  close: 10,
  pct,
  as_of: "2026-11-21",
  active: true,
  month_pct: null,
  spark: [],
  held: false,
  extreme: null,
  move_size: null,
  zone: null,
  ...extra,
});

const zone = (state: "met" | "near" | "far", met = 0, rules = 1) => ({
  state,
  rule: "buy_below",
  level: 10,
  gap: state === "met" ? -1 : 8,
  since: null,
  met,
  rules,
});

const row = (
  e: WatchlistEntry,
  c: CloseRow | null = null,
  earnings: WatchRow["earnings"] = null,
): WatchRow => ({ entry: e, close: c, earnings });

const tickers = (rows: WatchRow[]) => rows.map((r) => r.entry.ticker);

describe("groups", () => {
  const rows = [
    row(entry("AAPL", true, ["tech"])),
    row(entry("NVO", false, ["Salud"])),
    row(entry("XOM")),
  ];

  it("lists favourites, tags A–Z, the rest, then everything", () => {
    expect(groups(rows).map((g) => [g.id, g.count])).toEqual([
      ["fav", 1],
      ["tag:Salud", 1],
      ["tag:tech", 1],
      ["rest", 1],
      ["all", 3],
    ]);
  });

  it("is only «Todos» when nothing is starred or tagged", () => {
    expect(groups([row(entry("XOM")), row(entry("IBM"))]).map((g) => g.id)).toEqual([
      "all",
    ]);
  });

  it("opens on favourites, keeps a pick that still exists", () => {
    const list = groups(rows);
    expect(openGroup(list, null)).toBe("fav");
    expect(openGroup(list, "tag:Salud")).toBe("tag:Salud");
    expect(openGroup(list, "tag:gone")).toBe("fav");
    expect(tickers(inGroup(rows, "rest"))).toEqual(["XOM"]);
  });
});

describe("sortRows", () => {
  const rows = [
    row(entry("A"), close(0.01, { month_pct: -0.2 })),
    row(entry("B"), close(null)),
    row(entry("C"), close(0.05, { month_pct: 0.1, zone: zone("near") })),
    row(entry("D"), close(-0.02, { zone: zone("met", 1, 1) })),
  ];

  it("puts the best day first and unpriced last", () => {
    expect(tickers(sortRows(rows, "day"))).toEqual(["C", "A", "D", "B"]);
    expect(tickers(sortRows(rows, "month"))).toEqual(["C", "A", "B", "D"]);
  });

  it("puts a zone reached first, and keeps the list's own order", () => {
    expect(tickers(sortRows(rows, "zone"))).toEqual(["D", "C", "A", "B"]);
    expect(tickers(sortRows(rows, "own"))).toEqual(["A", "B", "C", "D"]);
  });
});

describe("nowItems", () => {
  it("reads zone met, odd move, part met, results soon, near", () => {
    const rows = [
      row(entry("NEAR"), close(0, { zone: zone("near") })),
      row(entry("SOON"), close(0), { date: "2026-11-27", days: 3 }),
      row(entry("LATER"), close(0), { date: "2026-12-12", days: 18 }),
      row(entry("PART"), close(0, { zone: zone("met", 1, 2) })),
      row(entry("ODD"), close(0.3, { move_size: 9.1 })),
      row(entry("MET"), close(0, { zone: zone("met", 1, 1) })),
    ];
    expect(nowItems(rows).map((n) => [n.kind, n.row.entry.ticker])).toEqual([
      ["met", "MET"],
      ["odd", "ODD"],
      ["part", "PART"],
      ["earn", "SOON"],
      ["near", "NEAR"],
    ]);
  });
});

describe("tally and columns", () => {
  it("counts up and down and takes the middle move", () => {
    const rows = [0.02, -0.01, 0.03, null, 0].map((pct, i) =>
      row(entry(`T${i}`), close(pct)),
    );
    expect(tally(rows)).toEqual({ up: 2, down: 1, median: 0.01 });
    expect(tally([]).median).toBeNull();
  });

  it("drops a column no row fills", () => {
    expect(columns([row(entry("A"), close(0))])).toEqual({
      zone: false,
      earnings: false,
    });
    expect(
      columns([
        row(entry("A"), close(0, { zone: zone("far") }), { date: "x", days: 2 }),
      ]),
    ).toEqual({ zone: true, earnings: true });
  });
});

describe("earningsByTicker", () => {
  it("keeps each name's nearest date within the horizon", () => {
    const map = earningsByTicker([
      { ticker: "crdo", date: "2026-12-02", days_until: 8 },
      { ticker: "CRDO", date: "2026-11-30", days_until: 6 },
      { ticker: "FAR", date: "2027-02-01", days_until: 69 },
      { ticker: "NONE", date: null, days_until: null },
    ]);
    expect([...map.entries()]).toEqual([["CRDO", { date: "2026-11-30", days: 6 }]]);
  });
});
