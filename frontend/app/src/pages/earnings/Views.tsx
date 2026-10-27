/**
 * The switcher, the filters and the month the grid is parked on.
 *
 * All three are local state, and nothing about this screen is deep-linked —
 * there is no `?view=` or `?month=` on it — so nothing here writes to the
 * query string.
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
import { BookLegend, HolidayLegend } from "./Book";
import { CentralBankLegend } from "./CentralBanks";
import { DividendLegend } from "./Dividends";
import { RepurchaseLegend } from "./Repurchase";
import { TaxLegend } from "./Tax";
import { ToggleChip, ToggleRow } from "../../ui/Toggle";
import { Segmented } from "../../ui/Segmented";

type View = "calendar" | "list";

/** What the calendar draws, one pill each, in the order a cell stacks them. */
type Kind = "tax" | "banks" | "earnings" | "trades" | "dividends" | "markets";

const KIND_KEYS: Record<Kind, string> = {
  tax: "earnings.kind_tax",
  banks: "earnings.kind_banks",
  earnings: "earnings.kind_earnings",
  trades: "earnings.kind_trades",
  dividends: "earnings.kind_dividends",
  markets: "earnings.kind_markets",
};

/** The two groups the API names rather than borrows from a watchlist tag. */
const GROUP_KEYS: Record<string, string> = {
  portfolio: "earnings.filter_portfolio",
  favorites: "earnings.filter_favorites",
};

/**
 * Phones open on the list, desktops on the grid.
 *
 * The viewport is the honest question here, not the User-Agent, and 640px is
 * the same breakpoint the shell's stylesheet uses to turn the nav rail into a
 * tab bar.
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

  // A payload cached before the book's own days shipped has none of them.
  const allTrades = data.trades ?? [];
  const allPayments = data.payments ?? [];
  const allHolidays = data.market_holidays ?? [];

  // Only the kinds this account has anything of get a pill.
  const present: Kind[] = (
    [
      ["tax", data.tax_deadlines.length + data.repurchase_windows.length],
      ["banks", data.central_banks.length],
      ["earnings", data.upcoming.length + data.results.length],
      ["trades", allTrades.length],
      // A payout is the cash an ex-date promised: one pill for both.
      ["dividends", data.dividends.length + allPayments.length],
      ["markets", allHolidays.length],
    ] as [Kind, number][]
  )
    .filter(([, count]) => count > 0)
    .map(([kind]) => kind);
  const shows = (kind: Kind) => kinds.length === 0 || kinds.includes(kind);

  const names = allowed(data.groups, picked);
  const events = shows("earnings") ? only(data.upcoming, names) : [];
  const results = shows("earnings") ? only(data.results, names) : [];
  const dividends = shows("dividends") ? only(data.dividends, names) : [];
  const trades = shows("trades") ? only(allTrades, names) : [];
  const payments = shows("dividends") ? only(allPayments, names) : [];
  // Deadlines and buy-back windows ignore the ticker filters: they are the
  // reader's, not a name's — and a name sold at a loss has usually left the
  // Portfolio group already. Rate decisions belong to no name at all.
  const deadlines = shows("tax") ? data.tax_deadlines : [];
  const windows = shows("tax") ? data.repurchase_windows : [];
  const banks = shows("banks") ? data.central_banks : [];
  // A holiday is the exchange's, not a name's: already cut by the API to the
  // venues the calendar's names trade on.
  const holidays = shows("markets") ? allHolidays : [];
  // The banks and the holidays are context: a filter that matched nothing
  // still says so — unless they are what the reader asked for.
  const empty =
    events.length === 0 &&
    results.length === 0 &&
    deadlines.length === 0 &&
    windows.length === 0 &&
    dividends.length === 0 &&
    trades.length === 0 &&
    payments.length === 0 &&
    (!kinds.includes("banks") || banks.length === 0) &&
    (!kinds.includes("markets") || holidays.length === 0);

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
        <Segmented
          label={t("earnings.view_label")}
          items={[
            { id: "calendar", label: t("earnings.view_calendar") },
            { id: "list", label: t("earnings.view_list") },
          ]}
          value={view}
          onPick={setView}
        />
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
          <ToggleRow label={t("earnings.kind_label")} className="earn-kinds">
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
          trades={trades}
          payments={payments}
          holidays={holidays}
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
            trades={trades}
            payments={payments}
            holidays={holidays}
            onPick={setDetail}
          />
          <ul className="earn-chipkey" aria-label={t("earnings.key_summary")}>
            {(
              [
                ...(events.length > 0 || results.length > 0
                  ? [
                      ["", "earnings.key_print"],
                      ["soon", "earnings.key_soon"],
                      ["beat", "earnings.key_beat"],
                      ["miss", "earnings.key_miss"],
                    ]
                  : []),
                ...(deadlines.length > 0 ? [["tax", "earnings.key_tax"]] : []),
                ...(windows.length > 0 ? [["rebuy", "earnings.key_rebuy"]] : []),
                ...(banks.length > 0 ? [["cb", "earnings.key_cb"]] : []),
                ...(trades.length > 0 ? [["trade", "earnings.key_trade"]] : []),
                ...(dividends.length > 0 ? [["div", "earnings.key_div"]] : []),
                ...(payments.length > 0 ? [["pay", "earnings.key_pay"]] : []),
              ] as [string, string][]
            ).map(([tone, label]) => (
              <li key={label}>
                <span className={`earn-chip earn-chip-key ${tone}`}>
                  <span>{t(label)}</span>
                </span>
              </li>
            ))}
            {holidays.length > 0 && (
              <li>
                <span className="earn-holiday earn-holiday-key">
                  {t("earnings.key_holiday")}
                </span>
              </li>
            )}
          </ul>
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
            {(trades.length > 0 || payments.length > 0) && <BookLegend />}
            {holidays.length > 0 && <HolidayLegend />}
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
