/**
 * The operator's answer to something this reader sent through Feedback,
 * shown once (`stocks feedback-reply`, `routes/feedback.replies`).
 *
 * A toast that stays, not a dialog: the reader came for their portfolio, and
 * the answer is a sentence they can close. Asked only after the first-load
 * modals have decided, so it never sits on the boot path, and it takes the
 * load's one nudge (`claimNudge`) so the rating prompt does not follow it.
 *
 * Stamped when shown, like the rating prompt: a reload or a closed tab is
 * still an answer given, and one shown again on every load would be a nag.
 */

import { useEffect, useRef } from "react";

import { get, send } from "./api";
import { useLang, useT } from "./i18n";
import { claimNudge, whenFirstLoadDecided } from "./tourPark";
import { toast } from "../ui/toast";

/** After the page has landed, not with it. */
const SETTLE_MS = 4000;

/** "2026-11-10T09-12-33Z" as the reader's day and month; "" when unreadable. */
export function aboutDay(stamp: string, lang: string): string {
  const [, year, month, day] = /^(\d{4})-(\d{2})-(\d{2})T/.exec(stamp) ?? [];
  if (!year || !month || !day) return "";
  const date = new Date(Date.UTC(+year, +month - 1, +day));
  return new Intl.DateTimeFormat(lang, {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(date);
}

export function FeedbackReply() {
  const t = useT();
  const lang = useLang();
  // Read through refs: `useT` hands out a new function every render, and
  // restarting the wait on each would mean never asking.
  const words = useRef({ t, lang });
  words.current = { t, lang };

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    void whenFirstLoadDecided().then((interrupted) => {
      if (interrupted || !alive) return;
      timer = window.setTimeout(() => {
        void get("/feedback/replies")
          .then((replies) => {
            if (!alive || !replies.length || !claimNudge()) return;
            const { t, lang } = words.current;
            for (const reply of replies) {
              toast.stay(
                t("feedback.reply_title", { date: aboutDay(reply.about, lang) }),
                {
                  id: `reply-${reply.id}`,
                  detail: reply.text,
                },
              );
            }
            return send(
              "POST",
              "/feedback/replies/seen",
              { ids: replies.map((reply) => reply.id) },
              { touches: [] },
            );
          })
          // Nothing to show is the usual answer; a failed ask waits for the
          // next load.
          .catch(() => undefined);
      }, SETTLE_MS);
    });
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, []);

  return null;
}
