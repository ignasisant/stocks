/**
 * "How is TopStocks for you?": five stars and an optional comment, asked once
 * per account, ever.
 *
 * Never on a first look. It waits for the `VISIT_DAYS`th day this browser
 * opened the app (`shell/rate.ts`), for the first-load modals
 * (`whenFirstLoadDecided`), and for half a minute of the page — the reader came
 * for their portfolio, and the question is fair only once they have had it.
 * A dialog already up wins, and so does the profile nudge if it asked on this
 * load (`claimNudge`); so does a field the reader is typing in.
 *
 * Stamped when shown, not when answered (`rate_prompt_done`, an account pref):
 * "Not now", Escape, the scrim, a reload or closing the tab are all the answer.
 * A one-time question that asks again whenever it was ignored is a nag.
 *
 * One star is enough to send. The box under the stars asks what to fix after a
 * low score and what works after a high one; it is optional either way.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { send } from "./api";
import { Icon } from "./Icon";
import { useLang, useT } from "./i18n";
import { asked, followUp, markAsked, recordVisit, VISIT_DAYS } from "./rate";
import { useRoute } from "./router";
import { useSession } from "./session";
import { claimNudge, whenFirstLoadDecided } from "./tourPark";
import { useDialog } from "./useDialog";
import { useExitGhost } from "./useSheet";
import { toast } from "../ui/toast";

/** After the reader has looked at the page, not as it lands. */
const SETTLE_MS = 30_000;

/** The store's ceiling (`web/feedback.MAX_CHARS`). */
const MAX = 4000;

const SCORES = [1, 2, 3, 4, 5] as const;

const TYPING =
  "input, textarea, select, [contenteditable]:not([contenteditable='false'])";

export function RatePrompt() {
  const { prefs, reload } = useSession();
  const done = Boolean(prefs.rate_prompt_done);
  const [open, setOpen] = useState(false);
  // Read through a ref: a session refetch hands out a new `reload`, and
  // restarting the half-minute wait on every refetch would mean never asking.
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  useEffect(() => {
    if (done || asked() || recordVisit() < VISIT_DAYS) return;
    let alive = true;
    let timer: number | undefined;
    void whenFirstLoadDecided().then((interrupted) => {
      if (interrupted || !alive) return;
      timer = window.setTimeout(() => {
        if (!alive || document.querySelector('[aria-modal="true"]')) return;
        // Mid-sentence in the chat or a form is a task, not a pause: skip this
        // load rather than take the keyboard away. Nothing is stamped, so the
        // next load asks instead.
        if (document.activeElement?.matches(TYPING)) return;
        if (!claimNudge()) return;
        markAsked();
        setOpen(true);
        void send(
          "PATCH",
          "/prefs",
          { rate_prompt_done: true },
          { touches: ["/prefs"] },
        )
          .then(() => reloadRef.current())
          // The local stamp above already stops this browser asking again.
          .catch(() => undefined);
      }, SETTLE_MS);
    });
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [done]);

  return open ? <Dialog onDone={() => setOpen(false)} /> : null;
}

function Dialog({ onDone }: { onDone: () => void }) {
  const t = useT();
  const lang = useLang();
  const { page } = useRoute();
  const [stars, setStars] = useState(0);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<"pick" | "failed" | null>(null);
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const radios = useRef<(HTMLButtonElement | null)[]>([]);
  useExitGhost(scrim);
  useDialog(card);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onDone();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  function pick(score: number) {
    setStars(score);
    setProblem(null);
  }

  // A radio group: the arrows move the score and the focus with it.
  function onArrow(event: KeyboardEvent<HTMLDivElement>) {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = Math.min(5, Math.max(1, (stars || (step > 0 ? 0 : 6)) + step));
    pick(next);
    radios.current[next - 1]?.focus();
  }

  function submit() {
    if (!stars) {
      setProblem("pick");
      return;
    }
    setBusy(true);
    setProblem(null);
    send(
      "POST",
      "/feedback/rating",
      { stars, text: text.trim(), page, lang },
      { touches: [] },
    )
      .then(() => {
        onDone();
        toast.ok(t("feedback.sent"));
      })
      // Kept open with the score and the words: the reader answered, and a
      // failed send must not throw that away.
      .catch(() => setProblem("failed"))
      .finally(() => setBusy(false));
  }

  return (
    <div ref={scrim} className="ag-tour-scrim" role="presentation" onClick={onDone}>
      <div
        ref={card}
        tabIndex={-1}
        className="ag-tour ag-rate"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ag-rate-h"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="ag-rate-h" className="ag-tour-h">
          {t("feedback.rate_title")}
        </h2>
        <p className="ag-tour-intro">{t("feedback.rate_intro")}</p>
        <div
          className="ag-rate-stars"
          role="radiogroup"
          aria-label={t("feedback.rate_title")}
          onKeyDown={onArrow}
        >
          {SCORES.map((score) => (
            <button
              key={score}
              ref={(node) => {
                radios.current[score - 1] = node;
              }}
              type="button"
              role="radio"
              aria-checked={stars === score}
              aria-label={t("feedback.rate_star", { n: score })}
              // Roving focus: Tab lands on the picked star, or the first.
              tabIndex={stars ? (stars === score ? 0 : -1) : score === 1 ? 0 : -1}
              className="ag-rate-star"
              data-on={score <= stars ? "" : undefined}
              onClick={() => pick(score)}
            >
              <Icon name="star" size={32} />
            </button>
          ))}
        </div>
        {stars ? (
          <textarea
            className="ag-fb-text ag-rate-text"
            rows={3}
            maxLength={MAX}
            value={text}
            aria-label={t(`feedback.${followUp(stars)}`)}
            placeholder={t(`feedback.${followUp(stars)}`)}
            onChange={(event) => setText(event.target.value)}
          />
        ) : null}
        {problem ? (
          <p className="ag-fb-bad" role="alert">
            {t(problem === "pick" ? "feedback.rate_pick" : "feedback.failed")}
          </p>
        ) : null}
        <footer className="ag-tour-foot">
          <button type="button" className="ag-tour-quiet" onClick={onDone}>
            {t("feedback.rate_later")}
          </button>
          <button
            type="button"
            className="ag-tour-cta"
            disabled={busy}
            onClick={submit}
          >
            {t("feedback.rate_send")}
          </button>
        </footer>
      </div>
    </div>
  );
}
