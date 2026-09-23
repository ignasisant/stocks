/**
 * Profile — who this account is, what it has set, and what it follows.
 *
 * Rebuilt from the same canvas as `web/app_pages/profile.py`: every setting is
 * a row with its label and explanation on the left and its control on the
 * right, the rows are grouped into cards rather than floating on the page, and
 * a sticky rail carries a read-only summary of what is set. Nothing has a Save
 * button — each control writes itself, which is what the strip beside the tabs
 * promises.
 *
 * Three scopes, one tab each, deep-linked as `?tab=` so a link into the
 * watchlist editor stays a link into the watchlist editor.
 */

import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useAccount, useGuest } from "../../shell/session";
import { SignInWall } from "../../shell/guest";
import { Notifications } from "./Notifications";
import { Investor } from "./Investor";
import { Preferences } from "./Preferences";
import { useSettings } from "./prefs";
import { CSS } from "./styles";
import { Watchlist } from "./Watchlist";
import { Card } from "./ui";

const TABS = [
  { id: "prefs", label: "profile.preferences" },
  { id: "iv", label: "profile.iv_section" },
  { id: "watch", label: "profile.watchlist" },
  { id: "notify", label: "profile.notifications" },
] as const;

/** Two initials off the address — the only identity `/me` carries. */
function initials(email: string): string {
  const parts = (email.split("@")[0] ?? "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const letters = parts.slice(0, 2).map((part) => part[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

export default function Page() {
  // Reachable by a guest and refusing inside, which is deliberate: dropping it
  // from the registry would make `pageFor()` serve Home for `/next/profile`,
  // silently, which is the exact failure `pages.test.ts` exists to catch. And
  // this page plus Import are the two reasons to sign in — hiding them hides
  // the offer. The wall comes before `useAccount()`, which throws rather than
  // pretending a guest has an address.
  if (useGuest()) return <SignInWall text="common.sign_in" />;
  return <Settings />;
}

function Settings() {
  const t = useT();
  const me = useAccount();
  const { params, setParams } = useRoute();
  const settings = useSettings(t("common.offline"));

  const wanted = params.get("tab") ?? "";
  const tab = TABS.some((entry) => entry.id === wanted) ? wanted : "prefs";
  const email = me.email ?? "";

  return (
    <>
      {/* React hoists this into the head and keeps one copy of it. */}
      <style href="ag-profile" precedence="default">
        {CSS}
      </style>

      <header className="pf-head">
        <h1 className="pf-title">{t("nav.profile")}</h1>
        {/* Nothing on this page has a Save button, so the page has to say so. */}
        <span className="pf-savehint">{t("profile.saves_instantly")}</span>
      </header>

      <Card>
        <div className="pf-ident">
          <div className="pf-avatar" aria-hidden="true">
            {initials(email)}
          </div>
          <div className="pf-ident-t">
            <span className="pf-ident-e">{email}</span>
            <span className="pf-ident-note">{t("profile.account_scope")}</span>
          </div>
          {/* A real link, not a fetch: signing out is the server clearing the
              cookie both front ends are authenticated by, and the page that
              comes back has to be one rendered without it. Streamlit serves
              the route; this app never runs a second sign-in flow, and it must
              not run a second sign-out either. */}
          <a className="pf-signout" href="/auth/logout">
            {t("common.log_out")}
          </a>
        </div>
      </Card>

      {/* A tab switch is not a navigation the back button should walk through. */}
      <div className="pf-tabs" role="tablist" aria-label={t("nav.profile")}>
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            aria-selected={entry.id === tab}
            className={entry.id === tab ? "pf-tab pf-tab-on" : "pf-tab"}
            onClick={() => setParams({ tab: entry.id })}
          >
            {t(entry.label)}
          </button>
        ))}
      </div>

      {tab === "prefs" && <Preferences {...settings} />}
      {tab === "iv" && <Investor />}
      {tab === "watch" && <Watchlist />}
      {tab === "notify" && <Notifications {...settings} />}
    </>
  );
}
