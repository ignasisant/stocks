/**
 * The header's per-ticker actions: favourite, then "More" with alert rules,
 * tag groups, the decision journal and sharing.
 *
 * Every one of these writes to this account's watchlist, and every one of them
 * is an upsert: favouriting or tagging a symbol that is only held — or only
 * searched for — lists it. That is why they go through POST /watchlist rather
 * than PATCH, which answers 404 for precisely the symbols somebody is most
 * likely to be starring.
 *
 * The alert editor asks the server what a rule can ask for (`/alert-types`,
 * from `config.ALERT_FORMS`), so a type added there shows up here without this
 * editor being edited.
 */

import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Glyph } from "../../chat/icons";
import { useT } from "../../shell/i18n";
import { useMobile } from "../../shell/useMobile";
import { usePresence, useSwipeDismiss } from "../../shell/useSheet";
import { useTickerJournal, type JournalEntry } from "../../ui/Journal";
import { complete, draft, duplicateAt, payload, summary } from "./alerts";
import { follow, getAlertTypes, getAlerts, getTags, setAlerts } from "./data";
import { useTickerShare } from "./Share";
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
  // Set by "Add" and cleared by the next edit: the draft then equals the rule
  // it just made, and the line under the button says "added", not "repeat".
  const [added, setAdded] = useState(false);

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
    setAdded(false);
  };

  const sent = form && rule ? payload(form, rule) : null;
  const repeat = sent ? duplicateAt(rules, sent) : -1;
  const ready = !!form && !!rule && complete(form, rule) && repeat < 0;

  const add = (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !sent) return;
    onRules([...rules, sent]);
    setAdded(true);
  };

  return (
    <form className="tk-editor" onSubmit={add} noValidate>
      <p className="tk-editor-help">{t("widgets.alerts_caption")}</p>
      {rules.length > 0 ? (
        <ul className="tk-rules">
          {rules.map((one, index) => (
            <li
              key={`${one.type}-${index}`}
              className={index === repeat && !added ? "tk-rule-same" : undefined}
            >
              <span>{summary(one, t)}</span>
              <button
                type="button"
                className="tk-x"
                title={t("widgets.alert_removed")}
                aria-label={t("widgets.alert_removed")}
                onClick={() => {
                  onRules(rules.filter((_, at) => at !== index));
                  setAdded(false);
                }}
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
          setAdded(false);
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
            inputMode="decimal"
            enterKeyHint="done"
            aria-label={t(`widgets.alert_${form.field}`)}
            aria-describedby="tk-alert-status"
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
            inputMode="numeric"
            enterKeyHint="done"
            aria-label={t("widgets.alert_window")}
            min={2}
            value={rule.window ?? form.window}
            onChange={(event) => set("window", Math.trunc(Number(event.target.value)))}
          />
        </>
      ) : null}

      <button type="submit" className="tk-add" disabled={!ready}>
        {t("widgets.alert_add")}
      </button>
      {/* Why the button is off, or that it worked: said in place, never as
          a dialog. Always rendered, so a screen reader hears the change. */}
      <p id="tk-alert-status" className="tk-editor-help tk-alert-status" role="status">
        {added
          ? t("widgets.alert_added", { ticker })
          : repeat >= 0
            ? t("widgets.alert_duplicate")
            : ""}
      </p>
    </form>
  );
}

type View = "menu" | "alerts" | "tags";

/** One row of the "More" menu: what it opens, and how many it holds. */
type Row = { id: string; label: string; count?: number; pick: () => void };

/**
 * "More": the header's overflow, one level under the page. A popover hanging
 * from its trigger on a wide page, a sheet from the foot of a narrow one —
 * portalled to the body there, since `.ag-main` is a size container and the
 * containing block of anything fixed inside it.
 *
 * Alerts and tags are edited in place: the row swaps the menu for its editor
 * under a back button, so the panel is one thing that changes, not a second
 * one stacked on the first.
 */
function MoreMenu({
  rows,
  view,
  onView,
  editor,
}: {
  rows: Row[];
  view: View | null;
  onView: (next: View | null) => void;
  editor: (view: Exclude<View, "menu">) => ReactNode;
}) {
  const t = useT();
  const sheet = useMobile();
  const open = view !== null;
  const presence = usePresence(open);
  // The view it was closed on stays drawn while it leaves.
  const drawn = useRef<View>("menu");
  if (view) drawn.current = view;
  const showing = drawn.current;

  const box = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  // The row an editor was opened from, focused again on the way back.
  const from = useRef(0);

  const close = useCallback(
    (refocus = false) => {
      onView(null);
      if (refocus) toggle.current?.focus();
    },
    [onView],
  );

  useEffect(() => {
    if (!open) return;
    // Pointerdown, not click, so a row's own handler still runs first.
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (box.current?.contains(target) || panel.current?.contains(target)) return;
      onView(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, onView]);

  useEffect(() => {
    if (view === "menu") items.current[from.current]?.focus();
    else if (view) back.current?.focus();
  }, [view]);

  // An editor may scroll, so there only its head drags; the menu drags whole.
  useSwipeDismiss(panel, "y", () => onView(null), {
    enabled: sheet && open,
    handle: showing === "menu" ? undefined : ".tk-more-drag",
  });

  const walk = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    }
    if (showing !== "menu") return;
    if (event.key === "Tab") {
      onView(null);
      return;
    }
    const list = items.current.filter(Boolean) as HTMLButtonElement[];
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "ArrowDown"
        ? (at + 1) % list.length
        : event.key === "ArrowUp"
          ? (at - 1 + list.length) % list.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? list.length - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    list[next]?.focus();
  };

  const body =
    showing === "menu" ? (
      <div role="menu" aria-label={t("ticker.more")} className="tk-more-list">
        {rows.map((row, n) => (
          <Fragment key={row.id}>
            {/* Passing the page on is not an edit to the reader's own list. */}
            {row.id === "share" ? (
              <div role="separator" className="tk-more-sep" />
            ) : null}
            <button
              ref={(el) => {
                items.current[n] = el;
              }}
              type="button"
              role="menuitem"
              className="tk-more-item"
              onClick={() => {
                from.current = n;
                row.pick();
              }}
            >
              <span>{row.label}</span>
              {row.count ? <span className="tk-more-count">{row.count}</span> : null}
            </button>
          </Fragment>
        ))}
      </div>
    ) : (
      <div role="group" aria-label={t(`widgets.${showing}`)}>
        <div className="tk-more-head tk-more-drag">
          <button
            ref={back}
            type="button"
            className="tk-icon"
            aria-label={t("nav.back")}
            title={t("nav.back")}
            onClick={() => onView("menu")}
          >
            <Glyph name="back" size={18} />
          </button>
          <span className="tk-more-title">{t(`widgets.${showing}`)}</span>
        </div>
        {editor(showing)}
      </div>
    );

  const drawer = presence.mounted ? (
    <div
      ref={panel}
      className={sheet ? "tk-more-sheet" : "tk-more-panel"}
      data-leaving={presence.leaving ? "" : undefined}
      data-view={showing}
      onKeyDown={walk}
    >
      {sheet ? <span className="tk-grabber tk-more-drag" aria-hidden="true" /> : null}
      {body}
    </div>
  ) : null;

  return (
    <div className="tk-more" ref={box}>
      <button
        ref={toggle}
        type="button"
        className={open ? "tk-icon tk-icon-on" : "tk-icon"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("ticker.more")}
        title={t("ticker.more")}
        onClick={() => {
          from.current = 0;
          onView(open ? null : "menu");
        }}
      >
        <Glyph name="more" size={20} />
      </button>
      {sheet && drawer
        ? createPortal(
            <div
              className="tk-more-veil"
              data-leaving={presence.leaving ? "" : undefined}
            >
              {drawer}
            </div>,
            document.body,
          )
        : drawer}
    </div>
  );
}

/**
 * What the reader set on this name, for the price card's line of their own
 * marks (`Yours.tsx`): the alert rules and the journal's entries, with the
 * way into each one's editor here in the header.
 */
export type Mine = {
  rules: AlertRule[];
  entries: JournalEntry[];
  openAlerts: () => void;
  openJournal: () => void;
};

/**
 * The header's actions after "Analyse with AI": the star, which is a state one
 * press flips and so stays in sight, and "More" for the rest — alerts, tags,
 * the decision journal, sharing.
 */
export function Actions({
  ticker,
  name,
  held,
  entry,
  onEntry,
  onMine,
}: {
  ticker: string;
  name: string;
  /** Whether the book holds it: the journal is offered to a holder even empty. */
  held: boolean;
  /** This ticker's watchlist row, or null when it is not listed yet. */
  entry: WatchlistEntry | null;
  onEntry: (entry: WatchlistEntry) => void;
  /** Told what the reader set here, and again whenever it changes. */
  onMine?: (mine: Mine | null) => void;
}) {
  const t = useT();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [forms, setForms] = useState<AlertForm[]>([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View | null>(null);
  const journal = useTickerJournal(ticker, name, held);
  const sharing = useTickerShare(ticker, name);

  const favorite = entry?.favorite ?? false;
  const tags = entry?.tags ?? [];

  // Rules belong to the company on screen and the count rides the menu row, so
  // they are fetched on arrival rather than when the editor opens. Only for a
  // listed ticker: rules live on the watchlist row, and the route 404s for
  // one nobody listed — a red line in the console on every other company.
  const listed = entry !== null;
  useEffect(() => {
    setRules([]);
    setView(null);
  }, [ticker]);
  useEffect(() => {
    if (!listed) return;
    let live = true;
    getAlerts(ticker)
      .then((body) => live && setRules(body.alerts))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [ticker, listed]);

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

  // The field table is the same for every ticker and only the editor needs
  // it, so it is fetched once, the first time the editor opens.
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

  const openJournal = journal.open;
  useEffect(() => {
    onMine?.({
      rules,
      entries: journal.entries,
      openAlerts: () => {
        loadForms();
        setView("alerts");
      },
      openJournal: () => {
        setView(null);
        openJournal();
      },
    });
  }, [onMine, rules, journal.entries, loadForms, openJournal]);
  useEffect(() => () => onMine?.(null), [onMine]);

  const rows: Row[] = [
    {
      id: "alerts",
      label: t("widgets.alerts"),
      count: rules.length,
      pick: () => {
        loadForms();
        setView("alerts");
      },
    },
    {
      id: "tags",
      label: t("widgets.tags"),
      count: tags.length,
      pick: () => setView("tags"),
    },
  ];
  if (journal.label)
    rows.push({
      id: "journal",
      label: journal.label,
      count: journal.count,
      pick: () => {
        setView(null);
        journal.open();
      },
    });
  rows.push({
    id: "share",
    label: t("ticker.share_menu"),
    pick: () => {
      setView(null);
      sharing.share();
    },
  });

  const starLabel = t(favorite ? "widgets.remove_favorite" : "widgets.add_favorite");
  return (
    <>
      <button
        type="button"
        className={favorite ? "tk-icon tk-star tk-star-on" : "tk-icon tk-star"}
        aria-pressed={favorite}
        disabled={busy}
        title={starLabel}
        aria-label={starLabel}
        onClick={() => write({ favorite: !favorite })}
      >
        <Glyph name={favorite ? "star_on" : "star"} size={20} />
      </button>
      <MoreMenu
        rows={rows}
        view={view}
        onView={setView}
        editor={(which) =>
          which === "alerts" ? (
            <AlertEditor
              ticker={ticker}
              rules={rules}
              forms={forms}
              onRules={writeAlerts}
            />
          ) : (
            <TagEditor tags={tags} onTags={(next) => write({ tags: next })} />
          )
        }
      />
      {journal.panel}
      {sharing.dialog}
    </>
  );
}
