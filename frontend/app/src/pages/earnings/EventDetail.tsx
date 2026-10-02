/**
 * The dialog a calendar chip opens: what that date is, and what it means for
 * the reader.
 *
 * A past print keeps the result overview it always opened (`ResultDetail`).
 * Every other kind gets a short card in the same modal shell — narrower,
 * because it carries a figure and a few lines rather than a breakdown:
 *
 * - an upcoming print: when, what the report contains, and a way on to the
 *   ticker, which is where the chip used to lead;
 * - a dividend: what lands in the account. Gross is per share × shares; net
 *   takes off the withholding the book's own statements printed for the name
 *   (or its currency), and says so when they printed none rather than
 *   promising a 0% no broker charged. The base-currency figure is at the
 *   ex-date's rate once it went ex, today's while it is ahead. No ticker CTA:
 *   the reader clicked to see the cash, not to leave;
 * - a tax deadline, a buy-back window, a rate decision: the date, the rule
 *   behind it in plain words, and where to act on it if anywhere.
 *
 * Shared by the Earnings page and the Home screen's four-week grid, so the two
 * explain a date the same way.
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Link } from "../../shell/router";
import { useLang, useT } from "../../shell/i18n";
import { useTickerProfile } from "../../shell/tickers";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { moneyIn, percent, shares as formatShares } from "../portfolio/format";
import type {
  CalendarDividend,
  CalendarEvent,
  CentralBankDecision,
  EventPick,
  RepurchaseWindow,
  TaxDeadline,
} from "./data";
import { isSoon } from "./data";
import { cash } from "./Dividends";
import { longDate } from "./format";
import type { T } from "./format";
import { loss, rule } from "./Repurchase";
import ResultDetail from "./ResultDetail";
import { taxBody, taxTitle } from "./Tax";

const DASH = "—";

/** "Today", "in 9 days", "3 days ago" — how far the date is, in words. */
export function relative(daysUntil: number | null, t: T): string {
  if (daysUntil === null) return DASH;
  if (daysUntil === 0) return t("earnings.ev_today");
  if (daysUntil === 1) return t("earnings.ev_tomorrow");
  if (daysUntil === -1) return t("earnings.ev_yesterday");
  return daysUntil > 0
    ? t("earnings.ev_in_days", { n: daysUntil })
    : t("earnings.ev_days_ago", { n: -daysUntil });
}

// ------------------------------------------------------------------- shell

function Dialog({
  head,
  children,
  onClose,
}: {
  head: ReactNode;
  children: ReactNode;
  onClose: () => void;
}) {
  const t = useT();
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Focus moves into the dialog and goes back to the chip it came from, so a
  // keyboard reader paging through a month does not restart from the top.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    return () => before?.focus?.();
  }, []);

  return (
    <div
      className="earn-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="earn-modal-card earn-ev"
        role="dialog"
        aria-modal="true"
        aria-label={t("earnings.ev_dialog")}
      >
        <div className="earn-modal-head">
          {head}
          <button ref={close} type="button" className="earn-close" onClick={onClose}>
            {t("earnings.close")}
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Logo, symbol (linked) and name over a line saying what kind of date it is. */
function TickerHead({ ticker, sub }: { ticker: string; sub: string }) {
  const profile = useTickerProfile(ticker);
  return (
    <div className="earn-modal-id">
      {profile?.logo && (
        <img className="earn-modal-logo" src={profile.logo} alt="" loading="lazy" />
      )}
      <div>
        <div className="earn-modal-name">
          <Link className="earn-ticker" page="ticker" params={{ ticker }}>
            {ticker}
          </Link>
          {profile?.name && <span>{` — ${profile.name}`}</span>}
        </div>
        <div className="earn-modal-date">{sub}</div>
      </div>
    </div>
  );
}

function PlainHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="earn-modal-id">
      <div>
        <div className="earn-modal-name earn-ev-title">{title}</div>
        <div className="earn-modal-date">{sub}</div>
      </div>
    </div>
  );
}

/** The one figure the card is about, with what qualifies it underneath. */
function Hero({
  label,
  value,
  sub,
  tags,
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  tags?: ReactNode;
}) {
  return (
    <div className="earn-ev-hero">
      <div className="earn-ev-label">{label}</div>
      <div className="earn-ev-value">{value}</div>
      {sub && <div className="earn-ev-sub">{sub}</div>}
      {tags && <div className="earn-ev-tags">{tags}</div>}
    </div>
  );
}

