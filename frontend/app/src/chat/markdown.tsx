/**
 * The assistant answers in markdown, and this renders it. No library.
 *
 * A markdown package is the largest thing this drawer could have added to a
 * bundle every page pays for, and it would buy footnotes, tables and HTML
 * passthrough that no answer in this app has ever needed. What is here is what
 * the answers actually use: paragraphs, headings, bold, emphasis, strikes,
 * inline and fenced code, ordered and unordered lists (nested, and with
 * paragraphs inside an item), rules, links and backslash escapes.
 *
 * Everything is built as React elements rather than an HTML string, so escaping
 * is React's and there is no sanitiser to get wrong. The only thing that can
 * carry a URL is a link, and a link whose href is not http(s) is rendered as
 * its own text — which is the whole of the `javascript:` story.
 *
 * Tables are the one block here that exists because the answers use it: the
 * skills that compare holdings, brokers or tax years lay their result out as a
 * GFM table, and printing the pipes would be the drawer saying less than the
 * answer does.
 *
 * A table also has to fit the drawer, which is 420px wide and a phone's width
 * on a phone. A column of sentences wraps instead of running off the side, and
 * a table that would still need a sideways scroll in a narrow box is stacked:
 * one card per row, the first cell its title and every other cell under its
 * header's name. Short figures keep their one line, because a weight that
 * breaks between the number and its `%` is not comparable down a column.
 *
 * What it deliberately does not render: footnotes, images, raw HTML. Those
 * arrive as their own source text, which is ugly and honest — the one
 * exception is `<br>` inside a table cell, because a GFM row is one line and
 * that is the only way a cell can carry two, so models write it. A half-parsed
 * table that drops a column is neither — which is also why a table needs its
 * delimiter row before it is treated as one, and a header row that has
 * streamed in without it reads as a line of text until the next chunk lands.
 */

import { Fragment, type ReactNode } from "react";

import { TickerCell, useTickerProfile } from "../shell/tickers";

/**
 * escape · inline code · bold emphasis · bold · strike · [text](url) ·
 * emphasis · a bare link. Where two could start at the same character the
 * earlier one here wins, so `***` is tried before `**` and `**` before `*`.
 *
 * Bold takes a lone `*` inside it ("**P/E 7x * 2**"), and emphasis has to
 * hug its words, so "3 * 4 * 5" stays arithmetic. Underscores are the same
 * marks, flanked: `Inline` leaves one inside a word (`snake_case`) as text.
 * No lookbehind, which would take the whole bundle down on an older Safari.
 */
const INLINE = new RegExp(
  `(${[
    /\\[!-/:-@[-`{-~]/,
    /`[^`\n]+`/,
    /\*\*\*[^*\n]+\*\*\*/,
    /\*\*(?:[^*\n]|\*(?!\*))+?\*\*/,
    /__[^_\n]+__/,
    /~~[^~\n]+~~/,
    /\[[^\]\n]*\]\([^)\s]+\)/,
    /\*[^\s*](?:[^*\n]*[^\s*])?\*/,
    /_[^\s_](?:[^_\n]*[^\s_])?_/,
    /https?:\/\/[^\s<>()[\]]+/,
  ]
    .map((part) => part.source)
    .join("|")})`,
);

/** A letter or digit, which an underscore mark may not touch. */
const WORD = /[\p{L}\p{N}]/u;

const LINK = /^\[([^\]\n]*)\]\(([^)\s]+)\)$/;

/** Ticker-shaped: NVDA, S, BRK.B, ASML.AS, BTC-EUR. */
const SYMBOL = /^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z0-9]{1,4})?$/;

/** How a bold run lists several: "ESTC, MNDY y HUBS", "PDD and JD". */
const JOIN = /(\s*,\s*|\s*\/\s*|\s+(?:y|e|o|and|or|&)\s+)/;

/**
 * Bold and ticker-shaped, and in an answer almost never the ticker: the
 * figures and bodies a financial answer names. Some are listed somewhere
 * (FCF, SBC), which is why the account's catalog alone is not enough.
 */
const NOT_SYMBOLS = new Set(
  (
    "A AI ADR API ARR ATH BCE BOE CAC CAGR CAPEX CEO CFO CNMV COO CPI CTO DCF " +
    "EBIT EBITDA ECB EDA EE EEUU EPS ESG ETF EU EUR EV FCF FED FIFO FX GAAP " +
    "GDP GLP I IA IFRS IPO IRPF IRR ISIN IVA KPI LIFO LLM LTV MRR NAV NDR NO " +
    "NRR NYSE OK OPEX OTC P PE PEG PER PIB PS REIT ROA ROCE ROE ROI ROIC RSI " +
    "SBC SEC SMA SPAC TAM TER TWR UE UK US USA USD UU VS WACC Y YOY YTD"
  ).split(" "),
);

