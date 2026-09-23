/**
 * A compact four-week reporting grid: last week, this week, and the two
 * coming ones, so recent prints sit beside what is due.
 *
 * Five weekday columns only — equity prints never land on a weekend, and a
 * Sat/Sun column would sit permanently empty and just waste width.
 *
 * Scope is the union of the calendar's own filter sets (`portfolio`,
 * `favorites` and one per watchlist tag), which is exactly the held +
 * starred + tagged set the Streamlit page builds its grid from. An untagged
 * watchlist name is not in any of them, and it is not in the grid either.
 *
 * Past prints open the ticker's own page rather than the result dialog the
 * Streamlit grid pops: the figures behind that dialog are per-ticker, the page
 * already shows them, and every symbol on screen owes the reader a link home.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT, useLang } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { CardQuery, Card, CardTitle, Note } from "./ui";
import { addDays, dayKey, decimal, mondayOf, plain, type Translate } from "./format";
import type { CalendarEvent, CalendarResult, EarningsCalendar } from "./types";

const WEEKS = 4;
const WEEKDAYS = 5;
/** How close a print has to be for its chip to go red. */
const SOON_DAYS = 7;

export function EarningsCard() {
  const t = useT();
  const lang = useLang();
  const query = useApi(() => get<EarningsCalendar>("/earnings"), []);

  return (
    <CardQuery
      query={query}
      title={plain(t("home.earnings_upcoming"))}
      note={t("home.earnings_unavailable")}
      skeleton={<Skeleton rows={6} />}
    >
      {(calendar) => {
        const scope = new Set(Object.values(calendar.groups).flat());
        // Nothing held and nothing starred: the card never comes.
        if (scope.size === 0) return null;

        const today = new Date();
        // The previous week's Monday through the last shown Friday.
        const start = addDays(mondayOf(today), -7);
        const end = addDays(start, WEEKS * 7 - 1);
        const upcoming = groupUpcoming(calendar.upcoming, scope, start, end);
        const results = groupResults(calendar.results, scope, start, end);
        const empty = upcoming.size === 0 && results.size === 0;

        return (
          <Card>
            <CardTitle>{plain(t("home.earnings_upcoming"))}</CardTitle>
            {empty ? (
              <Note>{t("home.no_reports_3w")}</Note>
            ) : (
              <>
                <table className="hm-cal">
                  <thead>
                    <tr>
                      {Array.from({ length: WEEKDAYS }, (_, day) => (
                        <th key={day}>{t(`home.wd_${day}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: WEEKS }, (_, week) => (
                      <tr key={week}>
                        {Array.from({ length: WEEKDAYS }, (_, day) => {
                          const date = addDays(start, week * 7 + day);
                          const key = dayKey(date);
                          const reference = dayKey(today);
                          const tone =
                            key === reference
                              ? "hm-today"
                              : key < reference
                                ? "hm-dim"
                                : "";
                          return (
                            <td key={day} className={tone}>
                              <div className="hm-cal-day">{date.getDate()}</div>
                              {(results.get(key) ?? []).map((result) => (
                                <ResultChip
                                  key={`${result.ticker}-${result.date}`}
                                  result={result}
                                  t={t}
                                  lang={lang}
                                />
                              ))}
                              {(upcoming.get(key) ?? []).map((event) => (
                                <EventChip key={event.ticker} event={event} />
                              ))}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="hm-caption">{t("home.earnings_3w_caption")}</p>
              </>
            )}
            <Link page="earnings" className="hm-link">
              {t("home.link_earnings_calendar")}
            </Link>
          </Card>
        );
      }}
    </CardQuery>
  );
}

function inWindow(iso: string, start: Date, end: Date): boolean {
  return iso >= dayKey(start) && iso <= dayKey(end);
}

/** Weekday-only, in-window and in-scope events, keyed by their day. */
function groupUpcoming(
  events: CalendarEvent[],
  scope: Set<string>,
  start: Date,
  end: Date,
): Map<string, CalendarEvent[]> {
  const byDay = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    if (!event.date || !scope.has(event.ticker)) continue;
    if (!inWindow(event.date, start, end) || !isWeekday(event.date)) continue;
    byDay.set(event.date, [...(byDay.get(event.date) ?? []), event]);
  }
  return byDay;
}

function groupResults(
  results: CalendarResult[],
  scope: Set<string>,
  start: Date,
  end: Date,
): Map<string, CalendarResult[]> {
  const byDay = new Map<string, CalendarResult[]>();
  for (const result of results) {
    if (!scope.has(result.ticker)) continue;
    if (!inWindow(result.date, start, end) || !isWeekday(result.date)) continue;
    byDay.set(result.date, [...(byDay.get(result.date) ?? []), result]);
  }
  return byDay;
}

function isWeekday(iso: string): boolean {
  const parts = iso.split("-").map(Number);
  const [year, month, day] = parts;
  if (year === undefined || month === undefined || day === undefined) return false;
  const weekday = new Date(year, month - 1, day).getDay();
  return weekday >= 1 && weekday <= 5;
}

/** An upcoming print — neutral, red once it is inside a week. */
function EventChip({ event }: { event: CalendarEvent }) {
  const soon = event.days_until !== null && event.days_until <= SOON_DAYS;
  return (
    <Link
      page="ticker"
      params={{ ticker: event.ticker }}
      className={soon ? "hm-cal-chip hm-soon" : "hm-cal-chip"}
    >
      {event.ticker}
    </Link>
  );
}

/**
 * A print that already landed — green beat, red miss, grey when there was
 * nothing to compare it against (`beat: null` is not a miss).
 */
function ResultChip({
  result,
  t,
  lang,
}: {
  result: CalendarResult;
  t: Translate;
  lang: string;
}) {
  const verdict = result.beat === null ? "" : result.beat ? " hm-beat" : " hm-miss";
  const arrow = result.beat === null ? "" : result.beat ? " ▲" : " ▼";
  const bits = [result.ticker];
  const reported = decimal(result.reported_eps, lang, 2);
  if (reported !== null) {
    const estimate = decimal(result.eps_estimate, lang, 2);
    const against =
      estimate === null ? "" : t("earnings.chip_vs_est", { est: estimate });
    bits.push(`EPS ${reported}${against}`);
  }
  const surprise = decimal(result.surprise_pct, lang, 1, { signed: true });
  if (surprise !== null) bits.push(`${surprise}%`);
  return (
    <Link
      page="ticker"
      params={{ ticker: result.ticker }}
      className={`hm-cal-chip hm-past${verdict}`}
      title={bits.join(" · ") + t("earnings.chip_click_details")}
    >
      {result.ticker}
      {arrow}
    </Link>
  );
}
