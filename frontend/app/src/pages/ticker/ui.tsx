/**
 * The handful of shapes every block on this page is built from.
 *
 * They exist for the reason the sibling pages' `ui` modules exist: a dozen
 * sections written a dozen ways drift, and this is the page where a figure
 * formatted loosely is a multiple somebody trades on. Same tiles, same tags,
 * same table, same "n/a".
 *
 * Every colour is a class resolving to a `--ag-*` custom property. Nothing here
 * writes one.
 */

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link } from "../../shell/router";
import { useTickerProfile } from "../../shell/tickers";

/**
 * Is this a phone?
 *
 * 640px, the same breakpoint `web/ds.py` uses and the same one this page's
 * stylesheet uses. A hook rather than a media query because the phone layout is
 * not a restyle of the desktop one: it drops two range pills, defaults to the
 * line chart, thins the axis and transposes two tables — decisions that have to
 * reach the data, not only the box model.
 */
const PHONE = "(max-width: 640px)";

export function useMobile(): boolean {
  const [mobile, setMobile] = useState(
    () => typeof matchMedia === "function" && matchMedia(PHONE).matches,
  );
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const query = matchMedia(PHONE);
    const onChange = () => setMobile(query.matches);
    query.addEventListener("change", onChange);
    onChange();
    return () => query.removeEventListener("change", onChange);
  }, []);
  return mobile;
}

export function Card({
  title,
  note,
  children,
}: {
  title?: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="tk-card">
      {(title || note) && (
        <div className="tk-card-head">
          {title && <h2 className="tk-h2">{title}</h2>}
          {note && <p className="tk-note">{note}</p>}
        </div>
      )}
      {children}
    </section>
  );
}

/** A heading inside a card — where the chart titles drawn on a canvas live. */
export function Subhead({ children }: { children: ReactNode }) {
  return <h3 className="tk-subhead">{children}</h3>;
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="tk-note">{children}</p>;
}

/**
 * A reading the page makes out loud — `st.success` / `st.warning` on the
 * Streamlit page. These are claims rather than data, so they are set apart
 * from the figures around them.
 */
export function Banner({
  tone,
  children,
}: {
  tone: "good" | "warn";
  children: ReactNode;
}) {
  return <p className={`tk-banner tk-banner-${tone}`}>{children}</p>;
}

/**
 * `**bold**`, because these strings are shared with a page that renders
 * markdown. Printed raw they would show their asterisks, and editing the
 * catalogs to suit this front end would break the Streamlit one.
 */
export function Bold({ text }: { text: string }) {
  return (
    <>
      {text
        .split("**")
        .map((part, i) =>
          i % 2 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>,
        )}
    </>
  );
}

/**
 * A ticker, always as a link to its own page, and with its mark where we have
 * one.
 *
 * House rule: every symbol on screen opens its analysis. `?ticker=` is the
 * param every other page in this shell links with and the one the Streamlit
 * page reads, so a link made here opens the same company on either front end.
 */
export function TickerLink({
  ticker,
  logo,
  label,
  title,
}: {
  ticker: string;
  /** A same-origin mirror URL, where the payload carried one. */
  logo?: string | null;
  label?: ReactNode;
  title?: string;
}) {
  // A logo the payload already carried is used as-is; everything else asks the
  // shell, which collects a whole screen's worth of names into one
  // `/market/profiles` call. Either way the house rule holds: a symbol on
  // screen is a mark and a way into its page, never four bare letters.
  const fetched = useTickerProfile(logo ? "" : ticker);
  const mark = logo ?? fetched?.logo ?? null;
  return (
    <Link
      className="tk-ticker"
      page="ticker"
      params={{ ticker }}
      title={title ?? fetched?.name ?? undefined}
    >
      {mark ? (
        <img className="tk-ticker-logo" src={mark} alt="" loading="lazy" />
      ) : null}
      {label ?? ticker}
    </Link>
  );
}

export function Tag({ tone, children }: { tone?: string | null; children: ReactNode }) {
  return <span className={`tk-tag tk-is-${tone ?? "gray"}`}>{children}</span>;
}

