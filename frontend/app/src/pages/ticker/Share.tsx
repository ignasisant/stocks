/**
 * The header's share button: the page's own link, credited to a ticker share
 * (`medium=ticker`), which unfurls with the symbol's card (`/og/ticker/`).
 *
 * Drawn for a guest too — a page anyone can open is one anyone can pass on.
 * On a phone it goes straight to the device's sheet, where the apps already
 * are; elsewhere, or when that sheet refuses, the dialog with the platforms.
 */

import { useState } from "react";
import { Glyph } from "../../chat/icons";
import { useT } from "../../shell/i18n";
import { clip, nativeFirst, sharedLink } from "../../share/link";
import { ShareDialog } from "../../share/ShareDialog";

export function TickerShare({ ticker, name }: { ticker: string; name?: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const url = sharedLink(`/ticker?ticker=${encodeURIComponent(ticker)}`, "ticker");
  const text = clip(t("ticker.share_text", { name: name || ticker, ticker }));
  const label = t("ticker.share", { ticker });

  return (
    <>
      <button
        type="button"
        className="tk-share"
        title={label}
        aria-label={label}
        aria-haspopup="dialog"
        onClick={() => {
          if (!nativeFirst()) return setOpen(true);
          // Closing the sheet is an answer, not a failure; anything else
          // (no permission, nothing to share to) falls back to the dialog.
          navigator.share({ title: text, text, url }).catch((error: unknown) => {
            if ((error as { name?: string } | null)?.name !== "AbortError")
              setOpen(true);
          });
        }}
      >
        <Glyph name="share" size={16} />
      </button>
      {open ? (
        <ShareDialog
          title={label}
          url={url}
          text={text}
          linkLabel={t("ticker.share_link", { ticker })}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
