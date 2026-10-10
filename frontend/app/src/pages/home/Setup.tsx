/**
 * The start card: the whole onboarding, drawn as a map rather than written
 * as instructions.
 *
 * Four nodes on a line — account, import, AI key, Telegram — each an icon and
 * a word, each a door straight into the section that switches it on. The
 * first one still to do is lit, and gets the card's one big button. Under the
 * line, three things that need nothing switched on (look a ticker up, ask the
 * assistant, make the watchlist yours) as icon chips.
 *
 * No paragraph anywhere, on purpose. A walkthrough read before the reader has
 * done anything was the part they skipped — in the drawer, in the modal, in
 * the markdown card this replaced. The sections teach themselves (Import has
 * its own stepper), so the card's only job is getting the reader there.
 *
 * Every state on screen is the server's. `/onboarding` derives both groups
 * from the registry the guided tour reads (`stocks.web.onboarding`'s
 * `setup_state` / `explore_state`), so the card and the tour cannot disagree
 * about whether this account has Telegram linked. Nothing here re-computes
 * any of it, and nothing here reads prefs. Everything done, the card is gone.
 */

import { useState, type ReactNode } from "react";

import { get, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Icon } from "../../shell/Icon";
import { Skeleton } from "../../shell/Layout";
import { openAssistant } from "../../shell/assistant";
import { signInHref } from "../../shell/guest";
import { useRoute } from "../../shell/router";
import { useSession, useSignIn } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import { EXPLORE, SETUP, target, type Row } from "./checks";
import type { Onboarding, TourStep } from "./types";
import { Card } from "./ui";

/*
 * The dismissal is an account setting (`setup_card_dismissed` in prefs.json),
 * not a browser one. A reader who put the card away has put it away, and
 * meeting it again on their phone is the app forgetting a decision they made.
 */

type Entry = { row: Row; on: boolean };

/**
 * One row as a control: a link, a button, or plain text when there is
 * nowhere to send the reader. Shared by the nodes, the big button and the
 * chips, so all three go to the same place by the same rules.
 */
function Door({
  row,
  steps,
  guest,
  className,
  label,
  children,
}: {
  row: Row;
  steps: TourStep[];
  guest: boolean;
  className: string;
  /** Accessible name: the visible word plus its state. */
  label: string;
  children: ReactNode;
}) {
  const { go } = useRoute();
  const signIn = signInHref(useSignIn());
  if (row.key === "login" && guest) {
    // A guest's pending sign-in is the action itself: a link to the login
    // route. A deployment with no identity provider has nowhere to send
    // anybody, so the node states the capability and stops.
    return signIn ? (
      <a className={className} href={signIn} aria-label={label}>
        {children}
      </a>
    ) : (
      <span className={className} aria-label={label} aria-disabled="true">
        {children}
      </span>
    );
  }
  const to = target(row, steps);
  if (!to) {
    return (
      <span className={className} aria-label={label}>
        {children}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={className}
      aria-label={label}
      // Every target but search sits behind a sign-in: shown, so a guest sees
      // what an account gets, and disabled, so pressing it does not walk into
      // a wall.
      disabled={guest && row.signedIn === true}
      onClick={() =>
        to.kind === "assistant" ? openAssistant() : go(to.page, to.params)
      }
    >
      {children}
    </button>
  );
}

export function SetupCard() {
  const t = useT();
  const query = useApi(() => get<Onboarding>("/onboarding"), []);
  const session = useSession();
  const { prefs, reload } = session;
  const [dismissed, setDismissed] = useState(prefs.setup_card_dismissed);

  // A registry that will not load has nothing to say about itself, so it says
  // nothing: an error where an invitation goes is worse than a blank nobody
  // would have noticed. The skeleton is only so the page below does not jump
  // when it lands.
  if (dismissed) return null;
  if (query.state === "loading") return <Skeleton rows={2} />;
  if (query.state !== "loaded") return null;

  const state = query.data;
  // The payload's own word on who is asking, since `/onboarding` reports
  // sign-in from the real caller; the session is the fallback for a deploy
  // whose API predates the field.
  const guest = state.signed_in === undefined ? session.guest : !state.signed_in;
  const setup: Entry[] = SETUP.map((row) => ({
    row,
    on: state.setup[row.key] === true,
  }));
  const explore: Entry[] = EXPLORE.map((row) => ({
    row,
    on: state.explore[row.key] === true,
  }));
  const done = setup.filter((e) => e.on).length;
  const next = setup.find((e) => !e.on);
  const untried = explore.filter((e) => !e.on);
  // Nothing left to switch on or to try: the card has done its job.
  if (!next && !untried.length) return null;
  const word = (e: Entry) =>
    `${t(e.row.label)} — ${t(e.on ? "tour.active" : "tour.pending")}`;

  return (
    <Card className="hm-start">
      <div className="hm-start-head">
        <span className="hm-start-title">{t("home.start_title")}</span>
        <span className="hm-start-count">
          {t("home.start_progress", { done, total: setup.length })}
        </span>
        <button
          type="button"
          className="hm-quiet hm-start-hide"
          onClick={() => {
            // Hidden first, saved after: the press is the decision and a
            // failed write is worth one card coming back, not an error in
            // front of somebody tidying their screen.
            setDismissed(true);
            void send("PATCH", "/prefs", { setup_card_dismissed: true })
              .then(reload)
              .catch(() => undefined);
          }}
        >
          {t("home.setup_hide")}
        </button>
      </div>

      {next ? (
        <>
          {/* The line: done nodes recede to a tick, the next one is lit, the
              rest wait as outlines. The connector before a node fills once
              the node is reached, so progress reads left to right. */}
          <ol className="hm-steps">
            {setup.map((e) => {
              const state_ = e.on ? "done" : e === next ? "next" : "todo";
              return (
                <li key={e.row.key} className="hm-step-item" data-state={state_}>
                  <Door
                    row={e.row}
                    steps={state.steps}
                    guest={guest}
                    className="hm-step"
                    label={word(e)}
                  >
                    <span className="hm-step-dot" aria-hidden="true">
                      <Icon name={e.on ? "check" : e.row.icon} size={20} />
                    </span>
                    <span className="hm-step-label" aria-hidden="true">
                      {t(e.row.label)}
                    </span>
                  </Door>
                </li>
              );
            })}
          </ol>
          {next.row.cta ? (
            <Door
              row={next.row}
              steps={state.steps}
              guest={guest}
              className="hm-start-go"
              label={t(next.row.cta)}
            >
              <Icon name={next.row.icon} size={18} />
              <span>{t(next.row.cta)}</span>
              <Icon name="arrow_forward" size={18} />
            </Door>
          ) : null}
        </>
      ) : null}

      {untried.length ? (
        <div className="hm-start-try">
          <span className="hm-start-try-label">{t("home.start_try")}</span>
          {/* Tried ones fall off: a chip is an invitation, and an invitation
              already taken is clutter. */}
          {untried.map((e) => (
            <Door
              key={e.row.key}
              row={e.row}
              steps={state.steps}
              guest={guest}
              className="hm-chip"
              label={t(e.row.label)}
            >
              <Icon name={e.row.icon} size={16} />
              <span>{t(e.row.label)}</span>
            </Door>
          ))}
        </div>
      ) : null}
    </Card>
  );
}