export function Kpis({ children }: { children: ReactNode }) {
  return <div className="tk-kpis">{children}</div>;
}

/**
 * One KPI tile: label, figure, and whatever the domain says about it.
 *
 * `help` rides a native `title`, the same hover hint `st.metric(help=…)` gives
 * the Streamlit page — there is no popover in this shell to hang it on.
 */
export function Kpi({
  label,
  value,
  help,
  meta,
}: {
  label: string;
  value: string;
  help?: string;
  meta?: ReactNode;
}) {
  return (
    <div className="tk-kpi">
      <span className="tk-kpi-label" title={help}>
        {label}
        {help ? <span className="tk-q">?</span> : null}
      </span>
      <span className="tk-kpi-value">{value}</span>
      {meta ? <span className="tk-kpi-meta">{meta}</span> : null}
    </div>
  );
}

/**
 * A row of metrics. `wide` is the seven-cell row a held name gets on desktop:
 * narrower minimum cells and a step smaller figure, so price, RSI, SMA20 and
 * the four holding figures share one line on a laptop instead of wrapping to
 * a second row that reads as a separate block.
 */
export function Metrics({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? "tk-metrics tk-metrics-wide" : "tk-metrics"}>{children}</div>
  );
}

export function Metric({
  label,
  value,
  help,
  delta,
  dim,
  note,
  noteTone,
}: {
  label: string;
  value: string;
  help?: string;
  /** A day move as a FRACTION, or null when there is none to quote. */
  delta?: number | null;
  /** Off-session: the figure belongs to a session that has closed. */
  dim?: boolean;
  note?: ReactNode;
  noteTone?: string | null;
}) {
  return (
    <div className={dim ? "tk-metric tk-dim" : "tk-metric"}>
      <span className="tk-metric-label" title={help}>
        {label}
      </span>
      <span className="tk-metric-value">{value}</span>
      {delta !== null && delta !== undefined ? (
        <span className={`tk-pill tk-pill-${delta >= 0 ? "up" : "down"}`}>
          {`${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(2)}%`}
        </span>
      ) : null}
      {note ? (
        <span
          className={noteTone ? `tk-metric-note tk-is-${noteTone}` : "tk-metric-note"}
        >
          {note}
        </span>
      ) : null}
    </div>
  );
}

/** A wide table pans inside its card rather than moving the whole page. */
export function Scroll({ children }: { children: ReactNode }) {
  return <div className="tk-scroll">{children}</div>;
}

/** The section said nothing because nothing was there, said in words. */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="tk-empty">{children}</p>;
}

/**
 * A segmented control: the range pills, the chart type, the statement view.
 *
 * The options carry their own labels because every one of them is translated —
 * "1w" reads "1S" in Spanish, and shipping the English shorthand would be the
 * first visible place the two front ends disagree.
 */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  format,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  format?: (option: T) => string;
}) {
  return (
    <div className="tk-seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          className={option === value ? "tk-seg-on" : undefined}
          aria-pressed={option === value}
          onClick={() => onChange(option)}
        >
          {format ? format(option) : option}
        </button>
      ))}
    </div>
  );
}

/**
 * A button with a panel under it, closed by a click anywhere else — the same
 * interaction `st.popover` gives the Streamlit page, and the same one the
 * search box uses.
 */
export function Popover({
  label,
  title,
  children,
  onOpen,
}: {
  label: string;
  title?: string;
  children: ReactNode;
  /** Fired the first time it opens: these panels each cost a request. */
  onOpen?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || !box) return;
    // Pointerdown, not click, so a row's own handler still runs: it fires on
    // the element before this sees it.
    const away = (event: PointerEvent) => {
      if (!box.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, box]);

  return (
    <div className="tk-pop" ref={setBox}>
      <button
        type="button"
        className={open ? "tk-pop-btn tk-pop-open" : "tk-pop-btn"}
        aria-expanded={open}
        title={title}
        onClick={() => {
          if (!open) onOpen?.();
          setOpen((was) => !was);
        }}
      >
        {label}
      </button>
      {open ? <div className="tk-pop-panel">{children}</div> : null}
    </div>
  );
}
