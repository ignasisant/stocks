/**
 * The investor profile: what the assistant is told about who it is advising.
 *
 * Not decoration. `stocks.chat.engine.persona` builds the sentence that rides
 * with every question from exactly these fields, so a wrong answer here is a
 * wrong answer in the chat drawer — which is why the rail says, in the app's
 * own words, that this is stored with the account and sent to the assistant.
 *
 * Three cards rather than one stack, the same split the Streamlit page makes:
 * the two scales that colour every answer, the lists that narrow it, then the
 * free text. And no Save button, because the tab strip promises there is none.
 */

import { useEffect, useState } from "react";

import { get, send } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useApi } from "../../shell/useApi";
import { describe } from "./errors";
import { Card, Failure, MultiChips, Row, Select } from "./ui";

/** `GET /profile` — `set` is false until the account has saved once. */
type InvestorProfile = {
  risk: string;
  horizon: string;
  focus: string[];
  constraints: string[];
  notes: string;
  set: boolean;
  /**
   * The sentence the assistant is actually given, built server-side from the
   * fields above. Read rather than rebuilt here: it is assembled in Python
   * from an enum table, and a second copy in TypeScript is a second place for
   * that wording to drift.
   */
  persona: string;
};

/** `GET /profile-options` — which answers each field offers, in offering order. */
type Options = {
  risk: string[];
  horizon: string[];
  focus: string[];
  constraints: string[];
};

type Loadedbits = { options: Options; profile: InvestorProfile };

export function Investor() {
  const query = useApi<Loadedbits>(async () => {
    const [options, profile] = await Promise.all([
      get<Options>("/profile-options"),
      get<InvestorProfile>("/profile"),
    ]);
    return { options, profile };
  }, []);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={8} />}>
      {(bits) => <Form options={bits.options} stored={bits.profile} />}
    </Loaded>
  );
}

