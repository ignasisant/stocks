/**
 * The investor profile: what the assistant is told about who it is advising.
 *
 * Not decoration. `stocks.chat.engine.persona` builds the sentence that rides
 * with every question from exactly these fields, so a wrong answer here is a
 * wrong answer in the chat drawer — which is why the rail says, in the app's
 * own words, that this is stored with the account and sent to the assistant.
 *
 * Three cards rather than one stack: the two scales that colour every answer,
 * the lists that narrow it, then the free text. And no Save button, because the
 * tab strip promises there is none.
 */

import { useEffect, useRef, useState } from "react";

import { get, send } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useApi } from "../../shell/useApi";
import { useSession } from "../../shell/session";
import { residenceClash } from "./residence";
import { describe } from "./errors";
import { Glyph } from "../../ui/Glyph";
import { Options } from "../../ui/Options";
import { Segmented } from "../../ui/Segmented";
import { Card, Failure, MultiChips, Row } from "./ui";

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

/** The longest note the server stores (`api/routes/prefs._MAX_NOTES`). */
const NOTES_MAX = 2000;

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
  // Said here and on Preferences; neither side is changed for the reader.
  const clash = residenceClash(useSession().prefs.tax_residence, profile.constraints);

  return (
    <div className="pr-body">
      <div className="pr-main">
        <Card title={t("profile.iv_how_title")} sub={t("profile.iv_how_sub")}>
          <Row label={t("profile.iv_risk")} help={t("profile.iv_risk_help")}>
            {/* Options with a line each, not a dropdown: "Balanced" alone
                says nothing about how far down the reader signs up to sit. */}
            <Options
              label={t("profile.iv_risk")}
              items={options.risk.map((o) => ({
                id: o,
                label: label("risk")(o),
                line: t(`profile.iv_risk_${o}_line`),
              }))}
              value={profile.risk || null}
              disabled={saving === "risk"}
              onPick={(risk) =>
                risk !== profile.risk && commit({ ...profile, risk }, "risk")
              }
            />
          </Row>
          <Row label={t("profile.iv_horizon")} help={t("profile.iv_horizon_help")}>
            <Segmented
              className="ag-seg-2up"
              label={t("profile.iv_horizon")}
              items={options.horizon.map((o) => ({
                id: o,
                label: label("horizon")(o),
              }))}
              value={profile.horizon || null}
              onPick={(horizon) =>
                saving !== "horizon" &&
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
            {clash && (
              <p className="pl-sum pl-sum-off" role="status">
                {t("profile.iv_residence_clash", {
                  residence: clash.residence,
                  constraint: t(`profile.iv_constraints_${clash.constraint}`),
                })}
              </p>
            )}
          </Row>
        </Card>

        <Card title={t("profile.iv_notes_title")} sub={t("profile.iv_caption")}>
          <Row label={t("profile.iv_notes")} help={t("profile.iv_notes_help")}>
            <Notes
              examples={[1, 2, 3].map((n) => t(`profile.iv_notes_ex${n}`))}
              value={profile.notes}
              placeholder={t("profile.iv_notes_ph")}
              label={t("profile.iv_notes")}
              disabled={saving === "notes"}
              onCommit={(notes) =>
                notes !== profile.notes && commit({ ...profile, notes }, "notes")
              }
              importer
            />
          </Row>
          <Failure message={failure} />
        </Card>
      </div>

      <aside className="pr-rail">
        <Card>
          <div className="pr-sum">
            <span className="pr-sum-t">{t("profile.iv_sum_title")}</span>
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
            <div className="pr-sum-rule" />
            <span className="pr-sum-note">{t("profile.iv_privacy")}</span>
          </div>
          {/* The summary above says what was chosen; this says what the model
              is told. Folded: it is a prompt, and the point of showing it is
              that somebody *can* check the second follows from the first, not
              that they have to read it. A native <details>, as the watchlist
              groups use. */}
          {profile.persona ? (
            <details className="pr-persona">
              <summary>
                <span>{t("profile.iv_persona_open")}</span>
                <Glyph name="expand" size={16} />
              </summary>
              <p className="pr-sum-note">{t("profile.iv_persona_help")}</p>
              <blockquote className="pr-persona-text" lang="en">
                {profile.persona}
              </blockquote>
            </details>
          ) : null}
        </Card>
      </aside>
    </div>
  );
}

/**
 * Somebody who already talks money with another AI has months of context there.
 * Two steps bring it over: copy a request to paste into that chat, then paste
 * its answer back. The request asks for the note's own ceiling, so the summary
 * fits the box instead of being cut where the textarea stops.
 *
 * Full while the note is empty, when it is the quickest way to fill it; one
 * line once there is a note, in the same place, so the field does not jump.
 */
