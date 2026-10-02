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

  it("turns a <br> inside a cell into a break", () => {
    const out = html(
      ["| Area | News |", "| --- | --- |", "| AI | Gemini <br> Vertex |"].join("\n"),
    );
    expect(out).toContain("Gemini<br/>Vertex");
    expect(out).not.toContain("&lt;br");
  });

  it("leaves a table of short figures on one line and unstacked", () => {
    const out = html(
      ["| Ticker | Weight |", "| --- | ---: |", "| AAPL | 12.4% |"].join("\n"),
    );
    expect(out).toContain('<table class="ag-chat-table">');
    expect(out).not.toContain("ag-chat-wrap");
    expect(out).not.toContain("ag-chat-label");
  });

  it("wraps a column of sentences and stacks its table under the headers", () => {
    const out = html(
      [
        "| Area | News |",
        "| --- | --- |",
        "| Cloud | Vertex AI lets clients build their own generative apps |",
        "| Ads | |",
      ].join("\n"),
    );
    expect(out).toContain('class="ag-chat-table ag-chat-stack"');
    // Only the long column wraps; the short one keeps its single line.
    expect(out).toContain('<th scope="col">Area</th>');
    expect(out).toContain('<th scope="col" class="ag-chat-wrap">News</th>');
    // Every cell but the card's title carries its header's name, unless empty.
    expect(out.match(/ag-chat-label/g)).toHaveLength(1);
    expect(out).toContain(
      '<td class="ag-chat-wrap"><span class="ag-chat-label">News</span>Vertex',
    );
  });

  it("stacks a table of figures too wide for a narrow box", () => {
    const head = "| Ticker | Price | Day | Week | Month | Year | Weight |";
    const out = html(
      [
        head,
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| AAPL | 231.40 | +1.2% | -0.4% | +3.9% | +18.2% | 12.4% |",
      ].join("\n"),
    );
    expect(out).toContain("ag-chat-stack");
    expect(out).not.toContain("ag-chat-wrap");
  });
});
