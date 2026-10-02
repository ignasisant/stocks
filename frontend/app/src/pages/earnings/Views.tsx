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
 *
 * Two rows of pills, both read the same way — nothing picked is everything,
 * and picking two widens rather than narrows. The group pills pick NAMES; the
 * kind pills pick what is drawn about them. Each kind pill carries the colour
 * of its chips, so the row is the grid's key too, and the paragraphs that
 * explain each colour fold away under it instead of trailing the month.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { addMonths, allowed, only, today } from "./data";
import type { EarningsCalendar, EventPick } from "./data";
import EventDetail from "./EventDetail";
import { plain } from "./format";
import MonthGrid from "./MonthGrid";
import ResultList from "./ResultList";
import { CentralBankLegend } from "./CentralBanks";
import { DividendLegend } from "./Dividends";
import { RepurchaseLegend } from "./Repurchase";
import { TaxLegend } from "./Tax";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";

type View = "calendar" | "list";

/** What the calendar draws, one pill each, in the order a cell stacks them. */
type Kind = "tax" | "banks" | "earnings" | "dividends";

const KIND_KEYS: Record<Kind, string> = {
  tax: "earnings.kind_tax",
  banks: "earnings.kind_banks",
  earnings: "earnings.kind_earnings",
  dividends: "earnings.kind_dividends",
};

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
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<EventPick | null>(null);

  // Only the kinds this account has anything of get a pill.
  const present: Kind[] = (
    [
      ["tax", data.tax_deadlines.length + data.repurchase_windows.length],
      ["banks", data.central_banks.length],
      ["earnings", data.upcoming.length + data.results.length],
      ["dividends", data.dividends.length],
    ] as [Kind, number][]
  )
    .filter(([, count]) => count > 0)
    .map(([kind]) => kind);
  const shows = (kind: Kind) => kinds.length === 0 || kinds.includes(kind);

  const names = allowed(data.groups, picked);
  const events = shows("earnings") ? only(data.upcoming, names) : [];
  const results = shows("earnings") ? only(data.results, names) : [];
  const dividends = shows("dividends") ? only(data.dividends, names) : [];
  // Deadlines and buy-back windows ignore the ticker filters: they are the
  // reader's, not a name's — and a name sold at a loss has usually left the
  // Portfolio group already. Rate decisions belong to no name at all.
  const deadlines = shows("tax") ? data.tax_deadlines : [];
  const windows = shows("tax") ? data.repurchase_windows : [];
  const banks = shows("banks") ? data.central_banks : [];
  // The banks are context: a filter that matched nothing still says so —
  // unless the banks are what the reader asked for.
  const empty =
    events.length === 0 &&
    results.length === 0 &&
    deadlines.length === 0 &&
    windows.length === 0 &&
    dividends.length === 0 &&
    (!kinds.includes("banks") || banks.length === 0);

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
  const toggleKind = (kind: Kind) =>
    setKinds((current) =>
      current.includes(kind) ? current.filter((k) => k !== kind) : [...current, kind],
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
          <ToggleRow label={t("earnings.filter_label")}>
            {Object.keys(data.groups).map((key) => {
              const label = GROUP_KEYS[key];
              return (
                <ToggleChip
                  key={key}
                  on={picked.includes(key)}
                  onClick={() => toggle(key)}
                >
                  {/* A tag is the reader's own word: it is data, not copy, so
                      it is printed as typed rather than looked up. */}
                  {label ? t(label) : key}
                </ToggleChip>
              );
            })}
          </ToggleRow>
        )}
        {present.length > 1 && (
          <ToggleRow label={t("earnings.kind_label")}>
            {present.map((kind) => (
              <ToggleChip
                key={kind}
                on={kinds.includes(kind)}
                onClick={() => toggleKind(kind)}
              >
                <span className={`earn-swatch ${kind}`} aria-hidden="true" />
                {t(KIND_KEYS[kind])}
              </ToggleChip>
            ))}
          </ToggleRow>
        )}
      </div>

      {empty ? (
        <p className="ag-note">{t("earnings.no_match_filters")}</p>
      ) : view === "list" ? (
        <ResultList
          events={events}
          results={results}
          deadlines={deadlines}
          windows={windows}
          banks={banks}
          dividends={dividends}
        />
      ) : (
        <>
          <div className="earn-nav">
            <h2 className="earn-month">{`${t(`earnings.month_${month}`)} ${year}`}</h2>
            <div
              className="earn-step"
              role="group"
              aria-label={t("earnings.month_nav")}
            >
              <button
                type="button"
                aria-label={t("earnings.prev_month")}
                onClick={() => setOffset(offset - 1)}
              >
                ‹
              </button>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(0)}
              >
                {t("earnings.today_btn")}
              </button>
              <button
                type="button"
                aria-label={t("earnings.next_month")}
                onClick={() => setOffset(offset + 1)}
              >
                ›
              </button>
            </div>
          </div>
          <MonthGrid
            year={year}
            month={month}
            now={now}
            events={events}
            results={results}
            deadlines={deadlines}
            windows={windows}
            banks={banks}
            dividends={dividends}
            onPick={setDetail}
          />
          {/* The caveats behind each colour — statutory dates, estimated
              amounts — stay one click away rather than trailing the month as a
              wall of copy; every chip's dialog says its own. */}
          <details className="earn-key">
            <summary>{t("earnings.key_summary")}</summary>
            {(events.length > 0 || results.length > 0) && (
              <p className="earn-legend">{plain(t("earnings.calendar_legend"))}</p>
            )}
            {deadlines.length > 0 && <TaxLegend jurisdiction={data.jurisdiction} />}
            <RepurchaseLegend windows={windows} />
            {banks.length > 0 && <CentralBankLegend />}
            {dividends.length > 0 && <DividendLegend />}
          </details>
        </>
      )}

      {detail && (
        <EventDetail
          pick={detail}
          held={data.groups.portfolio ?? []}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}
