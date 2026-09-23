/**
 * Erasing the account, behind a dialog and behind the account's own name.
 *
 * Two things make this different from every other control on the page. It is
 * not autosaved — a destructive control opens something before it can do
 * anything, which is where the Streamlit page puts it too. And it is not
 * confirmed by a tick: `DELETE /account` wants the signed-in address typed
 * back, so the request names the account it erases rather than merely asking
 * for one. A 422 means the address did not match and nothing was removed.
 *
 * Afterwards the browser is sent to the path the response carries. The data is
 * gone but the cookie is not — it belongs to the Streamlit sign-in the whole
 * deployment shares — and only a real navigation gets it cleared, which is why
 * this is `location.assign` and not a fetch.
 */

import { useEffect, useState } from "react";
import { ApiError, NotSignedIn, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useAccount } from "../../shell/session";
import { Failure, Prose, Row } from "./ui";

/** `DELETE /account` — `routes.account.Erased`. */
type Erased = { ok: boolean; sign_out: string };

/** Same shape the server compares: trimmed, case-folded. */
function names(typed: string, email: string): boolean {
  return typed.trim().toLowerCase() === email.trim().toLowerCase() && email !== "";
}

function Dialog({ email, onClose }: { email: string; onClose: () => void }) {
  const t = useT();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const armed = names(typed, email);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const erase = () => {
    setBusy(true);
    setRefused(null);
    send<Erased>("DELETE", "/account", { confirm: typed.trim() }).then(
      (done) => {
        // A path on this deployment and nothing else: "//elsewhere" is a URL
        // the browser reads as another origin, and a sign-out that a response
        // body could aim off-site would be an open redirect wearing a
        // logout's clothes.
        const path = done.sign_out;
        const to =
          path.startsWith("/") && !path.startsWith("//") ? path : "/auth/logout";
        window.location.assign(to);
      },
      (error: unknown) => {
        setBusy(false);
        if (error instanceof NotSignedIn) {
          // Nothing left to delete from here, and nothing to say about it.
          window.location.assign("/auth/logout");
          return;
        }
        // 422 is the one refusal the reader can act on — the address did not
        // match — and the server's sentence names it better than a generic
        // one would. Every other failure is the deletion itself failing, and
        // the catalog words that in the reader's language.
        setRefused(
          error instanceof ApiError && error.status === 422
            ? error.detail
            : error instanceof ApiError
              ? t("profile.delete_failed")
              : t("common.offline"),
        );
      },
    );
  };

  return (
    <div
      className="pf-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        className="pf-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label={t("profile.delete_title")}
      >
        <h2 className="pf-modal-t">{t("profile.delete_title")}</h2>
        {/* The honest list of what goes, straight from the catalog. */}
        <Prose text={t("profile.delete_body")} />
        <label className="pf-modal-confirm">
          <span className="pf-hint">{t("profile.delete_confirm")}</span>
          <input
            className="pf-input pf-input-wide"
            type="text"
            // The first thing to do in this dialog, and the only thing that
            // arms the button — a keyboard reader starts here rather than on
            // a control that is disabled until they have typed.
            autoFocus
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            // The address itself, as the thing to type. It is this account's
            // own, not copy: nothing to translate and nothing to guess.
            placeholder={email}
            value={typed}
            disabled={busy}
            onChange={(event) => setTyped(event.target.value)}
          />
        </label>
        <Failure message={refused} />
        <div className="pf-modal-foot">
          <button type="button" className="pf-btn" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-danger"
            disabled={!armed || busy}
            onClick={erase}
          >
            {t("profile.delete_button")}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The row that opens it.
 *
 * Always offered: whether this account *may* be erased is the server's to
 * answer — it refuses the owner and the shared guest directory with a 403 —
 * and a client that guessed at that rule would be a second copy of it.
 */
export function DeleteAccount() {
  const t = useT();
  const me = useAccount();
  const [open, setOpen] = useState(false);

  return (
    <Row
      label={t("profile.delete_row_title")}
      help={t("profile.delete_row_help")}
      middle
    >
      <button type="button" className="pf-btn" onClick={() => setOpen(true)}>
        {t("profile.delete_open")}
      </button>
      {open && <Dialog email={me.email ?? ""} onClose={() => setOpen(false)} />}
    </Row>
  );
}
