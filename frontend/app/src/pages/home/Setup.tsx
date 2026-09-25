/**
 * The two first-run groups: what this account has switched on, and the three
 * things that need nothing switched on at all.
 *
 * `web/app_pages/home.py` draws both inside one bordered card, and keeps them
 * apart on purpose. The first is a list of what is still missing — Google
 * sign-in, a ledger import, a provider key, Telegram — and a list of what is
 * missing is a poor answer to "what can I do here": an account that has
 * connected nothing can still look a company up, ask the assistant on the free
 * chain and make the watchlist its own, right now. The second group is what
 * says that, which is why it never gates the dismiss — it is an invitation,
 * not a chore.
 *
 * Every state on screen is the server's. `/onboarding` derives both from the
 * registry the Streamlit card and the guided tour already read
 * (`onboarding.setup_state` / `explore_state`), so the three surfaces cannot
 * disagree about whether this account has Telegram linked. Nothing here
 * re-computes any of it, and nothing here reads prefs.
 */

import { useState, type ReactNode } from "react";

import { get, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Skeleton } from "../../shell/Layout";
import { openAssistant } from "../../shell/assistant";
import { signInHref } from "../../shell/guest";
import { Link, useRoute } from "../../shell/router";
import { useSession, useSignIn } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import { plain } from "./format";
import { EXPLORE, SETUP, target, type Row } from "./checks";
import type { Onboarding, TourStep } from "./types";
import { Card } from "./ui";

/*
 * The dismissal is an account setting (`setup_card_dismissed` in prefs.json),
 * not a browser one — the same key the Streamlit card writes. A reader who put
 * the checklist away has put it away, and meeting it again on their phone is
 * the app forgetting a decision they made.
 */

/**
 * The state mark: a tick for a capability that is on, an empty ring for one
 * that is not.
 *
 * Decoration only — `Check` writes the same state in words beside it, because
 * a shape is not a label and a screen reader gets nothing from this.
 */
function Mark({ on }: { on: boolean }) {
  return (
    <span className={on ? "hm-mark hm-mark-on" : "hm-mark"} aria-hidden="true">
      {on ? "✓" : ""}
    </span>
  );
}

/**
 * One capability row.
 *
 * Done recedes to a muted tick: the badge on the heading already counts them,
 * and four emphatic rows would bury the one row that still needs doing — which
 * keeps its border, and so is the only thing on the strip that looks like a
 * control. A row with nowhere to go is drawn as text rather than as a button
 * that would swallow the press.
 */
function Check({
  row,
  on,
  steps,
  guest,
}: {
  row: Row;
  on: boolean;
  steps: TourStep[];
  guest: boolean;
}) {
  const t = useT();
  const { go } = useRoute();
  const signIn = signInHref(useSignIn());
  const to = target(row, steps);
  const className = on ? "hm-check hm-check-on" : "hm-check";
  const body = (
    <>
      <Mark on={on} />
      <span>{t(row.label)}</span>
      {/* The tour's own two words for these two states, so the app has one
          vocabulary for "switched on" rather than one per surface. */}
      <span className="hm-sr">{on ? t("tour.active") : t("tour.pending")}</span>
    </>
  );
  if (row.key === "login" && !on) {
    // A guest's pending sign-in is the action itself, as Streamlit's pill is a
    // link to the login route. A deployment with no identity provider has
    // nowhere to send anybody, so the row states the capability and stops —
    // `home.py` disables the pill for the same reason.
    return signIn ? (
      <a className={className} href={signIn}>
        {body}
      </a>
    ) : (
      <span className={`${className} hm-check-off`} aria-disabled="true">
        {body}
      </span>
    );
  }
  if (!to) return <span className={className}>{body}</span>;
  return (
    <button
      type="button"
      className={className}
      // Every target but search sits behind a sign-in: shown, so a guest sees
      // what an account gets, and disabled, so pressing it does not walk into
      // a wall.
      disabled={guest && row.signedIn === true}
      onClick={() =>
        to.kind === "assistant" ? openAssistant() : go(to.page, to.params)
      }
    >
      {body}
    </button>
  );
}

