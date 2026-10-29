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
import { countryName } from "../pages/review/countries";
import { maybe, sectorKey } from "../pages/sentiment/format";
import { useLang, useT } from "../shell/i18n";

/**
 * A slice's name in the reader's words. The server sums with Yahoo's English
 * labels and its own "Unknown" / "Crypto" buckets, the ones the Risk tab
 * already translates; the drawer printed them raw, an English ring under a
 * Spanish answer.
 */
export function sliceName(
  t: ReturnType<typeof useT>,
  lang: string,
  by: string,
  label: string,
): string {
  if (by === "position" || by === "currency") return label;
  if (label === "Unknown") return t("portfolio.alloc_unknown");
  if (by === "country") {
    return label === "Crypto" ? t("portfolio.alloc_crypto") : countryName(label, lang);
  }
  return maybe(t, `sentiment.sector_${sectorKey(label)}`) ?? label;
}

export function AllocationDonut({
  slices,
  label,
  other,
  by = "position",
}: {
  slices: Slice[];
  label: string;
  /** What the tail past the palette's hues folds into. */
  other: string;
  /** The split drawn, which says how its labels translate. */
  by?: string;
}) {
  const lang = useLang();
  const t = useT();
  const shown = slices
    .filter((slice) => typeof slice?.label === "string" && Number(slice.weight) > 0)
    .map((slice) => ({
      label: sliceName(t, lang, by, slice.label),
      weight: Number(slice.weight),
    }));
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
