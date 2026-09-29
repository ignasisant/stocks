/**
 * The page's line glyphs, drawn as the canvas draws them: a 24-unit stroke in
 * the colour of the text around it, so a tier's tint reaches its icon without a
 * rule per icon. Decorative every time — the word beside a glyph is the label.
 */

import type { ReactNode } from "react";

const SHAPES = {
  /** A tick: a done step, a clean scan, a written import. */
  check: <polyline points="5 12 10 17 19 7" />,
  /** The importable tier. */
  ok: (
    <>
      <circle cx="12" cy="12" r="9" />
      <polyline points="8 12 11 15 16 9" />
    </>
  ),
  /** The rejected tier. */
  bad: (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="9" x2="15" y1="9" y2="15" />
      <line x1="15" x2="9" y1="9" y2="15" />
    </>
  ),
  /** The warned tier. */
  warn: (
    <>
      <path d="M12 4 2 20h20z" />
      <line x1="12" x2="12" y1="10" y2="14" />
      <line x1="12" x2="12" y1="17" y2="17.2" />
    </>
  ),
  /** A note worth reading: rows gone, repairs waiting. */
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="12" x2="12" y1="8" y2="13" />
      <line x1="12" x2="12" y1="16" y2="16.2" />
    </>
  ),
  right: <polyline points="9 18 15 12 9 6" />,
  down: <polyline points="6 9 12 15 18 9" />,
  file: (
    <>
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
      <polyline points="14 3 14 8 19 8" />
    </>
  ),
  /** A statement read and staged. */
  fileOk: (
    <>
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
      <polyline points="14 3 14 8 19 8" />
      <polyline points="9 14 11 16 15 12" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type GlyphName = keyof typeof SHAPES;

export function Glyph({ name }: { name: GlyphName }) {
  return (
    <svg
      aria-hidden="true"
      className="im-glyph"
      fill="none"
      focusable="false"
      height="16"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      width="16"
    >
      {SHAPES[name]}
    </svg>
  );
}
