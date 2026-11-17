/**
 * Catalog keys drawn as their own dotted name (`shell/i18n`): each is sent to
 * the server log once per page load, batched, and asking whether a key
 * exists sends nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { _resetMissing, known, reportMissing } from "./i18n";

describe("missing catalog keys", () => {
  const fetch = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));

  beforeEach(() => {
    vi.useFakeTimers();
    _resetMissing();
    fetch.mockClear();
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("window", {
      location: { pathname: "/review", search: "?tab=journal" },
    });
  });
  afterEach(() => {
    _resetMissing();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const sent = () =>
    fetch.mock.calls.map((call) => {
      const [url, init] = call as unknown as [string, RequestInit];
      return { url, body: JSON.parse(init.body as string) };
    });

  it("sends each key once, together, after the render settles", () => {
    reportMissing("journal.action_dividend_cut", "es");
    reportMissing("journal.action_gross_margin_below", "es");
    reportMissing("journal.action_dividend_cut", "es");
    expect(fetch).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(sent()).toEqual([
      {
        url: "/api/v1/missing-strings",
        body: {
          lang: "es",
          keys: ["journal.action_dividend_cut", "journal.action_gross_margin_below"],
          where: "review?tab=journal",
        },
      },
    ]);
    reportMissing("journal.action_dividend_cut", "es");
    vi.runAllTimers();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("sends only what is shaped like a key", () => {
    reportMissing("Some plain text", "en");
    reportMissing("nodot", "en");
    vi.runAllTimers();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("stops after fifty keys in one page load", () => {
    for (let i = 0; i < 80; i++) reportMissing(`x.key_${i}`, "en");
    vi.runAllTimers();
    expect(sent()[0]!.body.keys).toHaveLength(50);
  });

  it("asks a stand-in translator the old way, a real one without reporting", () => {
    const plain = (key: string) => (key === "a.b" ? "A" : key);
    expect(known(plain, "a.b")).toBe(true);
    expect(known(plain, "a.c")).toBe(false);
    const real = Object.assign((key: string) => key, {
      has: (key: string) => key === "a.b",
    });
    expect(known(real, "a.b")).toBe(true);
    vi.runAllTimers();
    expect(fetch).not.toHaveBeenCalled();
  });
});
