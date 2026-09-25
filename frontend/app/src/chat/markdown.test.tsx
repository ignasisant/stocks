/**
 * Tables are the one block in this renderer that can be wrong quietly.
 *
 * Every other block is visibly missing when it fails to parse — a heading
 * reads as a paragraph, a fence reads as text. A table that drops a column,
 * or that swallows the sentence above it, still draws a table: it just says
 * something the answer did not. So the rules that decide what *is* a table,
 * and what each row is worth once it is one, are asserted here.
 *
 * Rendered to static markup rather than mounted: this file needs no DOM, and
 * the assertion is about the HTML the drawer ends up putting on the page.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

const html = (text: string) => renderToStaticMarkup(<Markdown text={text} />);

describe("tables", () => {
  it("renders a header, its alignments and its rows", () => {
    const out = html(
      [
        "| Ticker | Weight |",
        "| --- | ---: |",
        "| AAPL | 12.4% |",
        "| MSFT | 9.1% |",
      ].join("\n"),
    );
    expect(out).toContain("<table");
    expect(out).toContain('<th scope="col">Ticker</th>');
    // The right-aligned column is the one the delimiter marked, and only it.
    expect(out).toContain('<th scope="col" class="ag-chat-right">Weight</th>');
    expect(out).toContain('<td class="ag-chat-right">12.4%</td>');
    expect(out.match(/<tr>/g)).toHaveLength(3);
  });

  it("keeps a pipe in a sentence out of a table", () => {
    const out = html("Filter with grep | head, then read it.");
    expect(out).not.toContain("<table");
    expect(out).toContain("grep | head");
  });

  it("needs the delimiter row, so a half-streamed header is still text", () => {
    const out = html("| Ticker | Weight |");
    expect(out).not.toContain("<table");
  });

  it("ends the paragraph above it, blank line or not", () => {
    const out = html(
      [
        "Here is the split:",
        "| Broker | Shares |",
        "| --- | --- |",
        "| Revolut | 40 |",
      ].join("\n"),
    );
    expect(out).toContain('<p class="ag-chat-p">Here is the split:</p>');
    expect(out).toContain('<th scope="col">Broker</th>');
  });

  it("gives every row the table's own width", () => {
    const out = html(
      ["| A | B | C |", "| --- | --- | --- |", "| 1 |", "| 1 | 2 | 3 | 4 |"].join("\n"),
    );
    // Short row padded, long row cut: three cells on both.
    const body = out.slice(out.indexOf("<tbody>"));
    expect(body.match(/<td[^>]*>/g)).toHaveLength(6);
    expect(body).not.toContain(">4<");
  });

  it("renders the inline markup inside a cell", () => {
    const out = html(["| Name |", "| --- |", "| **AAPL** |"].join("\n"));
    expect(out).toContain("<strong>AAPL</strong>");
  });
});
