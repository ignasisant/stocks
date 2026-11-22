import { describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("../../shell/api", async (original) => ({
  ...(await original<typeof import("../../shell/api")>()),
  get,
}));

import { getWatchlist } from "./data";

describe("getWatchlist", () => {
  // Prod 2026-11-21, safari/ios on /ticker: "undefined is not an object
  // (evaluating 'e.map')" where the page merges `entries` with its own writes.
  it("reads a body without entries as an empty watchlist", async () => {
    get.mockResolvedValueOnce({});
    const body = await getWatchlist();
    expect(body.entries.map((entry) => entry.ticker)).toEqual([]);
  });

  it("keeps the entries the server sent", async () => {
    get.mockResolvedValueOnce({
      entries: [{ ticker: "NVO", favorite: true, tags: [] }],
    });
    const body = await getWatchlist();
    expect(body.entries.map((entry) => entry.ticker)).toEqual(["NVO"]);
  });
});
