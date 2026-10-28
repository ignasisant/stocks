/**
 * A section that folds to its heading on a phone.
 *
 * A company page is nine phone screens long; a reader after the moat scrolls
 * past fundamentals, valuation and analysts to reach it. Folded, the page
 * below the first screen is a list of headings — an index the reader opens
 * where they want. On a desktop there is room for all of it, so nothing
 * folds and the heading renders as it always did.
 *
 * Closed by default; a section the reader opens stays open on their next
 * visit (per section, in this browser only — a convenience, not state). A
 * link that lands inside it — a page's jump bar, a shared `#anchor` — opens
 * it, since a heading reached on purpose is a section asked for.
 */

import { type ReactNode, useEffect, useRef, useState } from "react";
import { useMobile } from "../shell/useMobile";
import "./ui.css";

const KEY = "ag.fold.";

function remembered(id: string): boolean {
  try {
    return localStorage.getItem(KEY + id) === "1";
  } catch {
    return false;
  }
}

function remember(id: string, open: boolean) {
  try {
    if (open) localStorage.setItem(KEY + id, "1");
    else localStorage.removeItem(KEY + id);
  } catch {
    /* private window, blocked storage — the fold just forgets */
  }
}

export function Fold({
  id,
  head,
  opened = false,
  children,
}: {
  /** Names the section in storage; stable across companies. */
  id: string;
  head: ReactNode;
  /** Open on arrival whatever was remembered: the URL asked for this part. */
  opened?: boolean;
  children: ReactNode;
}) {
  const mobile = useMobile();
  const [open, setOpen] = useState(() => opened || remembered(id));
  const fold = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!mobile) return;
    const land = () => {
      const target = location.hash
        ? document.getElementById(location.hash.slice(1))
        : null;
      if (target && fold.current?.contains(target)) setOpen(true);
    };
    land();
    addEventListener("hashchange", land);
    return () => removeEventListener("hashchange", land);
  }, [mobile]);
  if (!mobile) {
    return (
      <>
        {head}
        {children}
      </>
    );
  }
  return (
    <details
      ref={fold}
      className="ag-fold"
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        setOpen(next);
        remember(id, next);
      }}
    >
      <summary className="ag-fold-head">{head}</summary>
      {open ? children : null}
    </details>
  );
}
