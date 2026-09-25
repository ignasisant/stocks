/**
 * The watchlist as a working surface: search to add, group, and edit in place.
 *
 * Every edit writes as it is made, through the per-entry routes rather than a
 * whole-list save — `PATCH /watchlist/{ticker}` applies only the fields it is
 * sent, so starring a name cannot overwrite its groups and renaming a group
 * cannot drop a holding outside it. The server's answer is what the list
 * re-renders from.
 *
 * Shares and average cost are here too, as the Streamlit grid has them: the
 * hand-typed position that weights the fallback analytics by value when no
 * ledger has been imported. `GET /watchlist` reads them back (null for "not
 * set"), so each field shows what is stored before anyone can overwrite it.
 */

import { useState } from "react";
import type { Query } from "../../shell/useApi";
import { NotSignedIn, get, send } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Loaded } from "../../shell/Layout";
import { useApi } from "../../shell/useApi";
import { describe } from "./errors";
import { Card, Failure, Prose } from "./ui";
import { WatchlistAdd } from "./WatchlistAdd";
import { TickerCell } from "../../shell/tickers";

type Entry = {
  ticker: string;
  name: string;
  favorite: boolean;
  tags: string[];
  /** Null when unset — 0 on disk and "not a position" either way. */
  shares: number | null;
  cost: number | null;
  is_crypto: boolean;
};

export type Listing = { entries: Entry[] };

/** What a number field holds, as the text box shows it: empty for unset. */
const asText = (value: number | null) => (value ? String(value) : "");

/**
 * A number field's text, as the PATCH wants it — or undefined for "unchanged".
 *
 * Empty (or zero) is 0 on the wire, which is what clears the field; a value
 * that does not parse, or is negative, is left unsent rather than guessed at —
 * the server refuses a negative one anyway, as the grid's `min_value` does.
 */
export function parsed(text: string, before: number | null): number | undefined {
  const trimmed = text.trim().replace(",", ".");
  const value = trimmed === "" ? 0 : Number(trimmed);
  if (!Number.isFinite(value) || value < 0) return undefined;
  return value === (before ?? 0) ? undefined : value;
}

type Mode = "tags" | "favorites" | "flat";
const MODES: readonly Mode[] = ["tags", "favorites", "flat"];

type Section = { id: string; label: string; rows: Entry[]; tag: string | null };

/**
 * The list split into sections, as `watchlist_ui.groups` splits it: favorites
 * first (the app treats them as a group and Overview renders them first), then
 * every tag alphabetically, then whatever carries neither. A ticker in two
 * tags appears in both.
 */
function sections(
  entries: Entry[],
  mode: Mode,
  untagged: string,
  labels: Record<string, string>,
) {
  if (mode === "flat")
    return [{ id: "all", label: labels.all!, rows: entries, tag: null }];
  const out: Section[] = [];
  const favs = entries.filter((entry) => entry.favorite);
  if (favs.length)
    out.push({ id: "fav", label: labels.favorites!, rows: favs, tag: null });
  if (mode === "favorites") {
    const rest = entries.filter((entry) => !entry.favorite);
    if (rest.length)
      out.push({ id: "rest", label: labels.rest!, rows: rest, tag: null });
    return out;
  }
  const byTag = new Map<string, { label: string; rows: Entry[] }>();
  for (const entry of entries)
    for (const tag of entry.tags) {
      const key = tag.toLowerCase();
      const group = byTag.get(key) ?? { label: tag, rows: [] };
      group.rows.push(entry);
      byTag.set(key, group);
    }
  for (const key of [...byTag.keys()].sort()) {
    const group = byTag.get(key)!;
    out.push({
      id: `tag_${key}`,
      label: group.label,
      rows: group.rows,
      tag: group.label,
    });
  }
  const loose = entries.filter((entry) => !entry.tags.length && !entry.favorite);
  if (loose.length) out.push({ id: "none", label: untagged, rows: loose, tag: null });
  return out;
}

function matches(entry: Entry, needle: string): boolean {
  if (!needle) return true;
  const n = needle.trim().toUpperCase();
  return (
    entry.ticker.toUpperCase().includes(n) ||
    (entry.name ?? "").toUpperCase().includes(n) ||
    entry.tags.some((tag) => tag.toUpperCase().includes(n))
  );
}

