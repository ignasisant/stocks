/**
 * Sharing an answer by link: where the link goes, and what the reader sees.
 *
 * The link carries `src=share` so the signup it leads to is credited, and each
 * platform gets the URL its own share button opens. The reader's copy says
 * when amounts were hidden, so a "•••" reads as deliberate, not as a bug. A
 * shared list draws as its symbols, each one a link to its page.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { destinations } from "../share/link";
import { shareUrl } from "./ShareSheet";
import { SharedBody, SharedList, carriesOn, guestHrefs } from "./SharedPanel";

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { origin: "https://topstocks.app", pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("the link", () => {
  it("opens the app on the shared answer and credits the share", () => {
    expect(shareUrl("ab_c-1")).toBe("https://topstocks.app/?share=ab_c-1&src=share");
  });

  it("goes to every platform with the URL encoded once", () => {
    const url = shareUrl("x1");
    const to = destinations(url, "¿Vendo NVDA?");
    expect(to.map((each) => each.id)).toEqual([
      "whatsapp",
      "x",
      "linkedin",
      "telegram",
      "facebook",
      "email",
    ]);
    const encoded = encodeURIComponent(url);
    for (const each of to) expect(each.href).toContain(encoded);
    expect(to[0]?.href.startsWith("https://wa.me/?text=")).toBe(true);
    expect(to.find((each) => each.id === "x")?.href).toContain(
      encodeURIComponent("¿Vendo NVDA?"),
    );
  });
});

describe("the shared answer", () => {
  const share = {
    question: "¿Cuánto gano si vendo?",
    content: "Ganarías ••• € (un 12 %).",
    web: [],
    activities: [],
    masked: true,
  };

  it("draws the question and the answer, and says amounts were hidden", () => {
    const html = renderToStaticMarkup(<SharedBody share={share} onLeave={() => {}} />);
    expect(html).toContain("¿Cuánto gano si vendo?");
    expect(html).toContain("12 %");
    expect(html).toContain("ag-chat-share-masked");
  });

  it("says nothing about amounts when they were left in", () => {
    const html = renderToStaticMarkup(
      <SharedBody share={{ ...share, masked: false }} onLeave={() => {}} />,
    );
    expect(html).not.toContain("ag-chat-share-masked");
  });
});

describe("a guest reading it", () => {
  it("keeps asking through a sign-in that comes back to the answer", () => {
    const to = guestHrefs("/auth/login", "ab_c-1", { pathname: "/portfolio" });
    expect(to?.keep).toBe(
      "/auth/login?next=" +
        encodeURIComponent("/portfolio?share=ab_c-1&src=share&continue=1") +
        "&wall=share",
    );
  });

  it("can import instead, still credited to the link but without it", () => {
    const to = guestHrefs("/auth/login", "ab_c-1", { pathname: "/" });
    expect(to?.importer).toBe(
      `/auth/login?next=${encodeURIComponent("/import?src=share")}&wall=share`,
    );
  });

  it("is offered nothing where there is no sign-in", () => {
    expect(guestHrefs(null, "ab_c-1")).toBeNull();
  });

  it("starts the thread back from the sign-in, never on the sharer's own link", () => {
    expect(carriesOn(true, true, { mine: false })).toBe(true);
    expect(carriesOn(true, true, { mine: true })).toBe(false);
    expect(carriesOn(false, true, { mine: false })).toBe(false);
    expect(carriesOn(true, false, { mine: false })).toBe(false);
    expect(carriesOn(true, true, null)).toBe(false);
  });
});

describe("a shared list", () => {
  it("draws its name, how many, and each symbol as a link to its page", () => {
    const html = renderToStaticMarkup(
      <SharedList
        share={{ title: "Semis", tickers: ["NVDA", "ASML"] }}
        onLeave={() => {}}
      />,
    );
    expect(html).toContain("Semis");
    expect(html).toContain('<span class="ag-chat-shared-list-n">2</span>');
    expect(html.match(/<li>/g)).toHaveLength(2);
    expect(html).toContain("ticker=NVDA");
    expect(html).toContain("ticker=ASML");
  });

  it("is called a list when it has no name", () => {
    const html = renderToStaticMarkup(
      <SharedList share={{ title: "", tickers: ["NVDA"] }} onLeave={() => {}} />,
    );
    expect(html).toMatch(/<h3 class="ag-chat-shared-list-title">[^<]+</);
  });
});
