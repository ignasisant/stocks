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
 */

import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { Card } from "./ui";

export function TourCard() {
  const t = useT();
  const { setParams } = useRoute();

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
      </div>
    </Card>
  );
}
