/**
 * The page's building blocks: a section, a list of the card's lines and a
 * list of computed rows.
 *
 * A section is a heading the eye finds in the same place every morning, an
 * optional count and "?" beside it, then its body; under that the model's one
 * remark on it, when it made one, and which sources did not answer — said
 * plainly, so an empty news list reads as "Yahoo did not answer", not as
 * "nothing happened".
 *
 * A row is set like a wire item: its tickers first as logo and link, the line
 * in full — itself the link to the article or filing — and where it was read
 * (Yahoo, 8-K, results, SEC Form 4, BaFin) and its day in mono.
 */

import { useId, type ReactNode } from "react";
import { useT } from "../../shell/i18n";
import { Help } from "../../ui/Kpi";
import { TickerCell } from "../home/ui";
import { monthDay } from "../home/format";
import type { DailyItem } from "../home/types";
import { AnalysisPanel, type Panel } from "./Analysis";
import { missingKeys, opens, safeUrl, sourceKey } from "./card";
import type { TodayRow } from "./types";

export function Block({
  id,
  title,
  count,
  help,
  note,
  missing,
  children,
}: {
  id: string;
  title: string;
  count?: number | null;
  help?: string | null;
  /** The model's remark on the section; empty when it made none. */
  note?: string;
  /** Sources that did not answer. */
  missing?: string[];
  children: ReactNode;
}) {
  const t = useT();
  const heading = `td-sec-${id}`;
  const silent = missingKeys(missing ?? []).map((key) => t(key));
  return (
    <section className="td-sec" aria-labelledby={heading}>
      <header className="td-sec-head">
        <h2 className="td-sec-title" id={heading}>
          {title}
        </h2>
        {count ? <span className="td-count">{count}</span> : null}
        <Help text={help} />
      </header>
      {children}
      {note ? <p className="td-remark">{note}</p> : null}
      {silent.length ? (
        <p className="hm-note">{t("today.missing", { sources: silent.join(", ") })}</p>
      ) : null}
    </section>
  );
}

/** A line's tickers, at its end: logo and link, no chip row of their own. */
function Tickers({ tickers }: { tickers: string[] }) {
  if (!tickers.length) return null;
  return (
    <span className="td-tks">
      {tickers.map((ticker) => (
        <TickerCell key={ticker} ticker={ticker} name={false} />
      ))}
    </span>
  );
}

/** The card's own lines, each with its analysis a click away when it has one. */
export function Lines({
  items,
  canOpen,
  panels,
  toggle,
}: {
  items: DailyItem[];
  /** False while the card on screen is a stand-in about to be replaced. */
  canOpen: boolean;
  panels: Record<string, Panel>;
  toggle: (key: string) => void;
}) {
  const t = useT();
  const ids = useId();
  return (
    <ul className="td-lines">
      {items.map((item) => {
        const panel = panels[item.key];
        const expanded = panel !== undefined && panel.kind !== "failed";
        const id = `${ids}-an-${item.key}`;
        return (
          <li key={item.key}>
            {item.line}
            <Tickers tickers={item.tickers} />
            {canOpen && opens(item) ? (
              <>
                {" "}
                <button
                  type="button"
                  className="td-toggle"
                  aria-expanded={expanded}
                  aria-controls={panel ? id : undefined}
                  onClick={() => toggle(item.key)}
                >
                  {expanded ? t("home.daily_an_hide") : t("home.daily_an_show")}
                </button>
                <AnalysisPanel id={id} panel={panel} />
              </>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Computed rows — news, filings, insiders — set like an index of wire items:
 * the name first, the headline (the article or filing itself when it has one)
 * and where and when it was read last, in mono.
 *
 * `limit` shows the first few with the rest one press away, counted — the
 * All tab is a front page, the section's own tab the full list.
 */
export function Rows({
  rows,
  limit,
  onMore,
}: {
  rows: TodayRow[];
  limit?: number;
  onMore?: () => void;
}) {
  const t = useT();
  const cut = limit && onMore && rows.length > limit + 1 ? limit : rows.length;
  return (
    <>
      <ul className="td-rows">
        {rows.slice(0, cut).map((row) => {
          const source = sourceKey(row);
          const href = row.url ? safeUrl(row.url) : null;
          const day = row.date ? monthDay(row.date, t) : null;
          return (
            <li key={row.key} className="td-row">
              <span className="td-row-who">
                {row.tickers.map((ticker) => (
                  <TickerCell key={ticker} ticker={ticker} name={false} />
                ))}
              </span>
              <span className="td-line">
                {href ? (
                  <a
                    className="td-headlink"
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {row.line}
                  </a>
                ) : (
                  row.line
                )}
              </span>
              {source || day ? (
                <span className="td-wire">
                  {source ? <span className="td-src">{t(source)}</span> : null}
                  {day ? <span className="td-day">{day}</span> : null}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      {cut < rows.length && onMore ? (
        <button type="button" className="td-more td-more-btn" onClick={onMore}>
          {t("today.more_rows", { count: rows.length - cut })}
        </button>
      ) : null}
    </>
  );
}
