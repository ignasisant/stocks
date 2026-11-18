/**
 * The investor-profile nudge: once a day, for an account with no profile.
 *
 * The assistant is told who it is advising from exactly these five fields
 * (`chat.engine.persona`), and an account that never filled them in gets
 * generic advice without knowing why — so a signed-in account whose profile was
 * never saved is asked, once a day, with "skip for now" one press away.
 * It asks again another day until the profile is saved here or on the Profile
 * page — or until the reader says not to (`profile_prompt_off`, an account
 * setting): a question nobody can stop is a nag, and the Profile page keeps the
 * same five fields for whenever they want them.
 *
 * The day is remembered per account, on this device: two accounts signing in
 * one after the other in a tab are two people, and the first one's answer is
 * not the second one's.
 *
 * Last in line on a first load. The walkthrough and "what's new" come first,
 * and only one modal gets a first load; the tour says whether it took the slot
 * (`whenFirstLoadDecided`), and if it did this waits for the next session
 * rather than stacking a second dialog on the first.
 *
 * And behind the section guide altogether: while it is up, put away in its
 * strip, or still on offer on Home, the account is being shown round, and five
 * questions about how it invests would land in the middle of that. Nor on its
 * heels: somebody who has just been shown round, or pressed "skip the
 * tutorial", did not ask for a form instead, so a day that had the guide in it
 * asks nothing, and the next visit day does.
 *
 * Its own small form rather than the Profile page's: that page is a lazy chunk
 * with its own autosaving cards, and pulling it into the shell to draw a dialog
 * most sessions never show would make every reader pay for it.
 */

