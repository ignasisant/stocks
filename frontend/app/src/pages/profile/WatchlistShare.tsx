/**
 * Share the watchlist as it is shown — the search and the group filter
 * applied — as a list of symbols at `/?share=<id>`.
 *
 * The sheet shows exactly what the link will (`SharedList`, the reader's own
 * view) before anything is published, and under what name: a single group
 * picked in the filter names it, and the field can rename it. Only the
 * symbols and that name go out — no amounts, no labels typed on a row, no
 * other groups (`web/shares.py`). The reader follows it whole, under that
 * name. Once the link is made the name is fixed: another name is another link.
 */

import { useState } from "react";
import { Glyph } from "../../chat/icons";
import { shareList } from "../../chat/api";
import { SharedList } from "../../chat/SharedPanel";
import { useT } from "../../shell/i18n";
import { ShareDialog } from "../../share/ShareDialog";
import { clip, sharedLink } from "../../share/link";

/** The most a link carries (`shares.LIST_MAX`); the sheet says so past it. */
const LIST_MAX = 50;

export function WatchlistShare({
  tickers,
  title,
}: {
  tickers: string[];
  title: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="pr-btn pr-wshare"
        aria-haspopup="dialog"
        disabled={tickers.length === 0}
        onClick={() => setOpen(true)}
      >
        <Glyph name="share" size={14} />
        {t("watchlist.share")}
      </button>
      {open && (
        <ListSheet tickers={tickers} title={title} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

function ListSheet({
  tickers,
  title,
  onClose,
}: {
  tickers: string[];
  title: string;
  onClose: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(title);
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const going = tickers.slice(0, LIST_MAX);
  const text = clip(
    name.trim()
      ? t("watchlist.share_text_named", { name: name.trim() })
      : t("watchlist.share_text"),
  );

  const make = () => {
    setBusy(true);
    setFailed(false);
    shareList(going, name.trim())
      .then((share) =>
        setLink(sharedLink(`/?share=${encodeURIComponent(share.id)}`, "watchlist")),
      )
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  };

  return (
    <ShareDialog
      title={t("watchlist.share_title")}
      url={link}
      text={text}
      linkLabel={t("watchlist.share_link")}
      onClose={onClose}
      footer={
        link ? null : (
          <div className="pr-wshare-foot">
            <button
              type="button"
              className="ag-btn ag-btn-cta"
              disabled={busy}
              onClick={make}
            >
              {t("watchlist.share_make")}
            </button>
            {failed && (
              <span className="pr-hint" role="alert">
                {t("chat.share_failed")}
              </span>
            )}
          </div>
        )
      }
    >
      <label className="pr-wshare-name">
        <span className="pr-hint">{t("watchlist.share_name")}</span>
        <input
          className="pr-input"
          maxLength={60}
          value={name}
          disabled={link !== null}
          placeholder={t("chat.shared_list_title")}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <p className="pr-hint">
        {tickers.length > LIST_MAX
          ? t("watchlist.share_note_cut", { n: LIST_MAX })
          : t("watchlist.share_note")}
      </p>
      <div className="pr-wshare-preview">
        <SharedList share={{ title: name.trim(), tickers: going }} onLeave={onClose} />
      </div>
    </ShareDialog>
  );
}
