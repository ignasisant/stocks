/**
 * The top-bar ticker search — on every page, because it always has been.
 *
 * The ranking is not here and must not be: `stocks.search` decides which tier
 * answers first and how the tiers dedup, `/search` hands back one flat list
 * already in the order to draw, and this file groups consecutive rows by the
 * tier that produced them. A client that re-sorted would be a second opinion
 * about what "best match" means, and the Streamlit box would disagree with it.
 *
 * The last tier is a network round-trip (worldwide symbols, up to six seconds
 * on a cold query), which is why the panel opens with a "searching" row rather
 * than waiting for the answer: an inert field for six seconds reads as broken.
 */

import { useEffect, useRef, useState } from "react";

import { get, send } from "./api";
import { useLang, useT } from "./i18n";
import { BASE } from "./router";
import { useTickerProfile } from "./tickers";

type Match = {
  ticker: string;
  name: string;
  /** watch | crypto | fund | sec | world | analyze */
  kind: string;
  /** favorite | held | "" — own-list rows only. */
  mark: string;
  exchange: string;
};

type Results = { query: string; matches: Match[] };
type Recents = { tickers: string[]; names: Record<string, string> };
type Quote = { ticker: string; price: number | null; pct: number | null };
type Quotes = { quotes: Quote[] };

/** The caption above each tier. Own-list rows get none — they need no excuse. */
const CAPTIONS: Record<string, string> = {
  crypto: "widgets.crypto",
  fund: "widgets.funds",
  sec: "widgets.from_sec_search",
  world: "widgets.from_world_search",
};

const MARKS: Record<string, string> = { favorite: "★", held: "●" };

/** Long enough that typing a five-letter symbol is one request, not five. */
const DEBOUNCE_MS = 220;

