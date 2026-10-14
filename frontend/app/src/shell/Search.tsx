/**
 * The top-bar ticker search — on every page, because it always has been.
 *
 * The ranking is not here and must not be: `stocks.search` decides which tier
 * answers first and how the tiers dedup, `/search` hands back one flat list
 * already in the order to draw, and this file groups consecutive rows by the
 * tier that produced them. A client that re-sorted would be a second opinion
 * about what "best match" means.
 *
 * The last tier is a network round-trip (worldwide symbols, up to six seconds
 * on a cold query), which is why the panel opens with a "searching" row rather
 * than waiting for the answer: an inert field for six seconds reads as broken.
 */

import { useEffect, useId, useRef, useState } from "react";

import { get, send } from "./api";
import { assetLabel } from "./assets";
import { useLang, useT } from "./i18n";
import { BASE, push } from "./router";
import { useTickerProfile } from "./tickers";
import { Badge } from "../ui/Badge";
import { formatter } from "./numbers";

type Match = {
  ticker: string;
  name: string;
  /** watch | crypto | fund | sec | world | analyze */
  kind: string;
  /** favorite | held | "" — own-list rows only. */
  mark: string;
  exchange: string;
  /**
   * What kind of thing the symbol is (`shell/assets.ts`), or "fund" when the
   * server knows no more than that. Null when nothing on file says — no pill
   * rather than a guessed one.
   */
  asset?: string | null;
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

/**
 * The same field and panel as a picker: with `onPick`, choosing a row hands
 * the ticker to the caller instead of opening its page, and nothing is
 * recorded as a visit — a page that collects tickers (Review's "weigh other
 * tickers") gets the top bar's ranking without a second search to keep in
 * step with it.
 */
export function Search({
  onPick,
  placeholder,
}: {
  onPick?: (ticker: string, name: string) => void;
  placeholder?: string;
} = {}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  // The option the arrow keys are on, by position in the list as drawn — the
  // field keeps focus throughout (`aria-activedescendant`), so a reader can
  // keep typing while they walk the results.
  const [active, setActive] = useState(-1);
  const uid = useId();
  const listId = `${uid}-list`;
  const optionId = (index: number) => `${uid}-opt-${index}`;

  // "/" and Cmd/Ctrl+K jump to the top bar's field from anywhere, the way
  // every search box a reader has met does. Not the picker: a page may hold
  // several, and none of them should claim a global key.
  useEffect(() => {
    if (onPick) return;
    const onKey = (event: KeyboardEvent) => {
      const el = event.target;
      const typing =
        el instanceof HTMLElement &&
        (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
      const chord = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      const slash = event.key === "/" && !typing && !event.metaKey && !event.ctrlKey;
      if (!chord && !slash) return;
      event.preventDefault();
      field.current?.focus();
      field.current?.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onPick]);

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
    if (onPick) {
      setOpen(false);
      setQuery("");
      onPick(ticker, name);
      return;
    }
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
    push(`${BASE}/ticker?ticker=${encodeURIComponent(ticker)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.scrollTo(0, 0);
  }

  const term = query.trim();
  const analyze = matches?.find((match) => match.kind === "analyze");
  const rows = (matches ?? []).filter((match) => match.kind !== "analyze");
  // What the arrow keys walk, in drawing order: the rows, then "Analyze …".
  const options = term
    ? [
        ...rows.map((match) => ({ ticker: match.ticker, name: match.name })),
        ...(analyze ? [{ ticker: analyze.ticker, name: "" }] : []),
      ]
    : recent.map((ticker) => ({ ticker, name: names[ticker] ?? "" }));
  const shown = open && (term !== "" || recent.length > 0);
  // A new list starts with nothing chosen, so Enter keeps meaning "the top
  // match" until the reader has actually moved.
  const signature = options.map((option) => option.ticker).join(",");
  useEffect(() => setActive(-1), [signature, shown]);
  useEffect(() => {
    if (active < 0) return;
    document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return (
    <div className="ag-search" ref={box}>
      <input
        ref={field}
        type="search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={shown ? listId : undefined}
        aria-activedescendant={shown && active >= 0 ? optionId(active) : undefined}
        aria-keyshortcuts={onPick ? undefined : "/ Control+K Meta+K"}
        autoCapitalize="off"
        autoComplete="off"
        autoCorrect="off"
        enterKeyHint="search"
        spellCheck={false}
        className="ag-search-field"
        value={query}
        placeholder={placeholder ?? t("widgets.search_placeholder")}
        aria-label={placeholder ?? t("widgets.search_placeholder")}
        onFocus={focus}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            if (!options.length) return;
            event.preventDefault();
            if (!shown) return setOpen(true);
            const step = event.key === "ArrowDown" ? 1 : -1;
            // Wraps, and the field itself is the stop before the first row.
            setActive(
              ((active + 1 + step + options.length + 1) % (options.length + 1)) - 1,
            );
            return;
          }
          if (event.key !== "Enter") return;
          const chosen = options[active];
          if (chosen) {
            event.preventDefault();
            return open_(chosen.ticker, chosen.name);
          }
          if (rows[0]) open_(rows[0].ticker, rows[0].name);
          // A picker takes a symbol nothing matched, as typed: the caller
          // checks it, and an unlisted name is still worth asking about.
          else if (onPick && analyze) open_(analyze.ticker);
        }}
      />
      {shown ? (
        // Held on to the field: a press on a row must not blur it first, or
        // the panel's own `mousedown` bookkeeping and the caret both go.
        <div
          className="ag-search-panel"
          onMouseDown={(event) => event.preventDefault()}
        >
          {term ? (
            <Found
              busy={busy}
              rows={rows}
              analyze={analyze}
              term={term}
              onPick={open_}
              listId={listId}
              optionId={optionId}
              active={active}
            />
          ) : (
            <>
              <p className="ag-search-caption" id={`${uid}-recent`}>
                {t("widgets.recent")}
              </p>
              <div role="listbox" id={listId} aria-labelledby={`${uid}-recent`}>
                {recent.map((ticker, index) => (
                  <Row
                    key={ticker}
                    ticker={ticker}
                    name={names[ticker]}
                    quote={quotes[ticker]}
                    onPick={open_}
                    id={optionId(index)}
                    active={active === index}
                  />
                ))}
              </div>
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
  listId,
  optionId,
  active,
}: {
  listId: string;
  optionId: (index: number) => string;
  active: number;
  busy: boolean;
  rows: Match[];
  analyze: Match | undefined;
  term: string;
  onPick: (ticker: string, name?: string) => void;
}) {
  const t = useT();
  if (busy && rows.length === 0 && !analyze) {
    return (
      <p className="ag-search-caption" role="status">
        {t("widgets.searching")}
      </p>
    );
  }
  if (rows.length === 0 && !analyze) {
    // Never leave the panel blank: an empty box reads as "still working",
    // which is the state this line exists to distinguish itself from.
    return (
      <p className="ag-search-caption" role="status">
        {t("widgets.no_results")}
      </p>
    );
  }
  // One run per tier: a listbox may hold only options and groups, so the
  // caption becomes the group's name rather than a paragraph between rows.
  const runs: { kind: string; start: number; rows: Match[] }[] = [];
  rows.forEach((match, index) => {
    const last = runs[runs.length - 1];
    if (last && last.kind === match.kind) last.rows.push(match);
    else runs.push({ kind: match.kind, start: index, rows: [match] });
  });
  return (
    <div role="listbox" id={listId} aria-label={t("widgets.search_placeholder")}>
      {runs.map((run) => {
        const caption = CAPTIONS[run.kind];
        const body = run.rows.map((match, offset) => (
          <Row
            key={`${match.kind}-${match.ticker}`}
            ticker={match.ticker}
            name={match.name}
            mark={match.mark}
            exchange={match.exchange}
            asset={match.asset}
            onPick={onPick}
            id={optionId(run.start + offset)}
            active={active === run.start + offset}
          />
        ));
        return caption ? (
          <div role="group" aria-label={t(caption)} key={run.start}>
            <p className="ag-search-caption" aria-hidden="true">
              {t(caption)}
            </p>
            {body}
          </div>
        ) : (
          <div role="presentation" key={run.start}>
            {body}
          </div>
        );
      })}
      {analyze ? (
        <button
          type="button"
          role="option"
          id={optionId(rows.length)}
          aria-selected={active === rows.length}
          tabIndex={-1}
          className="ag-search-analyze"
          onClick={() => onPick(analyze.ticker)}
        >
          {/* The catalog string is "Analyze **{q}**" — the emphasis is markup
              this panel does not render, so it is stripped rather than shown. */}
          {t("widgets.analyze", { q: term.toUpperCase() }).replaceAll("**", "")}
        </button>
      ) : null}
    </div>
  );
}

function Row({
  ticker,
  name,
  mark,
  exchange,
  asset,
  quote,
  onPick,
  id,
  active,
}: {
  id: string;
  active: boolean;
  ticker: string;
  name?: string;
  mark?: string;
  exchange?: string;
  asset?: string | null;
  quote?: Quote;
  onPick: (ticker: string, name?: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  // The logo from the shared batch every ticker cell uses; the name and the
  // kind fall back to it too, for a recent entry nothing remembered them for.
  const profile = useTickerProfile(ticker);
  const company = name || profile?.name || "";
  const kind = assetLabel(asset ?? profile?.asset);
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
      id={id}
      role="option"
      aria-selected={active}
      tabIndex={-1}
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
      {/* The resolved symbol, as every ticker cell prints it: a broker's code
          (RCF) reads as the listing it stands for (TEP.PA). The pick still
          hands on the stored label. */}
      <span className="ag-search-ticker">{profile?.symbol || ticker}</span>
      {company ? <span className="ag-search-name">{company}</span> : null}
      {/* "XEON" alone does not say it is cash: the kind before the venue, so
          a share, a fund, a coin and an index are told apart in the list. */}
      {kind ? (
        <span className="ag-search-kind">
          <Badge>{t(kind)}</Badge>
        </span>
      ) : null}
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
  return formatter(lang, options).format(value);
}
