/**
 * The page's framing: the mono eyebrow every block opens with, and the rail
 * card that folds to one line when the rail drops under the task.
 *
 * Beside the task the rail is read at a glance — three cards, always open.
 * Under it (a phone, or a laptop with the chat drawer wide) the same cards
 * would push the preview a screen further down for figures nobody came for,
 * so each one folds to its title and a one-line summary, and opens on a tap.
 * Which of the two applies is the main column's width, not the viewport's —
 * the container query in import.css — so there is no resize listener.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import { Glyph } from "./Glyph";

/** "2 · Extracto de DEGIRO": the step it belongs to, where it has one. */
export function Eyebrow({
  n,
  id,
  children,
}: {
  n?: number;
  id?: string;
  children: ReactNode;
}) {
  return (
    <span className="im-eyebrow" id={id}>
      {n !== undefined ? `${n} · ` : null}
      {children}
    </span>
  );
}

/**
 * Scroll a section into view. A button rather than an `#anchor`: the router
 * reads the location on every history change, and a fragment is one.
 */
export function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function Fold({
  id,
  title,
  summary,
  children,
}: {
  id: string;
  title: string;
  /** What the folded line says instead of the card: "292 · 142.090 €". */
  summary?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section
      aria-labelledby={`${id}-title`}
      className="im-card im-fold"
      data-open={open ? "true" : "false"}
      id={id}
    >
      {/* Two titles for one card, one per width. The other is display:none,
          so a screen reader meets exactly one of them. */}
      <span className="im-eyebrow im-fold-label" id={`${id}-title`}>
        {title}
      </span>
      <button
        aria-controls={`${id}-body`}
        aria-expanded={open}
        className="im-fold-head"
        onClick={() => setOpen((was) => !was)}
        type="button"
      >
        <span className="im-fold-title">{title}</span>
        {summary ? <span className="im-fold-sum">{summary}</span> : null}
        <Glyph name="down" />
      </button>
      <div className="im-fold-body" id={`${id}-body`}>
        {children}
      </div>
    </section>
  );
}
