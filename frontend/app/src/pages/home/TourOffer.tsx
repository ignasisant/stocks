/**
 * "Your portfolio is in. Want a quick tour?" — once, after the first import.
 *
 * The welcome a newcomer meets on the way in points at the import and little
 * else: before there is a book, a tour of what the app reads from one is a
 * tour of empty screens. This is the moment it starts to mean something, so
 * the server raises `tour_offer` on the account's first real import
 * (`onboarding.first_book`) and Home asks, in the page rather than over it.
 *
 * "Not now" answers it on the account (`walked`, which also stamps the
 * release: an offer withdrawn on its own would leave the cards the account
 * was spared to fall on its next visit). Starting answers nothing yet: the
 * guide's own end or skip does, so one put away half-way is still on offer
 * the next day. The guide itself stays in Profile, which the caption says.
 */

import { useState, useSyncExternalStore } from "react";

import { send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useSession } from "../../shell/session";
import { isTouring, onTouring } from "../../shell/tourPark";
import { Card } from "./ui";

export function TourOffer() {
  const t = useT();
  const { guest, prefs, reload } = useSession();
  const { setParams } = useRoute();
  const [declined, setDeclined] = useState(false);
  // Asking for a guide that is already up, open or put away in its strip,
  // would be asking twice.
  const touring = useSyncExternalStore(onTouring, isTouring);
  if (guest || !prefs.tour_offer || declined || touring) return null;

  const start = () => setParams({ tour: "1" });
  const decline = () => {
    setDeclined(true);
    // The button that had focus is gone with the card.
    document.getElementById("ag-main")?.focus();
    void send(
      "POST",
      "/onboarding/seen",
      { walked: true },
      { touches: ["/onboarding", "/prefs"] },
    )
      .then(reload)
      // Gone for this visit regardless; a failed write asks once more later.
      .catch(() => undefined);
  };

  return (
    <Card className="hm-offer">
      <div className="hm-offer-copy">
        <h2 className="hm-offer-title">{t("tour.offer_title")}</h2>
        <p className="hm-offer-caption">{t("tour.offer_caption")}</p>
      </div>
      <div className="hm-offer-foot">
        <button type="button" className="ag-tour-quiet" onClick={decline}>
          {t("tour.offer_later")}
        </button>
        <button type="button" className="ag-tour-cta" onClick={start}>
          {t("tour.offer_start")}
        </button>
      </div>
    </Card>
  );
}
