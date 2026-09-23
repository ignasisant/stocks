/**
 * The assistant's one-a-day briefing, first thing on the page.
 *
 * Read-only here, and that is the whole shape of this component. `/daily`
 * reports the stored card; writing one fans out a fetch, spends the account's
 * free-model allowance and takes up to half a minute, which the app owns and
 * this API deliberately does not. So when the stored card is not fresh, the
 * card says it is the one written earlier rather than dressing it as today's —
 * and when nothing is stored at all there is nothing to show, so the section
 * stays off the page instead of shimmering for a card that will never land.
 *
 * `source: "computed"` is the fallback the app writes from the triggers alone
 * when no model answered. It is not prose, and it is not presented as a
 * briefing: that card carries `home.daily_computed_note` in place of the
 * model disclaimer.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { Card, TickerCell } from "./ui";
import { dayKey, monthDay } from "./format";
import type { DailyCard } from "./types";

export function Daily() {
  const t = useT();
  const lang = useLang();
  // The language is part of the freshness check, not decoration: a reader who
  // switched the app to Spanish should not be left holding an English card.
  const query = useApi(() => get<DailyCard>("/daily", { lang }), [lang]);

  return (
    <Loaded query={query} skeleton={<Skeleton rows={4} />}>
      {(card) => {
        if (!card.headline) return null;
        const stamp = card.day ?? card.action_day;
        const written = monthDay(stamp, t);
        const when =
          stamp === dayKey(new Date())
            ? t("home.daily_today_no_time")
            : (written ?? stamp);
        return (
          <Card className="hm-daily">
            <div className="hm-daily-head">
              <span className="hm-daily-badge">{t("home.daily_badge")}</span>
              <span className="hm-daily-when">{when}</span>
            </div>
            <p className="hm-daily-headline">{card.headline}</p>
            {card.bullets.length > 0 ? (
              <ul className="hm-daily-list">
                {card.bullets.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            ) : null}
            {card.focus.length > 0 ? (
              <div className="hm-daily-chips">
                {card.focus.map((ticker) => (
                  <TickerCell key={ticker} ticker={ticker} />
                ))}
              </div>
            ) : null}
            {!card.fresh ? (
              <p className="hm-note">
                {t("home.daily_stale", { date: written ?? stamp })}
              </p>
            ) : null}
            <p className="hm-note">
              {card.source === "computed"
                ? t("home.daily_computed_note")
                : t("home.daily_disclaimer")}
            </p>
          </Card>
        );
      }}
    </Loaded>
  );
}
