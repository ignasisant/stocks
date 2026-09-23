/**
 * The header's per-ticker actions: favourite, tag groups, alert rules.
 *
 * Every one of these writes to this account's watchlist, and every one of them
 * is an upsert: favouriting or tagging a symbol that is only held — or only
 * searched for — lists it, exactly as the Streamlit app has always behaved.
 * That is why they go through POST /watchlist rather than PATCH, which answers
 * 404 for precisely the symbols somebody is most likely to be starring.
 *
 * The alert editor asks the server what a rule can ask for (`/alert-types`).
 * The app's widget reads the same table from the domain, so a type added there
 * shows up in both editors without either one being edited.
 */

import { useCallback, useEffect, useState } from "react";
import { useT } from "../../shell/i18n";
import { complete, draft, payload, summary } from "./alerts";
import { follow, getAlertTypes, getAlerts, getTags, setAlerts } from "./data";
import { Popover } from "./ui";
import type { AlertForm, AlertRule, WatchlistEntry } from "./types";

function TagEditor({
  tags,
  onTags,
}: {
  tags: string[];
  onTags: (next: string[]) => void;
}) {
  const t = useT();
  const [known, setKnown] = useState<string[]>([]);
  const [typed, setTyped] = useState("");

  useEffect(() => {
    getTags()
      .then((body) => setKnown(body.tags))
      .catch(() => undefined);
  }, []);

  const add = (raw: string) => {
    const tag = raw.trim();
    // Case-insensitively already there is already there: the app's multiselect
    // cannot offer a duplicate, and typing one here must not create a second.
    if (!tag || tags.some((one) => one.toLowerCase() === tag.toLowerCase())) {
      setTyped("");
      return;
    }
    onTags([...tags, tag]);
    setTyped("");
  };

  const unused = known.filter(
    (tag) => !tags.some((one) => one.toLowerCase() === tag.toLowerCase()),
  );

  return (
    <div className="tk-editor">
      <p className="tk-editor-label">{t("widgets.tag_groups")}</p>
      {tags.length > 0 ? (
        <p className="tk-chips">
          {tags.map((tag) => (
            <span className="tk-group" key={tag}>
              {tag}
              <button
                type="button"
                className="tk-x"
                aria-label={tag}
                onClick={() => onTags(tags.filter((one) => one !== tag))}
              >
                ×
              </button>
            </span>
          ))}
        </p>
      ) : null}
      <input
        className="tk-field"
        list="tk-tag-options"
        value={typed}
        placeholder={t("widgets.tags_placeholder")}
        onChange={(event) => setTyped(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          add(typed);
        }}
        onBlur={() => add(typed)}
      />
      {/* Free-form with suggestions, which is what `accept_new_options` is: the
          account's existing groups are offered, a new one is just typed. */}
      <datalist id="tk-tag-options">
        {unused.map((tag) => (
          <option value={tag} key={tag} />
        ))}
      </datalist>
      <p className="tk-editor-help">{t("widgets.tags_help")}</p>
    </div>
  );
}

