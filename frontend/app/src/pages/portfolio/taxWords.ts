/**
 * Tax copy shared by the Tax tab and the Home tax card.
 */

import { useT } from "../../shell/i18n";

/**
 * The jurisdiction's own wording, most specific first.
 *
 * A key the catalog is missing renders as the dotted key itself (the shell and
 * the Python side agree on that), which is what makes "does this string
 * exist?" answerable here without a second endpoint.
 */
export function useTaxWords(code: string) {
  const t = useT();
  const resolve = (name: string): string | null => {
    const specific = `portfolio.${code.toLowerCase()}_${name}`;
    if (t(specific) !== specific) return specific;
    const neutral = `portfolio.${name}`;
    return t(neutral) !== neutral ? neutral : null;
  };
  return {
    has: (name: string) => resolve(name) !== null,
    // A name neither spelling covers renders as its own dotted key, which is
    // what the Python side does too: a blank is invisible in review, and a key
    // on screen is a bug report that writes itself.
    say: (name: string, slots?: Record<string, string | number>) =>
      t(resolve(name) ?? `portfolio.${name}`, slots),
  };
}