export function Search() {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const box = useRef<HTMLDivElement>(null);

  // Clicking anywhere else closes the panel. Not blur: a click *on* a result
  // blurs the field first, and closing there would eat the click.
  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setMatches(null);
      setBusy(false);
      return;
    }
    setBusy(true);
    let live = true;
    const timer = window.setTimeout(() => {
      get<Results>("/search", { q: term })
        .then((results) => {
          // A reply for a query the reader has already typed past is not an
          // answer any more — it would overwrite the newer one it raced.
          if (live) setMatches(results.matches);
        })
        .catch(() => {
          if (live) setMatches([]);
        })
        .finally(() => {
          if (live) setBusy(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  // Prices for the recents strip, asked each time it opens — a quote from the
  // last time the panel was shown would be stale by now. One batched request,
  // and only here: search results change per keystroke, and a Yahoo round-trip
  // per keystroke is how a shared cloud IP gets throttled.
  const recentKey = recent.join(",");
  useEffect(() => {
    if (!open || !recentKey) return;
    let live = true;
    get<Quotes>("/market/quotes", { tickers: recentKey })
      .then((answer) => {
        if (!live) return;
        setQuotes(Object.fromEntries(answer.quotes.map((q) => [q.ticker, q])));
      })
      .catch(() => undefined); // a row without a price is still a working link
    return () => {
      live = false;
    };
  }, [open, recentKey]);

  function focus() {
    setOpen(true);
    if (recent.length === 0) {
      get<Recents>("/search/recent")
        .then((rows) => {
          setRecent(rows.tickers);
          setNames(rows.names ?? {});
        })
        .catch(() => undefined); // an empty recents strip is not an error
    }
  }

  function open_(ticker: string, name = "") {
    // Recorded, not awaited: the reader is already on their way to the page,
    // and a failed write must not hold the navigation or surface an error.
    // The name travels with it: the row knows what the ticker is called, and
    // for a non-US listing nothing cheap on the server can find out later.
    void send<Recents>("POST", "/search/recent", { ticker, name })
      .then((rows) => {
        setRecent(rows.tickers);
        setNames(rows.names ?? {});
      })
      .catch(() => undefined);
    setOpen(false);
    setQuery("");
    window.history.pushState(
      null,
      "",
      `${BASE}/ticker?ticker=${encodeURIComponent(ticker)}`,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.scrollTo(0, 0);
  }

  const term = query.trim();
  const analyze = matches?.find((match) => match.kind === "analyze");
  const rows = (matches ?? []).filter((match) => match.kind !== "analyze");

  return (
    <div className="ag-search" ref={box}>
      <input
        type="search"
        className="ag-search-field"
        value={query}
        placeholder={t("widgets.search_placeholder")}
        aria-label={t("widgets.search_placeholder")}
        onFocus={focus}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "Enter" && rows[0]) open_(rows[0].ticker, rows[0].name);
        }}
      />
      {open && (term || recent.length > 0) ? (
        <div className="ag-search-panel" role="listbox">
          {term ? (
            <Found
              busy={busy}
              rows={rows}
              analyze={analyze}
              term={term}
              onPick={open_}
            />
          ) : (
            <>
              <p className="ag-search-caption">{t("widgets.recent")}</p>
              {recent.map((ticker) => (
                <Row
                  key={ticker}
                  ticker={ticker}
                  name={names[ticker]}
                  quote={quotes[ticker]}
                  onPick={open_}
                />
              ))}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Found({
  busy,
  rows,
  analyze,
  term,
  onPick,
}: {
  busy: boolean;
  rows: Match[];
  analyze: Match | undefined;
  term: string;
  onPick: (ticker: string, name?: string) => void;
}) {
  const t = useT();
  if (busy && rows.length === 0 && !analyze) {
    return <p className="ag-search-caption">{t("widgets.searching")}</p>;
  }
  if (rows.length === 0 && !analyze) {
    // Never leave the panel blank: an empty box reads as "still working",
    // which is the state this line exists to distinguish itself from.
    return <p className="ag-search-caption">{t("widgets.no_results")}</p>;
  }
  return (
    <>
      {rows.map((match, index) => (
        <div key={`${match.kind}-${match.ticker}`}>
          {/* A caption when the tier changes, so one head is printed per run
              rather than one per row. */}
          {CAPTIONS[match.kind] && match.kind !== rows[index - 1]?.kind ? (
            <p className="ag-search-caption">{t(CAPTIONS[match.kind]!)}</p>
          ) : null}
          <Row
            ticker={match.ticker}
            name={match.name}
            mark={match.mark}
            exchange={match.exchange}
            onPick={onPick}
          />
        </div>
      ))}
      {analyze ? (
        <button
          type="button"
          className="ag-search-analyze"
          onClick={() => onPick(analyze.ticker)}
        >
          {/* The catalog string is "Analyze **{q}**" — the emphasis is markup
              this panel does not render, so it is stripped rather than shown. */}
          {t("widgets.analyze", { q: term.toUpperCase() }).replaceAll("**", "")}
        </button>
      ) : null}
    </>
  );
}

function Row({
  ticker,
  name,
  mark,
  exchange,
  quote,
  onPick,
}: {
  ticker: string;
  name?: string;
  mark?: string;
  exchange?: string;
  quote?: Quote;
  onPick: (ticker: string, name?: string) => void;
}) {
  const lang = useLang();
  // The logo from the shared batch every ticker cell uses; the name falls back
  // to it too, for a recent entry nothing remembered a name for.
  const profile = useTickerProfile(ticker);
  const company = name || profile?.name || "";
  const price = format(quote?.price, lang, { maximumFractionDigits: 2 });
  const pct = format(quote?.pct, lang, {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "always",
  });
  return (
    <button
      type="button"
      className="ag-search-row"
      role="option"
      aria-selected="false"
      onClick={() => onPick(ticker, company)}
    >
      {mark && MARKS[mark] ? (
        <span className="ag-search-mark">{MARKS[mark]}</span>
      ) : null}
      {profile?.logo ? (
        <img className="ag-search-logo" src={profile.logo} alt="" loading="lazy" />
      ) : (
        <span className="ag-search-logo" aria-hidden="true" />
      )}
      <span className="ag-search-ticker">{ticker}</span>
      {company ? <span className="ag-search-name">{company}</span> : null}
      {exchange ? <span className="ag-search-venue">{exchange}</span> : null}
      {price ? (
        <span className="ag-search-quote">
          {price}
          {pct ? (
            <span className={(quote?.pct ?? 0) < 0 ? "ag-search-down" : "ag-search-up"}>
              {pct}
            </span>
          ) : null}
        </span>
      ) : null}
    </button>
  );
}

/**
 * A number in the reader's locale, or null for a missing one. No currency: the
 * batch quote does not say which one the listing trades in, and guessing would
 * print a Korean won price with a euro sign.
 */
function format(
  value: number | null | undefined,
  lang: string,
  options: Intl.NumberFormatOptions,
): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return new Intl.NumberFormat(lang, options).format(value);
}