/**
 * The parts of a bold run that is nothing but tickers — symbols at the even
 * slots, the words joining them at the odd — or null. A trailing colon
 * ("**SNPS:**") is kept as the last joiner.
 */
function symbols(text: string): string[] | null {
  const colon = text.endsWith(":");
  const parts = (colon ? text.slice(0, -1) : text).split(JOIN);
  for (let n = 0; n < parts.length; n += 2) {
    const part = parts[n] ?? "";
    if (!SYMBOL.test(part) || NOT_SYMBOLS.has(part)) return null;
  }
  return colon ? [...parts, ":"] : parts;
}

/**
 * A bold ticker, as the house rule draws every ticker: its mark and a link to
 * its page. Only once the account's catalog has a name for it — a holding, a
 * watched name, a search — so a ticker-shaped word nobody here has heard of
 * stays the bold text the model wrote rather than a link to an empty page.
 */
function Ticker({ ticker }: { ticker: string }) {
  const profile = useTickerProfile(ticker);
  if (!profile?.name) return ticker;
  return <TickerCell ticker={ticker} name={false} className="ag-chat-tick" />;
}

function Tickers({ parts }: { parts: string[] }) {
  return parts.map((part, n) =>
    n % 2 === 0 && part !== ":" ? <Ticker ticker={part} key={n} /> : part,
  );
}

/** An href this drawer is willing to put behind a word. */
export function href(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

function Link({ url, children }: { url: string; children: ReactNode }) {
  return (
    <a
      className="ag-chat-a"
      href={url}
      target="_blank"
      rel="noopener noreferrer nofollow"
    >
      {children}
    </a>
  );
}

/** One inline run: the spans inside a paragraph, a heading or a list item. */
export function Inline({ text }: { text: string }): ReactNode {
  // A capturing split alternates plain text and tokens, so the odd slots are
  // the matches and no match index has to be tracked by hand.
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 0 || !part) return part;
        if (part.startsWith("\\")) return part.slice(1);
        if (part.startsWith("_")) {
          const before = parts[i - 1]?.slice(-1) ?? "";
          const after = parts[i + 1]?.slice(0, 1) ?? "";
          if (WORD.test(before) || WORD.test(after)) return part;
          const bold = part.startsWith("__");
          const inner = <Inline text={part.slice(bold ? 2 : 1, bold ? -2 : -1)} />;
          return bold ? <strong key={i}>{inner}</strong> : <em key={i}>{inner}</em>;
        }
        if (part.startsWith("***"))
          return (
            <strong key={i}>
              <em>
                <Inline text={part.slice(3, -3)} />
              </em>
            </strong>
          );
        if (part.startsWith("~~"))
          return (
            <s key={i}>
              <Inline text={part.slice(2, -2)} />
            </s>
          );
        if (part.startsWith("**")) {
          const inner = part.slice(2, -2);
          const named = symbols(inner);
          return (
            <strong key={i}>
              {named ? <Tickers parts={named} /> : <Inline text={inner} />}
            </strong>
          );
        }
        if (part.startsWith("`"))
          return (
            <code className="ag-chat-code" key={i}>
              {part.slice(1, -1)}
            </code>
          );
        const link = LINK.exec(part);
        if (link) {
          const url = href(link[2] ?? "");
          const label = link[1] || link[2] || "";
          return url ? (
            <Link url={url} key={i}>
              {label}
            </Link>
          ) : (
            part
          );
        }
        if (part.startsWith("*"))
          return (
            <em key={i}>
              <Inline text={part.slice(1, -1)} />
            </em>
          );
        return (
          <Link url={part} key={i}>
            {part}
          </Link>
        );
      })}
    </>
  );
}

/** What a column's delimiter asked for; "" is the default, left. */
type Align = "" | "right" | "center";

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: Block[][] }
  | { kind: "code"; text: string }
  | { kind: "table"; head: string[]; align: Align[]; rows: string[][] }
  | { kind: "hr" };

