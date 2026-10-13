/**
 * The weights this book's verdicts were drawn at, for the copy to quote.
 *
 * Where a crumb ends, where an add goes and where a concentration starts
 * scale with how many companies the book holds, so the help text cannot
 * print them as constants: `useHelp` fills its `{small}`, `{add_to}`,
 * `{concentrated}` and `{sector}` slots from the answer's own lines.
 */

import { type ReactNode, createContext, useContext } from "react";
import { useLang, useT } from "../../shell/i18n";
import { line } from "./format";
import type { ReviewLines } from "./types";

/** The engine's narrow-book values, for an answer that carries none. */
export const NARROW: ReviewLines = {
  concentrated: 0.15,
  small: 0.005,
  add_to: 0.05,
  sector: 0.4,
};

const Context = createContext<ReviewLines>(NARROW);

export function LinesProvider({
  lines,
  children,
}: {
  lines: ReviewLines | null | undefined;
  children: ReactNode;
}) {
  return <Context.Provider value={lines ?? NARROW}>{children}</Context.Provider>;
}

/** The slots a help text may quote, printed in the reader's language. */
export function lineSlots(lines: ReviewLines, lang: string): Record<string, string> {
  return {
    concentrated: line(lines.concentrated ?? NARROW.concentrated!, lang),
    small: line(lines.small, lang),
    add_to: line(lines.add_to, lang),
    sector: line(lines.sector, lang),
  };
}

/** `t` for help copy: the same key, its line slots filled. */
export function useHelp() {
  const t = useT();
  const lang = useLang();
  const slots = lineSlots(useContext(Context), lang);
  return (key: string, extra?: Record<string, string | number>) =>
    t(key, { ...slots, ...extra });
}
