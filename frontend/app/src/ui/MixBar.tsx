/**
 * Today's share of the book as a fill, the target as a tick across it.
 * Decorative: the caller says the same in words, beside it or in `.ag-sr`.
 * Profile's plan tab draws one per bucket under the target field; Review's
 * "against your plan" rows draw one per bucket off its target.
 */

import "./ui.css";

export function MixBar({
  actual,
  target,
  caption,
}: {
  /** Percent, 0–100. */
  actual: number;
  target: number | null;
  caption?: string;
}) {
  const clamp = (value: number) => Math.min(100, Math.max(0, value));
  return (
    <span className="ag-mixbar-wrap">
      <span className="ag-mixbar" aria-hidden="true">
        <span className="ag-mixbar-fill" style={{ width: `${clamp(actual)}%` }} />
        {target !== null && (
          <span className="ag-mixbar-target" style={{ left: `${clamp(target)}%` }} />
        )}
      </span>
      {caption ? <span className="ag-mixbar-cap">{caption}</span> : null}
    </span>
  );
}
