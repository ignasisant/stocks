/**
 * Find a ticker and follow it.
 *
 * The same tiers the top-bar picker searches — this account's list, coins,
 * funds, the SEC company map, worldwide Yahoo — so a symbol is added by
 * picking it, with its real name, rather than spelled from memory into a blank
 * row. `POST /watchlist` is an upsert, so naming the ticker is enough; the
 * groups and the star ride along with it.
 */

import { useEffect, useState } from "react";
import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Card, Failure } from "./ui";

type Match = { ticker: string; name: string; kind: string; exchange: string };
type Results = { query: string; matches: Match[] };

/**
 * `/search` names its escape-hatch tier `analyze`; the catalog calls that row
 * `kind_raw`, which is the name `search.candidates` gives the same tier.
 */
const KIND_KEY: Record<string, string> = { analyze: "raw" };

/** Two characters, as the hint promises — one letter matches half of Yahoo. */
const MIN_QUERY = 2;

export function WatchlistAdd({
  listed,
  tags,
  onAdd,
  busy,
  failure,
}: {
  listed: ReadonlySet<string>;
  tags: readonly string[];
  /** The upsert body: `ticker` plus whatever the reader actually set. */
  onAdd: (entry: {
    ticker: string;
    name: string;
    favorite?: true;
    tags?: string[];
  }) => void;
  busy: boolean;
  failure: string | null;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [into, setInto] = useState<string[]>([]);
  const [newGroup, setNewGroup] = useState("");
  const [star, setStar] = useState(false);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [searchFailed, setSearchFailed] = useState<string | null>(null);

  const term = query.trim();
  useEffect(() => {
    if (term.length < MIN_QUERY) {
      setMatches(null);
      return;
    }
    // Typing is not a request per keystroke: the field settles first.
    let live = true;
    const timer = window.setTimeout(() => {
      get<Results>("/search", { q: term, limit: 8 }).then(
        (results) => live && (setMatches(results.matches), setSearchFailed(null)),
        () => live && (setMatches([]), setSearchFailed(t("common.offline"))),
      );
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term]);

  const pick = (match: Match) => {
    // POST is an upsert, and only the fields sent are applied: an empty group
    // list is left out rather than sent, so re-adding a symbol somebody else
    // just listed cannot wipe the groups it already carries.
    onAdd({
      ticker: match.ticker,
      name: match.name,
      ...(star ? { favorite: true } : {}),
      ...(into.length ? { tags: into } : {}),
    });
    setQuery("");
    setMatches(null);
  };

  const groups = [...new Set([...tags, ...into])].sort((a, b) =>
    a.toLowerCase().localeCompare(b.toLowerCase()),
  );

  return (
    <Card title={t("watchlist.add_title")} sub={t("watchlist.add_sub")}>
      <div className="pf-cardbody">
        <input
          className="pf-input pf-input-wide"
          type="search"
          aria-label={t("watchlist.add_title")}
          placeholder={t("watchlist.add_placeholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="pf-chips">
          <span className="pf-hint">{t("watchlist.add_groups")}</span>
          {groups.map((tag) => (
            <button
              key={tag}
              type="button"
              className={into.includes(tag) ? "pf-chip pf-chip-on" : "pf-chip"}
              aria-pressed={into.includes(tag)}
              onClick={() =>
                setInto((current) =>
                  current.includes(tag)
                    ? current.filter((n) => n !== tag)
                    : [...current, tag],
                )
              }
            >
              {tag}
            </button>
          ))}
          <input
            className="pf-input pf-input-sm"
            aria-label={t("watchlist.add_groups")}
            placeholder={t("watchlist.add_groups_ph")}
            value={newGroup}
            onChange={(event) => setNewGroup(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              const name = newGroup.trim();
              if (!name) return;
              setInto((current) =>
                current.includes(name) ? current : [...current, name],
              );
              setNewGroup("");
            }}
          />
        </div>
        <span className="pf-hint">{t("watchlist.add_groups_help")}</span>

        <label className="pf-switch">
          <input
            type="checkbox"
            checked={star}
            onChange={(event) => setStar(event.target.checked)}
          />
          <span>{t("watchlist.add_fav")}</span>
        </label>

        <Failure message={failure ?? searchFailed} />

        {term.length < MIN_QUERY ? (
          <p className="pf-hint">{t("watchlist.add_hint")}</p>
        ) : matches === null ? (
          <p className="pf-hint">{t("common.loading")}</p>
        ) : matches.length === 0 ? (
          <p className="pf-hint">{t("watchlist.add_none")}</p>
        ) : (
          <div className="pf-res">
            {matches.map((match) => {
              const already = listed.has(match.ticker.toUpperCase());
              const kind = KIND_KEY[match.kind] ?? match.kind;
              return (
                <button
                  key={match.ticker}
                  type="button"
                  className="pf-btn pf-resrow"
                  disabled={already || busy}
                  title={
                    already ? t("watchlist.add_listed") : t(`watchlist.kind_${kind}`)
                  }
                  onClick={() => pick(match)}
                >
                  <span className="pf-resrow-t">{match.ticker}</span>
                  <span className="pf-resrow-n">{match.name}</span>
                  <span className="pf-resrow-k">
                    {already
                      ? t("watchlist.add_listed")
                      : (match.exchange ?? "") || t(`watchlist.kind_${kind}`)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
