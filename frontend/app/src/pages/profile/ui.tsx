/**
 * The canvas's furniture: a card, a setting row, and the little renderer that
 * lets a catalog string keep its markdown.
 *
 * The catalogs were written for Streamlit, where `**bold**` and `` `code` ``
 * are markdown wherever they appear. Half the explanations on this page use
 * them, so a component that printed the raw text would show the asterisks.
 * This is deliberately not a markdown library: emphasis, code and bullets are
 * the whole of what those strings contain.
 */

import { Fragment, type ReactNode } from "react";
import { ToggleChip } from "../../ui/Toggle";

/** `**bold**` and `` `code` `` inside one line of catalog text. */
export function Inline({ text }: { text: string }): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
          return <b key={i}>{part.slice(2, -2)}</b>;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
          return <code key={i}>{part.slice(1, -1)}</code>;
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

/** A multi-line catalog string: paragraphs, and `- ` lines as a list. */
export function Prose({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: number) => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul${key}`}>
        {bullets.map((line, i) => (
          <li key={i}>
            <Inline text={line} />
          </li>
        ))}
      </ul>,
    );
    bullets = [];
  };
  text.split("\n").forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ")) {
      bullets.push(trimmed.slice(2));
      return;
    }
    flush(i);
    if (trimmed)
      blocks.push(
        <p key={i}>
          <Inline text={trimmed} />
        </p>,
      );
  });
  flush(-1);
  return <div className={className ?? "pr-prose"}>{blocks}</div>;
}

export function Card({
  title,
  sub,
  note,
  children,
}: {
  title?: string;
  sub?: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="pr-card">
      {title !== undefined && (
        <div className="pr-cardhead">
          <span className="pr-cardtitle">{title}</span>
          {sub && <span className="pr-cardsub">{sub}</span>}
          {note && <span className="pr-cardnote">{note}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

/**
 * One setting: label and explanation on the left, the control on the right.
 *
 * `middle` centres the two against each other, which is what the canvas does
 * for the rows whose control is a lone toggle or button.
 */
export function Row({
  label,
  help,
  middle,
  children,
}: {
  label: string;
  help?: string;
  middle?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={middle ? "pr-row pr-row-mid" : "pr-row"}>
      <div className="pr-row-l">
        <span className="pr-row-lab">{label}</span>
        {help && (
          <span className="pr-row-help">
            <Inline text={help} />
          </span>
        )}
      </div>
      <div className="pr-row-ctl">{children}</div>
    </div>
  );
}

export function Select<T extends string>({
  value,
  options,
  labelOf,
  onPick,
  label,
  disabled,
}: {
  value: T;
  options: readonly T[];
  labelOf: (option: T) => string;
  onPick: (option: T) => void;
  /** Accessible name — the visible one is the row's, which is not a `<label>`. */
  label: string;
  disabled?: boolean;
}) {
  return (
    <select
      className="pr-select"
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(event) => onPick(event.target.value as T)}
    >
      {options.map((option) => (
        <option key={option} value={option}>
          {labelOf(option)}
        </option>
      ))}
    </select>
  );
}

/** A row of one-of-these chips. */
export function Chips<T extends string>({
  value,
  options,
  labelOf,
  onPick,
  disabled,
}: {
  value: T | null;
  options: readonly T[];
  labelOf: (option: T) => string;
  onPick: (option: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="pr-chips">
      {options.map((option) => (
        <ToggleChip
          key={option}
          on={option === value}
          disabled={disabled}
          onClick={() => onPick(option)}
        >
          {labelOf(option)}
        </ToggleChip>
      ))}
    </div>
  );
}

export function Toggle({
  checked,
  onToggle,
  label,
  disabled,
}: {
  checked: boolean;
  onToggle: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <label className="pr-switch">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onToggle(event.target.checked)}
      />
    </label>
  );
}

/**
 * What a rejected save said, under the control that was rejected.
 *
 * Never swallowed and never drawn as success: the API validates, and its
 * `detail` names the problem in words the person can act on.
 */
export function Failure({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="pr-err" role="alert">
      {message}
    </p>
  );
}

/**
 * The same chips, for a setting that takes several answers.
 *
 * A separate component rather than a `multi` flag on `Chips`: the two differ in
 * what a press means — one replaces the answer, the other toggles one of them —
 * and a boolean that changes that is a boolean every caller has to read the
 * implementation to understand.
 */
export function MultiChips<T extends string>({
  values,
  options,
  labelOf,
  onToggle,
  disabled,
}: {
  values: readonly T[];
  options: readonly T[];
  labelOf: (option: T) => string;
  onToggle: (option: T, on: boolean) => void;
  disabled?: boolean;
}) {
  const chosen = new Set(values);
  return (
    <div className="pr-chips">
      {options.map((option) => {
        const on = chosen.has(option);
        return (
          <ToggleChip
            key={option}
            on={on}
            disabled={disabled}
            onClick={() => onToggle(option, !on)}
          >
            {labelOf(option)}
          </ToggleChip>
        );
      })}
    </div>
  );
}