function AlertEditor({
  ticker,
  rules,
  forms,
  onRules,
}: {
  ticker: string;
  rules: AlertRule[];
  forms: AlertForm[];
  onRules: (next: AlertRule[]) => void;
}) {
  const t = useT();
  const [type, setType] = useState("");
  const [drafted, setDrafted] = useState<AlertRule | null>(null);

  // The first form the server sent leads, as the app's selectbox does.
  useEffect(() => {
    const first = forms[0];
    if (type || !first) return;
    setType(first.type);
    setDrafted(draft(first));
  }, [forms, type]);

  const form = forms.find((one) => one.type === type);
  const rule = drafted ?? (form ? draft(form) : null);

  const set = (field: "price" | "pct" | "level" | "window", value: number) => {
    if (!rule) return;
    setDrafted({ ...rule, [field]: value });
  };

  return (
    <div className="tk-editor">
      <p className="tk-editor-help">{t("widgets.alerts_caption")}</p>
      {rules.length > 0 ? (
        <ul className="tk-rules">
          {rules.map((one, index) => (
            <li key={`${one.type}-${index}`}>
              <span>{summary(one, t)}</span>
              <button
                type="button"
                className="tk-x"
                title={t("widgets.alert_removed")}
                aria-label={t("widgets.alert_removed")}
                onClick={() => onRules(rules.filter((_, at) => at !== index))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="tk-editor-help">{t("widgets.alert_none", { ticker })}</p>
      )}

      <p className="tk-editor-label">{t("widgets.alert_type")}</p>
      <select
        className="tk-field"
        aria-label={t("widgets.alert_type")}
        value={type}
        onChange={(event) => {
          const next = forms.find((one) => one.type === event.target.value);
          setType(event.target.value);
          // A fresh draft per type: carrying the last one over would send a
          // price on a rule that reads a percentage.
          setDrafted(next ? draft(next) : null);
        }}
      >
        {forms.map((one) => (
          <option value={one.type} key={one.type}>
            {t(`widgets.alert_t_${one.type}`)}
          </option>
        ))}
      </select>

      {form?.field && rule ? (
        <>
          <p className="tk-editor-label">{t(`widgets.alert_${form.field}`)}</p>
          <input
            className="tk-field"
            type="number"
            aria-label={t(`widgets.alert_${form.field}`)}
            min={0}
            max={form.field === "level" ? 100 : undefined}
            value={rule[form.field] ?? 0}
            onChange={(event) => set(form.field!, Number(event.target.value))}
          />
        </>
      ) : null}
      {form && form.window !== null && rule ? (
        <>
          <p className="tk-editor-label">{t("widgets.alert_window")}</p>
          <input
            className="tk-field"
            type="number"
            aria-label={t("widgets.alert_window")}
            min={2}
            value={rule.window ?? form.window}
            onChange={(event) => set("window", Math.trunc(Number(event.target.value)))}
          />
        </>
      ) : null}

      <button
        type="button"
        className="tk-add"
        disabled={!form || !rule || !complete(form, rule)}
        onClick={() => form && rule && onRules([...rules, payload(form, rule)])}
      >
        {t("widgets.alert_add")}
      </button>
    </div>
  );
}

export function Actions({
  ticker,
  entry,
  onEntry,
}: {
  ticker: string;
  /** This ticker's watchlist row, or null when it is not listed yet. */
  entry: WatchlistEntry | null;
  onEntry: (entry: WatchlistEntry) => void;
}) {
  const t = useT();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [forms, setForms] = useState<AlertForm[]>([]);
  const [busy, setBusy] = useState(false);

  const favorite = entry?.favorite ?? false;
  const tags = entry?.tags ?? [];

  // Rules belong to the company on screen and the count rides the button, so
  // they are fetched on arrival rather than when the panel opens. The route
  // 404s for a ticker nobody has listed — that is "no rules", not a failure.
  useEffect(() => {
    let live = true;
    setRules([]);
    getAlerts(ticker)
      .then((body) => live && setRules(body.alerts))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker]);

  const write = useCallback(
    (fields: { favorite?: boolean; tags?: string[] }) => {
      setBusy(true);
      follow(ticker, fields)
        .then(onEntry)
        .catch(() => undefined)
        .finally(() => setBusy(false));
    },
    [ticker, onEntry],
  );

  // The field table is the same for every ticker and only the open panel needs
  // it, so it is fetched once, on the first open.
  const loadForms = useCallback(() => {
    if (forms.length) return;
    getAlertTypes()
      .then((body) => setForms(body.forms))
      .catch(() => undefined);
  }, [forms.length]);

  const writeAlerts = useCallback(
    (next: AlertRule[]) => {
      const before = rules;
      setRules(next); // optimistic: the list is the only feedback there is
      const save = () =>
        setAlerts(ticker, next)
          .then((body) => setRules(body.alerts))
          .catch(() => setRules(before));
      // A rule on an unlisted ticker lists it first, as `auth.set_alerts` does
      // in the app — the alert routes themselves refuse a ticker they cannot
      // find, and refusing is right for a typed symbol but not for this one.
      if (entry) void save();
      else
        follow(ticker, {})
          .then(onEntry)
          .then(save)
          .catch(() => setRules(before));
    },
    [ticker, rules, entry, onEntry],
  );

  return (
    <div className="tk-actions">
      <button
        type="button"
        className={favorite ? "tk-star tk-star-on" : "tk-star"}
        aria-pressed={favorite}
        disabled={busy}
        title={t(favorite ? "widgets.remove_favorite" : "widgets.add_favorite")}
        aria-label={t(favorite ? "widgets.remove_favorite" : "widgets.add_favorite")}
        onClick={() => write({ favorite: !favorite })}
      >
        ★
      </button>
      <Popover label={`${t("widgets.tags")}${tags.length ? ` (${tags.length})` : ""}`}>
        <TagEditor tags={tags} onTags={(next) => write({ tags: next })} />
      </Popover>
      <Popover
        label={`${t("widgets.alerts")}${rules.length ? ` (${rules.length})` : ""}`}
        onOpen={loadForms}
      >
        <AlertEditor
          ticker={ticker}
          rules={rules}
          forms={forms}
          onRules={writeAlerts}
        />
      </Popover>
      {/* The groups this ticker is in, readable without opening anything — the
          Streamlit page prints them under the header row for the same reason. */}
      {tags.length > 0 ? (
        <span className="tk-groups">
          {tags.map((tag) => (
            <span className="tk-group" key={tag}>
              {tag}
            </span>
          ))}
        </span>
      ) : null}
    </div>
  );
}
