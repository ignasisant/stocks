/**
 * The shared links block: what it draws for an answer and for a list. Static
 * markup with no catalog loaded, so strings are keys.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ListedShare } from "../../chat/types";
import { SharedLinkList, sharedOn } from "./SharedLinks";

const row = (over: Partial<ListedShare> = {}): ListedShare => ({
  id: "AbCdEfGh123",
  kind: "answer",
  answer_id: "a1",
  question: "¿Cuánto pago por vender NVDA?",
  masked: false,
  created: "2026-11-04T10:00:00Z",
  ...over,
});

const draw = (rows: ListedShare[]) =>
  renderToStaticMarkup(
    <SharedLinkList rows={rows} busy={null} failure={null} onStop={() => {}} />,
  );

describe("the shared answers block", () => {
  it("links each question to the page its readers see", () => {
    const html = draw([row(), row({ id: "x_y-Z12345", question: "Otra" })]);
    expect(html).toContain('href="/?share=AbCdEfGh123"');
    expect(html).toContain('href="/?share=x_y-Z12345"');
    expect(html.match(/profile\.shares_stop/g)).toHaveLength(2);
  });

  it("marks only the masked links", () => {
    const html = draw([row({ masked: true }), row({ id: "open12345" })]);
    expect(html.match(/profile\.shares_masked/g)).toHaveLength(1);
  });

  it("marks a list as one", () => {
    const html = draw([
      row(),
      row({ id: "list12345", kind: "watchlist", answer_id: "" }),
    ]);
    expect(html.match(/profile\.shares_list/g)).toHaveLength(1);
    expect(html).toContain('href="/?share=list12345"');
  });

  it("escapes a question", () => {
    expect(draw([row({ question: "<img src=x onerror=1>" })])).not.toContain("<img");
  });

  it("dates a link by its day, and skips a stamp it cannot read", () => {
    expect(sharedOn("2026-11-04T10:00:00Z", "en")).toBe("Nov 4, 2026");
    expect(sharedOn("", "en")).toBe("");
    expect(draw([row({ created: "" })])).not.toContain("profile.shares_on");
  });
});
