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
 *
 * The reader's own trades sit after the prints (hollow: something they did,
 * not something coming) and booked payouts after the ex-dates they paid. A
 * market holiday is no chip: it is a mark beside the day number (`Book.tsx`).
 *
 * A loss sale's buy-back window is more than its last day: every day from the
 * sale up to the chip is shaded amber, because a buy on any of them would
 * defer the loss.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { blocking, byDate, isSoon, monthWeeks } from "./data";
import type {
  CalendarDividend,
  CalendarEvent,
  CalendarPayment,
  CalendarResult,
  CalendarTrade,
  CentralBankDecision,
  Day,
  EventPick,
  MarketHoliday,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { HolidayMark, PaymentChip, TradeChip } from "./Book";
import { CentralBankChip } from "./CentralBanks";
import { DividendChip } from "./Dividends";
import { longDate } from "./format";
import type { T } from "./format";
import { blockedTitle, RepurchaseChip } from "./Repurchase";
import { TaxChip } from "./Tax";
import { DASH, decimal, percent } from "../../shell/format";

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
        : t("earnings.chip_vs_est", {
            est: decimal(result.eps_estimate, { digits: 2 }) ?? DASH,
          });
    bits.push(`EPS ${decimal(result.reported_eps, { digits: 2 }) ?? DASH}${versus}`);
  }
  if (result.surprise_pct !== null)
    bits.push(
      percent(result.surprise_pct, { digits: 1, signed: "always", points: true }) ??
        DASH,
    );
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
  /** The reader's own fills and payouts; the Home card draws neither. */
  trades?: CalendarTrade[];
  payments?: CalendarPayment[];
};

/**
 * One day's chips in reading order, folded past `limit` behind "+N". The fold
 * shows one fewer than the limit, so a cell never draws a button that hides a
 * single chip it had room for.
 */
