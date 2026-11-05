/**
 * Invite a friend: this account's invite link, sent the way any share is.
 *
 * The link is the app's address with the account's invite code as its source
 * (`POST /invite`, `accounts.invite_code`), so a signup it brings is counted
 * for it in `stocks logs shares`. Nothing in it names the account or shows the
 * book, and nothing is promised for sending it: no reward rides on an invite.
 *
 * The code is asked for on the first press, not when the page opens: most
 * readers of this rail never send one, and the first ask writes it.
 */

import { useState } from "react";
import { send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { ShareDialog } from "../../share/ShareDialog";
import { absolute, nativeFirst } from "../../share/link";
import { Card } from "./ui";

type Invite = { code: string; path: string };

export function InviteCard() {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const text = t("profile.invite_text");

  const out = (link: string) => {
    if (!nativeFirst()) return setOpen(true);
    // Closing the phone's sheet is an answer; any other refusal gets the
    // dialog with the platforms instead.
    navigator.share({ title: text, text, url: link }).catch((error: unknown) => {
      if ((error as { name?: string } | null)?.name !== "AbortError") setOpen(true);
    });
  };

  const invite = () => {
    if (url) return out(url);
    setBusy(true);
    setFailed(false);
    send<Invite>("POST", "/invite", undefined, { touches: [] })
      .then((body) => {
        const link = absolute(body.path);
        setUrl(link);
        out(link);
      })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  };

  return (
    <Card>
      <div className="pr-sum">
        <span className="pr-sum-t">{t("profile.invite_title")}</span>
        <span className="pr-sum-note">{t("profile.invite_note")}</span>
        <button
          type="button"
          className="pr-btn pr-selfstart"
          aria-haspopup="dialog"
          disabled={busy}
          onClick={invite}
        >
          {t("profile.invite_send")}
        </button>
        {failed && (
          <span className="pr-sum-note" role="alert">
            {t("chat.share_failed")}
          </span>
        )}
      </div>
      {open && url ? (
        <ShareDialog
          title={t("profile.invite_title")}
          url={url}
          text={text}
          linkLabel={t("profile.invite_link")}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </Card>
  );
}
