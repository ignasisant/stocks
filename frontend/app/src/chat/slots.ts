/**
 * What a scheduled run's row says about when it goes out — pure, so the
 * profile's Notifications tab and the chat's "Scheduled" block say it the
 * same way (`Scheduled.tsx`).
 */

import type { Schedule } from "../shell/session";

type T = (key: string, slots?: Record<string, string | number>) => string;

/** Monday-first short weekday names in `lang` (1 Jan 2024 was a Monday). */
export function weekdayNames(lang: string): string[] {
  const format = new Intl.DateTimeFormat(lang, { weekday: "short", timeZone: "UTC" });
  return Array.from({ length: 7 }, (_, d) =>
    format.format(new Date(Date.UTC(2024, 0, 1 + d))),
  );
}

/** "Mon–Fri", "Every day", or the days named — what a row says it runs on. */
export function daysLabel(
  days: number[],
  names: string[],
  t: (key: string) => string,
): string {
  const set = [...new Set(days)].sort((a, b) => a - b).join(",");
  if (set === "") return t("chat.sched_no_days");
  if (set === "0,1,2,3,4,5,6") return t("chat.sched_every_day");
  if (set === "0,1,2,3,4") return t("chat.sched_weekdays");
  return set
    .split(",")
    .map((d) => names[Number(d)])
    .join(", ");
}

/** "Mon–Fri · 08:30", "Mon–Fri · after the US close (~22:30)", or "Off". */
export function whenLabel(
  slot: Schedule,
  names: string[],
  t: T,
  zone?: string | null,
): string {
  if (!slot.on) return t("chat.sched_off");
  return t("chat.sched_when", {
    days: daysLabel(slot.days, names, t),
    time: slot.close ? t("chat.sched_close_at", { time: closeTime(zone) }) : slot.time,
  });
}

/**
 * The US session's end — 16:30 New York, when an evening briefing's card is
 * written (`daily.CLOSE_AT`) — on the reader's wall clock, "HH:MM". It goes
 * out within the quarter hour after: the server ticks every 15 minutes.
 *
 * Today's date, so it follows both sides' daylight saving: 22:30 in Madrid
 * most of the year, 21:30 in the weeks the two switch on different Sundays.
 */
export function closeTime(zone?: string | null, now: Date = new Date()): string {
  const ny = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
  }).formatToParts(now);
  const at = (type: Intl.DateTimeFormatPartTypes) =>
    Number(ny.find((part) => part.type === type)?.value);
  // New York's offset now, from its wall clock against the instant.
  const [year, month, day] = [at("year"), at("month") - 1, at("day")];
  const nyWall = Date.UTC(year, month, day, at("hour"), at("minute"));
  const offset = nyWall - Math.floor(now.getTime() / 60_000) * 60_000;
  const close = new Date(Date.UTC(year, month, day, 16, 30) - offset);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: zone || undefined,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(close);
  } catch {
    // A zone `Intl` does not know: the browser's own clock.
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(close);
  }
}
