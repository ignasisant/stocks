/**
 * The assistant answers in markdown, and this renders it. No library.
 *
 * A markdown package is the largest thing this drawer could have added to a
 * bundle every page pays for, and it would buy footnotes, tables and HTML
 * passthrough that no answer in this app has ever needed. What is here is what
 * `chat_core._rich()` and the Streamlit bubble around it actually show:
 * paragraphs, headings, bold, emphasis, inline and fenced code, ordered and
 * unordered lists, rules, and links.
 *
 * Everything is built as React elements rather than an HTML string, so escaping
 * is React's and there is no sanitiser to get wrong. The only thing that can
 * carry a URL is a link, and a link whose href is not http(s) is rendered as
 * its own text — which is the whole of the `javascript:` story.
 *
 * Tables are the one block here that exists because the answers use it: the
 * skills that compare holdings, brokers or tax years lay their result out as a
 * GFM table, and the Streamlit bubble renders those. Printing the pipes
 * instead was the drawer saying less than the page it replaces.
 *
 * What it deliberately does not render: footnotes, images, raw HTML. Those
 * arrive as their own source text, which is ugly and honest; a half-parsed
 * table that drops a column is neither — which is also why a table needs its
 * delimiter row before it is treated as one, and a header row that has
 * streamed in without it reads as a line of text until the next chunk lands.
 */

import { Fragment, type ReactNode } from "react";

/** bold · inline code · [text](url) · emphasis · a bare link. */
const INLINE =
  /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]*\]\([^)\s]+\)|\*[^*\n]+\*|https?:\/\/[^\s<>()[\]]+)/;

const LINK = /^\[([^\]\n]*)\]\(([^)\s]+)\)$/;

/** An href this drawer is willing to put behind a word. */
function href(url: string): string | null {
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
        if (part.startsWith("**"))
          return (
            <strong key={i}>
              <Inline text={part.slice(2, -2)} />
            </strong>
          );
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
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "table"; head: string[]; align: Align[]; rows: string[][] }
  | { kind: "hr" };

const FENCE = /^\s*```/;
const HEAD = /^ {0,3}#{1,6}\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBER = /^\s*\d+[.)]\s+(.*)$/;
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

function blocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
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
    const ordered = NUMBER.test(line);
    if (ordered || BULLET.test(line)) {
      const items: string[] = [];
      const shape = ordered ? NUMBER : BULLET;
      while (i < lines.length) {
        const item = shape.exec(lines[i] ?? "");
        if (!item) break;
        items.push(item[1] ?? "");
        i += 1;
      }
      out.push({ kind: "list", ordered, items });
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
        BULLET.test(next) ||
        NUMBER.test(next) ||
        tableAt(lines, i)
      )
        break;
      body.push(next.replace(QUOTE, "").trim());
      i += 1;
    }
    if (body.length) out.push({ kind: "p", lines: body });
  }
  return out;
}

/** The class a column's alignment needs, if it needs one. */
function pull(align: Align | undefined): string | undefined {
  if (align === "right") return "ag-chat-right";
  if (align === "center") return "ag-chat-center";
  return undefined;
}

export function Markdown({ text }: { text: string }): ReactNode {
  return (
    <>
      {blocks(text).map((block, i) => {
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
          return (
            <div className="ag-chat-tablewrap" key={i}>
              <table className="ag-chat-table">
                <thead>
                  <tr>
                    {block.head.map((cell, n) => (
                      <th scope="col" className={pull(block.align[n])} key={n}>
                        <Inline text={cell} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, r) => (
                    <tr key={r}>
                      {/* Walked by the header rather than by the row: a short
                          row leaves an empty cell and a long one is cut,
                          which keeps every row the width of its table. */}
                      {block.head.map((_, n) => (
                        <td className={pull(block.align[n])} key={n}>
                          <Inline text={row[n] ?? ""} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        if (block.kind === "list") {
          const items = block.items.map((item, n) => (
            <li key={n}>
              <Inline text={item} />
            </li>
          ));
          return block.ordered ? (
            <ol className="ag-chat-list" key={i}>
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
            {block.lines.map((line, n) => (
              <Fragment key={n}>
                {n > 0 && <br />}
                <Inline text={line} />
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}
