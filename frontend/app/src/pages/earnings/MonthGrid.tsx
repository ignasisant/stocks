/**
 * One month as a grid of weeks, with a chip per print in the day it lands on.
 *
 * Every chip is a button that hands its event to `onPick`, and the page opens
 * one dialog for whichever was clicked (`EventDetail`): a past print gets the
 * result overview, every other kind a short card on what the date means for
 * the reader — a dividend, what lands in the account. The dialogs link on to
 * the ticker; a chip never navigates by itself.
 *
 * Results are drawn before upcoming prints inside a cell: on the one day that
 * carries both, what already happened reads first.
 * The reader's own dates lead — tax deadlines, then the day a loss sold can
 * be bought back, then the Fed and ECB — and ex-dividend chips go last: a
 * print moves a price, an ex-date only docks it by the payment.
 *
 * A cell shows a handful of chips and folds the rest behind "+N": the last
 * week of a reporting season stacks seven prints on a Wednesday, and one tall
 * cell stretches its whole row. Saturday and Sunday run narrower — markets are
 * shut, and almost nothing lands there. The stacking and the fold live in
 * `DayChips`, which the Home screen's four-week grid draws its cells with too.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { byDate, isSoon, monthWeeks } from "./data";
import type {
  CalendarDividend,
  CalendarEvent,
  CalendarResult,
  CentralBankDecision,
  Day,
  EventPick,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { CentralBankChip } from "./CentralBanks";
import { DividendChip } from "./Dividends";
import { eps, signedPct } from "./format";
import type { T } from "./format";
import { RepurchaseChip } from "./Repurchase";
import { TaxChip } from "./Tax";

/** More chips than this and the cell shows one fewer, plus "+N". */
const CELL_CHIPS = 5;

const WEEKDAYS = [
  "earnings.wd_mon",
  "earnings.wd_tue",
  "earnings.wd_wed",
  "earnings.wd_thu",
  "earnings.wd_fri",
  "earnings.wd_sat",
  "earnings.wd_sun",
];

/** "AAPL — Apple Inc.", or the bare symbol while no catalog knows the name. */
function named(ticker: string, name: string | undefined): string {
  return name ? `${ticker} — ${name}` : ticker;
}

/**
 * The chip's mark. Same batched `/market/profiles` lookup the ticker cells use,
 * so a month of chips costs one request, and a chip nobody has a logo for is
 * just its symbol.
 */
function Mark({ logo }: { logo: string | null | undefined }) {
  return logo ? <img src={logo} alt="" loading="lazy" /> : null;
}

/** The hover line a past chip carries: EPS, what was expected, the surprise. */
function resultTitle(result: CalendarResult, name: string | undefined, t: T): string {
  const bits = [named(result.ticker, name)];
  if (result.reported_eps !== null) {
    const versus =
      result.eps_estimate === null
        ? ""
        : t("earnings.chip_vs_est", { est: eps(result.eps_estimate) });
    bits.push(`EPS ${eps(result.reported_eps)}${versus}`);
  }
  if (result.surprise_pct !== null) bits.push(signedPct(result.surprise_pct));
  return bits.join(" · ") + t("earnings.chip_click_details");
}