/** One holding: star, symbol, name, and the groups it belongs to. */
function EntryRow({
  entry,
  tags,
  busy,
  onEdit,
  onRemove,
}: {
  entry: Entry;
  tags: readonly string[];
  busy: boolean;
  onEdit: (ticker: string, body: Record<string, unknown>) => void;
  onRemove: (ticker: string) => void;
}) {
  const t = useT();
  const [name, setName] = useState(entry.name);
  const [named, setNamed] = useState(entry.name);
  const [newGroup, setNewGroup] = useState("");
  const [shares, setShares] = useState(asText(entry.shares));
  const [cost, setCost] = useState(asText(entry.cost));
  const [stored, setStored] = useState([entry.shares, entry.cost]);
  if (named !== entry.name) {
    setNamed(entry.name);
    setName(entry.name);
  }
  // The server's answer replaces what was typed, as the name does: a field
  // that kept its own text after a refused write would show a number nobody
  // stored.
  if (stored[0] !== entry.shares || stored[1] !== entry.cost) {
    setStored([entry.shares, entry.cost]);
    setShares(asText(entry.shares));
    setCost(asText(entry.cost));
  }
  const commit = (field: "shares" | "cost", text: string) => {
    const value = parsed(text, entry[field]);
    if (value === undefined) {
      // Unparseable or unchanged: put back what is stored.
      if (field === "shares") setShares(asText(entry.shares));
      else setCost(asText(entry.cost));
      return;
    }
    onEdit(entry.ticker, { [field]: value });
  };

  const toggleTag = (tag: string) =>
    onEdit(entry.ticker, {
      tags: entry.tags.some((held) => held.toLowerCase() === tag.toLowerCase())
        ? entry.tags.filter((held) => held.toLowerCase() !== tag.toLowerCase())
        : [...entry.tags, tag],
    });

  const known = [...new Set([...tags, ...entry.tags])].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );

  return (
    <div className="pf-wrow">
      <button
        type="button"
        className={entry.favorite ? "pf-star pf-star-on" : "pf-star"}
        aria-label={t("watchlist.col_favorite")}
        aria-pressed={entry.favorite}
        disabled={busy}
        onClick={() => onEdit(entry.ticker, { favorite: !entry.favorite })}
      >
        {entry.favorite ? "★" : "☆"}
      </button>
      {/* Every ticker on screen opens its own page. */}
      <TickerCell ticker={entry.ticker} className="pf-wsym">
        {entry.ticker}
      </TickerCell>
      <input
        className="pf-input pf-input-sm pf-wname"
        aria-label={t("watchlist.col_name")}
        value={name}
        disabled={busy}
        onChange={(event) => setName(event.target.value)}
        onBlur={() => name !== entry.name && onEdit(entry.ticker, { name })}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      {/* Shares and average cost, committed on blur like the name. Text
          boxes with a decimal keyboard rather than type=number: a number
          input swallows a comma decimal ("12,5") into an empty value, and
          half the readers here write decimals that way. */}
      <input
        className="pf-input pf-input-sm pf-wnum"
        aria-label={t("watchlist.col_shares")}
        placeholder={t("watchlist.col_shares")}
        inputMode="decimal"
        value={shares}
        disabled={busy}
        onChange={(event) => setShares(event.target.value)}
        onBlur={() => commit("shares", shares)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <input
        className="pf-input pf-input-sm pf-wnum"
        aria-label={t("watchlist.col_cost")}
        placeholder={t("watchlist.col_cost")}
        title={t("watchlist.col_cost_help")}
        inputMode="decimal"
        value={cost}
        disabled={busy}
        onChange={(event) => setCost(event.target.value)}
        onBlur={() => commit("cost", cost)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <button
        type="button"
        className="pf-btn"
        disabled={busy}
        onClick={() => onRemove(entry.ticker)}
      >
        {t("watchlist.act_remove")}
      </button>
      <details className="pf-wtags">
        <summary>
          {t("watchlist.col_tags")}
          {entry.tags.length ? ` · ${entry.tags.join(", ")}` : ""}
        </summary>
        <div>
          <span className="pf-hint">{t("watchlist.col_tags_help")}</span>
          <div className="pf-chips">
            {known.map((tag) => {
              const on = entry.tags.some(
                (held) => held.toLowerCase() === tag.toLowerCase(),
              );
              return (
                <button
                  key={tag}
                  type="button"
                  className={on ? "pf-chip pf-chip-on" : "pf-chip"}
                  aria-pressed={on}
                  disabled={busy}
                  onClick={() => toggleTag(tag)}
                >
                  {tag}
                </button>
              );
            })}
            <input
              className="pf-input pf-input-sm"
              aria-label={t("watchlist.col_tags")}
              placeholder={t("watchlist.add_groups_ph")}
              value={newGroup}
              disabled={busy}
              onChange={(event) => setNewGroup(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                const tag = newGroup.trim();
                if (!tag) return;
                setNewGroup("");
                toggleTag(tag);
              }}
            />
          </div>
        </div>
      </details>
    </div>
  );
}

/** A section's title and count, plus a tag group's own rename and dissolve. */
function GroupHead({
  section,
  busy,
  onRename,
  onDissolve,
}: {
  section: Section;
  busy: boolean;
  onRename: (tag: string, name: string) => void;
  onDissolve: (tag: string) => void;
}) {
  const t = useT();
  const [name, setName] = useState(section.tag ?? "");
  return (
    <div className="pf-ghead">
      <span className="pf-gt">{section.label}</span>
      <span className="pf-gc">{section.rows.length}</span>
      {section.tag !== null && (
        <details className="pf-more">
          <summary>{t("watchlist.group_manage")}</summary>
          <div className="pf-chips">
            <span className="pf-hint">{t("watchlist.group_manage_help")}</span>
            <input
              className="pf-input pf-input-sm"
              aria-label={t("watchlist.group_rename")}
              value={name}
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
            <button
              type="button"
              className="pf-btn"
              disabled={busy || !name.trim() || name.trim() === section.tag}
              onClick={() => onRename(section.tag!, name.trim())}
            >
              {t("watchlist.group_rename_apply")}
            </button>
            <button
              type="button"
              className="pf-btn"
              disabled={busy}
              title={t("watchlist.group_delete_help")}
              onClick={() => onDissolve(section.tag!)}
            >
              {t("watchlist.group_delete")}
            </button>
          </div>
        </details>
      )}
    </div>
  );
}

function Editor({ entries, reload }: { entries: Entry[]; reload: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  // Where the last refusal happened, so it is shown under the control that
  // caused it rather than twice on the page.
  const [failure, setFailure] = useState<{
    where: "add" | "list";
    message: string;
  } | null>(null);
  const [needle, setNeedle] = useState("");
  const [keep, setKeep] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>("tags");

  const write = (work: Promise<unknown>, where: "add" | "list" = "list") => {
    setBusy(true);
    setFailure(null);
    work.then(
      () => {
        setBusy(false);
        // The server's copy is the truth, and a tag edit can move a row
        // between sections — so the list is re-read rather than patched here.
        reload();
      },
      (error: unknown) => {
        setBusy(false);
        if (error instanceof NotSignedIn) {
          reload();
          return;
        }
        setFailure({ where, message: describe(error, t("common.offline")) });
      },
    );
  };

  const tags = [...new Set(entries.flatMap((entry) => entry.tags))].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );
  const listed = new Set(entries.map((entry) => entry.ticker.toUpperCase()));
  const keeping = new Set(keep.map((tag) => tag.toLowerCase()));
  const shown = entries.filter(
    (entry) =>
      matches(entry, needle) &&
      (!keeping.size || entry.tags.some((tag) => keeping.has(tag.toLowerCase()))),
  );

  return (
    <>
      <WatchlistAdd
        listed={listed}
        tags={tags}
        busy={busy}
        failure={failure?.where === "add" ? failure.message : null}
        onAdd={(entry) => write(send("POST", "/watchlist", entry), "add")}
      />

      {entries.length === 0 ? (
        <Card title={t("profile.empty_watchlist_title")}>
          <div className="pf-cardbody">
            <p className="pf-hint">{t("profile.empty_watchlist_body")}</p>
          </div>
        </Card>
      ) : (
        <Card title={t("watchlist.list_title")} sub={t("watchlist.list_sub")}>
          <div className="pf-cardbody">
            <div className="pf-chips">
              <input
                className="pf-input pf-input-sm"
                type="search"
                aria-label={t("watchlist.filter")}
                placeholder={t("watchlist.filter_ph")}
                value={needle}
                onChange={(event) => setNeedle(event.target.value)}
              />
              {MODES.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={option === mode ? "pf-chip pf-chip-on" : "pf-chip"}
                  aria-pressed={option === mode}
                  onClick={() => setMode(option)}
                >
                  {t(`watchlist.group_${option}`)}
                </button>
              ))}
            </div>
            {tags.length > 0 && (
              <div className="pf-chips">
                <span className="pf-hint">{t("watchlist.tag_filter")}</span>
                {tags.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className={
                      keeping.has(tag.toLowerCase()) ? "pf-chip pf-chip-on" : "pf-chip"
                    }
                    aria-pressed={keeping.has(tag.toLowerCase())}
                    onClick={() =>
                      setKeep((current) =>
                        current.includes(tag)
                          ? current.filter((held) => held !== tag)
                          : [...current, tag],
                      )
                    }
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}

            <Failure message={failure?.where === "list" ? failure.message : null} />

            {shown.length === 0 ? (
              <p className="pf-hint">{t("watchlist.no_match")}</p>
            ) : (
              sections(shown, mode, t("watchlist.g_untagged"), {
                all: t("watchlist.g_all"),
                favorites: t("watchlist.g_favorites"),
                rest: t("watchlist.g_rest"),
              }).map((section) => (
                <div key={section.id}>
                  <GroupHead
                    section={section}
                    busy={busy}
                    onRename={(tag, name) =>
                      write(
                        send("PATCH", `/watchlist/tags/${encodeURIComponent(tag)}`, {
                          name,
                        }),
                      )
                    }
                    onDissolve={(tag) =>
                      write(
                        send("DELETE", `/watchlist/tags/${encodeURIComponent(tag)}`),
                      )
                    }
                  />
                  {section.rows.map((entry) => (
                    <EntryRow
                      key={`${section.id}_${entry.ticker}`}
                      entry={entry}
                      tags={tags}
                      busy={busy}
                      onEdit={(ticker, body) =>
                        write(
                          send(
                            "PATCH",
                            `/watchlist/${encodeURIComponent(ticker)}`,
                            body,
                          ),
                        )
                      }
                      onRemove={(ticker) =>
                        write(
                          send("DELETE", `/watchlist/${encodeURIComponent(ticker)}`),
                        )
                      }
                    />
                  ))}
                </div>
              ))
            )}

            <div className="pf-foot">
              <span className="pf-hint">
                {t("watchlist.count", { n: entries.length })}
              </span>
              <details className="pf-more">
                <summary>{t("watchlist.how_open")}</summary>
                <div>
                  <Prose text={t("watchlist.how")} />
                </div>
              </details>
            </div>
          </div>
        </Card>
      )}
    </>
  );
}

/** `GET /watchlist/suggestions` — examples for the areas the profile declares. */
type Suggestion = { ticker: string; name: string; tags: string[] };

/**
 * Examples for the focus areas the investor profile names.
 *
 * Served, never held here: a list of securities frozen into a bundle goes
 * stale, and a stale list of company names sitting next to somebody's
 * portfolio starts reading as advice. The catalog's own caption says the same
 * thing in the reader's language, and it is not optional decoration.
 *
 * The card disappears as the offer is taken up — the server filters out
 * anything already on the list — so an account that adds them all never sees
 * it again.
 */
function Examples({ onAdded }: { onAdded: () => void }) {
  const t = useT();
  // A nonce rather than a retry: `useApi` only offers `retry` on a failed
  // query, and this one refetches after a *successful* write — the server is
  // what decides which examples are still on offer.
  const [nonce, setNonce] = useState(0);
  const query = useApi(
    () => get<{ suggestions: Suggestion[] }>("/watchlist/suggestions"),
    [nonce],
  );
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  if (query.state !== "loaded" || query.data.suggestions.length === 0) return null;

  const rows = query.data.suggestions;

  function addAll() {
    setBusy(true);
    setFailure(null);
    // One request per entry, because `POST /watchlist` is an upsert of one and
    // there is no bulk route. Sequential rather than parallel: they all write
    // the same YAML file, and the last writer would win.
    void rows
      .reduce(
        (chain, row) =>
          chain.then(() =>
            send("POST", "/watchlist", {
              ticker: row.ticker,
              name: row.name,
              tags: row.tags,
            }).then(() => undefined),
          ),
        Promise.resolve(),
      )
      .then(() => {
        setNonce((n) => n + 1);
        onAdded();
      })
      .catch((error: unknown) => setFailure(describe(error, t("common.offline"))))
      .finally(() => setBusy(false));
  }

  return (
    <Card title={t("profile.focus_suggest_title")}>
      <Prose text={t("profile.focus_suggest_help")} />
      <ul className="pf-examples">
        {rows.map((row) => (
          <li key={row.ticker}>
            <TickerCell ticker={row.ticker} className="pf-wsym" />
            <span>{row.name}</span>
          </li>
        ))}
      </ul>
      <button type="button" className="pf-linkbtn" disabled={busy} onClick={addAll}>
        {t("profile.focus_suggest_add", { n: rows.length })}
      </button>
      <Failure message={failure} />
    </Card>
  );
}

/**
 * The tab's body. The listing is read by the page, not here, because the tab
 * strip carries its count (the Streamlit tab's badge) — one request for both,
 * and an edit that reloads it moves the badge too.
 */
export function Watchlist({ query }: { query: Query<Listing> }) {
  return (
    <div className="pf-main">
      <Loaded query={query}>
        {(data, reload) => (
          <>
            <Editor entries={data.entries} reload={reload} />
            <Examples onAdded={reload} />
          </>
        )}
      </Loaded>
    </div>
  );
}
