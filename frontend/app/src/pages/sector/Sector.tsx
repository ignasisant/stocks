/**
 * Sector screen — a comparable cohort per sector, and the best three in it.
 *
 * The cohort is built for the reader rather than chosen by them: the sector
 * ETF's basket, widened with listed companies outside the US, scanned nightly
 * and scored by percentile ranking inside that cohort.
 *
 * Reading order is this layout's whole job. The podium is the reason to open
 * the page, so it comes first; the cohort table — seventeen rows nobody scans
 * top to bottom — comes last.
 *
 * The written verdict sits between the podium and the table (`Verdict.tsx`),
 * over `/sectors/{sector}/verdict`.
 *
 * The live "refresh this sector" button sits beside the picker and in the
 * empty card, as on the Streamlit page (`Rescan.tsx`): it starts a server-side
 * rescan, polls until it lands, then reloads the cohort underneath.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Cohort } from "./Cohort";
import { Podium } from "./Podium";
import { RescanButton, useRescan } from "./Rescan";
import { Verdict } from "./Verdict";
import { useLabels } from "./labels";
import type { SectorCohort, Sectors, SectorSummary } from "./types";
import "./sector.css";

export default function Page() {
  const t = useT();
  const sectors = useApi(() => get<Sectors>("/sectors"), []);
  return (
    <>
      <h1 className="ag-sec-h1">{t("sector.title")}</h1>
      <Loaded query={sectors} skeleton={<Skeleton rows={8} />}>
        {(data) => <Screen sectors={data.sectors} />}
      </Loaded>
    </>
  );
}

/**
 * The picker and what hangs off it.
 *
 * The picker is the whole navigation of this page, so it goes first and stays
 * put: everything below is a function of it, and it survives the cohort
 * reloading underneath. It offers all eleven sectors, including the ones the
 * nightly scan has never reached — "not scanned yet" and "does not exist" are
 * different answers, and the first is the empty card below, not a missing row
 * in the list.
 *
 * The choice rides the query string, so a sector is a link somebody can send.
 */
function Screen({ sectors }: { sectors: SectorSummary[] }) {
  const t = useT();
  const labels = useLabels();
  const { params, setParams } = useRoute();

  const asked = params.get("sector") ?? "";
  const current =
    sectors.find((entry) => entry.sector.toLowerCase() === asked.toLowerCase()) ??
    sectors[0];
  const name = current?.sector ?? "";
  // Bumped when a live rescan lands, so the cohort is asked for again and the
  // server answers from the fresh scan instead of last night's.
  const [fresh, setFresh] = useState(0);
  const cohort = useApi(
    () => get<SectorCohort>(`/sectors/${encodeURIComponent(name)}`),
    [name, fresh],
  );
  const rescan = useRescan(name, labels.sector(name), () => setFresh((n) => n + 1));

  if (!current) return <p className="ag-note">{t("sector.empty_title")}</p>;

  return (
    <>
      <div className="ag-sec-top">
        <label className="ag-sec-pick">
          <span>{t("sector.pick")}</span>
          <select
            value={current.sector}
            onChange={(event) => setParams({ sector: event.target.value })}
          >
            {sectors.map((entry) => (
              <option key={entry.sector} value={entry.sector}>
                {labels.sector(entry.sector)}
              </option>
            ))}
          </select>
        </label>
        {/* Quieter than the picker and beside it: a rare action that costs a
            minute of Yahoo. Left out only when the sector has no scan at all —
            the empty card below carries the same button as its only way out,
            and two copies of one action on one screen is one too many. */}
        {!(cohort.state === "loaded" && cohort.data.rows.length === 0) && (
          <RescanButton rescan={rescan} />
        )}
      </div>
      {rescan.note && <p className="ag-sec-caption ag-sec-status">{rescan.note}</p>}

      <Loaded query={cohort} skeleton={<Skeleton rows={8} />}>
        {(data) =>
          data.as_of === null || data.rows.length === 0 ? (
            // Never scanned. The rescan is the card's only way out, as on the
            // Streamlit page — a guest, who may not start one, gets the
            // explanation alone.
            <div className="ag-sec-card">
              <h2 className="ag-sec-h2">{t("sector.empty_title")}</h2>
              <p className="ag-sec-caption">{t("sector.empty_body")}</p>
              <RescanButton rescan={rescan} />
            </div>
          ) : (
            <>
              <p className="ag-sec-caption">
                {t("sector.as_of", { date: data.as_of })}
              </p>
              <Podium podium={data.podium} rows={data.rows} cohort={data.rows.length} />
              {data.podium.length > 0 && <Verdict sector={data.sector} />}
              <Cohort key={data.sector} data={data} />
            </>
          )
        }
      </Loaded>
    </>
  );
}
