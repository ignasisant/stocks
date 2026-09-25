/**
 * The investor-profile nudge: once per session, for an account with no profile.
 *
 * `auth.maybe_prompt_profile()` in the Streamlit app, moved. The assistant is
 * told who it is advising from exactly these five fields
 * (`chat.engine.persona`), and an account that never filled them in gets
 * generic advice without knowing why — so a signed-in account whose profile was
 * never saved is asked, once per session, with "skip for now" one press away.
 * It nags again next session until the profile is saved here or on the Profile
 * page, which is Streamlit's rule too.
 *
 * Last in line on a first load. The walkthrough and "what's new" come first,
 * and only one modal gets a first load (`app.py`); the tour says whether it
 * took the slot (`whenFirstLoadDecided`), and if it did this waits for the next
 * session rather than stacking a second dialog on the first.
 *
 * Its own small form rather than the Profile page's: that page is a lazy chunk
 * with its own autosaving cards, and pulling it into the shell to draw a dialog
 * most sessions never show would make every reader pay for it.
 */

import { useEffect, useState } from "react";

import { get, send } from "./api";
import { useT } from "./i18n";
import { whenFirstLoadDecided } from "./tourPark";

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

/** Whether this tab was already nudged. Storage that throws reads as "yes": a
 *  nag that cannot remember it asked would ask on every reload. */
function seen(): boolean {
  try {
    return window.sessionStorage.getItem(SEEN) === "1";
  } catch {
    return true;
  }
}

function markSeen(): void {
  try {
    window.sessionStorage.setItem(SEEN, "1");
  } catch {
    // `seen()` already reads a throwing store as "asked".
  }
}

export function ProfilePrompt() {
  const [loaded, setLoaded] = useState<{ options: Options; profile: Profile } | null>(
    null,
  );

  useEffect(() => {
    if (seen()) return;
    let alive = true;
    whenFirstLoadDecided()
      .then(async (interrupted) => {
        if (interrupted || !alive) return;
        const [options, profile] = await Promise.all([
          get<Options>("/profile-options"),
          get<Profile>("/profile"),
        ]);
        if (!alive || profile.set) return;
        // Stamped when it is shown, not when it is answered: a reload with the
        // dialog open is a "skip", as closing the tab would be.
        markSeen();
        setLoaded({ options, profile });
      })
      .catch(() => {
        // A nudge that could not load is a nudge nobody misses.
      });
    return () => {
      alive = false;
    };
  }, []);

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
  const [profile, setProfile] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

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

  const toggle = (list: string[], option: string) =>
    list.includes(option) ? list.filter((x) => x !== option) : [...list, option];

  return (
    <div className="ag-tour-scrim" role="presentation" onClick={onDone}>
      <div
        className="ag-tour ag-pp"
        role="dialog"
        aria-modal="true"
        aria-label={t("profile.iv_dialog_title")}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="ag-tour-h">{t("profile.iv_dialog_title")}</h2>
        <p className="ag-tour-intro">{t("profile.iv_dialog_intro")}</p>
        <Chips
          label={t("profile.iv_risk")}
          help={t("profile.iv_risk_help")}
          options={options.risk}
          labelOf={(o) => t(`profile.iv_risk_${o}`)}
          on={(o) => profile.risk === o}
          onPick={(risk) => setProfile({ ...profile, risk })}
        />
        <Chips
          label={t("profile.iv_horizon")}
          help={t("profile.iv_horizon_help")}
          options={options.horizon}
          labelOf={(o) => t(`profile.iv_horizon_${o}`)}
          on={(o) => profile.horizon === o}
          onPick={(horizon) => setProfile({ ...profile, horizon })}
        />
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
        {failed ? <p className="ag-fb-bad">{t("profile.iv_save_failed")}</p> : null}
        <footer className="ag-tour-foot">
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
      <span className="ag-pp-label" title={help}>
        {label}
      </span>
      <div className="ag-fb-kinds">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            className={on(option) ? "ag-fb-kind ag-fb-on" : "ag-fb-kind"}
            aria-pressed={on(option)}
            onClick={() => onPick(option)}
          >
            {labelOf(option)}
          </button>
        ))}
      </div>
    </div>
  );
}
