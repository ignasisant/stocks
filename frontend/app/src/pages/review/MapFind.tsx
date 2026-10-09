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
 * Only the names on the map are searched, never the market: a name not here
 * is added with the page's own ticker box.
 */

import { type ReactNode, useId, useState } from "react";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { VerdictChip } from "./Explain";
import type { ReviewRow } from "./types";

/** More than this and the list is longer than the map it sits on. */
const SHOWN = 8;

export function MapFind({
  needle,
  matches,
  placed,
  onType,
  onPick,
}: {
  needle: string;
  /** What the field matches now, in the order to list them. */
  matches: ReviewRow[];
  /** Whether a row has a dot; one without is listed, not picked. */
  placed: (row: ReviewRow) => boolean;
  onType: (value: string) => void;
  onPick: (row: ReviewRow) => void;
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
  const shown = open && query !== "";
  const at = Math.min(active, rows.length - 1);
  const pick = (row: ReviewRow) => {
    setOpen(false);
    onPick(row);
  };
  let panel: ReactNode = null;
  if (shown) {
    panel = (
      <ul id={list} className="ag-search-panel ag-rev-map-list" role="listbox">
        {rows.length === 0 && off.length === 0 ? (
          <li className="ag-search-caption" role="presentation">
            {t("review.find_none", { query })}
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
        aria-activedescendant={shown && rows.length ? `${list}-${at}` : undefined}
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
            setActive((at + step + rows.length) % Math.max(1, rows.length));
          } else if (event.key === "Enter" && shown && rows[at]) {
            event.preventDefault();
            pick(rows[at]);
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
