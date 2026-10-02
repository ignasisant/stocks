/**
 * An allocation in the drawer: what the A2UI `Donut` component draws.
 *
 * The Risk tab's own donut (`pages/portfolio/charts.tsx`) over the weights the
 * server summed (`stocks/chat/allocation.py`): the book by position, sector,
 * country or currency. All four splits arrive at once, so the chips under it
 * switch between them without a round trip, and a model never draws one.
 */

import { Donut, type Slice } from "../pages/portfolio/charts";
import { percent } from "../pages/portfolio/format";
import "../pages/portfolio/portfolio.css";
import { useLang } from "../shell/i18n";

export function AllocationDonut({
  slices,
  label,
  other,
}: {
  slices: Slice[];
  label: string;
  /** What the tail past the palette's hues folds into. */
  other: string;
}) {
  const lang = useLang();
  const shown = slices
    .filter((slice) => typeof slice?.label === "string" && Number(slice.weight) > 0)
    .map((slice) => ({ label: slice.label, weight: Number(slice.weight) }));
  if (!shown.length) return null;
  return (
    <div className="ag-a2ui-donut">
      <Donut
        title={label}
        slices={shown}
        otherLabel={other}
        format={(fraction) => percent(lang, fraction) ?? ""}
      />
    </div>
  );
}
