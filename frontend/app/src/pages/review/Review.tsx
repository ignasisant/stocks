/**
 * Review — what to sell, what to add to, and which outside names to buy.
 *
 * One read over `/review`: the book judged name by name on quality and price
 * (`stocks.analysis.review`), each move sized in money, a sale's tax and a
 * buy's repurchase-window date already worked out by the server.
 *
 * Reading order is the point. The plan comes first: the cash the moves need
 * or free, its tax, and the moves themselves, one row each — the answer to
 * the page's question before the evidence for it. Then the map: the whole
 * book and the outside names on one picture, the verdicts readable from
 * where the dots sit. The full tables come last for whoever wants every row.
 *
 * The three sections draw the same names, and one name pointed at in any of
 * them lights in the others (`focus.tsx`), so a dot is found in the table
 * and a row on the map without reading for it.
 *
 * Outside names are the watchlist's unheld tickers plus the ones typed into
 * the box at the top, which ride `?add=` and are written nowhere — following a
 * name for good is the watchlist's own button on its ticker page.
 *
 * Coins leave the read before it is drawn (`splitCoins`): there are no filings
 * to score, so they get one line under the book with their weight, not a
 * table of blanks.
 *
 * The include, sector and weight filters (`filter.ts`) cut every section at
 * once, the plan's figures and the question for the assistant included, and
 * ride the URL with the rest. They filter what came back; they never refetch.
 */

import { useEffect, useState } from "react";
import { get } from "../../shell/api";
import { askAssistant } from "../../shell/assistant";
import { Loaded, Skeleton, TopActions } from "../../shell/Layout";
import { LockedPreview } from "../../shell/LockedPreview";
import { Icon } from "../../shell/Icon";
import { useLang, useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useCurrency } from "../../shell/session";
import { Help } from "../../ui/Kpi";
import { maybe } from "../sentiment/format";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Plan } from "./Actions";
import { AddTickers } from "./AddTickers";
import { Filters, useFilterWords } from "./Filters";
import { QualityMap } from "./QualityMap";
import { FocusProvider } from "./focus";
import { LinesProvider } from "./lines";
import { ReturnsProvider } from "./returns";
import { CandidateTable, HeldTable } from "./Tables";
import {
  CLEAR,
  type Filter,
  applyFilter,
  includeParam,
  isFiltered,
  parseFilter,
  splitCoins,
} from "./filter";
import { askAgain, longDay, MAX_ADDED, parseAdded, percent, SYMBOL } from "./format";
import { buildPrompt, noteText } from "./prompt";
import type { Review, ReviewNote, ReviewRow } from "./types";
import "./review.css";

const RETRY_MS = 3000;