function ImportHint({
  compact,
  disabled,
  onPaste,
}: {
  compact: boolean;
  disabled?: boolean;
  /** Text read from the clipboard; null when the browser would not give it. */
  onPaste: (text: string | null) => void;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const prompt = t("profile.iv_import_prompt", { max: NOTES_MAX });
  const copy = () =>
    navigator.clipboard?.writeText(prompt).then(
      () => setCopied(true),
      () => {},
    );
  // Still holding our own request means the other chat has not answered yet:
  // saving it as the note would hand the assistant its own instructions.
  const paste = () => {
    const read = navigator.clipboard?.readText?.();
    if (!read) return onPaste(null);
    read.then(
      (text) => {
        const got = text.trim();
        onPaste(got && got !== prompt.trim() ? got : null);
      },
      () => onPaste(null),
    );
  };
  const copyBtn = (
    <button
      type="button"
      className={`pr-btn pr-import-btn${!compact && !copied ? " pr-btn-p" : ""}`}
      data-on={copied || undefined}
      onClick={copy}
    >
      <Glyph name={copied ? "check" : "copy"} size={14} />
      {t(copied ? "profile.iv_import_copied" : "profile.iv_import_copy")}
    </button>
  );
  const pasteBtn = (
    <button
      type="button"
      className={`pr-btn pr-import-btn${!compact && copied ? " pr-btn-p" : ""}`}
      disabled={disabled}
      onClick={paste}
    >
      <Glyph name="paste" size={14} />
      {t("profile.iv_import_paste")}
    </button>
  );
  const status = (
    <span className="ag-sr" role="status">
      {copied ? t("profile.iv_import_copied") : ""}
    </span>
  );
  if (compact)
    return (
      <div className="pr-import pr-import-min">
        <span className="pr-import-icon" aria-hidden="true">
          <Glyph name="spark" size={14} />
        </span>
        <span className="pr-import-min-t">{t("profile.iv_import_short")}</span>
        <span className="pr-import-acts">
          {copyBtn}
          {pasteBtn}
        </span>
        {status}
      </div>
    );
  return (
    <section className="pr-import" aria-labelledby="pr-import-t">
      <div className="pr-import-head">
        <span className="pr-import-icon" aria-hidden="true">
          <Glyph name="spark" size={18} />
        </span>
        <div className="pr-import-text">
          <b id="pr-import-t">{t("profile.iv_import_title")}</b>
          <span>{t("profile.iv_import_body")}</span>
        </div>
      </div>
      <ol className="pr-import-steps">
        <li data-done={copied || undefined}>
          <span className="pr-import-n" aria-hidden="true">
            {copied ? <Glyph name="check" size={12} /> : "1"}
          </span>
          <span className="pr-import-step">{t("profile.iv_import_step1")}</span>
          {copyBtn}
        </li>
        <li>
          <span className="pr-import-n" aria-hidden="true">
            2
          </span>
          <span className="pr-import-step">{t("profile.iv_import_step2")}</span>
          {pasteBtn}
        </li>
      </ol>
      {status}
    </section>
  );
}

function joined(keys: string[], labelOf: (key: string) => string, none: string) {
  return keys.length ? keys.map(labelOf).join(", ") : none;
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="pr-sum-row">
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
export function Notes({
  value,
  label,
  placeholder,
  disabled,
  examples = [],
  importer = false,
  onCommit,
}: {
  /** Sentences that append to the note with a touch. */
  examples?: string[];
  /** Offer to bring the note over from another AI chat (`ImportHint`). */
  importer?: boolean;
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
  const field = useRef<HTMLTextAreaElement>(null);
  const add = (text: string) => {
    const next = draft.trim() ? `${draft.trim()} ${text}` : text;
    if (next.length > NOTES_MAX) return;
    setDraft(next);
    onCommit(next);
  };
  // A pasted answer fills what room is left rather than being refused whole:
  // the request asked for the ceiling, and an answer a little over it is still
  // mostly worth keeping. No clipboard access: the caret goes to the field so
  // the person pastes it themselves.
  const pasted = (text: string | null) => {
    if (text === null) return field.current?.focus();
    const room = NOTES_MAX - (draft.trim() ? draft.trim().length + 1 : 0);
    if (room > 0) add(text.slice(0, room).trim());
  };
  return (
    <>
      {importer && (
        <ImportHint
          compact={draft.trim() !== ""}
          disabled={disabled}
          onPaste={pasted}
        />
      )}
      <textarea
        ref={field}
        className="pr-notes"
        rows={4}
        value={draft}
        maxLength={NOTES_MAX}
        aria-label={label}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => onCommit(draft.trim())}
      />
      <span className="pr-hint pr-notes-n">
        {draft.length} / {NOTES_MAX}
      </span>
      {examples.length > 0 && (
        <div className="pr-chips">
          {examples.map((text) => (
            <button
              key={text}
              type="button"
              className="pr-btn"
              disabled={disabled}
              onClick={() => add(text)}
            >
              + {text}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
