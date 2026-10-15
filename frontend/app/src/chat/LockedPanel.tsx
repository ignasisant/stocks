/**
 * What the locked drawer draws once opened (`Locked.tsx`).
 *
 * Its own chunk, like the real `Panel`: the markdown renderer is the weight
 * here, and a guest who never presses the launcher should not pay for it.
 *
 * The sample answer is qualitative on purpose — the demo book's prices move
 * every day, and a figure written into a locale file would be wrong by
 * tomorrow. What it says (one sector, one name heavier than the rest, one
 * currency) stays true of that book for as long as the book is that book.
 */

import { useT } from "../shell/i18n";
import { SignIn } from "../shell/guest";
import { Glyph } from "./icons";
import { Inline, Markdown } from "./markdown";

/** Past this many characters a question is folded to three lines. */
const FOLD = 180;

export default function LockedPanel({
  asked,
  onClose,
}: {
  /** The question a page asked, when one did. */
  asked: string | null;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <>
      <header className="ag-chat-head">
        <span className="ag-chat-locked-title">
          <Glyph name="spark" size={16} />
          {t("chat.title")}
        </span>
        <button
          type="button"
          className="ag-chat-icon"
          title={t("chat.close")}
          aria-label={t("chat.close")}
          onClick={onClose}
        >
          <Glyph name="close" size={18} />
        </button>
      </header>
      <div className="ag-chat-body">
        <div className="ag-chat-scroll">
          <p className="ag-chat-locked-label">{t("chat.guest_sample")}</p>
          <div className="ag-chat-turn ag-chat-mine">
            <div className="ag-chat-bubble">
              <Inline text={t("chat.guest_q")} />
            </div>
          </div>
          <div className="ag-chat-turn ag-chat-assistant">
            <div className="ag-chat-bubble">
              <Markdown text={t("chat.guest_a")} />
            </div>
          </div>
          {asked ? (
            <div className="ag-chat-turn ag-chat-mine">
              <div className="ag-chat-bubble">
                {/* Review's question runs to paragraphs: folded like a long
                    question of the reader's own (`Turn.tsx`). */}
                <div
                  className={asked.length > FOLD ? "ag-chat-fold" : undefined}
                  data-clipped={asked.length > FOLD ? "" : undefined}
                >
                  {asked}
                </div>
              </div>
            </div>
          ) : null}
        </div>
        <div className="ag-chat-locked-foot">
          <p>{t(asked ? "chat.guest_asked" : "chat.guest_lock")}</p>
          <SignIn className="ag-btn ag-btn-cta" wall="chat" />
          <p className="ag-help">{t("home.guest_perk_free")}</p>
        </div>
      </div>
    </>
  );
}
