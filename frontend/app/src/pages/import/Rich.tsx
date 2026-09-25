/**
 * The catalog's inline markdown, rendered as elements rather than as asterisks.
 *
 * Several of this page's strings were written for `st.markdown` and carry
 * `**bold**` and `` `code` `` — `import.last_import_summary` bolds the
 * filename, `import.rejected_help` prints a CLI command. Showing the raw
 * punctuation would be a visible regression against the page being replaced,
 * and rewriting the copy to drop it would change strings two languages share
 * with Streamlit.
 *
 * Deliberately two constructs and no HTML: the text is parsed into elements,
 * never handed to `dangerouslySetInnerHTML`, so a translation can never inject
 * markup.
 */

import type { ReactNode } from "react";

const INLINE = /\*\*([^*]+)\*\*|`([^`]+)`/g;

export function Rich({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    const start = match.index;
    if (start > at) parts.push(text.slice(at, start));
    const bold = match[1];
    if (bold !== undefined) parts.push(<strong key={start}>{bold}</strong>);
    else
      parts.push(
        <code className="im-code" key={start}>
          {match[2]}
        </code>,
      );
    at = start + match[0].length;
  }
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
}
