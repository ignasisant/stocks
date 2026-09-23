/**
 * The controls under one of the walkthrough's turns.
 *
 * Only the card for the step the account is *on* carries the ones that move
 * the guide: pressing Next on a card five turns up would walk it backwards,
 * and the reader would never see why. "Take me there" is the exception and
 * stays live on every card — navigating changes nothing about where the guide
 * is, and a thread you cannot re-follow is worse than the modal it replaced,
 * which at least had a Back button.
 *
 * Next takes the reader to the new step's page on a wide screen, the way the
 * Streamlit guide's `advance` does: a card describing Pulse while the reader
 * is still looking at Home is describing something that is not on screen. A
 * phone declines it — there the drawer *is* the viewport, and a jump on every
 * Next would spend the walkthrough reopening it.
 */

import { useT } from "../shell/i18n";
import { canonical } from "../shell/pages";
import { useRoute } from "../shell/router";
import { landing } from "../shell/Tour";
import type { GuideState, GuideStep } from "./guide";

const phone = () =>
  typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 640px)").matches;

export function GuideCard({
  step,
  guide,
  onNext,
  onSkip,
  onLeave,
}: {
  /** The step this card presents. */
  step: GuideStep;
  guide: GuideState;
  onNext: () => Promise<GuideState>;
  onSkip: () => void;
  /** The drawer steps aside for the page on a phone after a jump. */
  onLeave: () => void;
}) {
  const t = useT();
  const { go } = useRoute();
  const live = guide.active && guide.step?.id === step.id;
  const last = guide.index >= guide.of;
  const reachable = step.path !== null || Object.keys(step.session).length > 0;

  const visit = (target: GuideStep) => {
    go(canonical(target.path ?? ""), landing(target));
    if (phone()) onLeave();
  };

  return (
    <div className="ag-guide">
      {live && (
        <p className="ag-guide-progress">
          {step.done !== null && (
            <span className={step.done ? "ag-guide-on" : "ag-guide-off"}>
              {t(step.done ? "tour.active" : "tour.pending")}
            </span>
          )}
          {t("guide.progress", { n: guide.index, total: guide.of })}
        </p>
      )}
      <div className="ag-guide-acts">
        {reachable && (
          <button type="button" className="ag-chat-btn" onClick={() => visit(step)}>
            {t(step.cta_key ?? "guide.goto")}
          </button>
        )}
        {live && (
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-on"
            onClick={async () => {
              const next = await onNext();
              if (next.step && !phone()) visit(next.step);
            }}
          >
            {t(
              last
                ? "guide.finish"
                : step.done !== null
                  ? "guide.done_it"
                  : "guide.next",
            )}
          </button>
        )}
        {live && !last && (
          <button type="button" className="ag-guide-skip" onClick={onSkip}>
            {t("guide.skip")}
          </button>
        )}
      </div>
    </div>
  );
}