const FENCE = /^\s*```/;
const HEAD = /^ {0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*$/;
/** indent · bullet or number · the gap before the item's text · the text. */
const MARKER = /^( *)(?:([-*+])|(\d{1,9})[.)])( +|$)(.*)$/;
/**
 * A line that is all bold and does not end a sentence: "**What it misses:**".
 * Models write it where they mean a heading, and drawn as a bold paragraph it
 * sits beside their real `###` headings at a different size.
 */
const BOLD_HEAD = /^\*\*([^*\n]{1,80}?)\*\*:?$/;
const RULE = /^ {0,3}([-*_])\s*(\1\s*){2,}$/;
/** A quote marker is stripped rather than styled: the words are the point. */
const QUOTE = /^\s*>\s?/;

/** The cells of one row, with the optional leading and trailing pipes gone. */
function cells(line: string): string[] {
  let text = line.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  return text.split("|").map((cell) => cell.trim());
}

/**
 * The alignments a delimiter row asks for, or null if this is not one.
 *
 * `---`, `:---`, `---:`, `:---:`, one per column. Anything else — including a
 * paragraph that happens to contain a pipe — is not a table, and saying so
 * here is what keeps `a | b` in a sentence out of a `<table>`.
 */
function alignments(line: string): Align[] | null {
  if (!line.includes("|")) return null;
  const out: Align[] = [];
  for (const part of cells(line)) {
    if (!/^:?-+:?$/.test(part)) return null;
    const left = part.startsWith(":");
    const right = part.endsWith(":");
    out.push(left && right ? "center" : right ? "right" : "");
  }
  return out.length ? out : null;
}

/**
 * The table starting at `i`, or null. Read twice: once where a block begins,
 * and once to end a paragraph, because an answer that puts a table straight
 * under a sentence with no blank line between them means both.
 */
function tableAt(lines: string[], i: number): { block: Block; next: number } | null {
  const head = lines[i] ?? "";
  if (!head.includes("|")) return null;
  const align = alignments(lines[i + 1] ?? "");
  const columns = cells(head);
  // GFM: the delimiter row decides the column count, and a header that
  // disagrees with it is not a table at all.
  if (!align || align.length !== columns.length) return null;
  const rows: string[][] = [];
  let cut = i + 2;
  while (cut < lines.length) {
    const line = lines[cut] ?? "";
    if (!line.trim() || !line.includes("|")) break;
    rows.push(cells(line));
    cut += 1;
  }
  return { block: { kind: "table", head: columns, align, rows }, next: cut };
}

/** gpt-oss cites as `【2†L13-L17】`, pointers into a browser it does not
 * have here: noise to a reader. A half-streamed one goes too. */
const CITE_MARK = /【[^】\n]*(】|$)/g;

/** The answer as lines, a leading tab worth four spaces of indent. */
function split(source: string): string[] {
  return source
    .replace(/\r\n/g, "\n")
    .replace(CITE_MARK, "")
    .split("\n")
    .map((line) => line.replace(/^\t+/, (tabs) => "    ".repeat(tabs.length)));
}

function indent(line: string): number {
  return line.length - line.trimStart().length;
}

type Marker = {
  indent: number;
  ordered: boolean;
  start: number;
  text: string;
  col: number;
};

/** The list marker a line opens with, and the column its text starts at. */
function marker(line: string): Marker | null {
  const m = MARKER.exec(line);
  if (!m) return null;
  const lead = m[1]?.length ?? 0;
  const digits = m[3];
  const width = digits === undefined ? 1 : digits.length + 1;
  return {
    indent: lead,
    ordered: digits !== undefined,
    start: digits === undefined ? 1 : Number(digits),
    text: m[5] ?? "",
    col: lead + width + Math.max(1, m[4]?.length ?? 0),
  };
}

/**
 * The list starting at `i`. An item owns every line indented past its
 * marker's own indent — a wrapped sentence, a paragraph after a blank line, a
 * nested list — and those lines, with the item's indent taken off, are parsed
 * as blocks of their own, which is all nesting is. A blank line between two
 * items keeps them one list.
 *
 * One liberty CommonMark does not take: bullets flush under a numbered item
 * ("1. **Sells:**" then "- SNPS") belong to it. That is what every model that
 * writes them means, and read strictly they break the numbering in two.
 */