function ResultChip({
  result,
  onPick,
}: {
  result: CalendarResult;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const profile = useTickerProfile(result.ticker);
  // `beat` is three-valued. Null is "there was nothing to compare", so it gets
  // neither the verdict colour nor the arrow — a name that reported without a
  // published estimate has not missed.
  const verdict = result.beat === null ? "" : result.beat ? " beat" : " miss";
  const arrow = result.beat === null ? "" : result.beat ? " ▲" : " ▼";
  return (
    <button
      type="button"
      className={`earn-chip past${verdict}`}
      title={resultTitle(result, profile?.name, t)}
      onClick={() => onPick({ kind: "result", item: result })}
    >
      <Mark logo={profile?.logo} />
      <span>
        {result.ticker}
        {arrow}
      </span>
    </button>
  );
}

function EventChip({
  event,
  onPick,
}: {
  event: CalendarEvent;
  onPick: (pick: EventPick) => void;
}) {
  const profile = useTickerProfile(event.ticker);
  return (
    <button
      type="button"
      className={`earn-chip${isSoon(event) ? " soon" : ""}`}
      title={named(event.ticker, profile?.name)}
      onClick={() => onPick({ kind: "print", item: event })}
    >
      <Mark logo={profile?.logo} />
      <span>{event.ticker}</span>
    </button>
  );
}

/** Everything that lands on one day, by kind. */
export type DayItems = {
  events: CalendarEvent[];
  results: CalendarResult[];
  deadlines: TaxDeadline[];
  windows: RepurchaseWindow[];
  banks: CentralBankDecision[];
  dividends: CalendarDividend[];
};

/**
 * One day's chips in reading order, folded past `limit` behind "+N". The fold
 * shows one fewer than the limit, so a cell never draws a button that hides a
 * single chip it had room for.
 */
export function DayChips({
  events,
  results,
  deadlines,
  windows,
  banks,
  dividends,
  onPick,
  limit = CELL_CHIPS,
}: DayItems & { onPick: (pick: EventPick) => void; limit?: number }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const chips: ReactNode[] = [
    ...deadlines.map((deadline) => (
      <TaxChip key={`t-${deadline.key}`} deadline={deadline} onPick={onPick} />
    )),
    ...windows.map((window) => (
      <RepurchaseChip
        key={`w-${window.ticker}-${window.sell_date}`}
        window={window}
        onPick={onPick}
      />
    )),
    ...banks.map((decision) => (
      <CentralBankChip key={`b-${decision.bank}`} decision={decision} onPick={onPick} />
    )),
    ...results.map((result) => (
      <ResultChip key={`r-${result.ticker}`} result={result} onPick={onPick} />
    )),
    ...events.map((event) => (
      <EventChip key={`e-${event.ticker}`} event={event} onPick={onPick} />
    )),
    ...dividends.map((dividend) => (
      <DividendChip key={`d-${dividend.ticker}`} dividend={dividend} onPick={onPick} />
    )),
  ];
  const folds = chips.length > limit;
  const shown = folds && !open ? chips.slice(0, limit - 1) : chips;
  return (
    <>
      {shown}
      {folds && (
        <button
          type="button"
          className="earn-more"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open
            ? t("earnings.chips_less")
            : t("earnings.chips_more", { n: chips.length - shown.length })}
        </button>
      )}
    </>
  );
}

function Cell({
  day,
  onPick,
  ...items
}: DayItems & { day: Day; onPick: (pick: EventPick) => void }) {
  const classes = ["earn-day"];
  if (!day.inMonth) classes.push("dim");
  if (day.today) classes.push("today");
  return (
    <div className={classes.join(" ")}>
      <div className="earn-daynum">{day.day}</div>
      <DayChips {...items} onPick={onPick} />
    </div>
  );
}

export default function MonthGrid({
  year,
  month,
  now,
  events,
  results,
  deadlines,
  windows,
  banks,
  dividends,
  onPick,
}: {
  year: number;
  month: number;
  now: string;
  events: CalendarEvent[];
  results: CalendarResult[];
  deadlines: TaxDeadline[];
  windows: RepurchaseWindow[];
  banks: CentralBankDecision[];
  dividends: CalendarDividend[];
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const upcoming = byDate(events);
  const reported = byDate(results);
  const due = byDate(deadlines);
  const freed = byDate(windows);
  const decided = byDate(banks);
  const exDates = byDate(dividends);
  return (
    <div className="earn-cal-scroll">
      <div className="earn-cal">
        {WEEKDAYS.map((key) => (
          <div className="earn-wd" key={key}>
            {t(key)}
          </div>
        ))}
        {monthWeeks(year, month, now).map((week) =>
          week.map((day) => (
            <Cell
              key={day.iso}
              day={day}
              events={upcoming.get(day.iso) ?? []}
              results={reported.get(day.iso) ?? []}
              deadlines={due.get(day.iso) ?? []}
              windows={freed.get(day.iso) ?? []}
              banks={decided.get(day.iso) ?? []}
              dividends={exDates.get(day.iso) ?? []}
              onPick={onPick}
            />
          )),
        )}
      </div>
    </div>
  );
}