function DayChips({
  events,
  results,
  deadlines,
  windows,
  banks,
  dividends,
  trades = [],
  payments = [],
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
    ...trades.map((trade) => (
      <TradeChip
        key={`x-${trade.ticker}-${trade.side}`}
        trade={trade}
        onPick={onPick}
      />
    )),
    ...dividends.map((dividend) => (
      <DividendChip key={`d-${dividend.ticker}`} dividend={dividend} onPick={onPick} />
    )),
    ...payments.map((payment) => (
      <PaymentChip
        key={`p-${payment.ticker}-${payment.capital ? "c" : "d"}`}
        payment={payment}
        onPick={onPick}
      />
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

/** The chip class each thing on a day is drawn in: the dots reuse the key's colours. */
export function dotKinds(items: DayItems): string[] {
  const kinds: string[] = [];
  const add = (kind: string) => {
    if (!kinds.includes(kind)) kinds.push(kind);
  };
  if (items.deadlines.length > 0) add("tax");
  if (items.windows.length > 0) add("rebuy");
  if (items.banks.length > 0) add("cb");
  for (const result of items.results)
    add(result.beat === null ? "print" : result.beat ? "beat" : "miss");
  for (const event of items.events) add(isSoon(event) ? "soon" : "print");
  if ((items.trades ?? []).length > 0) add("trade");
  if (items.dividends.length > 0) add("div");
  if ((items.payments ?? []).length > 0) add("pay");
  return kinds;
}

/** The ISO day after `iso`. */
function nextDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function isMonday(iso: string): boolean {
  return new Date(`${iso}T00:00:00Z`).getUTCDay() === 1;
}

/**
 * The buy-back window as one bar along the top of every day it runs, joined
 * across the gaps between cells: it starts on the sale, ends the day before
 * the chip that frees it, and names the stock where it starts and at the head
 * of each week it carries on into.
 */
function Band({
  day,
  blocked,
  windows,
}: {
  day: Day;
  blocked: RepurchaseWindow[];
  windows: RepurchaseWindow[];
}) {
  const starts = blocked.filter((w) => w.sell_date === day.iso);
  const ends = windows.some((w) => w.date === nextDay(day.iso));
  const label = starts.length > 0 || isMonday(day.iso);
  const classes = ["earn-band"];
  if (starts.length > 0) classes.push("start");
  if (ends) classes.push("end");
  return (
    <div className={classes.join(" ")} aria-hidden="true">
      {label && <span>{blocked.map((w) => w.ticker).join(" · ")}</span>}
    </div>
  );
}

function Cell({
  day,
  blocked,
  running,
  holidays,
  selected,
  onSelect,
  onPick,
  ...items
}: DayItems & {
  day: Day;
  blocked: RepurchaseWindow[];
  /** Every window the grid draws, so a band knows where it ends. */
  running: RepurchaseWindow[];
  holidays: MarketHoliday[];
  selected: boolean;
  onSelect: (iso: string) => void;
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const classes = ["earn-day"];
  if (!day.inMonth) classes.push("dim");
  if (day.today) classes.push("today");
  else if (day.past) classes.push("past");
  if (selected) classes.push("selected");
  const shaded = blocked.length > 0;
  if (shaded) classes.push("rebuy-block");
  const dots = dotKinds(items);
  return (
    <div
      className={classes.join(" ")}
      title={shaded ? blockedTitle(blocked, t) : undefined}
    >
      {shaded && <Band day={day} blocked={blocked} windows={running} />}
      <div className="earn-dayhead">
        <div className="earn-daynum">{day.day}</div>
        <HolidayMark holidays={holidays} onPick={onPick} />
      </div>
      <div className="earn-day-chips">
        <DayChips {...items} onPick={onPick} />
      </div>
      {/* On a phone the day is its dots; the day's own list opens under the
          grid. A button, so the whole cell's worth is one 44px target. */}
      <button
        type="button"
        className="earn-dots"
        aria-pressed={selected}
        aria-label={`${day.day}`}
        onClick={() => onSelect(day.iso)}
      >
        {dots.map((kind) => (
          <i key={kind} className={`earn-dot ${kind}`} />
        ))}
      </button>
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
  trades = [],
  payments = [],
  holidays = [],
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
  trades?: CalendarTrade[];
  payments?: CalendarPayment[];
  holidays?: MarketHoliday[];
  onPick: (pick: EventPick) => void;
}) {
  const t = useT();
  const [chosen, setChosen] = useState<string | null>(null);
  const upcoming = byDate(events);
  const reported = byDate(results);
  const due = byDate(deadlines);
  const freed = byDate(windows);
  const decided = byDate(banks);
  const exDates = byDate(dividends);
  const filled = byDate(trades);
  const paid = byDate(payments);
  const shut = byDate(holidays);
  const weeks = monthWeeks(year, month, now);
  const days = weeks.flat();
  // The day the phone's panel lists: the one tapped, else today when it is on
  // this page, else nothing yet.
  const open =
    days.find((day) => day.inMonth && day.iso === chosen)?.iso ??
    days.find((day) => day.inMonth && day.today)?.iso ??
    null;
  const itemsOn = (iso: string): DayItems => ({
    events: upcoming.get(iso) ?? [],
    results: reported.get(iso) ?? [],
    deadlines: due.get(iso) ?? [],
    windows: freed.get(iso) ?? [],
    banks: decided.get(iso) ?? [],
    dividends: exDates.get(iso) ?? [],
    trades: filled.get(iso) ?? [],
    payments: paid.get(iso) ?? [],
  });
  const plan = open === null ? null : itemsOn(open);
  const planned =
    plan === null
      ? 0
      : plan.events.length +
        plan.results.length +
        plan.deadlines.length +
        plan.windows.length +
        plan.banks.length +
        plan.dividends.length +
        (plan.trades?.length ?? 0) +
        (plan.payments?.length ?? 0) +
        (shut.get(open as string)?.length ?? 0);
  return (
    <>
      <div className="earn-cal-scroll">
        <div className="earn-cal">
          {WEEKDAYS.map((key) => (
            <div className="earn-wd" key={key}>
              {t(key)}
            </div>
          ))}
          {days.map((day) => (
            <Cell
              key={day.iso}
              day={day}
              {...itemsOn(day.iso)}
              blocked={blocking(windows, day.iso)}
              running={windows}
              holidays={shut.get(day.iso) ?? []}
              selected={day.iso === open}
              onSelect={setChosen}
              onPick={onPick}
            />
          ))}
        </div>
      </div>
      {open !== null && plan !== null && (
        <section className="earn-dayplan" aria-label={open}>
          <h3 className="earn-dayplan-h">{longDate(open, t)}</h3>
          {planned === 0 ? (
            <p className="earn-dayplan-none">{t("earnings.day_none")}</p>
          ) : (
            <div className="earn-dayplan-list">
              <HolidayMark holidays={shut.get(open) ?? []} onPick={onPick} />
              <DayChips {...plan} onPick={onPick} limit={Infinity} />
            </div>
          )}
        </section>
      )}
    </>
  );
}
