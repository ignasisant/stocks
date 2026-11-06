/**
 * A shared answer, as the person who was sent the link reads it.
 *
 * `/?share=<id>` opens the app on its own page — Home by default — with the
 * drawer open on this view: the thread's earlier exchanges, then the
 * question, the lens and the bull and bear cases above the answer as the
 * sharer saw them, the answer, the charts it drew (inert: a press on a link's
 * chart would act on somebody else's book) and the pages it cited. What
 * follows depends on who is reading:
 *
 * - signed in, it offers to carry on: a thread of the reader's own starts
 *   from the shared thread, so the next question has all of it above it;
 * - a guest gets the same "Keep asking", as a sign-in whose `next=` is this
 *   answer with `&continue=1`: they come back to it and the thread is
 *   started for them (`carryOnNow`), so the press they made is the one that
 *   happens. Under it, the way to import a statement instead;
 * - the sharer, opening their own link, gets the way to take it down.
 *
 * A shared list of tickers (`kind` "watchlist") draws the same way with the
 * list for a body, and "Follow all" in place of "Keep asking": it puts the
 * symbols on the reader's watchlist under the list's name. A guest's press
 * goes through the same sign-in and `continue=1`.
 *
 * The frozen copy is the server's (`web/shares.py`): a link outlives the
 * thread it came from, and one taken down reads as gone, not as an error.
 */

import { useEffect, useRef, useState } from "react";
import { calendarDay } from "../shell/dates";
import { Link } from "../shell/router";
import { TickerCell } from "../shell/tickers";
import { signInHref } from "../shell/guest";
import { NumbersIn, useLang, useT } from "../shell/i18n";
import { useSignIn } from "../shell/session";
import { Status } from "../ui/Status";
import { continueShare, followShare, readShare, unshare } from "./api";
import { Debate } from "./Debate";
import { figuresIn, skillName } from "./format";
import { Glyph } from "./icons";
import { Inline, Markdown } from "./markdown";
import { Surfaces } from "./Surfaces";
import { Sources } from "./Sources";
import type { SharedAnswer, SharedTurn } from "./types";

/**
 * The thread a link shows: the exchanges before the shared answer, then the
 * shared one, each question as the asker's turn and each answer as the
 * assistant's. The sheet's preview draws the same, so what the sharer sees
 * before sending is what the reader gets.
 */
export function SharedBody({
  share,
  onLeave,
}: {
  share: SharedTurn & Pick<SharedAnswer, "masked"> & { turns?: SharedTurn[] };
  onLeave: () => void;
}) {
  return (
    <>
      {(share.turns ?? []).map((turn, i) => (
        <Exchange key={i} turn={turn} masked={false} onLeave={onLeave} />
      ))}
      <Exchange turn={share} masked={share.masked} onLeave={onLeave} />
    </>
  );
}

/** One question and its answer; the note on hidden amounts goes under the
 *  last answer only, once for the whole link. */
