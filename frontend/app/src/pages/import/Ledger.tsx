/**
 * What the book holds, and the one control that can empty it.
 *
 * `DELETE /v1/portfolio/transactions` removes every transaction — every import,
 * and every row typed in by hand years ago — takes no backup and cannot be
 * undone, which is why it is the only route on this page that demands the
 * signed-in address typed back. The control therefore opens something before it
 * can act, and the address is the thing that arms it: a tick nobody reads is
 * not a confirmation.
 *
 * `DELETE /import/last` is what almost every reader wants instead, and it lives
 * beside the last-import note where the batch it removes is named.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useAccount } from "../../shell/session";
import type { Query } from "../../shell/useApi";
import { wipeLedger } from "./api";
import type { Book } from "./api";
import { names } from "./repairs";
import { Rich } from "./Rich";
import { useVocabulary } from "./text";

export function Ledger({ book, onWiped }: { book: Query<Book>; onWiped: () => void }) {
  const t = useT();
  const vocab = useVocabulary();
  const me = useAccount();
  const [cleared, setCleared] = useState(false);

  return (
    <section className="im-ledger">
      {cleared && <p className="im-ok">{t("import.toast_cleared")}</p>}
      <Loaded query={book} skeleton={<Skeleton rows={1} />}>
        {(held) => (
          <>
            <div className="im-ledger-head">
              <p className="im-metric">
                <span className="im-metric-label">{t("import.metric_in_ledger")}</span>
                <span className="im-metric-value">{vocab.num(held.total, 0)}</span>
              </p>
              {/* No address, no confirmation anybody could type — and a control
                  that cannot be armed is worse than one that is not offered.
                  A token session is the case: it has no email. */}
              {held.total > 0 && me.email ? (
                <ClearAll
                  email={me.email}
                  total={held.total}
                  onWiped={() => {
                    setCleared(true);
                    onWiped();
                  }}
                />
              ) : null}
            </div>
            {/* Not a warning: on this page the demo book is on its way out, and
                what the reader needs to know is that importing is what removes
                it. */}
            {held.demo > 0 && (
              <p className="im-help">
                {t("import.demo_rows_caption", { n: held.demo })}
              </p>
            )}
          </>
        )}
      </Loaded>
    </section>
  );
}

function ClearAll({
  email,
  total,
  onWiped,
}: {
  email: string;
  total: number;
  onWiped: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!open) {
    return (
      <button className="ag-btn" onClick={() => setOpen(true)} type="button">
        {t("import.clear_all_imports")}
      </button>
    );
  }

  const wipe = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await wipeLedger(typed.trim());
      setOpen(false);
      setTyped("");
      onWiped();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="im-danger" role="group">
      <p>
        <Rich text={t("import.clear_all_confirm", { n: total })} />
      </p>
      {/* The address itself as the label: it is this account's own, so there is
          nothing to translate and nothing to guess about what to type. */}
      <label className="im-label" htmlFor="im-wipe">
        {email}
      </label>
      <input
        autoCapitalize="off"
        autoComplete="off"
        autoFocus
        className="im-input"
        disabled={busy}
        id="im-wipe"
        onChange={(event) => setTyped(event.target.value)}
        placeholder={email}
        spellCheck={false}
        type="text"
        value={typed}
      />
      {failed && <p className="im-bad">{t("common.failed")}</p>}
      <div className="im-row">
        <button
          className="ag-btn"
          disabled={busy}
          onClick={() => {
            setOpen(false);
            setTyped("");
            setFailed(false);
          }}
          type="button"
        >
          {t("common.cancel")}
        </button>
        <button
          className="ag-btn im-destructive"
          disabled={busy || !names(typed, email)}
          onClick={wipe}
          type="button"
        >
          {t("import.delete_everything")}
        </button>
      </div>
    </div>
  );
}
