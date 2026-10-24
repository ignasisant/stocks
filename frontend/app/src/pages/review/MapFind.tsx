/**
 * The quality map's search box: a combobox over the names on the map.
 *
 * Typing fades every dot that does not match and lists the matches under the
 * field, the top bar's panel at the map's scale — logo, symbol, name and
 * verdict, so two tickers that read alike are told apart before one is
 * picked. Picking one (a click, or the arrows and Enter) narrows the map to
 * that dot and opens its tooltip. Escape shuts the list, and again empties
 * the field.
 *
 * The page's own names come first. Under them, with `onAdd`, the market: the
 * top bar's lookup, minus every name already on the page, so a ticker the
 * reader does not follow is one pick from a dot. Picking one of those adds it
 * the way the page's ticker box does (`?add=`) instead of narrowing the map.
 */

import { type ReactNode, useEffect, useId, useState } from "react";
import { findTickers } from "../../shell/findTickers";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import type { SearchMatch } from "../ticker/types";
import { VerdictChip } from "./Explain";
import type { ReviewRow } from "./types";

/** More than this and the list is longer than the map it sits on. */
const SHOWN = 8;
/** The market's rows: a few, under the page's own. */
const MARKET = 4;
/** The top bar's wait: a five-letter symbol is one request, not five. */
const DEBOUNCE_MS = 220;

/**
 * The market's answer for `query`, minus the names `known` already holds
 * (ticker or symbol, upper case). Empty without a query or with `off`.
 */
