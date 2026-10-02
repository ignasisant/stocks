/**
 * Signing in to a provider instead of pasting its key (`connect.ts`).
 *
 * The parts that can be wrong without anything looking wrong: a challenge the
 * provider will not match to its verifier (every sign-in fails at the trade),
 * a verifier that can be spent twice or outlives the code (a forged return
 * gets a second go), and a callback that carries the page's query (the
 * provider's `?code=` lands somewhere it was not expected).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  challengeFor,
  connectUrl,
  exchange,
  newVerifier,
  takeConnect,
} from "./connect";

/** A tab's sessionStorage, or one that refuses every write when `blocked`. */
function storage(blocked = false) {
  const held = new Map<string, string>();
  return {
    getItem: (key: string) => held.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (blocked) throw new Error("QuotaExceededError");
      held.set(key, value);
    },
    removeItem: (key: string) => void held.delete(key),
  };
}

function page(search = "", blocked = false) {
  vi.stubGlobal("window", {
    sessionStorage: storage(blocked),
    location: { origin: "https://topstocks.app", pathname: "/portfolio", search },
  });
}

const openrouter = {
  id: "openrouter",
  connect_url: "https://openrouter.ai/auth",
  connect_token_url: "https://openrouter.ai/api/v1/auth/keys",
};

beforeEach(() => page());
afterEach(() => vi.unstubAllGlobals());

describe("the PKCE pair", () => {
  it("hashes a verifier the way RFC 7636 does", async () => {
    // Appendix B's worked example, byte for byte.
    expect(await challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("draws a fresh, URL-safe verifier of a length the RFC allows", () => {
    const one = newVerifier();
    expect(one).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(newVerifier()).not.toBe(one);
  });
});

describe("leaving for the sign-in", () => {
  it("sends the challenge, never the verifier, and a callback without the query", async () => {
    page("?tab=risk");
    const url = new URL((await connectUrl(openrouter, true, "TopStocks"))!);
    expect(`${url.origin}${url.pathname}`).toBe("https://openrouter.ai/auth");
    expect(url.searchParams.get("callback_url")).toBe(
      "https://topstocks.app/portfolio",
    );
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("key_label")).toBe("TopStocks");

    const pending = takeConnect()!;
    expect(pending.provider).toBe("openrouter");
    expect(pending.remember).toBe(true);
    expect(pending.back).toBe("?tab=risk");
    expect(pending.tokenUrl).toBe(openrouter.connect_token_url);
    expect(url.searchParams.get("code_challenge")).toBe(
      await challengeFor(pending.verifier),
    );
    expect(url.toString()).not.toContain(pending.verifier);
  });

  it("does not start a sign-in the tab could not finish", async () => {
    page("", true);
    expect(await connectUrl(openrouter, true, "TopStocks")).toBeNull();
  });

  it("does not start one for a provider without a sign-in", async () => {
    expect(await connectUrl({ id: "anthropic" }, true, "TopStocks")).toBeNull();
    expect(takeConnect()).toBeNull();
  });
});

describe("coming back", () => {
  it("hands the verifier over once", async () => {
    await connectUrl(openrouter, false, "TopStocks");
    expect(takeConnect()?.remember).toBe(false);
    expect(takeConnect()).toBeNull();
  });

  it("refuses a verifier older than the code it was for", async () => {
    await connectUrl(openrouter, true, "TopStocks");
    expect(takeConnect(Date.now() + 11 * 60 * 1000)).toBeNull();
  });

  it("finds nothing when this tab never left", () => {
    expect(takeConnect()).toBeNull();
  });
});

describe("the trade", () => {
  const pending = {
    provider: "openrouter",
    verifier: "v".repeat(43),
    tokenUrl: openrouter.connect_token_url,
    remember: true,
    back: "",
    at: Date.now(),
  };

  it("posts the code and verifier straight to the provider, without cookies", async () => {
    const fetch = vi.fn(
      async () => new Response(JSON.stringify({ key: "sk-or-v1-abc" })),
    );
    vi.stubGlobal("fetch", fetch);
    expect(await exchange("c0de", pending)).toBe("sk-or-v1-abc");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(openrouter.connect_token_url);
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(init.body as string)).toEqual({
      code: "c0de",
      code_verifier: pending.verifier,
      code_challenge_method: "S256",
    });
  });

  it("throws when the provider refuses, or answers without a key", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 403 })),
    );
    await expect(exchange("c0de", pending)).rejects.toThrow();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}")),
    );
    await expect(exchange("c0de", pending)).rejects.toThrow();
  });
});
