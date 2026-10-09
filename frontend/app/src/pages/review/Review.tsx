/**
 * Review — what to sell, what to add to, and which outside names to buy.
 *
 * One read over `/review`: the book judged name by name on quality and price
 * (`stocks.analysis.review`), each move sized in money, a sale's tax and a
 * buy's repurchase-window date already worked out by the server.
 *
 * Reading order is the point. The map comes first: the whole book and the
 * outside names on one picture, the verdicts readable from where the dots
 * sit before a word is read. Then the plan's four figures say how big the
 * whole thing is, the action cards say what to do, and the full tables come
 * last for whoever wants every row.
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

import { useState } from "react";
import { get } from "../../shell/api";
import { draftAssistant } from "../../shell/assistant";
import { Loaded, Skeleton } from "../../shell/Layout";
import { SignedInOnly } from "../../shell/guest";
import { Icon } from "../../shell/Icon";
import { useLang, useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useCurrency } from "../../shell/session";
import { TickerCell } from "../../shell/tickers";
import { useApi } from "../../shell/useApi";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { Actions } from "./Actions";
import { AddTickers } from "./AddTickers";
import { Filters, useFilterWords } from "./Filters";
import { QualityMap } from "./QualityMap";
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
import { money, parseAdded, percent } from "./format";
import { buildPrompt } from "./prompt";
import type { Review, ReviewRow } from "./types";
import "./review.css";

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

  // The ask sits in the header, written from whatever read is on screen.
  const shown = review.state === "loaded" ? review.data : last;

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

  return (
    <>
      <div className="ag-rev-head">
        <h1 className="ag-rev-h1">{t("review.title")}</h1>
        {book ? (
          <Ask
            data={applyFilter(book, filter)}
            filter={filter}
            busy={review.state === "loading"}
          />
        ) : null}
      </div>
      <div className="ag-rev-lead">
        <p className="ag-rev-caption ag-rev-intro">{t("review.intro")}</p>
        <AddTickers
          added={added}
          onChange={(next) =>
            setParams({ add: next.length ? next.join(",") : undefined })
          }
        />
      </div>
      {stale ? (
        <div className="ag-rev-body" aria-busy="true">
          <Screen data={stale} filter={filter} onFilter={setFilter} />
        </div>
      ) : (
        <Loaded query={review} skeleton={<Skeleton rows={8} />}>
          {(data) => (
            <div className="ag-rev-body">
              <Screen data={data} filter={filter} onFilter={setFilter} />
            </div>
          )}
        </Loaded>
      )}
    </>
  );
}

function Screen({
  data: read,
  filter,
  onFilter,
}: {
  data: Review;
  filter: Filter;
  onFilter: (next: Filter) => void;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const [all, coins] = splitCoins(read);
  const data = applyFilter(all, filter);
  const plan = data.plan;
  const net = plan.buys - plan.sells;
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

  return (
    <>
      <Filters
        data={all}
        shown={data}
        filter={filter}
        onChange={onFilter}
        aside={
          <p className="ag-rev-caption ag-rev-asof">
            {t("review.as_of", { date: data.as_of })}
            {data.unpriced > 0
              ? ` · ${t("review.unpriced", { count: data.unpriced })}`
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

      <QualityMap held={data.held} candidates={data.candidates} />

      {data.held.length > 0 && (
        <KpiGrid>
          <Kpi
            label={t("review.plan_sells")}
            value={money(plan.sells, data.base, lang) ?? na}
            help={t("review.plan_sells_help")}
          />
          <Kpi
            label={t("review.plan_buys")}
            value={money(plan.buys, data.base, lang) ?? na}
            help={t("review.plan_buys_help")}
          />
          <Kpi
            label={t("review.plan_net")}
            value={money(net, data.base, lang, true) ?? na}
            help={t("review.plan_net_help")}
          />
          <Kpi
            label={t("review.plan_tax")}
            value={money(plan.tax, plan.tax_currency, lang) ?? na}
            help={t("review.plan_tax_help", { code: data.jurisdiction })}
          />
        </KpiGrid>
      )}

      {data.held.length > 0 && <Actions data={data} />}

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
    </>
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
 * "Draft a question for the AI", top right of the page: it reads the filtered
 * rows, so it is the same press at the top as it was at the bottom, and the
 * reader finds it before scrolling through every table. Dimmed while a new
 * read loads — the question would be about the old one. The drawer it writes
 * into is not mounted for a guest, so for a guest there is no button at all.
 */
function Ask({ data, filter, busy }: { data: Review; filter: Filter; busy: boolean }) {
  const t = useT();
  const lang = useLang();
  const words = useFilterWords(filter);
  if (data.held.length === 0 && data.candidates.length === 0) return null;
  return (
    <SignedInOnly>
      <button
        type="button"
        className="ag-btn ag-btn-cta ag-rev-ask"
        title={t("review.ask_help")}
        disabled={busy}
        onClick={() => draftAssistant(buildPrompt(data, t, lang, words))}
      >
        <Icon name="auto_awesome" size={18} />
        {t("review.ask")}
      </button>
    </SignedInOnly>
  );
}
