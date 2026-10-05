/**
 * What is coming, as one agenda: every dated thing ahead — prints, ex-dates,
 * filing deadlines, buy-back days, rate decisions — under the week it falls in.
 *
 * The per-kind tables this replaces ran months of rows end to end (about
 * fifty thousand pixels on a phone for a busy watchlist). A week header is
 * what a reader scans by, so the list opens on the next few weeks and a
 * button reveals the next few more. The filters have already run by the time
 * rows arrive here: the cut is made over what the reader asked to see, so a
 * narrow filter reaches further ahead instead of showing four empty weeks.
 */

import { Fragment, useState, type ReactNode } from "react";
import { useLang, useT } from "../../shell/i18n";
import { DenseRow } from "../../ui/Rows";
import type {
  CalendarDividend,
  CalendarEvent,
  CentralBankDecision,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { cash } from "./Dividends";
import { days, plain } from "./format";
import type { T } from "./format";
import { loss } from "./Repurchase";
import { taxTitle } from "./Tax";

/** Weeks shown at first, and added by each "show more". */
const WEEKS = 4;

const DAY = 86_400_000;

type Row = {
  key: string;
  date: string | null;
  node: ReactNode;
};

function utc(iso: string): number {
  const [year = 0, month = 1, day = 1] = iso.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

/** The Monday of the week an ISO day is in, as a UTC timestamp. */
function monday(iso: string): number {
  const at = utc(iso);
  return at - ((new Date(at).getUTCDay() + 6) % 7) * DAY;
}

/** "Wed 14 Oct": the day a row lands on, off the catalog's own names. */
function shortDate(iso: string, t: T): string {
  const at = new Date(utc(iso));
  const weekday = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][at.getUTCDay()];
  return `${t(`earnings.wd_${weekday}`)} ${at.getUTCDate()} ${t(`earnings.mon_${at.getUTCMonth() + 1}`)}`;
}

/** "This week", "Next week", then the span: "13–19 Oct", "28 Oct – 3 Nov". */
function weekLabel(start: number, thisWeek: number, t: T): string {
  const gap = Math.round((start - thisWeek) / DAY / 7);
  if (gap <= 0) return t("earnings.week_this");
  if (gap === 1) return t("earnings.week_next");
  const from = new Date(start);
  const to = new Date(start + 6 * DAY);
  const month = (at: Date) => t(`earnings.mon_${at.getUTCMonth() + 1}`);
  return from.getUTCMonth() === to.getUTCMonth()
    ? `${from.getUTCDate()}–${to.getUTCDate()} ${month(to)}`
    : `${from.getUTCDate()} ${month(from)} – ${to.getUTCDate()} ${month(to)}`;
}

/** A row with no ticker behind it, so no page to open: the dense row's look. */
function Plain({
  title,
  sub,
  date,
  until,
  approximate = false,
}: {
  title: string;
  sub: string;
  date: string;
  until: number;
  /** A statutory default that varies by region: printed with a "≈". */
  approximate?: boolean;
}) {
  const t = useT();
  return (
    <div className="ag-dense-row">
      <div className="ag-dense-main">
        <div className="ag-dense-l1">{title}</div>
        <div className="ag-dense-l2">{sub}</div>
      </div>
      <div className="ag-dense-side">
        <div className="ag-dense-l1">
          {`${approximate ? t("earnings.tax_approx_mark") : ""}${shortDate(date, t)}`}
        </div>
        <div className="ag-dense-l2">{`${days(until)} ${t("earnings.list_col_days_out")}`}</div>
      </div>
    </div>
  );
}

function PrintRow({ event }: { event: CalendarEvent }) {
  const t = useT();
  return (
    <DenseRow
      row={event}
      spec={{
        ticker: (e) => e.ticker,
        names: true,
        sub: () => [t("earnings.kind_earnings")],
        value: (e) => (e.date === null ? "" : shortDate(e.date, t)),
        delta: (e) => `${days(e.days_until)} ${t("earnings.list_col_days_out")}`,
      }}
    />
  );
}

function DividendRow({ dividend }: { dividend: CalendarDividend }) {
  const t = useT();
  const lang = useLang();
  return (
    <DenseRow
      row={dividend}
      spec={{
        ticker: (d) => d.ticker,
        names: true,
        sub: (d) => [
          `${d.projected ? t("earnings.tax_approx_mark") : ""}${t("earnings.div_ex")}`,
        ],
        value: (d) => cash(lang, d.amount, d.currency),
        delta: (d) => shortDate(d.date, t),
      }}
    />
  );
}

function RebuyRow({ window }: { window: RepurchaseWindow }) {
  const t = useT();
  const lang = useLang();
  return (
    <DenseRow
      row={window}
      spec={{
        ticker: (w) => w.ticker,
        names: true,
        sub: (w) => [`${plain(t("earnings.rebuy_windows"))} · ${loss(lang, w)}`],
        value: (w) => shortDate(w.date, t),
        delta: (w) => `${days(w.days_until)} ${t("earnings.list_col_days_out")}`,
      }}
    />
  );
}

export default function Agenda({
  events,
  deadlines,
  windows,
  banks,
  dividends,
}: {
  events: CalendarEvent[];
  deadlines: TaxDeadline[];
  windows: RepurchaseWindow[];
  banks: CentralBankDecision[];
  dividends: CalendarDividend[];
}) {
  const t = useT();
  const [shown, setShown] = useState(WEEKS);
  const rows: Row[] = [
    ...events.map((e) => ({
      key: `print-${e.ticker}`,
      date: e.date,
      node: <PrintRow event={e} />,
    })),
    ...dividends
      .filter((d) => d.days_until >= 0)
      .map((d) => ({
        key: `div-${d.ticker}-${d.date}`,
        date: d.date,
        node: <DividendRow dividend={d} />,
      })),
    ...windows
      .filter((w) => w.days_until >= 0)
      .map((w) => ({
        key: `rebuy-${w.ticker}-${w.sell_date}`,
        date: w.date,
        node: <RebuyRow window={w} />,
      })),
    ...deadlines
      .filter((d) => d.days_until >= 0)
      .map((d) => ({
        key: `tax-${d.key}-${d.year}`,
        date: d.date,
        node: (
          <Plain
            title={taxTitle(d, t)}
            sub={t("earnings.kind_tax")}
            date={d.date}
            until={d.days_until}
            approximate={d.approximate}
          />
        ),
      })),
    ...banks
      .filter((b) => b.days_until >= 0)
      .map((b) => ({
        key: `bank-${b.bank}-${b.date}`,
        date: b.date,
        node: (
          <Plain
            title={t(`earnings.cb_${b.bank}`)}
            sub={t("earnings.kind_banks")}
            date={b.date}
            until={b.days_until}
          />
        ),
      })),
  ];
  if (rows.length === 0) return null;

  const dated = rows
    .filter((row): row is Row & { date: string } => row.date !== null)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  // A print the feed knows but has no day for yet: last, with no week of its own.
  const undated = rows.filter((row) => row.date === null);

  // Weeks with something in them, soonest first. The cut counts these rather
  // than calendar weeks: a quiet fortnight should not eat the page's budget.
  const weeks = new Map<number, Row[]>();
  for (const row of dated) {
    const start = monday(row.date!);
    const bucket = weeks.get(start);
    if (bucket) bucket.push(row);
    else weeks.set(start, [row]);
  }
  const starts = [...weeks.keys()];
  const now = new Date();
  const thisWeek = monday(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`,
  );
  const more = starts.length > shown;

  return (
    <section className="earn-block">
      <h2 className="earn-h2">{plain(t("earnings.upcoming"))}</h2>
      {starts.slice(0, shown).map((start) => (
        <div key={start} className="earn-week">
          <h3 className="earn-week-h">{weekLabel(start, thisWeek, t)}</h3>
          <div className="ag-dense">
            {weeks.get(start)!.map((row) => (
              <Fragment key={row.key}>{row.node}</Fragment>
            ))}
          </div>
        </div>
      ))}
      {!more && undated.length > 0 && (
        <div className="earn-week">
          <h3 className="earn-week-h">{t("earnings.week_undated")}</h3>
          <div className="ag-dense">
            {undated.map((row) => (
              <Fragment key={row.key}>{row.node}</Fragment>
            ))}
          </div>
        </div>
      )}
      {more && (
        <button
          type="button"
          className="ag-btn earn-show-more"
          onClick={() => setShown(shown + WEEKS)}
        >
          {t("earnings.show_more_weeks")}
        </button>
      )}
    </section>
  );
}
