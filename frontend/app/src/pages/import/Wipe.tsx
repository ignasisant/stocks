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
 *
 * The block has no button of its own: the address arms "Confirm", and the
 * confirm bar says so while it is missing.
 */

import { useT } from "../../shell/i18n";
import { useAccount } from "../../shell/session";
import { Danger } from "./Danger";

export type WipeChoice = { on: boolean; confirm: string };

export const NO_WIPE: WipeChoice = { on: false, confirm: "" };

export function Wipe({
  total,
  hasLast,
  value,
  onChange,
}: {
  /** Rows the book holds now — what this would delete. */
  total: number;
  /** A last import exists, so the block can point at undoing only that. */
  hasLast: boolean;
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
    <>
      <label className="im-check">
        <input
          checked={value.on}
          onChange={(event) => onChange({ on: event.target.checked, confirm: "" })}
          type="checkbox"
        />
        <span>
          {t("import.wipe_short")}{" "}
          <span className="im-faint">· {t("import.wipe_short_note")}</span>
        </span>
      </label>

      {value.on && (
        <Danger
          email={email}
          id="im-wipe-confirm"
          onChange={(typed) => onChange({ on: true, confirm: typed })}
          prompt={t("import.wipe_type_commit", { email })}
          safer={hasLast}
          total={total}
          value={value.confirm}
        />
      )}
    </>
  );
}