function listAt(
  lines: string[],
  i: number,
  first: Marker,
): { block: Block; next: number } {
  const { ordered, indent: base } = first;
  const sibling = (line: string, col: number) => {
    const m = marker(line);
    return m !== null && m.ordered === ordered && m.indent >= base && m.indent < col;
  };
  const items: Block[][] = [];
  let at = i;
  let col = first.col;
  while (at < lines.length) {
    const head = marker(lines[at] ?? "");
    if (!head || !sibling(lines[at] ?? "", col)) break;
    col = head.col;
    const body = [head.text];
    at += 1;
    let blank = false;
    while (at < lines.length) {
      const line = lines[at] ?? "";
      if (!line.trim()) {
        let k = at + 1;
        while (k < lines.length && !(lines[k] ?? "").trim()) k += 1;
        const next = lines[k];
        if (next === undefined || indent(next) <= base) break;
        for (; at < k; at += 1) body.push("");
        blank = true;
        continue;
      }
      if (sibling(line, col)) break;
      const deep = indent(line);
      const m = marker(line);
      const flush = ordered && !blank && m !== null && !m.ordered && deep === base;
      if (deep <= base && !flush) break;
      body.push(line.slice(Math.min(deep, flush ? base : col)));
      blank = false;
      at += 1;
    }
    items.push(blocks(body, false));
    // A blank line between two items is a loose list, not two lists.
    let k = at;
    while (k < lines.length && !(lines[k] ?? "").trim()) k += 1;
    if (k < lines.length && sibling(lines[k] ?? "", col)) at = k;
    else break;
  }
  return { block: { kind: "list", ordered, start: first.start, items }, next: at };
}

/** `top` is the answer itself rather than the inside of a list item. */
function blocks(lines: string[], top: boolean): Block[] {
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (FENCE.test(line)) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i] ?? "")) {
        body.push(lines[i] ?? "");
        i += 1;
      }
      i += 1; // the closing fence, or the end of the text
      out.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ kind: "hr" });
      i += 1;
      continue;
    }
    const table = tableAt(lines, i);
    if (table) {
      out.push(table.block);
      i = table.next;
      continue;
    }
    const head = HEAD.exec(line);
    if (head) {
      out.push({ kind: "h", text: head[1] ?? "" });
      i += 1;
      continue;
    }
    const first = marker(line);
    if (first) {
      const list = listAt(lines, i, first);
      out.push(list.block);
      i = list.next;
      continue;
    }
    // A paragraph runs to the next blank line or to whatever starts a block of
    // its own. Its internal newlines are kept as breaks: an answer that laid
    // three figures on three lines meant three lines.
    const body: string[] = [];
    while (i < lines.length) {
      const next = lines[i] ?? "";
      if (
        !next.trim() ||
        FENCE.test(next) ||
        HEAD.test(next) ||
        RULE.test(next) ||
        marker(next) ||
        tableAt(lines, i)
      )
        break;
      body.push(next.replace(QUOTE, "").trim());
      i += 1;
    }
    const bold = top && body.length === 1 ? BOLD_HEAD.exec(body[0] ?? "") : null;
    if (bold && !/[.!?]$/.test(bold[1] ?? "")) {
      const text = (bold[1] ?? "").replace(/:$/, "");
      // "**NVDA:**" over a paragraph is a company's heading, and still a
      // ticker: kept bold, so `Inline` draws its mark and its link.
      out.push({ kind: "h", text: symbols(text) ? `**${text}**` : text });
    } else if (body.length) out.push({ kind: "p", lines: body });
  }
  return out;
}

/** The class a column's alignment needs, if it needs one. */
function pull(align: Align | undefined): string | undefined {
  if (align === "right") return "ag-chat-right";
  if (align === "center") return "ag-chat-center";
  return undefined;
}

/** A line break inside a cell, as the models write it. */
const BREAK = /<br\s*\/?>/i;

/** A column whose longest line is past this reads as text, and wraps. */
const PROSE = 28;

/** Past this many characters across a row, a table overflows a narrow box. */
const ROOMY = 56;