export default function Page() {
  const t = useT();
  const base = useCurrency();
  const { params, setParams } = useRoute();
  const added = parseAdded(params.get("add"));
  const add = added.join(",");
  const review = useApi(
    () => get<Review>("/review", { base, add: add || undefined }),
    [base, add],
  );
  // A ticker added or removed refetches the whole read (~seconds on a cold
  // cache): the last one stays up, dimmed, instead of a skeleton.
  const [last, setLast] = useState<Review | null>(null);
  if (review.state === "loaded" && review.data !== last) setLast(review.data);
  const stale = review.state === "loading" ? last : null;

  // A wide book read cold answers with the names that arrived in time; the
  // rest keep loading on the server, so ask once more a moment later.
  const asked = `${base}|${add}`;
  const [retried, setRetried] = useState<string | null>(null);
  useEffect(() => {
    if (review.state !== "loaded" || !askAgain(review.data, retried, asked)) return;
    const timer = setTimeout(() => {
      setRetried(asked);
      review.reload();
    }, RETRY_MS);
    return () => clearTimeout(timer);
  }, [review, retried, asked]);

  // The ask sits in the header, written from whatever read is on screen.
  const shown = review.state === "loaded" ? review.data : last;

  // Nothing of the reader's to judge: the page is the reason to import, so it
  // is drawn from the demo book behind the import wall, with nothing to type.
  if (shown?.locked) {
    return (
      <>
        <div className="ag-rev-lead">
          <div className="ag-rev-head">
            <h1 className="ag-rev-h1">{t("review.title")}</h1>
            <p className="ag-rev-caption ag-rev-intro">{t("review.intro")}</p>
          </div>
        </div>
        <ImportWall />
      </>
    );
  }

  const book = shown ? splitCoins(shown)[0] : null;

  // Opens on the book alone, unless nothing is held: then on everything.
  const held = book ? book.held.length > 0 : true;
  const filter = parseFilter(
    params.get("sector"),
    params.get("w"),
    params.get("in"),
    held,
  );
  const setFilter = (next: Filter) =>
    setParams({
      sector: next.sectors.length ? next.sectors.join(",") : undefined,
      w: next.band ?? undefined,
      in: includeParam(next.sources, held),
    });

  const setAdded = (next: string[]) =>
    setParams({ add: next.length ? next.join(",") : undefined });
  // The map's search offers the market too; a pick there joins `?add=` the
  // way the ticker box's does, within the same checks.
  const addOne = (ticker: string) => {
    const symbol = ticker.trim().toUpperCase();
    if (!SYMBOL.test(symbol) || added.includes(symbol) || added.length >= MAX_ADDED)
      return;
    setAdded([...added, symbol]);
  };
  const canAdd = added.length < MAX_ADDED ? addOne : undefined;

  return (
    <>
      {book ? (
        <TopActions>
          <Ask
            data={applyFilter(book, filter)}
            filter={filter}
            busy={review.state === "loading"}
          />
        </TopActions>
      ) : null}
      <div className="ag-rev-lead">
        <div className="ag-rev-head">
          <h1 className="ag-rev-h1">{t("review.title")}</h1>
          <p className="ag-rev-caption ag-rev-intro">{t("review.intro")}</p>
        </div>
        <AddTickers added={added} onChange={setAdded} />
      </div>
      {stale ? (
        <div className="ag-rev-body" aria-busy="true">
          <Screen
            data={stale}
            filter={filter}
            onFilter={setFilter}
            onAdd={canAdd}
            measured
          />
        </div>
      ) : (
        <Loaded query={review} skeleton={<Skeleton rows={8} />}>
          {(data) => (
            <div className="ag-rev-body">
              <Screen
                data={data}
                filter={filter}
                onFilter={setFilter}
                onAdd={canAdd}
                measured
              />
            </div>
          )}
        </Loaded>
      )}
    </>
  );
}

/**
 * The page an import opens, judged over the shared demo book and drawn behind
 * glass. Its filter is the page's opening one; nothing on it answers a press.
 */
function ImportWall() {
  const t = useT();
  const base = useCurrency();
  const preview = useApi(() => get<Review>("/review/preview", { base }), [base]);
  return (
    <LockedPreview
      title={t("review.locked_title")}
      body={t("review.locked_body")}
      cta={{ label: t("review.locked_cta"), page: "import" }}
    >
      {preview.state === "loaded" ? (
        <div className="ag-rev-body">
          <Screen data={preview.data} filter={OPENING} onFilter={() => {}} />
        </div>
      ) : preview.state === "loading" ? (
        <Skeleton rows={8} />
      ) : null}
    </LockedPreview>
  );
}

const OPENING = parseFilter(null, null);