function Exchange({
  turn,
  masked,
  onLeave,
}: {
  turn: SharedTurn;
  masked: boolean;
  onLeave: () => void;
}) {
  const t = useT();
  const lang = useLang();
  // The reader has no catalog of the sharer's skills: the label or the id.
  const lens = turn.skills.length
    ? t("chat.lens", { skills: turn.skills.map((id) => skillName(t, id)).join(" · ") })
    : "";
  return (
    <>
      {turn.question && (
        <div className="ag-chat-turn ag-chat-mine">
          <div className="ag-chat-bubble">
            <Inline text={turn.question} />
          </div>
        </div>
      )}
      <div className="ag-chat-turn ag-chat-assistant">
        {lens && <span className="ag-chat-lens">{lens}</span>}
        {turn.debate.length > 0 && <Debate sides={turn.debate} />}
        <div className="ag-chat-bubble">
          <Markdown text={turn.content} />
        </div>
        {turn.activities.length > 0 && (
          <NumbersIn lang={figuresIn(turn.content, lang)}>
            <Surfaces activities={turn.activities} />
          </NumbersIn>
        )}
        {(turn.web.length > 0 || masked) && (
          <div className="ag-chat-foot">
            {turn.web.length > 0 && <Sources web={turn.web} onLeave={onLeave} />}
            {masked && (
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

/**
 * A shared list: its name, then each symbol with its logo and company, each a
 * link to its page. The sharer's preview draws the same.
 */
export function SharedList({
  share,
  onLeave,
}: {
  share: Pick<SharedAnswer, "title" | "tickers">;
  onLeave: () => void;
}) {
  const t = useT();
  return (
    <div
      className="ag-chat-shared-list"
      // A symbol opens its page under the drawer; on a phone it has to go.
      onClickCapture={(event) => {
        if ((event.target as Element).closest("a")) onLeave();
      }}
    >
      <h3 className="ag-chat-shared-list-title">
        {share.title || t("chat.shared_list_title")}
        <span className="ag-chat-shared-list-n">{share.tickers.length}</span>
      </h3>
      <ul>
        {share.tickers.map((ticker) => (
          <li key={ticker}>
            <TickerCell ticker={ticker} className="ag-chat-tick" />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Where a guest's two presses sign in to: back to this answer with the thread
 * to be started (`continue=1`), or to the importer. `src=share` rides along
 * so the signup is credited to the link even from the importer; `share=` only
 * on the first, since on the importer it would open the drawer over it.
 */
export function guestHrefs(
  login: string | null,
  id: string,
  here: Pick<Location, "pathname"> = window.location,
): { keep: string; importer: string } | null {
  if (!login) return null;
  const at = (pathname: string, search: string) =>
    signInHref(login, { pathname, search } as Location, "share") ?? "";
  return {
    keep: at(here.pathname, `?share=${encodeURIComponent(id)}&src=share&continue=1`),
    importer: at("/import", "?src=share"),
  };
}

/** Whether the thread starts unasked: only for a reader who asked for it
 *  before signing in, once the answer is read, and never on their own link. */
export function carriesOn(
  asked: boolean,
  signedIn: boolean,
  share: Pick<SharedAnswer, "mine"> | null,
): boolean {
  return asked && signedIn && share !== null && !share.mine;
}

export function SharedPanel({
  id,
  signedIn,
  carryOnNow = false,
  onClose,
  onContinue,
  onLeave,
}: {
  id: string;
  /** A guest is offered the sign-in instead of carrying on. */
  signedIn: boolean;
  /** Start the reader's thread as soon as the answer is read (a guest's
   *  "Keep asking", back from the sign-in). Never on the sharer's own link. */
  carryOnNow?: boolean;
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
  /** The symbols "Follow all" added; null until it was pressed. */
  const [followed, setFollowed] = useState<string[] | null>(null);
  const hrefs = guestHrefs(useSignIn(), id);
  const list = share?.kind === "watchlist";
  const carried = useRef(false);

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
      if (list) {
        setFollowed((await followShare(id)).added);
      } else {
        const thread = await continueShare(id);
        onContinue?.(thread.id);
      }
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!carriesOn(carryOnNow, signedIn, share) || carried.current) return;
    carried.current = true;
    void carryOn();
  }, [carryOnNow, signedIn, share]);

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
              : t(list ? "chat.shared_list_title" : "chat.shared_title")}
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
        ) : share && list ? (
          <SharedList share={share} onLeave={onLeave} />
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
          ) : followed !== null ? (
            <>
              <p role="status">
                {followed.length === 0
                  ? t("chat.shared_followed_none")
                  : followed.length === 1
                    ? t("chat.shared_followed_one")
                    : t("chat.shared_followed_n", { n: followed.length })}
              </p>
              {/* Opens under the drawer; on a phone the drawer has to go. */}
              <span style={{ display: "contents" }} onClickCapture={onLeave}>
                <Link page="profile" params={{ tab: "watch" }} className="ag-btn">
                  {t("chat.shared_followed_open")}
                </Link>
              </span>
            </>
          ) : signedIn ? (
            <button
              type="button"
              className="ag-btn ag-btn-cta"
              disabled={busy}
              onClick={() => void carryOn()}
            >
              {t(list ? "chat.shared_follow" : "chat.shared_continue")}
            </button>
          ) : hrefs ? (
            <>
              <p>{t(list ? "chat.shared_list_guest" : "chat.shared_guest")}</p>
              <a className="ag-btn ag-btn-cta" href={hrefs.keep}>
                {t(list ? "chat.shared_follow" : "chat.shared_continue")}
              </a>
              <p className="ag-chat-hint">{t("chat.shared_guest_free")}</p>
              <a className="ag-chat-shared-import" href={hrefs.importer}>
                {t("chat.shared_guest_import")}
              </a>
            </>
          ) : null}
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
