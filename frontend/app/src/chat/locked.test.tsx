/**
 * The assistant a guest meets: a sample exchange, the question a page asked,
 * and the sign-in where the composer would be — and that question waiting in
 * the real composer once the round trip is done.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../shell/session", async (original) => ({
  ...(await original<typeof import("../shell/session")>()),
  useSignIn: () => "/auth/login",
}));

import LockedPanel from "./LockedPanel";
import { hasDraft, keepDraft, takeDraft } from "./draft";

/** A `Storage` with nothing behind it but a map. */
function memory(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  };
}

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/review", search: "" },
    matchMedia: () => ({ matches: false }),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("LockedPanel", () => {
  it("shows the sample exchange and a sign-in, and no composer", () => {
    const out = renderToStaticMarkup(<LockedPanel asked={null} onClose={() => {}} />);
    expect(out).toContain("chat.guest_q");
    expect(out).toContain("chat.guest_a");
    expect(out).toContain("chat.guest_lock");
    expect(out).toContain("/auth/login?next=");
    expect(out).toContain("wall=chat");
    expect(out).not.toContain("<textarea");
  });

  it("shows the question a page asked as the reader's own turn", () => {
    const out = renderToStaticMarkup(
      <LockedPanel asked="Analyse NVDA" onClose={() => {}} />,
    );
    expect(out).toContain("Analyse NVDA");
    expect(out).toContain("chat.guest_asked");
    expect(out).not.toContain("ag-chat-fold");
  });

  it("folds a question that runs to paragraphs", () => {
    const out = renderToStaticMarkup(
      <LockedPanel asked={"x".repeat(400)} onClose={() => {}} />,
    );
    expect(out).toContain("ag-chat-fold");
  });
});

describe("draft", () => {
  it("is taken once", () => {
    const store = memory();
    keepDraft("Analyse NVDA", store);
    expect(hasDraft(store)).toBe(true);
    expect(takeDraft(store)).toBe("Analyse NVDA");
    expect(hasDraft(store)).toBe(false);
    expect(takeDraft(store)).toBeNull();
  });

  it("is lost, not thrown, where storage is refused", () => {
    const refused = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    expect(() => keepDraft("x", refused)).not.toThrow();
    expect(takeDraft(refused)).toBeNull();
    expect(hasDraft(refused)).toBe(false);
  });
});
