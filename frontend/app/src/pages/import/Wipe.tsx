/**
 * "Read this statement as a replacement for the book, not an addition to it."
 *
 * The decision has to precede the preview and not just the write: duplicate
 * flags, split-ratio derivation and the oversell replay all read the prior
 * ledger, so validating against rows that are about to be deleted rejects sells
 * whose "missing" buys are merely doubled. `POST /import/preview` takes `wipe`
 * for exactly that, and does only that with it.
 *
 * On the commit it also empties the book, so it carries the same confirmation
 * `DELETE /v1/portfolio/transactions` demands — the signed-in address, typed
 * back. The two halves travel in one request on purpose: a client that emptied
 * the ledger first and then failed its commit would hold an empty book and no
 * undo. Nothing is deleted until the statement has parsed, validated and
 * produced rows worth writing.
 */

import { useT } from "../../shell/i18n";
import { useAccount } from "../../shell/session";
import { Rich } from "./Rich";

export type WipeChoice = { on: boolean; confirm: string };

export const NO_WIPE: WipeChoice = { on: false, confirm: "" };

export function Wipe({
  total,
  value,
  onChange,
}: {
  /** Rows the book holds now — what this would delete. */
  total: number;
  value: WipeChoice;
  onChange: (next: WipeChoice) => void;
}) {
  const t = useT();
  const me = useAccount();
  const email = me.email ?? "";

  // Nothing to replace, or no address to confirm with (a token session has
  // none): the server would refuse the request, so the page does not offer it.
  if (total === 0 || !email) return null;

  return (
    <div className="im-field">
      <label className="im-check">
        <input
          checked={value.on}
          onChange={(event) => onChange({ on: event.target.checked, confirm: "" })}
          type="checkbox"
        />
        <span>{t("import.wipe_checkbox")}</span>
      </label>

      {value.on && (
        <div className="im-danger">
          <p>
            <Rich text={t("import.clear_all_confirm", { n: total })} />
          </p>
          {/* The address itself as the label: this account's own, so there is
              nothing to translate and nothing to guess about what to type. */}
          <label className="im-label" htmlFor="im-wipe-confirm">
            {email}
          </label>
          <input
            autoCapitalize="off"
            autoComplete="off"
            className="im-input"
            id="im-wipe-confirm"
            onChange={(event) => onChange({ on: true, confirm: event.target.value })}
            placeholder={email}
            spellCheck={false}
            type="text"
            value={value.confirm}
          />
        </div>
      )}
    </div>
  );
}
