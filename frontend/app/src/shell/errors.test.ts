/**
 * Browser errors reported to the server (`shell/errors`): ours once each,
 * never somebody else's, never a flood.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, Cancelled } from "./api";
import {
  _reset,
  ignored,
  reloadForNewBuild,
  report,
  staleChunk,
  topFrame,
} from "./errors";

describe("crash reports", () => {
  const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));

  beforeEach(() => {
    _reset();
    fetch.mockClear();
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("window", {
      location: { pathname: "/ticker", search: "?symbol=AAPL" },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const sent = () =>
    fetch.mock.calls.map((call) =>
      JSON.parse((call as unknown as [string, RequestInit])[1].body as string),
    );

  it("sends a render error once, with its top frame and component stack", () => {
    const error = new TypeError("x is undefined");
    error.stack =
      "TypeError: x is undefined\n    at q (https://h/next-assets/app-A1.js:3:18)";
    report("render", error, "\n    at Fees\n    at Ticker");
    report("render", error, "\n    at Fees");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [body] = sent();
    expect(body.kind).toBe("render");
    expect(body.name).toBe("TypeError");
    expect(body.src).toBe("https://h/next-assets/app-A1.js:3:18");
    expect(body.component).toBe("at Fees\n    at Ticker");
    expect(body.where).toBe("ticker?symbol=AAPL");
  });

  it("stops after a handful per page load", () => {
    for (let i = 0; i < 20; i++) report("error", new Error(`loop ${i}`));
    expect(fetch).toHaveBeenCalledTimes(5);
  });

  it("leaves out what is not a bug in the bundle", () => {
    expect(ignored(new ApiError(500, "x"), "x")).toBe(true);
    expect(ignored(new Cancelled(), "")).toBe(true);
    expect(ignored(new DOMException("gone", "AbortError"), "gone")).toBe(true);
    expect(ignored(new TypeError("Failed to fetch"), "Failed to fetch")).toBe(true);
    expect(
      ignored(
        new Error("ResizeObserver loop completed"),
        "ResizeObserver loop completed",
      ),
    ).toBe(true);
    expect(ignored(new TypeError("a is null"), "a is null")).toBe(false);
  });

  it("reports a thrown string", () => {
    report("rejection", "nope");
    expect(sent()[0]).toMatchObject({
      kind: "rejection",
      name: "Error",
      message: "nope",
    });
  });

  it("finds no frame in a stack without one", () => {
    expect(topFrame("Error: x\n    at <anonymous>")).toBe("");
  });
  describe("a chunk gone after a deploy", () => {
    const store = new Map<string, string>();
    const reload = vi.fn();

    beforeEach(() => {
      store.clear();
      reload.mockClear();
      vi.stubGlobal("window", {
        location: { pathname: "/ticker", search: "", reload },
        sessionStorage: {
          getItem: (k: string) => store.get(k) ?? null,
          setItem: (k: string, v: string) => void store.set(k, v),
        },
      });
    });

    it("knows the message of each browser", () => {
      expect(
        staleChunk(
          "Failed to fetch dynamically imported module: https://h/next-assets/Ticker-A1.js",
        ),
      ).toBe(true);
      expect(staleChunk("Importing a module script failed.")).toBe(true);
      expect(staleChunk("error loading dynamically imported module: x")).toBe(true);
      expect(staleChunk("a is null")).toBe(false);
    });

    it("reloads instead of reporting, once a minute at most", () => {
      const error = new TypeError("Importing a module script failed.");
      report("render", error);
      expect(reload).toHaveBeenCalledTimes(1);
      expect(fetch).not.toHaveBeenCalled();

      // The new page still cannot load it: a real missing file, reported.
      _reset();
      report("render", error);
      expect(reload).toHaveBeenCalledTimes(1);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("tries again after the guard has passed", () => {
      expect(reloadForNewBuild(1_000_000)).toBe(true);
      expect(reloadForNewBuild(1_030_000)).toBe(false);
      expect(reloadForNewBuild(1_070_000)).toBe(true);
    });
  });
});
