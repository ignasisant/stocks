/**
 * Sharing the page's own link, credited to a ticker share (`medium=ticker`),
 * which unfurls with the symbol's card (`/og/ticker/`).
 *
 * `useTickerShare` is the act, so the header's "More" menu can offer it as a
 * row; `TickerShare` is the icon a guest gets in its place — a page anyone can
 * open is one anyone can pass on, and a menu of one row is no menu.
 * On a phone it goes straight to the device's sheet, where the apps already
 * are; elsewhere, or when that sheet refuses, the dialog with the platforms.
 */

import { type ReactNode, useState } from "react";
import { Glyph } from "../../chat/icons";
import { useT } from "../../shell/i18n";
import { clip, nativeFirst, sharedLink } from "../../share/link";
import { ShareDialog } from "../../share/ShareDialog";

export function useTickerShare(
  ticker: string,
  name?: string,
): { label: string; share: () => void; dialog: ReactNode } {
  const t = useT();
  const [open, setOpen] = useState(false);
  const url = sharedLink(`/ticker?ticker=${encodeURIComponent(ticker)}`, "ticker");
  const text = clip(t("ticker.share_text", { name: name || ticker, ticker }));
  const label = t("ticker.share", { ticker });

  const share = () => {
    if (!nativeFirst()) return setOpen(true);
    // Closing the sheet is an answer, not a failure; anything else
    // (no permission, nothing to share to) falls back to the dialog.
    navigator.share({ title: text, text, url }).catch((error: unknown) => {
      if ((error as { name?: string } | null)?.name !== "AbortError") setOpen(true);
    });
  };

  const dialog = open ? (
    <ShareDialog
      title={label}
      url={url}
      text={text}
      linkLabel={t("ticker.share_link", { ticker })}
      onClose={() => setOpen(false)}
    />
  ) : null;

  return { label, share, dialog };
}

export function TickerShare({ ticker, name }: { ticker: string; name?: string }) {
  const { label, share, dialog } = useTickerShare(ticker, name);
  return (
    <>
      <button
        type="button"
        className="tk-icon"
        title={label}
        aria-label={label}
        aria-haspopup="dialog"
        onClick={share}
      >
        <Glyph name="share" size={18} />
      </button>
      {dialog}
    </>
  );
}
