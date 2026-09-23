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
import { byDate, isSoon, monthWeeks } from "./data";
import type { CalendarEvent, CalendarResult, Day } from "./data";
import { eps, signedPct } from "./format";
import type { T } from "./format";

const WEEKDAYS = [
  "earnings.wd_mon",
  "earnings.wd_tue",
  "earnings.wd_wed",
  "earnings.wd_thu",
  "earnings.wd_fri",
  "earnings.wd_sat",
  "earnings.wd_sun",
];

/** The hover line a past chip carries: EPS, what was expected, the surprise. */
function resultTitle(result: CalendarResult, t: T): string {
  const bits = [result.ticker];
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
  // `beat` is three-valued. Null is "there was nothing to compare", so it gets
  // neither the verdict colour nor the arrow — a name that reported without a
  // published estimate has not missed.
  const verdict = result.beat === null ? "" : result.beat ? " beat" : " miss";
  const arrow = result.beat === null ? "" : result.beat ? " ▲" : " ▼";
  return (
    <button
      type="button"
      className={`earn-chip past${verdict}`}
      title={resultTitle(result, t)}
      onClick={() => onPick(result)}
    >
      <span>
        {result.ticker}
        {arrow}
      </span>
    </button>
  );
}

function EventChip({ event }: { event: CalendarEvent }) {
  return (
    <Link
      page="ticker"
      params={{ ticker: event.ticker }}
      className={`earn-chip${isSoon(event) ? " soon" : ""}`}
    >
      <span>{event.ticker}</span>
    </Link>
  );
}

function Cell({
  day,
  events,
  results,
  onPick,
}: {
  day: Day;
  events: CalendarEvent[];
  results: CalendarResult[];
  onPick: (result: CalendarResult) => void;
}) {
  const classes = ["earn-day"];
  if (!day.inMonth) classes.push("dim");
  if (day.today) classes.push("today");
  return (
    <div className={classes.join(" ")}>
      <div className="earn-daynum">{day.day}</div>
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
  onPick,
}: {
  year: number;
  month: number;
  now: string;
  events: CalendarEvent[];
  results: CalendarResult[];
  onPick: (result: CalendarResult) => void;
}) {
  const t = useT();
  const upcoming = byDate(events);
  const reported = byDate(results);
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
              onPick={onPick}
            />
          )),
        )}
      </div>
    </div>
  );
}