function Form({ options, stored }: { options: Options; stored: InvestorProfile }) {
  const t = useT();
  const [profile, setProfile] = useState(stored);
  const [saving, setSaving] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  // PUT is a whole-object replace, so every change sends the whole thing. That
  // is the endpoint's shape and the right one here: these five fields are read
  // together to build one sentence, and a half-applied patch would describe an
  // investor who does not exist.
  function commit(next: InvestorProfile, field: string) {
    setProfile(next);
    setSaving(field);
    setFailure(null);
    send<InvestorProfile>("PUT", "/profile", {
      risk: next.risk,
      horizon: next.horizon,
      focus: next.focus,
      constraints: next.constraints,
      notes: next.notes,
    })
      .then((saved) => setProfile(saved))
      .catch((error: unknown) => {
        // Put back what the server still holds: a control left showing a value
        // that was not stored is the one lie a form must not tell.
        setProfile(stored);
        setFailure(describe(error, t("common.offline")));
      })
      .finally(() => setSaving(null));
  }

  const label = (group: string) => (option: string) =>
    t(`profile.iv_${group}_${option}`);

  return (
    <div className="pf-body">
      <div className="pf-main">
        <Card title={t("profile.iv_how_title")} sub={t("profile.iv_how_sub")}>
          <Row label={t("profile.iv_risk")} help={t("profile.iv_risk_help")}>
            <Select
              label={t("profile.iv_risk")}
              value={profile.risk}
              options={options.risk}
              labelOf={label("risk")}
              disabled={saving === "risk"}
              onPick={(risk) =>
                risk !== profile.risk && commit({ ...profile, risk }, "risk")
              }
            />
          </Row>
          <Row label={t("profile.iv_horizon")} help={t("profile.iv_horizon_help")}>
            <Select
              label={t("profile.iv_horizon")}
              value={profile.horizon}
              options={options.horizon}
              labelOf={label("horizon")}
              disabled={saving === "horizon"}
              onPick={(horizon) =>
                horizon !== profile.horizon &&
                commit({ ...profile, horizon }, "horizon")
              }
            />
          </Row>
        </Card>

        <Card title={t("profile.iv_what_title")} sub={t("profile.iv_what_sub")}>
          <Row label={t("profile.iv_focus")} help={t("profile.iv_focus_help")}>
            <MultiChips
              values={profile.focus}
              options={options.focus}
              labelOf={label("focus")}
              disabled={saving === "focus"}
              onToggle={(option, on) =>
                commit(
                  {
                    ...profile,
                    focus: on
                      ? [...profile.focus, option]
                      : profile.focus.filter((f) => f !== option),
                  },
                  "focus",
                )
              }
            />
          </Row>
          <Row
            label={t("profile.iv_constraints")}
            help={t("profile.iv_constraints_help")}
          >
            <MultiChips
              values={profile.constraints}
              options={options.constraints}
              labelOf={label("constraints")}
              disabled={saving === "constraints"}
              onToggle={(option, on) =>
                commit(
                  {
                    ...profile,
                    constraints: on
                      ? [...profile.constraints, option]
                      : profile.constraints.filter((c) => c !== option),
                  },
                  "constraints",
                )
              }
            />
          </Row>
        </Card>

        <Card title={t("profile.iv_notes_title")} sub={t("profile.iv_caption")}>
          <Row label={t("profile.iv_notes")} help={t("profile.iv_notes_help")}>
            <Notes
              value={profile.notes}
              placeholder={t("profile.iv_notes_ph")}
              label={t("profile.iv_notes")}
              disabled={saving === "notes"}
              onCommit={(notes) =>
                notes !== profile.notes && commit({ ...profile, notes }, "notes")
              }
            />
          </Row>
          <Failure message={failure} />
        </Card>
      </div>

      <aside className="pf-rail">
        <Card>
          <div className="pf-sum">
            <span className="pf-sum-t">{t("profile.iv_sum_title")}</span>
            <Summary
              label={t("profile.iv_risk")}
              value={t(`profile.iv_risk_${profile.risk}`)}
            />
            <Summary
              label={t("profile.iv_horizon")}
              value={t(`profile.iv_horizon_${profile.horizon}`)}
            />
            <Summary
              label={t("profile.iv_focus")}
              value={joined(profile.focus, label("focus"), t("profile.iv_sum_none"))}
            />
            <Summary
              label={t("profile.iv_constraints")}
              value={joined(
                profile.constraints,
                label("constraints"),
                t("profile.iv_sum_none"),
              )}
            />
            <div className="pf-sum-rule" />
            <span className="pf-sum-note">{t("profile.iv_privacy")}</span>
          </div>
          {/* The summary above says what was chosen; this says what the model
              is told. Folded rather than always open — it is a prompt, and the
              point of showing it is that somebody *can* check the second
              follows from the first, not that they have to read it. A native
              <details>, as the watchlist groups use: no popover in this shell
              to hang it on, and none needed. */}
          {profile.persona ? (
            <details className="pf-persona">
              <summary>{t("profile.iv_persona_open")}</summary>
              <p className="pf-sum-note">{t("profile.iv_persona_help")}</p>
              <code className="pf-persona-text">{profile.persona}</code>
            </details>
          ) : null}
        </Card>
      </aside>
    </div>
  );
}

function joined(keys: string[], labelOf: (key: string) => string, none: string) {
  return keys.length ? keys.map(labelOf).join(", ") : none;
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="pf-sum-row">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

/**
 * Free text, committed when the field is left — never on every keystroke.
 *
 * One PUT per character would be a request storm, and a half-typed sentence is
 * not a note anybody meant to save. The same bargain the number fields on the
 * Preferences tab make.
 */
function Notes({
  value,
  label,
  placeholder,
  disabled,
  onCommit,
}: {
  value: string;
  label: string;
  placeholder: string;
  disabled?: boolean;
  onCommit: (text: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  // A save that came back normalised (or another tab's edit) has to win over a
  // draft nobody is typing into any more.
  useEffect(() => setDraft(value), [value]);
  return (
    <textarea
      className="pf-notes"
      rows={4}
      value={draft}
      aria-label={label}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => onCommit(draft.trim())}
    />
  );
}
