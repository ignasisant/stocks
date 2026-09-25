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

import { useState } from "react";
import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useAccount, useGuest } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import { SignInWall } from "../../shell/guest";
import { Notifications } from "./Notifications";
import { Investor } from "./Investor";
import { Preferences } from "./Preferences";
import { useSettings } from "./prefs";
import { CSS } from "./styles";
import { Watchlist } from "./Watchlist";
import type { Listing } from "./Watchlist";
import { Card } from "./ui";

/**
 * `GET /me`, the fields the identity card reads. The shell's session reads the
 * same route for who is signing in; this reads it again for how to draw them —
 * a name, an avatar, where the files live, whether it is the owner's book —
 * which is presentation the shell has no business carrying around.
 */
type Identity = {
  name?: string | null;
  picture?: string | null;
  data_dir?: string | null;
  data_dir_full?: string | null;
  owner?: boolean;
};

const TABS = [
  { id: "prefs", label: "profile.preferences" },
  { id: "iv", label: "profile.iv_section" },
  { id: "watch", label: "profile.watchlist" },
  { id: "notify", label: "profile.notifications" },
] as const;

/**
 * Two initials for the avatar when there is no picture: off the display name
 * when the provider gave one (as the Streamlit card takes them), else off the
 * address.
 */
export function initials(email: string, name?: string | null): string {
  const source = name?.trim()
    ? name.trim().split(/\s+/)
    : (email.split("@")[0] ?? "").split(/[^\p{L}\p{N}]+/u);
  const letters = source
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}

export default function Page() {
  // Reachable by a guest and refusing inside, which is deliberate: dropping it
  // from the registry would make `pageFor()` serve Home for `/profile`,
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
  const identity = useApi(() => get<Identity>("/me"), []);
  const who = identity.state === "loaded" ? identity.data : null;
  // Read here rather than inside the tab: the tab strip carries the count.
  const listing = useApi(() => get<Listing>("/watchlist"), []);
  const count = listing.state === "loaded" ? listing.data.entries.length : 0;
  // A Google avatar URL can expire or be blocked; the initials are the fallback.
  const [brokenPicture, setBrokenPicture] = useState(false);
  const name = who?.name?.trim() || "";

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
            {who?.picture && !brokenPicture ? (
              // No referrer: the provider's image host has no need to learn
              // which page of this app its avatar was drawn on.
              <img
                src={who.picture}
                alt=""
                referrerPolicy="no-referrer"
                onError={() => setBrokenPicture(true)}
              />
            ) : (
              initials(email, name)
            )}
          </div>
          <div className="pf-ident-t">
            {name && name !== email && <span className="pf-ident-n">{name}</span>}
            <span className="pf-ident-e">{email}</span>
          </div>
          {/* Where this account's files live — the tail, with the whole path
              in the tooltip — and what that scope means, as the Streamlit
              card's right-hand column has it. */}
          <div className="pf-ident-r">
            {who?.data_dir && (
              <span className="pf-folder" title={who.data_dir_full ?? who.data_dir}>
                <span className="pf-folder-p">{who.data_dir}</span>
              </span>
            )}
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
            {entry.id === "watch" && count > 0 && (
              <span className="pf-tab-n">{count}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "prefs" && (
        <Preferences
          {...settings}
          owner={identity.state === "loaded" ? Boolean(who?.owner) : null}
        />
      )}
      {tab === "iv" && <Investor />}
      {tab === "watch" && <Watchlist query={listing} />}
      {tab === "notify" && <Notifications {...settings} />}
    </>
  );
}
