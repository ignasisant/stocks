/**
 * The handful of shapes this page repeats: a bordered card, a KPI tile, a
 * tinted delta pill and a ticker cell.
 *
 * They mirror `web/tables.py` — same tile, same pill, same colour rule — so the
 * rebuilt page and the Streamlit one beside it read as one app. Every colour is
 * a `--ag-*` custom property; none of it is written by hand here.
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
 * this page draws four independent sections and degrades one at a time, which
 * is the behaviour `web/app_pages/home.py` has — a throttled earnings pass
 * leaves the glance, the transactions and the watchlist exactly where they
 * were. A bare "something went wrong" in the middle of that says nothing about
 * which part of the page is the part that is gone, so the catalog's specific
 * sentence goes here instead, under the card's own heading — again as in
 * Streamlit, which keeps the title and captions the failure beneath it.
 *
 * The retry is this shell's own improvement on the copy: the sentence says
 * "reload to retry" because a Streamlit page has no button to offer, and this
 * one does.
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

/** A signed percentage as a pill, coloured by sign — `kpi_delta_chip`'s twin. */
export type Chip = { text: string; tone: "up" | "down" | "flat" };

export function chipFor(
  pct: number | null | undefined,
  text: string | null,
  /**
   * Grey the pill instead of colouring it by sign — `kpi_delta_chip(off=True)`.
   * For a figure that is real but not live: outside a session the day change is
   * the last completed one, and colouring it green implies something is moving
   * right now.
   */
  off = false,
): Chip | null {
  if (text === null || pct === null || pct === undefined) return null;
  return { text, tone: off ? "flat" : pct >= 0 ? "up" : "down" };
}

export function DeltaChip({ chip }: { chip: Chip | null }) {
  if (!chip) return null;
  return <span className={`hm-chip hm-chip-${chip.tone}`}>{chip.text}</span>;
}

export function Tiles({ children }: { children: ReactNode }) {
  return <div className="hm-kpis">{children}</div>;
}

/**
 * One KPI tile: label, figure, optional pill.
 *
 * `help` rides a native `title`, the same hover hint the Python grid uses —
 * there is no popover in this shell to hang it on.
 */
export function Tile({
  label,
  value,
  chip,
  help,
}: {
  label: string;
  value: string;
  chip?: Chip | null;
  help?: string;
}) {
  return (
    <div className="hm-kpi">
      <div className="hm-kpi-head">
        <span className="hm-kpi-label">{label}</span>
        {help ? (
          <span className="hm-kpi-help" title={help} aria-label={help}>
            ?
          </span>
        ) : null}
      </div>
      <div className="hm-kpi-row">
        <span className="hm-kpi-value">{value}</span>
        <DeltaChip chip={chip ?? null} />
      </div>
    </div>
  );
}

/**
 * A ticker, always as a link to its own page.
 *
 * House rule: every symbol on screen opens its analysis, behind the same
 * mirrored logo the Streamlit cell carries. The shell's cell collects a whole
 * table's worth of names into one `/market/profiles` call, so the marks cost
 * one request per screen rather than one per row.
 */
export function TickerCell({
  ticker,
  name = true,
}: {
  ticker: string;
  /**
   * Print the company name after the symbol — `ticker_table_html`'s `names`.
   * Off where Streamlit turns it off (the movers and recent-transactions
   * tables) and where the cell is a chip with no room for it.
   */
  name?: boolean;
}) {
  return <Cell ticker={ticker} className="hm-ticker" name={name} />;
}