function Notes({ lines }: { lines: (string | null | false)[] }) {
  const shown = lines.filter((line): line is string => Boolean(line));
  if (shown.length === 0) return null;
  return (
    <div className="earn-ev-notes">
      {shown.map((line) => (
        <p key={line}>{line}</p>
      ))}
    </div>
  );
}

function Actions({ children }: { children: ReactNode }) {
  return <div className="earn-ev-actions">{children}</div>;
}

// ------------------------------------------------------------------- kinds

function PrintCard({ event, held }: { event: CalendarEvent; held: boolean }) {
  const t = useT();
  const soon = isSoon(event);
  return (
    <>
      <Hero
        label={event.date ? longDate(event.date, t) : DASH}
        value={relative(event.days_until, t)}
        tags={
          (soon || held) && (
            <>
              {soon && (
                <span className="earn-ev-tag soon">{t("earnings.ev_soon")}</span>
              )}
              {held && (
                <span className="earn-ev-tag held">{t("earnings.ev_held")}</span>
              )}
            </>
          )
        }
      />
      <Notes
        lines={[
          t("earnings.ev_print_body"),
          soon && t("earnings.ev_print_soon"),
          t("earnings.ev_print_after"),
        ]}
      />
      <Actions>
        <Link className="ag-btn" page="ticker" params={{ ticker: event.ticker }}>
          {t("earnings.ev_open", { name: event.ticker })}
        </Link>
      </Actions>
    </>
  );
}

function DividendCard({ dividend }: { dividend: CalendarDividend }) {
  const t = useT();
  const lang = useLang();
  const ahead = dividend.days_until >= 0;
  const rate = dividend.withholding;
  const gross = dividend.amount;
  const net = gross === null || rate === null ? null : gross * (1 - rate);
  const withheld = gross === null || rate === null ? null : gross * rate;
  const rateText = rate === null ? DASH : (percent(lang, rate, { digits: 0 }) ?? DASH);
  const base = dividend.base_currency;
  // A second figure only when it says something the first does not.
  const converted =
    base !== null &&
    dividend.amount_base !== null &&
    (dividend.currency ?? "").toUpperCase() !== base.toUpperCase();
  const inBase = converted
    ? moneyIn(lang, base)(dividend.amount_base! * (1 - (rate ?? 0)), { digits: 2 })
    : null;

  const basis =
    dividend.withholding_basis === "ticker"
      ? t("earnings.ev_div_basis_ticker", { ticker: dividend.ticker, pct: rateText })
      : dividend.withholding_basis === "currency"
        ? t("earnings.ev_div_basis_currency", {
            ticker: dividend.ticker,
            currency: dividend.currency ?? DASH,
            pct: rateText,
          })
        : t("earnings.ev_div_basis_none");
  const status = dividend.projected
    ? t("earnings.ev_div_projected")
    : ahead
      ? t("earnings.ev_div_next")
      : t("earnings.ev_div_past");

  return (
    <>
      <Hero
        label={t(ahead ? "earnings.ev_div_will_get" : "earnings.ev_div_got")}
        value={cash(lang, net ?? gross, dividend.currency)}
        sub={[
          rate === null
            ? t("earnings.ev_div_gross")
            : t("earnings.ev_div_net", { pct: rateText }),
          inBase &&
            t(ahead ? "earnings.ev_div_in_base_today" : "earnings.ev_div_in_base_ex", {
              amount: inBase,
            }),
        ]
          .filter(Boolean)
          .join(" · ")}
        tags={<span className="earn-ev-tag">{relative(dividend.days_until, t)}</span>}
      />
      <KpiGrid>
        <Kpi
          label={t("earnings.ev_div_per_share")}
          value={cash(lang, dividend.per_share, dividend.currency)}
        />
        <Kpi
          label={t("earnings.ev_div_shares")}
          value={formatShares(lang, dividend.shares) ?? DASH}
        />
        <Kpi
          label={t("earnings.ev_div_gross_tile")}
          value={cash(lang, gross, dividend.currency)}
        />
        <Kpi
          label={t("earnings.ev_div_withheld")}
          value={withheld === null ? DASH : cash(lang, withheld, dividend.currency)}
          note={rate === null ? undefined : rateText}
        />
      </KpiGrid>
      <Notes
        lines={[
          basis,
          status,
          t(ahead ? "earnings.ev_div_rule_ahead" : "earnings.ev_div_rule_past"),
        ]}
      />
      <Actions>
        <Link className="ag-btn" page="portfolio" params={{ tab: "dividends" }}>
          {t("earnings.ev_open", { name: t("portfolio.tab_dividends") })}
        </Link>
      </Actions>
    </>
  );
}

