/**
 * The agenda: the next seven days as a list, each name's weight in the book
 * beside it.
 *
 * It is the Calendar page's own "next 7 days" strip (`earnings/Strip`) — the
 * same rows, the same weights from `/earnings`, the same side panel on a tap —
 * scoped to the union of the calendar's own filter sets (`portfolio`,
 * `favorites` and one per watchlist tag): the held + starred + tagged set. The
 * reader's own dates (tax, buy-backs) and the banks belong to no name, so the
 * scope leaves them alone. The four-week grid it replaces sat almost empty for
 * a book that reports a few times a quarter; the full grid is one link away.
 */

import "../earnings/earnings.css";
import { useState } from "react";
import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import type { EarningsCalendar, EventPick } from "../earnings/data";
import EventDetail from "../earnings/EventDetail";
import { Strip } from "../earnings/Strip";
import { CardQuery, Card } from "./ui";
import { plain } from "./format";

export function EarningsCard() {
  const t = useT();
  const query = useApi(() => get<EarningsCalendar>("/earnings"), []);
  // The row whose dialog is open, if any: one dialog serves the whole list.
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
        const named = (row: { ticker: string }) => scope.has(row.ticker);
        return (
          <Card className="hm-agenda">
            <Strip
              events={calendar.upcoming.filter(named)}
              dividends={calendar.dividends.filter(named)}
              deadlines={calendar.tax_deadlines}
              windows={calendar.repurchase_windows}
              banks={calendar.central_banks}
              weights={calendar.weights}
              onPick={setOpen}
            />
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
