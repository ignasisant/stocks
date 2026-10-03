/**
 * A compact four-week calendar: last week, this week, and the two coming
 * ones, so recent prints sit beside what is due.
 *
 * Five weekday columns only — markets are shut at the weekend, so prints,
 * ex-dates and rate decisions never land there, and a Sat/Sun column would sit
 * permanently empty and just waste width. A tax date or a buy-back day that
 * falls on one is left to the full calendar.
 *
 * It draws what the Earnings page's grid draws, with the same chips and the
 * same fold (`DayChips`, three to a cell here): tax deadlines, buy-back days,
 * Fed and ECB decisions, prints and ex-dividend dates. Names are scoped to the
 * union of the calendar's own filter sets (`portfolio`, `favorites` and one per
 * watchlist tag): the held + starred + tagged set. The reader's own dates (tax,
 * buy-backs) and the banks belong to no name, so the scope leaves them alone;
 * and as on the page, the banks alone never make the card worth drawing.
 *
 * Every chip opens the dialog the Earnings page opens (`EventDetail`): a past
 * print its result, a dividend what lands in the account, the rest what the
 * date means. The dialogs carry the links on to the ticker.
 */

import "../earnings/earnings.css";
import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { byDate } from "../earnings/data";
import type { EarningsCalendar, EventPick } from "../earnings/data";
import EventDetail from "../earnings/EventDetail";
import { DayChips } from "../earnings/MonthGrid";
import type { DayItems } from "../earnings/MonthGrid";
import { CardQuery, Card, CardTitle, Note } from "./ui";
import { addDays, dayKey, mondayOf, plain } from "./format";

const WEEKS = 4;
const WEEKDAYS = 5;
/** A cell is ~62px tall: three chips, then "+N". */
const CELL_CHIPS = 3;

export function EarningsCard() {
  const t = useT();
  const query = useApi(() => get<EarningsCalendar>("/earnings"), []);
  // The chip whose dialog is open, if any. Held here rather than in the chip
  // so one dialog serves the whole grid.
  const [open, setOpen] = useState<EventPick | null>(null);

  return (
    <CardQuery
      query={query}
      title={plain(t("home.calendar_title"))}
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
        const shown = (row: { date: string | null }) =>
          row.date !== null && inWindow(row.date, start, end) && isWeekday(row.date);
        const named = (row: { ticker: string; date: string | null }) =>
          scope.has(row.ticker) && shown(row);
        const upcoming = byDate(calendar.upcoming.filter(named));
        const reported = byDate(calendar.results.filter(named));
        const exDates = byDate(calendar.dividends.filter(named));
        const due = byDate(calendar.tax_deadlines.filter(shown));
        const freed = byDate(calendar.repurchase_windows.filter(shown));
        const decided = byDate(calendar.central_banks.filter(shown));
        const empty =
          upcoming.size + reported.size + exDates.size + due.size + freed.size === 0;
        const itemsOn = (key: string): DayItems => ({
          events: upcoming.get(key) ?? [],
          results: reported.get(key) ?? [],
          deadlines: due.get(key) ?? [],
          windows: freed.get(key) ?? [],
          banks: decided.get(key) ?? [],
          dividends: exDates.get(key) ?? [],
        });
        const reference = dayKey(today);

        return (
          <Card>
            <CardTitle>{plain(t("home.calendar_title"))}</CardTitle>
            {empty ? (
              <Note>{t("home.calendar_empty")}</Note>
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
                          const tone =
                            key === reference
                              ? "hm-today"
                              : key < reference
                                ? "hm-dim"
                                : "";
                          return (
                            <td key={day} className={tone}>
                              <div className="hm-cal-day">{date.getDate()}</div>
                              <DayChips
                                {...itemsOn(key)}
                                onPick={setOpen}
                                limit={CELL_CHIPS}
                              />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="hm-caption">{t("home.calendar_caption")}</p>
              </>
            )}
            <Link page="earnings" className="hm-link">
              {t("home.link_earnings_calendar")}
            </Link>
            {open ? (
              <EventDetail
                pick={open}
                held={calendar.groups.portfolio ?? []}
                onClose={() => setOpen(null)}
              />
            ) : null}
          </Card>
        );
      }}
    </CardQuery>
  );
}

function inWindow(iso: string, start: Date, end: Date): boolean {
  return iso >= dayKey(start) && iso <= dayKey(end);
}

function isWeekday(iso: string): boolean {
  const parts = iso.split("-").map(Number);
  const [year, month, day] = parts;
  if (year === undefined || month === undefined || day === undefined) return false;
  const weekday = new Date(year, month - 1, day).getDay();
  return weekday >= 1 && weekday <= 5;
}
