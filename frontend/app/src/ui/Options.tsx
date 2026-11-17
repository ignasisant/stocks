/**
 * One choice among a few, each option with a line of its own to say what it
 * means — risk tolerance, where "Balanced" alone tells nobody how far down
 * they are expected to sit. Toggle buttons in a labelled group, as
 * `Segmented`; `ui.css` styles it (`.ag-opts`).
 */

import "./ui.css";

export type OptionItem<T extends string> = {
  id: T;
  label: string;
  line: string;
};

export function Options<T extends string>({
  items,
  value,
  onPick,
  label,
  disabled,
}: {
  items: readonly OptionItem<T>[];
  value: T | null;
  onPick: (next: T) => void;
  /** Names the group for assistive tech. */
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="ag-opts" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="ag-opt"
          aria-pressed={item.id === value}
          disabled={disabled}
          onClick={() => onPick(item.id)}
        >
          <b>{item.label}</b>
          <small>{item.line}</small>
        </button>
      ))}
    </div>
  );
}
