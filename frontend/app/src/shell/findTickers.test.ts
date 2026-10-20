import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("./api", () => ({ get: (...args: unknown[]) => get(...args) }));

const { findTickers, forgetSearches } = await import("./findTickers");

describe("findTickers", () => {
  beforeEach(() => {
    get.mockReset();
    forgetSearches();
  });

  it("asks once for a query typed again, whatever its case", async () => {
    get.mockResolvedValue({ query: "ASML", matches: [] });
    await findTickers("asml");
    await findTickers(" ASML ");
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("keeps the local-only answer apart from the full one", async () => {
    get.mockResolvedValue({ query: "ASML", matches: [] });
    await findTickers("asml", { world: false });
    await findTickers("asml");
    expect(get.mock.calls.map((call) => call[1].world)).toEqual(["false", undefined]);
  });

  it("asks again after a failure", async () => {
    get.mockRejectedValueOnce(new Error("offline"));
    await expect(findTickers("asml")).rejects.toThrow("offline");
    get.mockResolvedValue({ query: "ASML", matches: [] });
    await findTickers("asml");
    expect(get).toHaveBeenCalledTimes(2);
  });
});
