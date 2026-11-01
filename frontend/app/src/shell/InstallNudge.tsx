/**
 * "TopStocks as an app": one toast, once per device, never on a first look.
 *
 * A toast rather than a dialog: the reader came for their portfolio, and an
 * offer they did not ask for must not stand between them and it. It waits
 * for the first-load modals (`whenFirstLoadDecided`) and a few seconds of the
 * page, steps aside if a dialog is up, and is stamped asked when shown — a
 * close, a reload or ignoring it are all the same "not now". The Profile's
 * App card keeps the offer for whoever wants it later (`pages/profile`).
 *
 * Chromium gets a button that opens the browser's own dialog; Safari on
 * iPhone and iPad, which has none, gets the two taps to make in the Share
 * sheet. See `shell/install.ts` for which browser is which.
 */

import { useEffect } from "react";

import { useT } from "./i18n";
import {
  VISIT_DAYS,
  asked,
  install,
  markAsked,
  useInstallWay,
  visitDays,
} from "./install";
import { whenFirstLoadDecided } from "./tourPark";
import { toast } from "../ui/toast";

/** After the page has landed, not with it. */
const SETTLE_MS = 8000;

export function InstallNudge() {
  const t = useT();
  const way = useInstallWay();

  useEffect(() => {
    if (!way || asked() || visitDays() < VISIT_DAYS) return;
    let alive = true;
    let timer: number | undefined;
    void whenFirstLoadDecided().then((interrupted) => {
      if (interrupted || !alive) return;
      timer = window.setTimeout(() => {
        // A dialog the reader is answering wins; this waits for the next load.
        if (!alive || document.querySelector('[aria-modal="true"]')) return;
        markAsked();
        if (way === "prompt") {
          toast.stay(t("common.install_nudge"), {
            id: "install",
            detail: t("common.install_nudge_detail"),
            action: {
              label: t("common.install_action"),
              onClick: () => void install(),
            },
          });
        } else {
          toast.stay(t("common.install_nudge_ios"), {
            id: "install",
            detail: t("common.install_nudge_ios_detail"),
          });
        }
      }, SETTLE_MS);
    });
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [way, t]);

  return null;
}
