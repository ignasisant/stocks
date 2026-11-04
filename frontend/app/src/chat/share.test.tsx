/**
 * Sharing an answer by link: where the link goes, and what the reader sees.
 *
 * The link carries `src=share` so the signup it leads to is credited, and each
 * platform gets the URL its own share button opens. The reader's copy says
 * when amounts were hidden, so a "•••" reads as deliberate, not as a bug.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { destinations, shareUrl } from "./ShareSheet";
import { SharedBody } from "./SharedPanel";

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
