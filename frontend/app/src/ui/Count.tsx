/**
 * A figure that counts to its new value instead of swapping.
 *
 * A price refresh used to replace "138.857 €" with "138.912 €" in one frame,
 * and nobody saw it happen: the page looked the same, so it looked stale. The
 * figure now runs from the old value to the new one, tinted by the direction
 * it moved, so a refresh reads as a refresh.
 *
 * It works on the text the caller already formatted, so no tile changes how
 * it spells a figure: the one number in the string is read in the account's
 * language (`numberLang`), and every frame reprints it with the same decimals,
 * grouping, sign and surrounding text. The last frame is the caller's string
 * itself. Anything that does not read as one comparable number — two numbers,
 * a dash, a different unit or decimals — just swaps, as do the first render,
 * reduced motion and a hidden tab.
 *
 * A new value mid-count starts from the figure on screen, not from where the
 * old count was going, so a burst of refreshes never jumps.
 */

import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { num, numberLang } from "../shell/numbers";

/** How long a count runs (ms). Long enough to read as counting. */
const COUNT_MS = 800;

const SIGNS = "+-−";

/** One number inside a formatted string, and the text around it. */
export type Figure = {
  head: string;
  tail: string;
  /** "" when unsigned; where it sat — glued to the digits or leading. */
  sign: string;
  signAt: "lead" | "digits" | null;
  value: number;
  digits: number;
  grouped: boolean;
};

const seps = new Map<string, { group: string; decimal: string }>();

function separators(lang: string): { group: string; decimal: string } {
  let found = seps.get(lang);
  if (!found) {
    const parts = new Intl.NumberFormat(lang).formatToParts(12345.6);
    found = {
      group: parts.find((p) => p.type === "group")?.value ?? ",",
      decimal: parts.find((p) => p.type === "decimal")?.value ?? ".",
    };
    seps.set(lang, found);
  }
  return found;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The one number in `text`, or null when there is none or more than one. */
export function readFigure(text: string, lang: string): Figure | null {
  const { group, decimal } = separators(lang);
  const pattern = new RegExp(
    `\\d(?:\\d|${escape(group)}(?=\\d))*(?:${escape(decimal)}\\d+)?`,
    "g",
  );
  const hits = [...text.matchAll(pattern)];
  const hit = hits.length === 1 ? hits[0] : undefined;
  if (!hit) return null;
  const at = hit.index ?? 0;
  let head = text.slice(0, at);
  const tail = text.slice(at + hit[0].length);
  let sign = "";
  let signAt: Figure["signAt"] = null;
  const last = head.charAt(head.length - 1);
  const first = head.charAt(0);
  if (last && SIGNS.includes(last)) {
    sign = last;
    signAt = "digits";
    head = head.slice(0, -1);
  } else if (first && SIGNS.includes(first)) {
    sign = first;
    signAt = "lead";
    head = head.slice(1);
  }
  const [whole = "", fraction = ""] = hit[0].split(decimal);
  const value = Number(`${whole.split(group).join("")}.${fraction || "0"}`);
  if (!Number.isFinite(value)) return null;
  return {
    head,
    tail,
    sign,
    signAt,
    value: sign && sign !== "+" ? -value : value,
    digits: fraction.length,
    grouped: whole.includes(group),
  };
}

/** Two figures a count can run between: same unit, same text, same decimals. */
export function countable(from: Figure | null, to: Figure | null): boolean {
  return (
    !!from &&
    !!to &&
    from.head === to.head &&
    from.tail === to.tail &&
    from.digits === to.digits &&
    from.value !== to.value
  );
}

/** `value` printed the way `to` (and, for a sign `to` lacks, `from`) prints. */
export function printFigure(
  value: number,
  from: Figure,
  to: Figure,
  lang: string,
): string {
  let digits = num(Math.abs(value), to.digits, lang);
  // A caller whose formatter leaves thousands bare keeps them bare mid-count.
  if (!to.grouped && Math.abs(to.value) >= 1000) {
    digits = digits.split(separators(lang).group).join("");
  }
  const minus = [to.sign, from.sign].find((s) => s && s !== "+") ?? "-";
  const plus = to.sign === "+" || from.sign === "+" ? "+" : "";
  // A count crossing zero prints "0,00" once, not "-0,00".
  const sign = value < 0 && /[1-9]/.test(digits) ? minus : plus;
  const at = to.signAt ?? from.signAt ?? "lead";
  return at === "digits"
    ? `${to.head}${sign}${digits}${to.tail}`
    : `${sign}${to.head}${digits}${to.tail}`;
}

/** Fast out, soft landing — no overshoot: a figure never passes its value. */
function settle(k: number): number {
  return 1 - (1 - k) ** 3;
}

function still(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  return (
    document.visibilityState === "hidden" ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function Count({ text, tint = false }: { text: string; tint?: boolean }) {
  const [frame, setFrame] = useState<{ text: string; dir: "up" | "down" } | null>(null);
  /** The text on screen right now — where an interrupted count restarts. */
  const shown = useRef(text);
  const raf = useRef(0);

  useLayoutEffect(() => {
    if (shown.current === text) return;
    cancelAnimationFrame(raf.current);
    const lang = numberLang();
    const from = readFigure(shown.current, lang);
    const to = readFigure(text, lang);
    if (!from || !to || !countable(from, to) || still()) {
      shown.current = text;
      setFrame(null);
      return;
    }
    const dir = to.value > from.value ? "up" : "down";
    let start: number | null = null;
    const step = (now: number) => {
      start ??= now;
      const k = Math.min(1, (now - start) / COUNT_MS);
      if (k >= 1) {
        shown.current = text;
        setFrame(null);
        return;
      }
      const value = from.value + (to.value - from.value) * settle(k);
      shown.current = printFigure(value, from, to, lang);
      setFrame({ text: shown.current, dir });
      raf.current = requestAnimationFrame(step);
    };
    // Hold the old figure until the first frame, so the new one never flashes.
    setFrame({ text: shown.current, dir });
    raf.current = requestAnimationFrame(step);
  }, [text]);

  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  return (
    <span className="ag-count" data-dir={tint && frame ? frame.dir : undefined}>
      {frame ? frame.text : text}
    </span>
  );
}

/** `Count` for a slot that takes any node: only a string counts. */
export function counted(node: ReactNode, tint = false): ReactNode {
  return typeof node === "string" ? <Count text={node} tint={tint} /> : node;
}
