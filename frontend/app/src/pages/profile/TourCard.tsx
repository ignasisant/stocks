/**
 * The walkthrough, offered by hand.
 *
 * The tour auto-opens once, and after that only for a release the account has
 * not seen. This card is the entry point for everybody else — the Streamlit
 * page keeps it in the same place, the Preferences rail, because that is where
 * a returning reader goes looking for it.
 *
 * Nothing here draws the tour. The shell owns it and reads `?tour=` off the
 * URL (`?tour=1` from the top, `?tour=<step id>` onto one step), which is also
 * the deep link a shared URL carries — so starting it is writing that
 * parameter and letting the shell notice.
 *
 * Under the button, how much of the app is switched on: the capabilities
 * `onboarding.setup_state` counts (the Home setup card's list), as a bar and a
 * "2/4" — the same line the Streamlit card draws, off the same `/onboarding`
 * read. A failed read draws no bar rather than a wrong one.
 */

import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Card } from "./ui";

/** The one field of `GET /onboarding` this card reads. */
type Setup = { setup: Record<string, boolean> };

/** Capabilities on, and of how many — null when there is nothing to count. */
export function progress(setup: Record<string, boolean>): [number, number] | null {
  const states = Object.values(setup);
  if (!states.length) return null;
  return [states.filter(Boolean).length, states.length];
}

export function TourCard() {
  const t = useT();
  const { setParams } = useRoute();
  const onboarding = useApi(() => get<Setup>("/onboarding"), []);
  const counted =
    onboarding.state === "loaded" ? progress(onboarding.data.setup) : null;

  const start = () => {
    // Not a navigation: the tour is a modal over this page, and the back
    // button should not have to walk through opening one.
    setParams({ tour: "1" });
  };

  return (
    <Card>
      <div className="pf-sum">
        <span className="pf-sum-t">{t("tour.launch")}</span>
        <span className="pf-sum-note">{t("tour.launch_caption")}</span>
        <button type="button" className="pf-btn pf-btn-p pf-selfstart" onClick={start}>
          {t("tour.launch_start")}
        </button>
        {counted && (
          <div
            className="pf-prog"
            role="progressbar"
            aria-label={t("home.setup_progress", {
              done: counted[0],
              total: counted[1],
            })}
            aria-valuemin={0}
            aria-valuemax={counted[1]}
            aria-valuenow={counted[0]}
          >
            <div className="pf-prog-track">
              <div
                className="pf-prog-fill"
                style={{ width: `${Math.round((counted[0] / counted[1]) * 100)}%` }}
              />
            </div>
            <span className="pf-prog-n">
              {counted[0]}/{counted[1]}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}
