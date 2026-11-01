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

/** "Mon–Fri · 22:30", or "Off" when the switch is. */
export function whenLabel(slot: Schedule, names: string[], t: T): string {
  if (!slot.on) return t("chat.sched_off");
  return t("chat.sched_when", {
    days: daysLabel(slot.days, names, t),
    time: slot.time,
  });
}