/** A heading line, its count, and the rows still worth showing under it. */
function Group({
  title,
  badge,
  rows,
  steps,
  guest,
  collapsed,
  check,
  actions,
}: {
  title: string;
  badge: string;
  rows: { row: Row; on: boolean }[];
  steps: TourStep[];
  guest: boolean;
  /** Nothing left to do: the heading is the whole group. */
  collapsed: boolean;
  /** The receipt tick beside the heading, for a group that is finished. */
  check?: boolean;
  actions?: ReactNode;
}) {
  return (
    <div className="hm-check-group">
      <div className="hm-check-head">
        {check ? <Mark on /> : null}
        <span className={check ? "hm-check-title hm-muted" : "hm-check-title"}>
          {title}
        </span>
        <span className="hm-badge">{badge}</span>
        {actions ? <span className="hm-check-acts">{actions}</span> : null}
      </div>
      {collapsed ? null : (
        <div className="hm-checks">
          {rows.map(({ row, on }) => (
            <Check key={row.key} row={row} on={on} steps={steps} guest={guest} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SetupCard() {
  const t = useT();
  const query = useApi(() => get<Onboarding>("/onboarding"), []);
  const session = useSession();
  const { prefs, reload } = session;
  const [dismissed, setDismissed] = useState(prefs.setup_card_dismissed);

  // A registry that will not load has nothing to say about itself, so it says
  // nothing: an error message where an invitation goes is worse than a blank
  // nobody would have noticed. The shell's tour fails the same way, off the
  // same call. The skeleton is only so the page below does not jump when it
  // lands.
  if (query.state === "loading") return <Skeleton rows={2} />;
  if (query.state !== "loaded") return null;

  const state = query.data;
  // The payload's own word on who is asking, since `/onboarding` reports
  // sign-in from the real caller; the session is the fallback for a deploy
  // whose API predates the field.
  const guest = state.signed_in === undefined ? session.guest : !state.signed_in;
  const setup = SETUP.map((row) => ({ row, on: state.setup[row.key] === true }));
  const done = setup.filter((entry) => entry.on).length;
  const complete = done === setup.length;
  if (complete && dismissed) return null;

  const explore = EXPLORE.map((row) => ({ row, on: state.explore[row.key] === true }));
  const tried = explore.filter((entry) => entry.on).length;

  return (
    <Card className="hm-firstrun">
      <Group
        title={plain(t("home.setup_title"))}
        badge={t("home.setup_progress", { done, total: setup.length })}
        rows={setup}
        steps={state.steps}
        guest={guest}
        collapsed={complete}
        actions={
          <>
            {/* The tour explains all four of these and everything else, so the
                card that lists them is the obvious way into it — but it is an
                action, not a fifth capability, which is why it sits up here
                rather than inline with the states. A real link, so the step it
                opens can be shared; the shell's modal answers `?tour=`. */}
            <Link page="home" params={{ tour: "1" }} className="hm-quiet">
              {t("tour.launch")}
            </Link>
            {/* Offered only once there is nothing left to connect: a checklist
                dismissed half-done is a checklist that was in the way. */}
            {complete ? (
              <button
                type="button"
                className="hm-quiet"
                onClick={() => {
                  // Hidden first, saved after: the press is the decision and
                  // a failed write is worth one card coming back, not an
                  // error in front of somebody tidying their screen.
                  setDismissed(true);
                  void send("PATCH", "/prefs", { setup_card_dismissed: true })
                    .then(reload)
                    .catch(() => undefined);
                }}
              >
                {t("home.dismiss")}
              </button>
            ) : null}
          </>
        }
      />
      <Group
        title={plain(t("home.explore_title"))}
        badge={t("home.explore_progress", { done: tried, total: explore.length })}
        rows={explore}
        steps={state.steps}
        guest={guest}
        // Nothing left to invite: one line of receipt rather than three rows
        // leading nowhere the reader has not already been.
        collapsed={tried === explore.length}
        check={tried === explore.length}
      />
    </Card>
  );
}