function useMarket(query: string, known: Set<string>, off: boolean) {
  const [found, setFound] = useState<{ query: string; rows: SearchMatch[] } | null>(
    null,
  );
  useEffect(() => {
    if (off || !query) return;
    let live = true;
    const timer = window.setTimeout(() => {
      findTickers<SearchMatch>(query, { limit: 8 })
        .then((answer) => {
          if (live) setFound({ query, rows: answer.matches });
        })
        .catch(() => {
          if (live) setFound({ query, rows: [] });
        });
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query, off]);
  if (off || !query) return { rows: [], busy: false };
  // A reply for an older query stays up until the new one lands: rows
  // jumping out and back on every keystroke read as flicker.
  return { rows: marketRows(found?.rows ?? [], known), busy: found?.query !== query };
}

/**
 * The market rows worth offering: listings the page does not already weigh.
 * Not the "analyze" offer (a guess, not a listing), not a coin.
 */
export function marketRows(matches: SearchMatch[], known: Set<string>): SearchMatch[] {
  return matches
    .filter((match) => match.kind !== "analyze" && match.kind !== "crypto")
    .filter((match) => !known.has(match.ticker.toUpperCase()))
    .slice(0, MARKET);
}

export function MapFind({
  needle,
  matches,
  placed,
  known,
  onType,
  onPick,
  onAdd,
}: {
  needle: string;
  /** What the field matches now, in the order to list them. */
  matches: ReviewRow[];
  /** Whether a row has a dot; one without is listed, not picked. */
  placed: (row: ReviewRow) => boolean;
  /** Every ticker and symbol on the page, upper case: not offered again. */
  known: Set<string>;
  onType: (value: string) => void;
  onPick: (row: ReviewRow) => void;
  /** Weighs a name from the market; none leaves the market out. */
  onAdd?: (ticker: string) => void;
}) {
  const t = useT();
  const list = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const query = needle.trim();
  const rows = matches.filter(placed).slice(0, SHOWN);
  // A name the engine could not score is still named, so a search for it
  // says why it has no dot instead of finding nothing.
  const off = matches.filter((row) => !placed(row)).slice(0, 3);
  const more = matches.length - rows.length - off.length;
  const market = useMarket(query, known, !onAdd);
  const shown = open && query !== "";
  // The arrow keys walk the map's rows, then the market's.
  const count = rows.length + market.rows.length;
  const at = Math.min(active, count - 1);
  const pick = (row: ReviewRow) => {
    setOpen(false);
    onPick(row);
  };
  const add = (match: SearchMatch) => {
    setOpen(false);
    onAdd?.(match.ticker);
  };
  let panel: ReactNode = null;
  if (shown) {
    panel = (
      <ul id={list} className="ag-search-panel ag-rev-map-list" role="listbox">
        {rows.length === 0 && off.length === 0 && market.rows.length === 0 ? (
          <li className="ag-search-caption" role="presentation">
            {market.busy ? t("widgets.searching") : t("review.find_none", { query })}
          </li>
        ) : null}
        {rows.map((row, index) => (
          <Suggestion
            key={`${row.held ? "h" : "c"}-${row.ticker}`}
            id={`${list}-${index}`}
            row={row}
            on={index === at}
            onHover={() => setActive(index)}
            onPick={() => pick(row)}
          />
        ))}
        {off.map((row) => (
          <Unplaced key={`off-${row.held ? "h" : "c"}-${row.ticker}`} row={row} />
        ))}
        {more > 0 ? (
          <li className="ag-search-caption" role="presentation">
            {t("review.map_find_more", { count: more })}
          </li>
        ) : null}
        {market.rows.length > 0 ? (
          <li className="ag-search-caption" role="presentation">
            {t("review.map_find_add")}
          </li>
        ) : null}
        {market.rows.map((match, offset) => (
          <Outside
            key={`add-${match.ticker}`}
            id={`${list}-${rows.length + offset}`}
            match={match}
            on={rows.length + offset === at}
            onHover={() => setActive(rows.length + offset)}
            onPick={() => add(match)}
          />
        ))}
      </ul>
    );
  }
  return (
    <div className="ag-search ag-rev-map-find">
      <input
        type="search"
        className="ag-search-field"
        role="combobox"
        aria-label={t("review.map_find")}
        aria-expanded={shown}
        aria-controls={list}
        aria-autocomplete="list"
        aria-activedescendant={shown && count ? `${list}-${at}` : undefined}
        placeholder={t("review.find_ph")}
        value={needle}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onChange={(event) => {
          onType(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const step = event.key === "ArrowDown" ? 1 : -1;
            setOpen(true);
            setActive((at + step + count) % Math.max(1, count));
          } else if (event.key === "Enter" && shown && at >= 0) {
            event.preventDefault();
            const row = rows[at];
            const match = market.rows[at - rows.length];
            if (row) pick(row);
            else if (match) add(match);
          } else if (event.key === "Escape") {
            // First the list, then the words: the browser's own Escape
            // empties a search field, which would take both at once.
            event.preventDefault();
            if (shown) setOpen(false);
            else onType("");
          }
        }}
      />
      {panel}
    </div>
  );
}

function Suggestion({
  id,
  row,
  on,
  onHover,
  onPick,
}: {
  id: string;
  row: ReviewRow;
  on: boolean;
  onHover: () => void;
  onPick: () => void;
}) {
  const profile = useTickerProfile(row.ticker);
  const symbol = profile?.symbol || row.symbol || row.ticker;
  const company = profile?.name || "";
  return (
    <li
      id={id}
      className={`ag-search-row${on ? " ag-rev-map-hit-on" : ""}`}
      role="option"
      aria-selected={on}
      onPointerEnter={onHover}
      // The field keeps focus, so its blur does not shut the list first.
      onPointerDown={(event) => event.preventDefault()}
      onClick={onPick}
    >
      {profile?.logo ? (
        <img className="ag-search-logo" src={profile.logo} alt="" loading="lazy" />
      ) : (
        <span className="ag-search-logo" aria-hidden="true" />
      )}
      <span className="ag-search-ticker">{symbol}</span>
      {company && company.toUpperCase() !== symbol.toUpperCase() ? (
        <span className="ag-search-name">{company}</span>
      ) : null}
      <span className="ag-search-kind">
        <VerdictChip row={row} />
      </span>
    </li>
  );
}

/** A name from the market, not on the page: picking it weighs it here. */
function Outside({
  id,
  match,
  on,
  onHover,
  onPick,
}: {
  id: string;
  match: SearchMatch;
  on: boolean;
  onHover: () => void;
  onPick: () => void;
}) {
  const t = useT();
  const profile = useTickerProfile(match.ticker);
  const symbol = profile?.symbol || match.ticker;
  const company = match.name || profile?.name || "";
  return (
    <li
      id={id}
      className={`ag-search-row${on ? " ag-rev-map-hit-on" : ""}`}
      role="option"
      aria-selected={on}
      aria-label={t("review.map_find_add_one", { ticker: symbol })}
      onPointerEnter={onHover}
      onPointerDown={(event) => event.preventDefault()}
      onClick={onPick}
    >
      {profile?.logo ? (
        <img className="ag-search-logo" src={profile.logo} alt="" loading="lazy" />
      ) : (
        <span className="ag-search-logo" aria-hidden="true" />
      )}
      <span className="ag-search-ticker">{symbol}</span>
      {company && company.toUpperCase() !== symbol.toUpperCase() ? (
        <span className="ag-search-name">{company}</span>
      ) : null}
      {match.exchange ? (
        <span className="ag-search-venue">{match.exchange}</span>
      ) : null}
      <span className="ag-search-kind ag-rev-map-add" aria-hidden="true">
        +
      </span>
    </li>
  );
}

/** A match with no dot: its verdict and why, nothing to pick. */
function Unplaced({ row }: { row: ReviewRow }) {
  const t = useT();
  const profile = useTickerProfile(row.ticker);
  const symbol = profile?.symbol || row.symbol || row.ticker;
  const why = row.reasons[0] ? t(`review.reason_${row.reasons[0]}`) : "";
  return (
    <li className="ag-search-row ag-rev-map-off" role="presentation">
      {profile?.logo ? (
        <img className="ag-search-logo" src={profile.logo} alt="" loading="lazy" />
      ) : (
        <span className="ag-search-logo" aria-hidden="true" />
      )}
      <span className="ag-search-ticker">{symbol}</span>
      <span className="ag-search-name">
        {t("review.map_find_off")}
        {why ? ` · ${why}` : ""}
      </span>
    </li>
  );
}
