/**
 * The sector picker: all eleven as one row of chips, each saying how old its
 * scan is and, for a reader with a book, how much of it sits in that sector.
 *
 * A select hid ten of the eleven answers behind a tap; a rail shows where the
 * reader's money is and which sectors are out of date before anything is
 * picked. The weights come late (`/pulse/book`, asked once the cohort is in)
 * and only add a line: the chips never wait for them.
 */

import { useEffect, useRef } from "react";
import { percent } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { useLabels } from "./labels";
import { ageDays, sectorWeight, STALE_DAYS } from "./rank";
import type { SectorSummary } from "./types";

export function SectorRail({
  sectors,
  current,
  onPick,
  weights,
}: {
  sectors: SectorSummary[];
  current: string;
  onPick: (sector: string) => void;
  /** The reader's weight per sector; null while unknown or for a guest. */
  weights: Record<string, number> | null;
}) {
  const t = useT();
  const labels = useLabels();
  const rail = useRef<HTMLDivElement>(null);
  const now = new Date();

  // The picked chip in view: a link to the tenth sector opens on a phone with
  // the rail scrolled to it, not on the first four.
  useEffect(() => {
    const on = rail.current?.querySelector<HTMLElement>('[aria-pressed="true"]');
    on?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
  }, [current]);

  return (
    <div ref={rail} className="ag-sec-rail" role="group" aria-label={t("sector.pick")}>
      {sectors.map((entry) => {
        const age = ageDays(entry.as_of, now);
        const weight = sectorWeight(weights, entry.sector);
        const stale = age === null || age > STALE_DAYS;
        const on = entry.sector === current;
        return (
          <button
            key={entry.sector}
            type="button"
            className={on ? "ag-sec-chip ag-sec-chip-on" : "ag-sec-chip"}
            aria-pressed={on}
            onClick={() => onPick(entry.sector)}
          >
            <span className="ag-sec-chip-name">{labels.sector(entry.sector)}</span>
            <span className="ag-sec-chip-meta">
              <span
                className={
                  stale ? "ag-sec-chip-age ag-sec-chip-stale" : "ag-sec-chip-age"
                }
              >
                {age === null
                  ? t("sector.age_never")
                  : age === 0
                    ? t("sector.age_today")
                    : t("sector.age_days", { n: age })}
              </span>
              {weight ? (
                <span className="ag-sec-chip-you">
                  {t("sector.you_weight", {
                    pct: percent(weight, { digits: 0, tight: true }) ?? "",
                  })}
                </span>
              ) : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
