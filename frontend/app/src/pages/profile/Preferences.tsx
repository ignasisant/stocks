/**
 * The Preferences tab: interface, tax residence, the data and the account
 * itself — in the Streamlit page's order — and a rail carrying the guided tour
 * and a summary of what is set.
 *
 * Every row saves itself the moment it is changed — the tab strip promises it,
 * and a Save button here would be the one place that broke the promise. The
 * two exceptions prove it: the export is a download and the deletion is a
 * dialog, and neither is a setting.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useApi } from "../../shell/useApi";
import {
  CHURCH_RATES,
  CURRENCIES,
  LANGUAGES,
  TOP_CURRENCIES,
  activeJurisdiction,
  currencyLabel,
} from "./data";
import type { Jurisdictions } from "./data";
import { DeleteAccount } from "./DeleteAccount";
import type { Settings } from "./prefs";
import { TourCard } from "./TourCard";
import { Card, Chips, Failure, Row, Select, Toggle } from "./ui";

/** `GET /import/last` — only the stamp, which is all the rail shows. */
type LastImport = { imported_at: string | null };

/** Enough of `GET /portfolio/transactions` to know whether there is a book. */
type Ledger = { total: number };

const AUTO = "auto";

/**
 * A figure typed rather than picked: committed when the field is left or
 * Enter is pressed, never on every keystroke — one PATCH per digit would be a
 * request storm and a half-typed number is not a setting.
 */