import {
  type ReactNode,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { get, send } from "./api";
import { useT } from "./i18n";
import { useGuest, useSession } from "./session";
import { claimNudge, isTouring, onTouring, whenFirstLoadDecided } from "./tourPark";
import { useDialog } from "./useDialog";
import { useExitGhost } from "./useSheet";
import { Help } from "../ui/Kpi";
import { Options } from "../ui/Options";
import { Segmented } from "../ui/Segmented";
import { ToggleChip, ToggleRow } from "../ui/Toggle";

type Options = {
  risk: string[];
  horizon: string[];
  focus: string[];
  constraints: string[];
};

type Profile = {
  risk: string;
  horizon: string;
  focus: string[];
  constraints: string[];
  notes: string;
  set: boolean;
};

const SEEN = "profilePromptSeen";

/** The reader's own calendar day, which is when "today" turns over for them. */
function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** The account's storage key: a hash of the address rather than the address,
 *  which would otherwise sit in this browser after signing out. FNV-1a; telling
 *  accounts apart is all it is for. */
export function seenKey(account: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < account.length; i++) {
    hash ^= account.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${SEEN}:${(hash >>> 0).toString(36)}`;
}

/** Whether this account was already nudged, or shown round, on `day`. Storage
 *  that throws reads as "yes": a nag that cannot remember it asked would ask
 *  on every reload. */
export function seen(account: string, day = today()): boolean {
  try {
    return window.localStorage.getItem(seenKey(account)) === day;
  } catch {
    return true;
  }
}

export function markSeen(account: string, day = today()): void {
  try {
    window.localStorage.setItem(seenKey(account), day);
  } catch {
    // `seen()` already reads a throwing store as "asked".
  }
}

export function ProfilePrompt() {
  const { prefs, me } = useSession();
  const account = me?.email ?? "";
  const off = prefs.profile_prompt_off;
  // The offer is the account's (it survives the tab); the guide on screen is
  // this tab's, strip included.
  const touring = useSyncExternalStore(onTouring, isTouring);
  const guided = touring || prefs.tour_offer === true;
  const wasGuided = useRef(false);
  const [loaded, setLoaded] = useState<{ options: Options; profile: Profile } | null>(
    null,
  );

  // Declared first, so it has run by the time the one below reads it.
  useEffect(() => {
    if (!guided) return;
    wasGuided.current = true;
    markSeen(account);
  }, [guided, account]);

  useEffect(() => {
    if (off || guided || wasGuided.current || seen(account)) return;
    let alive = true;
    whenFirstLoadDecided()
      .then(async (interrupted) => {
        // A guide may have opened while this waited; the effect runs again
        // when it ends.
        if (interrupted || !alive || isTouring()) return;
        const [options, profile] = await Promise.all([
          get<Options>("/profile-options"),
          get<Profile>("/profile"),
        ]);
        if (!alive || isTouring() || wasGuided.current) return;
        if (profile.set || !claimNudge()) return;
        // Stamped when it is shown, not when it is answered: a reload with the
        // dialog open is a "skip", as closing the tab would be.
        markSeen(account);
        setLoaded({ options, profile });
      })
      .catch(() => {
        // A nudge that could not load is a nudge nobody misses.
      });
    return () => {
      alive = false;
    };
  }, [off, guided, account]);

  if (!loaded) return null;
  return (
    <Dialog
      options={loaded.options}
      initial={loaded.profile}
      onDone={() => setLoaded(null)}
    />
  );
}

function Dialog({
  options,
  initial,
  onDone,
}: {
  options: Options;
  initial: Profile;
  onDone: () => void;
}) {
  const t = useT();
  const guest = useGuest();
  const { reload } = useSession();
  const [profile, setProfile] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  useDialog(card);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDone();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  function save() {
    setBusy(true);
    setFailed(false);
    send("PUT", "/profile", {
      risk: profile.risk,
      horizon: profile.horizon,
      focus: profile.focus,
      constraints: profile.constraints,
      notes: profile.notes.trim(),
    })
      .then(onDone)
      // Kept open with what was chosen: the reader answered five questions and
      // a failed save must not throw the answers away.
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }

  function never() {
    // Closed first, written after, as the Home card's "don't show again": the
    // press is the decision, and a failed write costs one more ask next
    // session rather than an error in front of somebody saying no.
    onDone();
    void send("PATCH", "/prefs", { profile_prompt_off: true }, { touches: ["/prefs"] })
      .then(reload)
      .catch(() => undefined);
  }

  const toggle = (list: string[], option: string) =>
    list.includes(option) ? list.filter((x) => x !== option) : [...list, option];

  return (
    <div ref={scrim} className="ag-tour-scrim" role="presentation" onClick={onDone}>
      <div
        ref={card}
        tabIndex={-1}
        className="ag-tour ag-dlg-wide ag-pp"
        role="dialog"
        aria-modal="true"
        aria-label={t("profile.iv_dialog_title")}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="ag-tour-h">{t("profile.iv_dialog_title")}</h2>
        <p className="ag-tour-intro">{t("profile.iv_dialog_intro")}</p>
        {/* Tolerance as options with a line each, horizon as one track: the
            prototype's Perfil de inversor. "Balanced" alone tells nobody how
            far down they are signing up to sit. */}
        <Field label={t("profile.iv_risk")} help={t("profile.iv_risk_help")}>
          <Options
            label={t("profile.iv_risk")}
            items={options.risk.map((o) => ({
              id: o,
              label: t(`profile.iv_risk_${o}`),
              line: t(`profile.iv_risk_${o}_line`),
            }))}
            value={profile.risk || null}
            onPick={(risk) => setProfile({ ...profile, risk })}
          />
        </Field>
        <Field label={t("profile.iv_horizon")} help={t("profile.iv_horizon_help")}>
          <Segmented
            className="ag-seg-2up"
            label={t("profile.iv_horizon")}
            items={options.horizon.map((o) => ({
              id: o,
              label: t(`profile.iv_horizon_${o}`),
            }))}
            value={profile.horizon || null}
            onPick={(horizon) => setProfile({ ...profile, horizon })}
          />
        </Field>
        <Chips
          label={t("profile.iv_focus")}
          help={t("profile.iv_focus_help")}
          options={options.focus}
          labelOf={(o) => t(`profile.iv_focus_${o}`)}
          on={(o) => profile.focus.includes(o)}
          onPick={(o) => setProfile({ ...profile, focus: toggle(profile.focus, o) })}
        />
        <Chips
          label={t("profile.iv_constraints")}
          help={t("profile.iv_constraints_help")}
          options={options.constraints}
          labelOf={(o) => t(`profile.iv_constraints_${o}`)}
          on={(o) => profile.constraints.includes(o)}
          onPick={(o) =>
            setProfile({ ...profile, constraints: toggle(profile.constraints, o) })
          }
        />
        <label className="ag-pp-field">
          <span className="ag-pp-label">{t("profile.iv_notes")}</span>
          <textarea
            className="ag-fb-text"
            rows={3}
            // The API's own ceiling (`routes/prefs._MAX_NOTES`): the notes ride
            // in every system prompt the account sends.
            maxLength={2000}
            value={profile.notes}
            placeholder={t("profile.iv_notes_ph")}
            onChange={(event) => setProfile({ ...profile, notes: event.target.value })}
          />
        </label>
        {failed ? (
          <p className="ag-fb-bad" role="alert">
            {t("profile.iv_save_failed")}
          </p>
        ) : null}
        <footer className="ag-tour-foot">
          {/* A guest has no prefs to keep the answer in. */}
          {guest ? null : (
            <button
              type="button"
              className="ag-tour-quiet ag-tour-lead"
              onClick={never}
            >
              {t("profile.iv_never")}
            </button>
          )}
          <button type="button" className="ag-tour-quiet" onClick={onDone}>
            {t("profile.iv_skip")}
          </button>
          <button type="button" className="ag-tour-cta" disabled={busy} onClick={save}>
            {t("profile.iv_save")}
          </button>
        </footer>
      </div>
    </div>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <div className="ag-pp-field">
      <span className="ag-pp-label">
        {label}
        <Help text={help} />
      </span>
      {children}
    </div>
  );
}

function Chips({
  label,
  help,
  options,
  labelOf,
  on,
  onPick,
}: {
  label: string;
  help: string;
  options: string[];
  labelOf: (option: string) => string;
  on: (option: string) => boolean;
  onPick: (option: string) => void;
}) {
  return (
    <div className="ag-pp-field" role="group" aria-label={label}>
      {/* The "?" rather than a `title`: a tooltip on hover is nothing on a
          phone, which is where most first sessions are. */}
      <span className="ag-pp-label">
        {label}
        <Help text={help} />
      </span>
      <ToggleRow>
        {options.map((option) => (
          <ToggleChip key={option} on={on(option)} onClick={() => onPick(option)}>
            {labelOf(option)}
          </ToggleChip>
        ))}
      </ToggleRow>
    </div>
  );
}
