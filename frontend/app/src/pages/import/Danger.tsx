/**
 * The one block every total deletion on this page opens before it can act.
 *
 * Two controls empty the book — "Delete all" beside the figures, and "Empty
 * the portfolio before importing" beside the statement — and both demand the
 * signed-in address typed back, so they share one look and one sentence: what
 * goes, that it does not come back, and the safer control that undoes only the
 * last import, for the reader who reached for the big one by mistake.
 */

import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { Rich } from "./Rich";
import { useVocabulary } from "./text";

export function Danger({
  id,
  total,
  email,
  prompt,
  safer,
  value,
  onChange,
  disabled = false,
  autoFocus = false,
  children,
}: {
  id: string;
  /** Rows the book holds now — what this deletes. */
  total: number;
  email: string;
  /** What typing the address unlocks, already translated. */
  prompt: string;
  /** Point at "Clear the last import": only when there is one to clear. */
  safer: boolean;
  value: string;
  onChange: (typed: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  /** The block's own buttons, beside the field. */
  children?: ReactNode;
}) {
  const t = useT();
  const vocab = useVocabulary();
  return (
    <div aria-labelledby={`${id}-title`} className="im-danger" role="group">
      <p className="im-danger-title" id={`${id}-title`}>
        {vocab.tn("import.wipe_warning", total)}
      </p>
      {safer && <p className="im-danger-safer">{t("import.wipe_safer")}</p>}
      {/* The address itself in the prompt: this account's own, so there is
          nothing to translate and nothing to guess about what to type. */}
      <label className="im-danger-prompt" htmlFor={id}>
        <Rich text={prompt} />
      </label>
      <div className="im-danger-row">
        <input
          autoCapitalize="off"
          autoComplete="off"
          autoFocus={autoFocus}
          className="im-input"
          disabled={disabled}
          id={id}
          onChange={(event) => onChange(event.target.value)}
          placeholder={email}
          spellCheck={false}
          type="text"
          value={value}
        />
        {children}
      </div>
    </div>
  );
}
