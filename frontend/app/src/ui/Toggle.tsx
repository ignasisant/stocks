/**
 * The filter / choice chip: a pill-shaped button that is either on or off.
 *
 * Every screen that let a reader pick among a few options drew its own —
 * Profile, the sector cohort, the earnings views, the ticker's peer picker,
 * the feedback form — five sizes and three "on" colours for one control. This
 * is the one; `ui.css` styles it and a page only lays out the row it sits in.
 *
 * A read-only pill that states a figure is `Chip` (`Kpi.tsx`), not this: one
 * is a control, the other is a reading, and they must not look alike.
 */

import type { ReactNode } from "react";
import "./ui.css";

export function ToggleChip({
  on,
  onClick,
  children,
  disabled,
  title,
  label,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
  /** Hover text, for a chip whose label is cut short. */
  title?: string;
  /** Accessible name, when the visible content is not one (a logo, a ×). */
  label?: string;
}) {
  return (
    <button
      type="button"
      className={on ? "ag-toggle ag-toggle-on" : "ag-toggle"}
      aria-pressed={on}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/** A wrapping row of chips (or of anything that sits with them). */
export function ToggleRow({
  children,
  label,
  className,
}: {
  children: ReactNode;
  /** Names the group for assistive tech. */
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={className ? `ag-toggles ${className}` : "ag-toggles"}
      role={label ? "group" : undefined}
      aria-label={label}
    >
      {children}
    </div>
  );
}
