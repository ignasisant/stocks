/**
 * The handful of shapes this page repeats: a bordered card, a note and a
 * ticker cell. The KPI tile and its delta pill are the shared ones in
 * `src/ui/Kpi.tsx`.
 *
 * Every colour is a `--ag-*` custom property; none of it is written by hand
 * here.
 */

import type { ReactNode } from "react";
import { Loaded } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { TickerCell as Cell } from "../../shell/tickers";
import type { Query } from "../../shell/useApi";

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ? `hm-card ${className}` : "hm-card"}>{children}</div>
  );
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h3 className="hm-card-title">{children}</h3>;
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="hm-note">{children}</p>;
}

/**
 * `<Loaded>`, with this page's own sentence for a section that failed.
 *
 * The shell's failure copy serves every screen and so cannot name anything;
 * this page draws four independent sections and degrades one at a time — a
 * throttled earnings pass leaves the glance, the transactions and the
 * watchlist exactly where they were. A bare "something went wrong" in the
 * middle of that says nothing about which part of the page is the part that
 * is gone, so the catalog's specific sentence goes here instead, under the
 * card's own heading, with the failure captioned beneath it.
 *
 * The sentence still says "reload to retry"; the button beside it is the
 * quicker way to do that.
 */
export function CardQuery<T>({
  query,
  note,
  title,
  skeleton,
  children,
}: {
  query: Query<T>;
  /** Already translated: the sentence naming what is unavailable. */
  note: string;
  /** The card's heading, kept over the failure so the gap has a name. */
  title?: string;
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  const t = useT();
  if (query.state === "failed") {
    return (
      <Card>
        {title ? <CardTitle>{title}</CardTitle> : null}
        <Note>{note}</Note>
        <button type="button" className="ag-btn hm-retry" onClick={query.retry}>
          {t("common.retry")}
        </button>
      </Card>
    );
  }
  return (
    <Loaded query={query} skeleton={skeleton}>
      {(data) => children(data)}
    </Loaded>
  );
}

/**
 * A ticker, always as a link to its own page.
 *
 * House rule: every symbol on screen opens its analysis, behind its mirrored
 * logo. The shell's cell collects a whole table's worth of names into one
 * `/market/profiles` call, so the marks cost one request per screen rather
 * than one per row.
 */
export function TickerCell({
  ticker,
  name = true,
}: {
  ticker: string;
  /**
   * Print the company name after the symbol. Off in the movers and
   * recent-transactions tables and where the cell is a chip with no room for
   * it.
   */
  name?: boolean;
}) {
  return <Cell ticker={ticker} className="hm-ticker" name={name} />;
}
