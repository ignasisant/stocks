/**
 * Sharing one answer by link: what the link would show, then where to send it.
 *
 * The preview comes first and is the server's own cut (`preview: true`), not
 * a guess drawn here: amounts hidden, the proposals and the tables of money
 * gone, the charts inert. "Hide my amounts" starts on — an answer about a
 * portfolio quotes it, and the safe link is the one that needs no thought.
 * Turning it off asks for the other cut, which the preview then shows.
 *
 * Nothing is published until "Create link". The same answer cut the same way
 * is the same link, so pressing it again on an answer already shared shows
 * the link it went out under rather than minting a second one.
 *
 * Then the destinations (`share/ShareOut.tsx`). The URL carries `src=share`,
 * so a signup it leads to is credited (`attribution.py`).
 */

import { useEffect, useState } from "react";
import { useT } from "../shell/i18n";
import { ShareDialog } from "../share/ShareDialog";
import { clip, sharedLink } from "../share/link";
import { Status } from "../ui/Status";
import { shareTurn, unshare } from "./api";
import { SharedBody } from "./SharedPanel";
import type { SharedAnswer, ShareLink } from "./types";

export function shareUrl(id: string): string {
  return sharedLink(`/?share=${encodeURIComponent(id)}`);
}

export function ShareSheet({
  tid,
  links,
  onShared,
  onClose,
}: {
  /** The answer being shared. */
  tid: string;
  /** The links it already went out under (`Message.shares`). */
  links: ShareLink[];
  /** The links changed: the thread keeps them, as the server did. */
  onShared: (links: ShareLink[]) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [masked, setMasked] = useState(true);
  const [preview, setPreview] = useState<SharedAnswer | null>(null);
  const [made, setMade] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // The link this cut already has, if it has one: shown as made.
  const existing = links.find((link) => link.masked === masked)?.id ?? null;
  const link = made ?? existing;

  useEffect(() => {
    let live = true;
    setPreview(null);
    setMade(null);
    setFailed(false);
    shareTurn(tid, { masked, preview: true }).then(
      (cut) => live && setPreview(cut),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [tid, masked]);

  const create = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const share = await shareTurn(tid, { masked });
      setMade(share.id);
      onShared([
        ...links.filter((each) => each.masked !== masked),
        { id: share.id, masked },
      ]);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    const any = links[0]?.id ?? made;
    if (!any) return;
    setBusy(true);
    setFailed(false);
    try {
      await unshare(any);
      setMade(null);
      onShared([]);
      onClose();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  // The sharer's own voice on the question ("I asked TopStocks' AI: …"): on X
  // the card is an image and a domain, so the post's text is all that says
  // what the link is.
  const text = preview?.question
    ? t("chat.share_said", { question: clip(preview.question) })
    : t("chat.share_text");

  return (
    <ShareDialog
      title={t("chat.share_title")}
      url={link ? shareUrl(link) : null}
      text={text}
      onClose={onClose}
      footer={
        links.length > 0 || made ? (
          <button
            type="button"
            className="ag-chat-link ag-share-stop"
            disabled={busy}
            onClick={() => void stop()}
          >
            {t("chat.share_stop")}
          </button>
        ) : null
      }
    >
      <label className="ag-share-mask">
        <input
          type="checkbox"
          checked={masked}
          disabled={busy}
          onChange={(event) => setMasked(event.target.checked)}
        />
        <span>
          {t("chat.share_mask")}
          <span className="ag-chat-hint">{t("chat.share_mask_help")}</span>
        </span>
      </label>

      <div className="ag-share-preview" aria-label={t("chat.share_preview")}>
        {preview ? (
          <SharedBody share={preview} onLeave={onClose} />
        ) : failed ? null : (
          <Status label={t("common.loading")} />
        )}
      </div>

      {failed && (
        <p className="ag-chat-hint" role="alert">
          {t("chat.share_failed")}
        </p>
      )}

      {link ? null : (
        <button
          type="button"
          className="ag-btn ag-btn-cta ag-share-make"
          disabled={busy || !preview}
          onClick={() => void create()}
        >
          {t("chat.share_create")}
        </button>
      )}
    </ShareDialog>
  );
}
