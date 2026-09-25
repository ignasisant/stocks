/**
 * The three steps to a live portfolio, for an account with nothing in it yet.
 *
 * Not the same card as `Setup.tsx`, and the two are deliberately separate:
 * that one lists what is switched *on* — Google, an import, a provider key,
 * Telegram — and this one says what to *do* next, in order, in prose. A
 * reader who has connected everything still gets that one; a reader who has
 * imported nothing needs this one, and neither answers for the other. The
 * Streamlit page draws both, above everything else, for the same reason.
 *
 * Shown only while the ledger is empty, which is what "new here" means: an
 * account that has imported has done step two, and the card would be telling
 * somebody to do what they already did. It disappears on its own then — the
 * dismiss is for the reader who wants it gone before that.
 *
 * The copy is one markdown blob in the catalog (`home.onboarding_md`) rather
 * than a list assembled here, because it is a paragraph of guidance and the
 * translation has to be able to move a sentence between steps. Rendered with
 * the drawer's own renderer, so the app has one markdown and not two.
 */

import { useState } from "react";

import { send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useSession } from "../../shell/session";
import type { Query } from "../../shell/useApi";
import { Markdown } from "../../chat/markdown";
import { Card } from "./ui";
import type { Transactions } from "./types";

/** Streamlit's icon tokens — `:material/waving_hand:` and friends. */
const ICON = /:material\/[a-z0-9_]+:/g;

export function FirstRun({ ledger }: { ledger: Query<Transactions> }) {
  const t = useT();
  const { prefs, reload } = useSession();
  const [dismissed, setDismissed] = useState(prefs.onboarding_dismissed);

  // Until the ledger answers, nothing is drawn: a card that appears and then
  // vanishes a moment later is worse than one that arrives a moment late. A
  // read that failed is treated as "not new" for the same reason — this is
  // guidance, and guidance is the wrong thing to force in front of somebody
  // whose page is already having a bad time.
  if (dismissed || ledger.state !== "loaded" || ledger.data.total > 0) return null;

  return (
    <Card className="hm-firstrun">
      <div className="hm-prose">
        {/* The icon token comes off and the `**` stays: `plain()` strips both,
            which is right for a heading rendered as text and wrong here, where
            the emphasis is the markdown this renders. Streamlit draws
            `:material/…:` from a font this app does not load for page content,
            and the literal token on screen is worse than no icon. */}
        <Markdown text={t("home.onboarding_md").replace(ICON, "").trimStart()} />
      </div>
      <div className="hm-firstrun-actions">
        <button
          type="button"
          className="hm-quiet"
          onClick={() => {
            // Hidden first, saved after — the press is the decision, and a
            // failed write is worth one card coming back rather than an error
            // in front of somebody tidying their screen. Same key the
            // Streamlit page writes, so this is put away on both.
            setDismissed(true);
            void send("PATCH", "/prefs", { onboarding_dismissed: true })
              .then(reload)
              .catch(() => undefined);
          }}
        >
          {t("home.onboarding_dismiss")}
        </button>
      </div>
    </Card>
  );
}
