/**
 * The ledger's vocabulary, in the reader's language.
 *
 * A transaction is stored in one vocabulary and one only — English column
 * names (`quantity`, `fee`) and canonical verbs (`buy`, `split`) — and nothing
 * here changes that. The import preview is simply the one screen where a
 * reader meets those words, so they are translated on the way to the table and
 * nowhere else. This mirrors `stocks/web/tx_text.py`, down to translating the
 * `action` parameter inside a validation issue.
 */

import { useLang, useT } from "../../shell/i18n";
import type { Issue } from "./api";

export function useVocabulary() {
  const t = useT();
  const lang = useLang();

  /** "buy" -> "compra". An unknown verb passes through unchanged. */
  const action = (verb: string) => {
    const key = `import.action_${verb}`;
    const label = t(key);
    return label === key ? verb : label;
  };

  /** A column's header text, or its raw name when nobody has named it. */
  const column = (name: string) => {
    const key = `import.col_${name}`;
    const label = t(key);
    return label === key ? name : label;
  };

  /**
   * One validation issue, translated.
   *
   * The API sends `key` and `params` precisely so a client with a catalog does
   * not have to ship the English `message` — which is the fallback, and only
   * for a key this catalog has never heard of.
   */
  const issue = (found: Issue) => {
    const params: Record<string, string | number> = { ...found.params };
    const verb = params.action;
    if (typeof verb === "string") params.action = action(verb);
    const text = t(found.key, params);
    return text === found.key ? found.message : text;
  };

  const issues = (list: Issue[]) => list.map(issue).join("; ");

  const num = (value: number, places: number) =>
    new Intl.NumberFormat(lang, {
      minimumFractionDigits: places,
      maximumFractionDigits: places,
    }).format(value);

  /** An ISO instant as the page has always printed it: `2026-09-18 14:03 UTC`. */
  const when = (iso: string) => {
    const at = new Date(iso);
    if (Number.isNaN(at.getTime())) return iso;
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
      `${at.getUTCFullYear()}-${pad(at.getUTCMonth() + 1)}-${pad(at.getUTCDate())} ` +
      `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())} UTC`
    );
  };

  return { action, column, issue, issues, num, when };
}
