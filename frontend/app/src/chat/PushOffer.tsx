/**
 * "Notify me when it's ready": the chat's offer of Web Push, under an answer
 * that is taking a while.
 *
 * The moment the offer makes sense is the moment the wait is felt, so it
 * appears only after `DELAY_MS` of an answer being written — a quick answer
 * never shows it. And only where pressing it can work: the deployment has a
 * key, this browser can push, permission is not already refused, and this
 * device is not subscribed. "Not now" is kept on this device and the offer
 * does not come back; the Profile's Notifications tab is the way in after.
 *
 * The button is the tap the browser's permission prompt needs, which is why
 * this is an offer to press and not a prompt raised on its own.
 */

import { useEffect, useState } from "react";
import { useLang, useT } from "../shell/i18n";
import {
  type PushState,
  enablePush,
  permission,
  readPush,
  supported,
} from "../shell/push";

const DELAY_MS = 5_000;
const DISMISSED = "ts.push_offer_dismissed";

type Phase = "idle" | "asking" | "done";

function dismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED) === "1";
  } catch {
    return false;
  }
}

function dismiss(): void {
  try {
    window.localStorage.setItem(DISMISSED, "1");
  } catch {
    /* private window: the offer simply comes back next time */
  }
}

export function PushOffer({ busy }: { busy: boolean }) {
  const t = useT();
  const lang = useLang();
  const [state, setState] = useState<PushState | null>(null);
  const [waited, setWaited] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [gone, setGone] = useState(dismissed);

  const eligible =
    !gone && supported() && permission() !== "denied" && !state?.subscribed;

  // Asked once, on the first long wait: nothing is fetched for a reader who
  // never waits, and the answer holds for the rest of the drawer's life.
  useEffect(() => {
    if (!busy || !eligible) {
      setWaited(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setWaited(true);
      if (state === null) readPush().then(setState, () => setGone(true));
    }, DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [busy, eligible, state]);

  useEffect(() => {
    if (phase !== "done") return;
    const timer = window.setTimeout(() => setGone(true), 6_000);
    return () => window.clearTimeout(timer);
  }, [phase]);

  if (phase === "done") {
    return <p className="ag-chat-note">{t("chat.push_offer_done")}</p>;
  }
  if (!waited || !eligible || !state?.configured || !state.key) return null;
  const key = state.key;

  const accept = async () => {
    setPhase("asking");
    try {
      const granted = await enablePush(key, lang.startsWith("es") ? "es" : "en");
      if (granted) {
        setState({ ...state, subscribed: true });
        setPhase("done");
        return;
      }
    } catch {
      /* the Profile's switch says why; here the offer just steps aside */
    }
    dismiss();
    setGone(true);
  };

  const decline = () => {
    dismiss();
    setGone(true);
  };

  return (
    <div className="ag-chat-push">
      <span>{t("chat.push_offer")}</span>
      <div className="ag-guide-acts">
        <button
          type="button"
          className="ag-chat-btn ag-chat-btn-on"
          disabled={phase === "asking"}
          onClick={() => void accept()}
        >
          {t("chat.push_offer_yes")}
        </button>
        <button
          type="button"
          className="ag-chat-btn"
          disabled={phase === "asking"}
          onClick={decline}
        >
          {t("chat.push_offer_no")}
        </button>
      </div>
    </div>
  );
}
