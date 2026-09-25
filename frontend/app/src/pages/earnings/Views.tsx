/**
 * The switcher, the filters and the month the grid is parked on.
 *
 * All three are local state. The Streamlit page keeps them in `session_state`
 * and nothing about this screen is deep-linked — there is no `?view=` or
 * `?month=` on it to keep working — so nothing here writes to the query string.
 *
 * Filtering is done on data already in hand: one `/earnings` call fetched the
 * whole watchlist, so toggling a pill or paging a month is a re-render, never a
 * request.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { addMonths, allowed, only, today } from "./data";
import type { CalendarResult, EarningsCalendar } from "./data";
import { plain } from "./format";
import MonthGrid from "./MonthGrid";
import ResultDetail from "./ResultDetail";
import ResultList from "./ResultList";
import { TaxLegend } from "./Tax";

type View = "calendar" | "list";

/** The two groups the API names rather than borrows from a watchlist tag. */
const GROUP_KEYS: Record<string, string> = {
  portfolio: "earnings.filter_portfolio",
  favorites: "earnings.filter_favorites",
};

/**
 * Phones open on the list, desktops on the grid.
 *
 * The Python page decides this from the User-Agent because Streamlit renders
 * server-side and has no viewport to ask. Here the viewport is the honest
 * question, and 640px is the same breakpoint the shell's stylesheet uses to
 * turn the nav rail into a tab bar.
 */
function initialView(): View {
  return window.matchMedia("(max-width: 640px)").matches ? "list" : "calendar";
}

export default function Views({ data }: { data: EarningsCalendar }) {
  const t = useT();
  const [view, setView] = useState<View>(initialView);
  const [picked, setPicked] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<CalendarResult | null>(null);

  const names = allowed(data.groups, picked);
  const events = only(data.upcoming, names);
  const results = only(data.results, names);
  // Deadlines ignore the ticker filters: they are the reader's, not a name's.
  const deadlines = data.tax_deadlines;
  const empty = events.length === 0 && results.length === 0 && deadlines.length === 0;

  const now = today();
  const [year, month] = addMonths(
    Number(now.slice(0, 4)),
    Number(now.slice(5, 7)),
    offset,
  );

  const toggle = (key: string) =>
    setPicked((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );

  return (
    <>
      <div className="earn-bar">
        <div className="earn-seg" role="group" aria-label={t("earnings.view_label")}>
          <button
            type="button"
            aria-pressed={view === "calendar"}
            onClick={() => setView("calendar")}
          >
            {t("earnings.view_calendar")}
          </button>
          <button
            type="button"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            {t("earnings.view_list")}
          </button>
        </div>
        {Object.keys(data.groups).length > 0 && (
          <div
            className="earn-pills"
            role="group"
            aria-label={t("earnings.filter_label")}
          >
            {Object.keys(data.groups).map((key) => {
              const label = GROUP_KEYS[key];
              return (
                <button
                  type="button"
                  key={key}
                  className="earn-pill"
                  aria-pressed={picked.includes(key)}
                  onClick={() => toggle(key)}
                >
                  {/* A tag is the reader's own word: it is data, not copy, so
                      it is printed as typed rather than looked up. */}
                  {label ? t(label) : key}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {empty ? (
        <p className="ag-note">{t("earnings.no_match_filters")}</p>
      ) : view === "list" ? (
        <ResultList events={events} results={results} deadlines={deadlines} />
      ) : (
        <>
          <div className="earn-nav">
            <button
              type="button"
              className="ag-btn"
              aria-label={t("earnings.prev_month")}
              onClick={() => setOffset(offset - 1)}
            >
              ‹
            </button>
            <button
              type="button"
              className="ag-btn"
              aria-label={t("earnings.next_month")}
              onClick={() => setOffset(offset + 1)}
            >
              ›
            </button>
            <h2 className="earn-month">{`${t(`earnings.month_${month}`)} ${year}`}</h2>
            <button type="button" className="ag-btn" onClick={() => setOffset(0)}>
              {t("earnings.today_btn")}
            </button>
          </div>
          <MonthGrid
            year={year}
            month={month}
            now={now}
            events={events}
            results={results}
            deadlines={deadlines}
            onPick={setDetail}
          />
          <p className="earn-legend">{plain(t("earnings.calendar_legend"))}</p>
          {deadlines.length > 0 && <TaxLegend jurisdiction={data.jurisdiction} />}
        </>
      )}

      {detail && (
        <ResultDetail
          ticker={detail.ticker}
          date={detail.date}
          result={detail}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}
