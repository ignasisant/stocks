/**
 * The names this page puts on screen, all of them out of the catalog.
 *
 * Metric labels are `kpi.<key>.label` with the definition at `kpi.<key>.desc`
 * — the same keys `web/kpi_text.py` reads, so the React table and the
 * Streamlit one beside it cannot end up calling the same column two things.
 * Sector names are Pulse's (`sentiment.sector_*`), which already ships all
 * eleven; this page adds no copy of its own for them.
 */

import { useT } from "../../shell/i18n";

/** A miss renders as the dotted key, so ask first and fall back deliberately. */
function orElse(value: string, key: string, fallback: string): string {
  return value === key ? fallback : value;
}

export function useLabels() {
  const t = useT();
  return {
    /** A metric's name; the raw key if the catalog has never heard of it. */
    metric: (key: string) => orElse(t(`kpi.${key}.label`), `kpi.${key}.label`, key),
    /** A metric's definition, or "" — an absent tooltip beats a dotted key. */
    describe: (key: string) => orElse(t(`kpi.${key}.desc`), `kpi.${key}.desc`, ""),
    /** The sector in the reader's language, or its own English spelling. */
    sector: (name: string) => {
      const key = `sentiment.sector_${name.toLowerCase().replaceAll(" ", "_")}`;
      return orElse(t(key), key, name);
    },
  };
}