function TaxCard({ deadline }: { deadline: TaxDeadline }) {
  const t = useT();
  const mark = deadline.approximate ? t("earnings.tax_approx_mark") : "";
  return (
    <>
      <Hero
        label={`${mark}${longDate(deadline.date, t)}`}
        value={relative(deadline.days_until, t)}
        tags={
          deadline.remind && (
            <span className="earn-ev-tag warn">{t("earnings.ev_tax_soon")}</span>
          )
        }
      />
      <Notes
        lines={[
          taxBody(deadline, t),
          deadline.approximate && t("earnings.ev_tax_approx"),
          t("earnings.ev_tax_note"),
        ]}
      />
      <Actions>
        <Link className="ag-btn" page="portfolio" params={{ tab: "tax" }}>
          {t("earnings.ev_open", { name: t("portfolio.tab_realized_tax") })}
        </Link>
      </Actions>
    </>
  );
}

function RebuyCard({ window }: { window: RepurchaseWindow }) {
  const t = useT();
  const lang = useLang();
  const words = rule(window.window, t);
  return (
    <>
      <Hero
        label={t("earnings.ev_rebuy_free", { date: longDate(window.date, t) })}
        value={relative(window.days_until, t)}
      />
      <KpiGrid>
        <Kpi
          label={t("earnings.ev_rebuy_sold")}
          value={longDate(window.sell_date, t)}
        />
        <Kpi
          label={t("earnings.ev_rebuy_loss")}
          value={loss(lang, window)}
          valueTone="down"
        />
        <Kpi label={t("earnings.ev_rebuy_rule")} value={words} />
      </KpiGrid>
      <Notes
        lines={[
          t("earnings.ev_rebuy_body", { ticker: window.ticker, rule: words }),
          t("earnings.ev_rebuy_early"),
        ]}
      />
      <Actions>
        <Link className="ag-btn" page="ticker" params={{ ticker: window.ticker }}>
          {t("earnings.ev_open", { name: window.ticker })}
        </Link>
      </Actions>
    </>
  );
}

function BankCard({ decision }: { decision: CentralBankDecision }) {
  const t = useT();
  return (
    <>
      <Hero
        label={longDate(decision.date, t)}
        value={relative(decision.days_until, t)}
      />
      <Notes
        lines={[t(`earnings.cb_${decision.bank}_title`), t("earnings.ev_bank_body")]}
      />
    </>
  );
}

// ------------------------------------------------------------------ dialog

export default function EventDetail({
  pick,
  held = [],
  onClose,
}: {
  pick: EventPick;
  /** The Portfolio group, so an upcoming print can say the reader owns it. */
  held?: string[];
  onClose: () => void;
}) {
  const t = useT();
  switch (pick.kind) {
    case "result":
      return (
        <ResultDetail
          ticker={pick.item.ticker}
          date={pick.item.date}
          result={pick.item}
          onClose={onClose}
        />
      );
    case "print":
      return (
        <Dialog
          head={
            <TickerHead ticker={pick.item.ticker} sub={t("earnings.ev_print_kind")} />
          }
          onClose={onClose}
        >
          <PrintCard event={pick.item} held={held.includes(pick.item.ticker)} />
        </Dialog>
      );
    case "dividend": {
      const mark = pick.item.projected ? t("earnings.tax_approx_mark") : "";
      return (
        <Dialog
          head={
            <TickerHead
              ticker={pick.item.ticker}
              sub={`${t("earnings.ev_div_kind")} · ${t("earnings.ev_div_ex_on", {
                date: `${mark}${longDate(pick.item.date, t)}`,
              })}`}
            />
          }
          onClose={onClose}
        >
          <DividendCard dividend={pick.item} />
        </Dialog>
      );
    }
    case "tax":
      return (
        <Dialog
          head={
            <PlainHead title={taxTitle(pick.item, t)} sub={t("earnings.ev_tax_kind")} />
          }
          onClose={onClose}
        >
          <TaxCard deadline={pick.item} />
        </Dialog>
      );
    case "rebuy":
      return (
        <Dialog
          head={
            <TickerHead ticker={pick.item.ticker} sub={t("earnings.ev_rebuy_kind")} />
          }
          onClose={onClose}
        >
          <RebuyCard window={pick.item} />
        </Dialog>
      );
    case "bank":
      return (
        <Dialog
          head={
            <PlainHead
              title={t(`earnings.ev_bank_${pick.item.bank}`)}
              sub={t("earnings.ev_bank_kind")}
            />
          }
          onClose={onClose}
        >
          <BankCard decision={pick.item} />
        </Dialog>
      );
  }
}
