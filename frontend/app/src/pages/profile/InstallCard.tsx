/**
 * The Preferences tab's install row: MyBrainStock on this device.
 *
 * The standing half of the shell's one-time nudge (`shell/InstallNudge.tsx`):
 * drawn only where there is something to do — a Chromium browser holding the
 * install event, or Safari on iPhone and iPad — and gone once the app runs
 * standalone, which is also where it is opened from afterwards.
 */

import { useT } from "../../shell/i18n";
import { install, useInstallWay } from "../../shell/install";
import { Row } from "./ui";

export function InstallRow() {
  const t = useT();
  const way = useInstallWay();
  if (!way) return null;
  // A row of the Interface card: one line, the way in on its right.
  return way === "prompt" ? (
    <Row label={t("profile.install_row")} help={t("profile.install_help")} middle>
      <button type="button" className="pr-btn" onClick={() => void install()}>
        {t("profile.install_button")}
      </button>
    </Row>
  ) : (
    <Row label={t("profile.install_row")} help={t("profile.install_ios")} middle>
      <span />
    </Row>
  );
}
