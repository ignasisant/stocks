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
import { Fold } from "../../ui/Fold";
import { Kpi, KpiGrid, bandTone, chipFor } from "../../ui/Kpi";
import { Segmented as Seg } from "../../ui/Segmented";
import { num } from "../../shell/numbers";

export { useMobile } from "../../shell/useMobile";

export function Card({
  title,
  note,
  fold,
  onShown,
  children,
}: {
  title?: string;
  note?: string;
  /** Folds to its heading on a phone (`ui/Fold`); the id keeps it open once opened. */
  fold?: string;
  /** Its content is on show (`ui/Fold`): what a section waiting to fetch waits for. */
  onShown?: () => void;
  children: ReactNode;
}) {
  const head = (title || note) && (
    <div className="tk-card-head">
      {title && <h2 className="tk-h2">{title}</h2>}
      {note && <p className="tk-note">{note}</p>}
    </div>
  );
  return (
    <section className="tk-card">
      {fold && head ? (
        <Fold id={fold} head={head} onShown={onShown}>
          {children}
        </Fold>
      ) : (
        <>
          {head}
          {children}
        </>
      )}
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
 * A reading the page makes out loud. These are claims rather than data, so they
 * are set apart from the figures around them.
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
 * `**bold**`, as the catalog stores its emphasis. Printed raw these strings
 * would show their asterisks.
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

export function Tag({ tone, children }: { tone?: string | null; children: ReactNode }) {
  return <span className={`tk-tag tk-is-${tone ?? "gray"}`}>{children}</span>;
}

/**
 * A row of the page's figures — the app-wide tile (`src/ui/Kpi.tsx`), so the
 * ticker reads like every other screen.
 */
export function Metrics({ children }: { children: ReactNode }) {
  return <KpiGrid>{children}</KpiGrid>;
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
  /** Off-session: the move belongs to a session that has closed — grey pill. */
  dim?: boolean;
  note?: ReactNode;
  /** The domain's band (green / orange / red / gray). */
  noteTone?: string | null;
}) {
  const move =
    delta === null || delta === undefined
      ? null
      : `${delta >= 0 ? "+" : ""}${num(delta * 100, 2)}%`;
  return (
    <Kpi
      label={label}
      value={value}
      help={help}
      chip={chipFor(delta, move, dim)}
      note={note}
      noteTone={noteTone ? bandTone(noteTone) : null}
    />
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
 * "1w" reads "Semana" in Spanish, and shipping the English shorthand would leave
 * an English word on a Spanish page.
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
    <Seg
      className="tk-seg"
      label={label}
      items={options.map((option) => ({
        id: option,
        label: format ? format(option) : option,
      }))}
      value={value}
      onPick={onChange}
    />
  );
}
