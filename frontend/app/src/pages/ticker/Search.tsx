/**
 * The ticker search box — the page's only way in other than a link.
 *
 * Every ranking decision is the server's (`stocks.search`), the same module the
 * Streamlit top bar reads, so the two boxes cannot answer one query
 * differently. What is decided here is the interaction: when to ask, what to
 * show while waiting, and what a row looks like.
 *
 * Two things are copied from the app deliberately. The panel opens BEFORE the
 * matches are known and shows "searching" in place — the last tier is a network
 * round-trip that can take seconds, and a field that looks inert for that long
 * reads as broken. And an empty, focused field offers the account's recent
 * tickers, which is the fastest path back to what somebody was just looking at.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../../shell/i18n";
import { getRecents, rememberTicker, searchTickers } from "./data";
import { Bold } from "./ui";
import type { SearchMatch } from "./types";

/** The app's own alphabet for the tiers, kept row for row. */
const GLYPH: Record<string, string> = {
  favorite: "★",
  held: "💼",
  crypto: "🪙",
  fund: "🧺",
  sec: "🔎",
  world: "🌐",
};

/** Caption above each tier, exactly the app's. `watch` leads and needs none. */
const CAPTION: Record<string, string> = {
  crypto: "widgets.crypto",
  fund: "widgets.funds",
  sec: "widgets.from_sec_search",
  world: "widgets.from_world_search",
};

/** Typing settles before a query goes out; the app debounces by the same. */
const DEBOUNCE_MS = 160;

export function Search({ onPick }: { onPick: (ticker: string) => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [matches, setMatches] = useState<SearchMatch[] | null>(null);
  const [recents, setRecents] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);

  const trimmed = query.trim();

  useEffect(() => {
    if (!trimmed) {
      setMatches(null);
      return;
    }
    let live = true;
    // null is "asking", which is what draws the searching row. Set before the
    // debounce even fires, so the whole dead window is visibly loading.
    setMatches(null);
    const timer = setTimeout(() => {
      searchTickers(trimmed)
        .then((body) => live && setMatches(body.matches))
        .catch(() => live && setMatches([]));
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [trimmed]);

  // Fetched on the first focus rather than at mount: an account that never
  // opens the box should not cost a request for a list nobody will read.
  const loadRecents = useCallback(() => {
    if (recents.length) return;
    getRecents()
      .then((body) => setRecents(body.tickers))
      .catch(() => undefined);
  }, [recents.length]);

  // A click anywhere else closes the panel. Pointerdown, not click, so a row's
  // own handler still runs — it fires on the element before this sees it.
  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  const rows: SearchMatch[] = trimmed
    ? (matches ?? [])
    : recents.map((ticker) => ({
        ticker,
        name: "",
        kind: "recent",
        mark: "",
        exchange: "",
      }));

  const pick = useCallback(
    (ticker: string) => {
      onPick(ticker);
      setQuery("");
      setMatches(null);
      setOpen(false);
      setCursor(-1);
      field.current?.blur();
      // Recorded so the Streamlit top bar offers the same history. A failure is
      // not worth a word on screen: the navigation already happened.
      rememberTicker(ticker)
        .then((body) => setRecents(body.tickers))
        .catch(() => undefined);
    },
    [onPick],
  );

  const onKey = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      field.current?.blur();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!rows.length) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setCursor((at) => (at + step + rows.length) % rows.length);
      return;
    }
    if (event.key === "Enter") {
      const row = rows[cursor] ?? rows[0];
      if (row) pick(row.ticker);
    }
  };

  const panel = open && (trimmed !== "" || rows.length > 0);

  return (
    <div className="tk-search" ref={box}>
      <input
        ref={field}
        className="tk-field"
        type="text"
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-expanded={Boolean(panel)}
        aria-controls="tk-search-results"
        placeholder={t("widgets.search_placeholder")}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setCursor(-1);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          loadRecents();
        }}
        onKeyDown={onKey}
      />
      {trimmed !== "" && matches === null ? (
        <span className="tk-busy" aria-hidden="true" />
      ) : null}
      {panel ? (
        <div className="tk-results" id="tk-search-results" role="listbox">
          {!trimmed && rows.length > 0 ? (
            <p className="tk-results-cap">{t("widgets.recent")}</p>
          ) : null}
          {trimmed && matches === null ? (
            <p className="tk-results-cap">{t("widgets.searching")}</p>
          ) : null}
          {trimmed && matches?.length === 0 ? (
            <p className="tk-results-cap">{t("widgets.no_results")}</p>
          ) : null}
          {rows.map((match, index) => {
            const caption = CAPTION[match.kind];
            const first = rows.findIndex((row) => row.kind === match.kind) === index;
            return (
              <div key={`${match.kind}-${match.ticker}`}>
                {caption && first ? (
                  <p className="tk-results-cap">{t(caption)}</p>
                ) : null}
                <button
                  type="button"
                  role="option"
                  aria-selected={index === cursor}
                  className={[
                    "tk-row",
                    index === cursor ? "tk-row-on" : "",
                    match.kind === "analyze" ? "tk-row-analyze" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => pick(match.ticker)}
                >
                  {match.kind === "analyze" ? (
                    <Bold text={t("widgets.analyze", { q: match.ticker })} />
                  ) : (
                    <>
                      <span className="tk-row-glyph">
                        {GLYPH[match.mark] ?? GLYPH[match.kind] ?? ""}
                      </span>
                      <strong>{match.ticker}</strong>
                      {match.name ? (
                        <span className="tk-row-name">{match.name}</span>
                      ) : null}
                      {/* The venue is what disambiguates a worldwide row, and
                          the hint that the symbol is foreign. */}
                      {match.exchange ? (
                        <span className="tk-row-venue">{match.exchange}</span>
                      ) : null}
                    </>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