function NumberField({
  value,
  onCommit,
  label,
  min,
  max,
  step,
  suffix,
  disabled,
}: {
  value: number;
  onCommit: (next: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(String(value));
  const [shown, setShown] = useState(value);
  // The stored value changed under us (a save came back, or was refused and
  // rolled back): show what is stored, not what was typed at it.
  if (shown !== value) {
    setShown(value);
    setDraft(String(value));
  }

  const commit = () => {
    const parsed = Number(draft);
    if (draft.trim() === "" || Number.isNaN(parsed)) {
      setDraft(String(value));
      return;
    }
    if (parsed !== value) onCommit(parsed);
  };

  return (
    <span className="pf-chips">
      <input
        className="pf-input"
        type="number"
        inputMode="decimal"
        aria-label={label}
        value={draft}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      {suffix && <span className="pf-hint">{suffix}</span>}
    </span>
  );
}

export function Preferences({
  prefs,
  saving,
  failure,
  save,
  owner,
}: Settings & {
  /**
   * Whether this is the deployment owner's book (`/me` `owner`), or null while
   * that is not known. Only a known non-owner is offered deletion.
   */
  owner: boolean | null;
}) {
  const t = useT();
  const lastImport = useApi(() => get<LastImport>("/import/last"), []);
  // One row is enough: the question is whether the export has anything to
  // write, and the route 404s on an empty book rather than handing back a
  // zero-byte attachment.
  const ledger = useApi(() => get<Ledger>("/portfolio/transactions", { limit: 1 }), []);

  const langs = [AUTO, ...Object.keys(LANGUAGES)];
  const langLabel = (code: string) =>
    code === AUTO ? t("profile.lang_auto") : (LANGUAGES[code] ?? code);

  // The five in daily use are chips; a currency set from outside them joins
  // the row rather than disappearing behind the disclosure.
  const chips = TOP_CURRENCIES.includes(
    prefs.currency as (typeof TOP_CURRENCIES)[number],
  )
    ? [...TOP_CURRENCIES]
    : [...TOP_CURRENCIES, prefs.currency];
  const rest = CURRENCIES.filter((code) => !chips.includes(code));

  // The jurisdictions come from the server, not from a table transcribed here:
  // the engine ships a country at a time, and a client holding its own copy
  // drops the next one silently. It is a registry read with no I/O behind it,
  // but the tab does not wait on it — language and currency have nothing to do
  // with tax, and a failed read must not take them down with it.
  const table = useApi(() => get<Jurisdictions>("/jurisdictions"), []);
  const rows = table.state === "loaded" ? table.data : null;

  const residences = [AUTO, ...(rows?.jurisdictions ?? []).map((j) => j.code)];
  const residenceLabel = (code: string) => {
    if (code === AUTO) return `🌐 ${t("profile.tax_residence_auto")}`;
    // The flag travels with the row rather than being derived here: two of the
    // codes are not ISO 3166-1 alpha-2 (the tax code is "UK", the country is
    // GB), and that exception lives on the server side of the wire.
    const entry = rows?.jurisdictions.find((j) => j.code === code);
    const name = t(`profile.tax_residence_${code.toLowerCase()}`);
    return `${entry?.flag ?? ""} ${name}`.trim();
  };

  // What the pick actually decides — read off the jurisdiction, so it stays
  // honest when a country's rules change.
  const active = rows ? activeJurisdiction(rows, prefs.tax_residence) : null;
  const yearRule = !active
    ? ""
    : active.year_start[0] === 1 && active.year_start[1] === 1
      ? t("profile.tax_year_calendar")
      : t("profile.tax_year_from", {
          day: active.year_start[1],
          month: active.year_start[0],
        });
  const matchLabel = active ? t(`profile.tax_match_${active.matching}`) : "";
  const fail = (field: string) => (failure?.field === field ? failure.message : null);

  return (
    <div className="pf-body">
      <div className="pf-main">
        <Card title={t("profile.ui_section")} sub={t("profile.ui_section_sub")}>
          <Row label={t("profile.language")} help={t("profile.language_caption")}>
            <Select
              label={t("profile.language")}
              value={prefs.language ?? AUTO}
              options={langs}
              labelOf={langLabel}
              disabled={saving === "language"}
              onPick={(code) => {
                // Re-picking what is already set would reload the whole app
                // for nothing — the language decides which catalog it fetches.
                const next = code === AUTO ? null : code;
                if (next !== prefs.language) save("language", next);
              }}
            />
            <Failure message={fail("language")} />
          </Row>

          <Row
            label={t("profile.display_currency")}
            help={t("profile.currency_caption")}
          >
            <Chips
              value={prefs.currency}
              options={chips}
              labelOf={currencyLabel}
              disabled={saving === "currency"}
              onPick={(code) => code !== prefs.currency && save("currency", code)}
            />
            {rest.length > 0 && (
              <details className="pf-more">
                <summary>{t("profile.currency_more", { n: rest.length })}</summary>
                <div>
                  <Chips
                    value={prefs.currency}
                    options={rest}
                    labelOf={currencyLabel}
                    disabled={saving === "currency"}
                    onPick={(code) => code !== prefs.currency && save("currency", code)}
                  />
                </div>
              </details>
            )}
            {/* What is behind the disclosure, without opening it — the
                Streamlit row prints the same line under its popover. Codes
                only, so there is nothing in it to translate. */}
            {rest.length > 0 && <span className="pf-morehint">{rest.join(" · ")}</span>}
            <Failure message={fail("currency")} />
          </Row>
        </Card>

        <Card title={t("profile.tax_section")} note={t("profile.tax_legal_note")}>
          <Row
            label={t("profile.tax_residence")}
            help={t("profile.tax_residence_caption")}
          >
            <Select
              label={t("profile.tax_residence")}
              value={prefs.tax_residence ?? AUTO}
              options={residences}
              labelOf={residenceLabel}
              disabled={saving === "tax_residence"}
              onPick={(code) => {
                const next = code === AUTO ? null : code;
                if (next !== prefs.tax_residence) save("tax_residence", next);
              }}
            />
            <Failure message={fail("tax_residence")} />
            {active ? (
              <div className="pf-rules">
                <div className="pf-rule">
                  <span className="pf-rule-k">{t("profile.tax_rule_cost")}</span>
                  <span className="pf-rule-v">
                    {active.currency} · {t("profile.tax_rule_fx")}
                  </span>
                </div>
                <div className="pf-rule">
                  <span className="pf-rule-k">{t("profile.tax_rule_matching")}</span>
                  <span className="pf-rule-v">{matchLabel}</span>
                </div>
                <div className="pf-rule">
                  <span className="pf-rule-k">{t("profile.tax_rule_year")}</span>
                  <span className="pf-rule-v">{yearRule}</span>
                </div>
              </div>
            ) : null}
          </Row>

          {/* Only the knobs this jurisdiction actually reads, in its own order:
              Spain's savings base has no filing status and no bracket to stack
              income on, so an ES account sees nothing below. */}
          {(active?.settings_fields ?? []).map((field) => {
            const code = active!.code.toLowerCase();
            if (field === "filing_status")
              return (
                <Row
                  key={field}
                  label={t("profile.tax_filing_status")}
                  help={t(`profile.tax_filing_status_caption_${code}`)}
                >
                  <Select
                    label={t("profile.tax_filing_status")}
                    value={
                      active!.filing_statuses.includes(prefs.tax_filing_status)
                        ? prefs.tax_filing_status
                        : (active!.filing_statuses[0] ?? "single")
                    }
                    options={active!.filing_statuses}
                    labelOf={(status) => t(`profile.tax_status_${status}`)}
                    disabled={saving === "tax_filing_status"}
                    onPick={(status) => save("tax_filing_status", status)}
                  />
                  <Failure message={fail("tax_filing_status")} />
                </Row>
              );
            if (field === "church_tax_rate")
              return (
                <Row
                  key={field}
                  label={t("profile.tax_church")}
                  help={t("profile.tax_church_caption")}
                >
                  <Select
                    label={t("profile.tax_church")}
                    value={String(
                      CHURCH_RATES.includes(
                        prefs.tax_church_rate as (typeof CHURCH_RATES)[number],
                      )
                        ? prefs.tax_church_rate
                        : 0,
                    )}
                    options={CHURCH_RATES.map(String)}
                    labelOf={(rate) =>
                      t(`profile.tax_church_${Math.round(Number(rate) * 100)}`)
                    }
                    disabled={saving === "tax_church_rate"}
                    onPick={(rate) => save("tax_church_rate", Number(rate))}
                  />
                  <Failure message={fail("tax_church_rate")} />
                </Row>
              );
            if (field === "other_income")
              return (
                <Row
                  key={field}
                  label={t("profile.tax_other_income")}
                  help={t(`profile.tax_other_income_caption_${code}`)}
                >
                  <NumberField
                    label={t("profile.tax_other_income")}
                    value={prefs.tax_other_income}
                    min={0}
                    step={1000}
                    suffix={active!.currency}
                    disabled={saving === "tax_other_income"}
                    onCommit={(value) => save("tax_other_income", value)}
                  />
                  <Failure message={fail("tax_other_income")} />
                </Row>
              );
            if (field === "subnational_rate")
              return (
                /* Entered as a percentage because that is how every rate table
                   prints it; stored as the fraction the API insists on. */
                <Row
                  key={field}
                  label={t("profile.tax_subnational")}
                  help={t("profile.tax_subnational_caption")}
                >
                  <NumberField
                    label={t("profile.tax_subnational")}
                    value={Math.round(prefs.tax_subnational_rate * 10000) / 100}
                    min={0}
                    max={100}
                    step={0.5}
                    suffix="%"
                    disabled={saving === "tax_subnational_rate"}
                    onCommit={(percent) =>
                      save("tax_subnational_rate", Math.round(percent * 100) / 10000)
                    }
                  />
                  <Failure message={fail("tax_subnational_rate")} />
                </Row>
              );
            return (
              <Row
                key={field}
                label={t("profile.tax_niit")}
                help={t("profile.tax_niit_caption")}
                middle
              >
                <Toggle
                  label={t("profile.tax_niit")}
                  checked={prefs.tax_niit}
                  disabled={saving === "tax_niit"}
                  onToggle={(on) => save("tax_niit", on)}
                />
                <Failure message={fail("tax_niit")} />
              </Row>
            );
          })}
        </Card>
        <Card title={t("profile.data_section")}>
          <Row label={t("profile.export_title")} help={t("profile.export_help")}>
            {/* A plain link, because a download is a navigation the browser
                does: fetching it would buffer the whole ledger in memory only
                to hand it straight back to the same browser, and lose the
                filename the server puts in Content-Disposition. */}
            {ledger.state === "loaded" && ledger.data.total > 0 ? (
              <a className="pf-download" href="/api/v1/portfolio/transactions.csv">
                {t("profile.export_button")}
              </a>
            ) : (
              <span className="pf-muted">{t("profile.export_none")}</span>
            )}
          </Row>
          {/* The other half of the promise the privacy policy makes: the data
              can be taken out, and it can be erased. Never offered to the
              owner, as the Streamlit page never offers it: that "account" is
              the repo-root files the CLI shares, and `DELETE /account` refuses
              it — a button that can only fail is not a control. */}
          {owner === false && <DeleteAccount />}
        </Card>
      </div>

      <aside className="pf-rail">
        <TourCard />
        <Card>
          <div className="pf-sum">
            <span className="pf-sum-t">{t("profile.summary_title")}</span>
            <div className="pf-sum-row">
              <span>{t("profile.language")}</span>
              {/* Short forms on purpose: a 320px rail is a summary, not a
                  second copy of the controls. */}
              <b>{(langLabel(prefs.language ?? AUTO).split("(")[0] ?? "").trim()}</b>
            </div>
            <div className="pf-sum-row">
              <span>{t("profile.display_currency")}</span>
              <b>{prefs.currency}</b>
            </div>
            <div className="pf-sum-row">
              <span>{t("profile.tax_section")}</span>
              <b>
                {/* Behind its flag, as `tax_ui.label` draws it there: eleven
                    countries is where a list of names wants something to
                    scan by, and the flag comes off the row, not a table. */}
                {active
                  ? `${active.flag ? `${active.flag} ` : ""}${(
                      t(`profile.tax_residence_${active.code.toLowerCase()}`).split(
                        "—",
                      )[0] ?? ""
                    ).trim()} · ${matchLabel}`
                  : t("common.loading")}
              </b>
            </div>
            <div className="pf-sum-row">
              <span>{t("profile.summary_last_import")}</span>
              <b>
                {lastImport.state === "loaded"
                  ? (lastImport.data.imported_at?.slice(0, 10) ??
                    t("profile.summary_never"))
                  : t("common.loading")}
              </b>
            </div>
            <div className="pf-sum-rule" />
            <span className="pf-sum-note">{t("profile.summary_note")}</span>
          </div>
        </Card>
      </aside>
    </div>
  );
}
