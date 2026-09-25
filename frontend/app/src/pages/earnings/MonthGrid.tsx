/**
 * One month as a grid of weeks, with a chip per print in the day it lands on.
 *
 * Upcoming chips are links to the ticker page — there is nothing else to say
 * about a date that has not happened. Past chips are buttons: they open the
 * result overview, which is what the Streamlit calendar does with its custom
 * component, except that here the click never has to travel to a server.
 *
 * Results are drawn before upcoming prints inside a cell, matching the Python
 * page: on the one day that carries both, what already happened reads first.
 */

import { Link } from "../../shell/router";
import { useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { byDate, isSoon, monthWeeks } from "./data";
import type { CalendarEvent, CalendarResult, Day, TaxDeadline } from "./data";
import { eps, signedPct } from "./format";
import type { T } from "./format";
import { TaxChip } from "./Tax";

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
 * just its symbol — as it is in the Streamlit grid.
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
  onPick: (result: CalendarResult) => void;
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
      onClick={() => onPick(result)}
    >
      <Mark logo={profile?.logo} />
      <span>
        {result.ticker}
        {arrow}
      </span>
    </button>
  );
}

function EventChip({ event }: { event: CalendarEvent }) {
  const profile = useTickerProfile(event.ticker);
  return (
    <Link
      page="ticker"
      params={{ ticker: event.ticker }}
      className={`earn-chip${isSoon(event) ? " soon" : ""}`}
      title={named(event.ticker, profile?.name)}
    >
      <Mark logo={profile?.logo} />
      <span>{event.ticker}</span>
    </Link>
  );
}

function Cell({
  day,
  events,
  results,
  deadlines,
  onPick,
}: {
  day: Day;
  events: CalendarEvent[];
  results: CalendarResult[];
  deadlines: TaxDeadline[];
  onPick: (result: CalendarResult) => void;
}) {
  const classes = ["earn-day"];
  if (!day.inMonth) classes.push("dim");
  if (day.today) classes.push("today");
  return (
    <div className={classes.join(" ")}>
      <div className="earn-daynum">{day.day}</div>
      {deadlines.map((deadline) => (
        <TaxChip key={`t-${deadline.key}`} deadline={deadline} />
      ))}
      {results.map((result) => (
        <ResultChip key={`r-${result.ticker}`} result={result} onPick={onPick} />
      ))}
      {events.map((event) => (
        <EventChip key={`e-${event.ticker}`} event={event} />
      ))}
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
  onPick,
}: {
  year: number;
  month: number;
  now: string;
  events: CalendarEvent[];
  results: CalendarResult[];
  deadlines: TaxDeadline[];
  onPick: (result: CalendarResult) => void;
}) {
  const t = useT();
  const upcoming = byDate(events);
  const reported = byDate(results);
  const due = byDate(deadlines);
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
              onPick={onPick}
            />
          )),
        )}
      </div>
    </div>
  );
}