function Screen({
  data: read,
  filter,
  onFilter,
  onAdd,
  measured = false,
}: {
  data: Review;
  filter: Filter;
  onFilter: (next: Filter) => void;
  /** Weighs a ticker from the map's search; the import wall's glass has none. */
  onAdd?: (ticker: string) => void;
  /** Ask what each name returned; the import wall's glass does not. */
  measured?: boolean;
}) {
  const t = useT();
  const lang = useLang();
  const [all, coins] = splitCoins(read);
  const data = applyFilter(all, filter);
  const plan = data.plan;
  const empty = all.held.length === 0 && all.candidates.length === 0;
  const none = data.held.length === 0 && data.candidates.length === 0;

  if (empty) {
    return (
      <div className="ag-rev-card ag-rev-empty">
        <h2 className="ag-rev-h2">{t("review.empty_title")}</h2>
        <p className="ag-rev-caption">{t("review.empty_body")}</p>
        <Coins rows={coins} />
      </div>
    );
  }

  const page = (
    <LinesProvider lines={read.lines}>
      <FocusProvider>
        <Filters
          data={all}
          shown={data}
          filter={filter}
          onChange={onFilter}
          aside={
            <p className="ag-rev-caption ag-rev-asof">
              {t("review.as_of", { date: longDay(data.as_of, lang) })}
              {data.unpriced > 0
                ? ` · ${t("review.unpriced", { count: data.unpriced })}`
                : null}
              {data.pending
                ? ` · ${t("review.pending", { count: data.pending })}`
                : null}
            </p>
          }
        />

        {none && isFiltered(filter) ? (
          <div className="ag-rev-card ag-rev-empty">
            <p className="ag-rev-caption">{t("review.filter_none")}</p>
            <button type="button" className="ag-btn" onClick={() => onFilter(CLEAR)}>
              {t("review.filter_clear")}
            </button>
          </div>
        ) : null}

        <Notes notes={read.notes ?? []} taxCurrency={plan.tax_currency} />

        {data.held.length > 0 && <Plan data={data} filtered={isFiltered(filter)} />}

        <QualityMap
          held={data.held}
          candidates={data.candidates}
          taxCurrency={plan.tax_currency}
          onAdd={onAdd}
        />

        {data.held.length > 0 && (
          <section className="ag-rev-card">
            <h2 className="ag-rev-h2">{t("review.held_title")}</h2>
            <p className="ag-rev-caption">{t("review.held_help")}</p>
            <HeldTable
              rows={data.held}
              base={data.base}
              taxCurrency={plan.tax_currency}
            />
            <Coins rows={coins} />
          </section>
        )}

        {/* Filtered to nothing outside, the section goes rather than claiming
          the watchlist is empty. */}
        {data.candidates.length > 0 || !isFiltered(filter) ? (
          <section className="ag-rev-card">
            <h2 className="ag-rev-h2">{t("review.outside_title")}</h2>
            <p className="ag-rev-caption">{t("review.outside_help")}</p>
            {data.candidates.length > 0 ? (
              <CandidateTable rows={data.candidates} />
            ) : (
              <p className="ag-rev-caption">{t("review.outside_empty")}</p>
            )}
          </section>
        ) : null}

        <p className="ag-rev-caption ag-rev-disclaimer">{t("review.disclaimer")}</p>
      </FocusProvider>
    </LinesProvider>
  );
  if (!measured) return page;
  // Every row the read drew, filtered or not: a filter must not refetch.
  const names = [...all.held, ...all.candidates].map((row) => row.symbol);
  return (
    <ReturnsProvider names={[...new Set(names)]} base={read.base}>
      {page}
    </ReturnsProvider>
  );
}

/** What the read says about the whole book: too few names, one sector,
 *  country or currency carrying it, funds at its core, cash idle beside
 *  buys, coins past a quarter, losses that would cut the plan's tax.
 *  Unfiltered — a note is about the book, not about what the filters leave
 *  on screen. */
function Notes({ notes, taxCurrency }: { notes: ReviewNote[]; taxCurrency: string }) {
  const t = useT();
  const lang = useLang();
  if (notes.length === 0) return null;
  return (
    <div className="ag-rev-card">
      {notes.map((note) => {
        const help = maybe(t, `review.note_${note.key}_help`);
        return (
          <p
            key={`${note.key}-${note.sector ?? note.country ?? note.currency ?? ""}`}
            className="ag-rev-caption"
          >
            {noteText(note, taxCurrency, t, lang)}
            {help ? <Help text={help} /> : null}
          </p>
        );
      })}
    </div>
  );
}

/** The held coins, left out of the read: what they are and how big. */
function Coins({ rows }: { rows: ReviewRow[] }) {
  const t = useT();
  const lang = useLang();
  if (rows.length === 0) return null;
  const weight = rows.reduce((sum, row) => sum + (row.weight ?? 0), 0);
  return (
    <div className="ag-rev-coins">
      <p className="ag-rev-caption">
        {t("review.coins", { weight: percent(weight, lang) ?? t("review.na") })}
      </p>
      <ul className="ag-rev-coin-list">
        {rows.map((row) => (
          <li key={row.ticker}>
            <TickerCell ticker={row.ticker} name={false} />
            <span className="ag-rev-caption">{percent(row.weight, lang)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * "Ask the AI", on the search row at the top right: it reads the filtered
 * rows, so it is the same press at the top as it was at the bottom, and the
 * reader finds it before scrolling through every table. Dimmed while a new
 * read loads — the question would be about the old one. It is asked in a new
 * conversation, sent at once. A guest gets the button too: it opens the
 * locked assistant, which keeps the question for after the sign-in.
 */
function Ask({ data, filter, busy }: { data: Review; filter: Filter; busy: boolean }) {
  const t = useT();
  const lang = useLang();
  const words = useFilterWords(filter);
  if (data.held.length === 0 && data.candidates.length === 0) return null;
  return (
    <button
      type="button"
      className="ag-btn ag-ai ag-rev-ask"
      title={t("review.ask_help")}
      aria-label={t("review.ask")}
      disabled={busy}
      onClick={() => askAssistant(buildPrompt(data, t, lang, words), { fresh: true })}
    >
      <Icon name="auto_awesome" size={18} />
      <span className="ag-rev-ask-label">{t("review.ask")}</span>
    </button>
  );
}
