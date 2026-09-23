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
 * One thing the Streamlit page has is deliberately absent: the live "rescan"
 * button. It is a write that costs a minute of Yahoo and has no route, and a
 * button that cannot do the thing is worse than no button.
 */

import { get } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Cohort } from "./Cohort";
import { Podium } from "./Podium";
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
  const cohort = useApi(
    () => get<SectorCohort>(`/sectors/${encodeURIComponent(name)}`),
    [name],
  );

  if (!current) return <p className="ag-note">{t("sector.empty_title")}</p>;

  return (
    <>
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

      <Loaded query={cohort} skeleton={<Skeleton rows={8} />}>
        {(data) =>
          data.as_of === null || data.rows.length === 0 ? (
            // Never scanned. The Streamlit card offers a rescan from here; that
            // is the write this API does not have, so the card says what is
            // missing and stops.
            <div className="ag-sec-card">
              <h2 className="ag-sec-h2">{t("sector.empty_title")}</h2>
              <p className="ag-sec-caption">{t("sector.empty_body")}</p>
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