/** The characters a cell's longest line puts on screen, markup stripped. */
function span(cell: string): number {
  return Math.max(
    0,
    ...cell.split(BREAK).map(
      (line) =>
        line
          .replace(/\[([^\]\n]*)\]\([^)\s]+\)/g, "$1")
          .replace(/\\(?=[!-/:-@[-`{-~])|\*|`|__|~~/g, "")
          .trim().length,
    ),
  );
}

/**
 * How a table lays out: which columns wrap, and whether a narrow box stacks it.
 *
 * Measured from the text rather than left to the browser, because the browser
 * only finds out after drawing it too wide: `white-space` and the stacking
 * query have to be decided before there is a layout to measure.
 */
function shape(head: string[], rows: string[][]): { wrap: boolean[]; stack: boolean } {
  const widths = head.map((cell, n) =>
    Math.max(span(cell), ...rows.map((row) => span(row[n] ?? ""))),
  );
  const wrap = widths.map((w) => w > PROSE);
  // The padding of a cell is worth about three characters.
  const row = widths.reduce((sum, w) => sum + w + 3, 0);
  return { wrap, stack: wrap.some(Boolean) || row > ROOMY };
}

/** A cell's text, its `<br>`s turned into the breaks they meant. */
function Cell({ text }: { text: string }): ReactNode {
  return text.split(BREAK).map((line, n) => {
    // A cell that is only a ticker is one, bold or not: a holdings table's
    // first column is the commonest place an answer names them.
    const named = symbols(line.trim());
    return (
      <Fragment key={n}>
        {n > 0 && <br />}
        {named ? <Tickers parts={named} /> : <Inline text={line.trim()} />}
      </Fragment>
    );
  });
}

function Table({
  head,
  align,
  rows,
}: {
  head: string[];
  align: Align[];
  rows: string[][];
}) {
  const { wrap, stack } = shape(head, rows);
  const style = (n: number) =>
    [pull(align[n]), wrap[n] && "ag-chat-wrap"].filter(Boolean).join(" ") || undefined;
  return (
    <div className="ag-chat-tablewrap">
      <table className={stack ? "ag-chat-table ag-chat-stack" : "ag-chat-table"}>
        <thead>
          <tr>
            {head.map((cell, n) => (
              <th scope="col" className={style(n)} key={n}>
                <Cell text={cell} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {/* Walked by the header rather than by the row: a short
                  row leaves an empty cell and a long one is cut,
                  which keeps every row the width of its table. */}
              {head.map((cell, n) => {
                const text = row[n] ?? "";
                return (
                  <td className={style(n)} key={n}>
                    {/* The header's name, shown only once the table is
                        stacked and the header row is gone. The first cell
                        titles its card and an empty one is hidden, so
                        neither needs one. */}
                    {stack && n > 0 && text && (
                      <span className="ag-chat-label">
                        <Cell text={cell} />
                      </span>
                    )}
                    <Cell text={text} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A paragraph's lines, its newlines kept as the breaks they meant. */
function Lines({ lines }: { lines: string[] }): ReactNode {
  return lines.map((line, n) => (
    <Fragment key={n}>
      {n > 0 && <br />}
      <Inline text={line} />
    </Fragment>
  ));
}

/**
 * One list item. A first paragraph is drawn bare, so a tight list reads as
 * lines rather than as a stack of spaced paragraphs; whatever follows it — a
 * second paragraph, a nested list — is drawn as the blocks it is.
 */
function Item({ blocks: inner }: { blocks: Block[] }) {
  const [lead, ...rest] = inner;
  if (lead?.kind !== "p")
    return <li>{inner.length > 0 && <Blocks blocks={inner} />}</li>;
  return (
    <li>
      <Lines lines={lead.lines} />
      {rest.length > 0 && <Blocks blocks={rest} />}
    </li>
  );
}

function Blocks({ blocks: list }: { blocks: Block[] }): ReactNode {
  return list.map((block, i) => {
    if (block.kind === "hr") return <hr className="ag-chat-hr" key={i} />;
    if (block.kind === "h")
      return (
        <div className="ag-chat-h" key={i}>
          <Inline text={block.text} />
        </div>
      );
    if (block.kind === "code")
      return (
        <pre className="ag-chat-pre" key={i}>
          <code>{block.text}</code>
        </pre>
      );
    if (block.kind === "table")
      return <Table head={block.head} align={block.align} rows={block.rows} key={i} />;
    if (block.kind === "list") {
      const items = block.items.map((item, n) => <Item blocks={item} key={n} />);
      return block.ordered ? (
        <ol
          className="ag-chat-list"
          start={block.start === 1 ? undefined : block.start}
          key={i}
        >
          {items}
        </ol>
      ) : (
        <ul className="ag-chat-list" key={i}>
          {items}
        </ul>
      );
    }
    return (
      <p className="ag-chat-p" key={i}>
        <Lines lines={block.lines} />
      </p>
    );
  });
}

export function Markdown({ text }: { text: string }): ReactNode {
  return <Blocks blocks={blocks(split(text), true)} />;
}
