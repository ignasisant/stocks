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

import { seed } from "../shell/tickers";
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

describe("lists", () => {
  it("carries on from the written number after a run of bullets", () => {
    // Blank lines around the bullets: CommonMark ends the list there, and the
    // second half still has to say 2.
    const out = html(["1. Sells", "", "- SNPS", "", "2. Buys"].join("\n"));
    expect(out).toContain('<ol class="ag-chat-list" start="2">');
  });

  it("nests an indented list inside its item", () => {
    const out = html(
      ["1. **Sells:**", "   - SNPS", "   - HUBS", "2. **Buys:**", "   - PDD"].join(
        "\n",
      ),
    );
    expect(out).toBe(
      '<ol class="ag-chat-list"><li><strong>Sells:</strong><ul class="ag-chat-list">' +
        "<li>SNPS</li><li>HUBS</li></ul></li><li><strong>Buys:</strong>" +
        '<ul class="ag-chat-list"><li>PDD</li></ul></li></ol>',
    );
  });

  it("hangs flush bullets under a numbered item", () => {
    const out = html(["1. Sells:", "* SNPS", "* HUBS", "2. Buys:", "* PDD"].join("\n"));
    expect(out.match(/<ol/g)).toHaveLength(1);
    expect(out).toContain("<li>Sells:<ul");
    expect(out).toContain("<li>Buys:<ul");
  });

  it("keeps a wrapped line in its item", () => {
    const out = html(["- First item that", "  wraps on", "- Second"].join("\n"));
    expect(out).toBe(
      '<ul class="ag-chat-list"><li>First item that<br/>wraps on</li><li>Second</li></ul>',
    );
  });

  it("keeps a paragraph after a blank line in its item", () => {
    const out = html(["1. Step one", "", "   The detail", "2. Step two"].join("\n"));
    expect(out.match(/<ol/g)).toHaveLength(1);
    expect(out).toContain('<li>Step one<p class="ag-chat-p">The detail</p></li>');
  });

  it("keeps items split by blank lines in one list", () => {
    expect(html("- a\n\n- b\n\n- c").match(/<ul/g)).toHaveLength(1);
  });

  it("ends the list at a flush line that is not an item", () => {
    const out = html("- a\n- b\nAfter the list.");
    expect(out).toContain('</ul><p class="ag-chat-p">After the list.</p>');
  });
});

describe("headings", () => {
  it("reads a bold line ending in a colon as a heading", () => {
    expect(html("**What it misses:**\n\n1. x")).toContain(
      '<div class="ag-chat-h">What it misses</div>',
    );
  });

  it("leaves a bold sentence and a bold line inside a list alone", () => {
    expect(html("**Do not sell yet.**")).toContain('<p class="ag-chat-p"><strong>');
    expect(html("1. **Sells:**")).toContain("<li><strong>Sells:</strong></li>");
  });

  it("drops a closing run of hashes", () => {
    expect(html("## Plan ##")).toContain('<div class="ag-chat-h">Plan</div>');
  });
});

describe("inline marks", () => {
  it("renders bold emphasis, strikes and underscore marks", () => {
    expect(html("***both***")).toContain("<strong><em>both</em></strong>");
    expect(html("~~old~~ new")).toContain("<s>old</s> new");
    expect(html("__bold__ and _em_")).toContain(
      "<strong>bold</strong> and <em>em</em>",
    );
  });

  it("leaves an underscore inside a word as text", () => {
    expect(html("snake_case_name")).toContain(">snake_case_name<");
  });

  it("keeps a lone asterisk inside bold", () => {
    expect(html("**P/E 7x * 2**")).toContain("<strong>P/E 7x * 2</strong>");
  });

  it("does not read arithmetic as emphasis", () => {
    expect(html("3 * 4 * 5")).not.toContain("<em>");
  });

  it("drops the backslash of an escape", () => {
    expect(html("costs \\$5 and 3\\*4")).toContain("costs $5 and 3*4");
  });
});

describe("tickers", () => {
  seed([
    { ticker: "SNPS", name: "Synopsys", logo: "/logos/snps.png" },
    { ticker: "MNDY", name: "monday.com", logo: null },
    { ticker: "HUBS", name: "HubSpot", logo: null },
    { ticker: "FCF", name: "First Commonwealth", logo: null },
  ]);

  it("links a bold ticker the account knows, behind its mark", () => {
    const out = html("**SNPS:** duopoly");
    expect(out).toContain('href="/ticker?ticker=SNPS"');
    expect(out).toContain('<img class="ag-tick-logo" src="/logos/snps.png"');
    expect(out).toContain("</a>:</strong> duopoly");
  });

  it("links each name of a bold list and keeps the words between", () => {
    const out = html("**SNPS, MNDY y HUBS** lead the sells");
    expect(out.match(/<a /g)).toHaveLength(3);
    expect(out).toContain("</a>, <a ");
    expect(out).toContain("</a> y <a ");
  });

  it("leaves a ticker-shaped word the account has no name for as bold text", () => {
    expect(html("**ZZZQ** rose")).toBe(
      '<p class="ag-chat-p"><strong>ZZZQ</strong> rose</p>',
    );
  });

  it("never reads a financial acronym as its ticker", () => {
    expect(html("**FCF**")).not.toContain("<a ");
  });

  it("leaves a bold phrase and a plain mention alone", () => {
    expect(html("**Paso 1 (SNPS)**")).not.toContain("<a ");
    expect(html("Sell SNPS now")).not.toContain("<a ");
  });

  it("keeps a company heading a linked ticker", () => {
    expect(html("**SNPS:**\n\nThe duopoly.")).toMatch(
      /<div class="ag-chat-h"><strong><a [^>]*ticker=SNPS/,
    );
  });

  it("links a table cell that is only a ticker", () => {
    const out = html(
      ["| Ticker | Weight |", "| --- | ---: |", "| SNPS | 4% |"].join("\n"),
    );
    expect(out).toContain('href="/ticker?ticker=SNPS"');
  });
});
