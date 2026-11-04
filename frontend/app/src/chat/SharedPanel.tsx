/**
 * A shared answer, as the person who was sent the link reads it.
 *
 * `/?share=<id>` opens the app on its own page — Home by default — with the
 * drawer open on this view: the question, the answer, the charts it drew
 * (inert: a press on a link's chart would act on somebody else's book) and
 * the pages it cited. What follows depends on who is reading:
 *
 * - signed in, it offers to carry on: a thread of the reader's own starts
 *   from the shared exchange, so the next question has it above it;
 * - a guest gets the sign-in, and `?share=` rides the round trip in `next=`,
 *   so they come back to the same answer with the offer to carry on;
 * - the sharer, opening their own link, gets the way to take it down.
 *
 * The frozen copy is the server's (`web/shares.py`): a link outlives the
 * thread it came from, and one taken down reads as gone, not as an error.
 */

import { useEffect, useState } from "react";
import { calendarDay } from "../shell/dates";
import { SignIn } from "../shell/guest";
import { NumbersIn, useLang, useT } from "../shell/i18n";
import { Status } from "../ui/Status";
import { continueShare, readShare, unshare } from "./api";
import { figuresIn } from "./format";
import { Glyph } from "./icons";
import { Inline, Markdown } from "./markdown";
import { Surfaces } from "./Surfaces";
import { Sources } from "./Sources";
import type { SharedAnswer } from "./types";

/**
 * The exchange a link shows: the question as the asker's turn, the answer as
 * the assistant's. The sheet's preview draws the same, so what the sharer
 * sees before sending is what the reader gets.
 */
export function SharedBody({
  share,
  onLeave,
}: {
  share: Pick<SharedAnswer, "question" | "content" | "web" | "activities" | "masked">;
  onLeave: () => void;
}) {
  const t = useT();
  const lang = useLang();
  return (
    <>
      {share.question && (
        <div className="ag-chat-turn ag-chat-mine">
          <div className="ag-chat-bubble">
            <Inline text={share.question} />
          </div>
        </div>
      )}
      <div className="ag-chat-turn ag-chat-assistant">
        <div className="ag-chat-bubble">
          <Markdown text={share.content} />
        </div>
        {share.activities.length > 0 && (
          <NumbersIn lang={figuresIn(share.content, lang)}>
            <Surfaces activities={share.activities} />
          </NumbersIn>
        )}
        {(share.web.length > 0 || share.masked) && (
          <div className="ag-chat-foot">
            {share.web.length > 0 && <Sources web={share.web} onLeave={onLeave} />}
            {share.masked && (
              <span className="ag-chat-share-masked">
                {t("chat.share_masked_note")}
              </span>
            )}
          </div>
        )}
      </div>
    </>
  );
}

export function SharedPanel({
  id,
  signedIn,
  onClose,
  onContinue,
  onLeave,
}: {
  id: string;
  /** A guest is offered the sign-in instead of carrying on. */
  signedIn: boolean;
  /** Back to the drawer's own view (or shut, for a guest). */
  onClose: () => void;
  /** The thread carrying on from this answer was made: open it. */
  onContinue?: (cid: string) => void;
  /** A cited page opened over the drawer, on a phone. */
  onLeave: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [share, setShare] = useState<SharedAnswer | null>(null);
  const [gone, setGone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setShare(null);
    setGone(false);
    readShare(id).then(
      (found) => live && setShare(found),
      () => live && setGone(true),
    );
    return () => {
      live = false;
    };
  }, [id]);

  const carryOn = async () => {
    setBusy(true);
    setFailed(false);
    try {
      const thread = await continueShare(id);
      onContinue?.(thread.id);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const takeDown = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await unshare(id);
      setShare(null);
      setGone(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ag-chat-body ag-chat-shared">
      <div className="ag-chat-scroll">
        <div className="ag-chat-shared-head">
          <span className="ag-chat-locked-label">
            {share?.created
              ? share.by
                ? t("chat.shared_by", {
                    name: share.by,
                    date: calendarDay(share.created, lang),
                  })
                : t("chat.shared_on", { date: calendarDay(share.created, lang) })
              : t("chat.shared_title")}
          </span>
          <button
            type="button"
            className="ag-chat-icon"
            title={t("chat.shared_close")}
            aria-label={t("chat.shared_close")}
            onClick={onClose}
          >
            <Glyph name="close" size={16} />
          </button>
        </div>
        {gone ? (
          <p className="ag-chat-note">{t("chat.shared_gone")}</p>
        ) : share ? (
          <SharedBody share={share} onLeave={onLeave} />
        ) : (
          <Status label={t("common.loading")} />
        )}
      </div>
      {share && (
        <div className="ag-chat-locked-foot">
          {share.mine ? (
            <>
              <p>{t("chat.shared_mine")}</p>
              <button
                type="button"
                className="ag-btn"
                disabled={busy}
                onClick={() => void takeDown()}
              >
                {t("chat.share_stop")}
              </button>
            </>
          ) : signedIn ? (
            <button
              type="button"
              className="ag-btn ag-btn-cta"
              disabled={busy}
              onClick={() => void carryOn()}
            >
              {t("chat.shared_continue")}
            </button>
          ) : (
            <>
              <p>{t("chat.shared_guest")}</p>
              <SignIn className="ag-btn ag-btn-cta" wall="share" />
            </>
          )}
          {failed && (
            <p className="ag-chat-hint" role="alert">
              {t("chat.share_failed")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
