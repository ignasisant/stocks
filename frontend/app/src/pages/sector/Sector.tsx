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
 * The live "refresh this sector" button sits on the line that says how old the
 * scan is, and in the empty card (`Rescan.tsx`): it starts a server-side
 * rescan, polls until it lands, then reloads the cohort underneath.
 */

import { useEffect, useState } from "react";
import { forgetUnder, get } from "../../shell/api";
import { calendarDay } from "../../shell/dates";
import { Loaded, Refreshable, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useCurrency, useGuest } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import { Cohort } from "./Cohort";
import { useLabels } from "./labels";
import { type Lens, Podium } from "./Podium";
import { SectorRail } from "./Rail";
import { ageDays, sectorWeight, STALE_DAYS } from "./rank";
import { type Rescan, RescanButton, useRescan } from "./Rescan";
import { type Held, SectorMap } from "./SectorMap";
import { TopThree } from "./TopThree";
import type { BookSectors, SectorCohort, Sectors, SectorSummary } from "./types";
import { Verdict } from "./Verdict";
import { YouHere } from "./YouHere";
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
 * different answers, and the first is the empty card below, not a missing
 * chip in the rail.
 *
 * The sector and the podium's lens ride the query string, so either is a link
 * somebody can send.
 */
function Screen({ sectors }: { sectors: SectorSummary[] }) {
  const t = useT();
  const labels = useLabels();
  const guest = useGuest();
  const base = useCurrency();
  const { params, setParams } = useRoute();

  const asked = params.get("sector") ?? "";
  const current =
    sectors.find((entry) => entry.sector.toLowerCase() === asked.toLowerCase()) ??
    sectors[0];
  const name = current?.sector ?? "";
  const lens: Lens = params.get("lens") === "tech" ? "tech" : "fund";
  // Bumped when a live rescan lands, so the cohort is asked for again and the
  // server answers from the fresh scan instead of last night's.
  const [fresh, setFresh] = useState(0);
  // A sector picked keeps the last one's cards up, dimmed, until its own land.
  const cohort = useApi(
    () => get<SectorCohort>(`/sectors/${encodeURIComponent(name)}`),
    [name, fresh],
    { keep: true },
  );
  const rescan = useRescan(name, labels.sector(name), () => {
    forgetUnder(["/sectors"]);
    setFresh((n) => n + 1);
  });

  // The reader's holdings, once for the podium, the "you" card and the table.
  const book = useApi(() => get<{ positions: Held[] }>("/portfolio/positions"), []);
  const positions = book.state === "loaded" ? book.data.positions : [];
  const held = new Map<string, number | null>(
    positions.map((p) => [p.ticker.toUpperCase(), p.weight]),
  );
  // The weight per sector only decorates the rail, so it is asked for once the
  // cohort has answered and never holds anything up. A guest's book is the
  // shared demo ledger, whose weights would read as theirs: not asked.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (cohort.state !== "loading") setSettled(true);
  }, [cohort.state]);
  const weights = useApi(
    () =>
      !settled || guest
        ? Promise.resolve<BookSectors | null>(null)
        : get<BookSectors>("/pulse/book", { base }).catch(() => null),
    [settled, guest, base],
  );
  const sectorWeights =
    weights.state === "loaded" && weights.data && !weights.data.unavailable
      ? weights.data.sector_weights
      : null;

  if (!current) return <p className="ag-note">{t("sector.empty_title")}</p>;

  return (
    <>
      <SectorRail
        sectors={sectors}
        current={current.sector}
        onPick={(sector) => setParams({ sector })}
        weights={sectorWeights}
      />
      {/* Always mounted, so a screen reader hears the rescan start and end:
          a live region that arrives with its text is announced by none. */}
      <p className="ag-sec-caption ag-sec-status" role="status">
        {rescan.note}
      </p>

      <Loaded query={cohort} skeleton={<Skeleton rows={8} />}>
        {(data) =>
          data.as_of === null || data.rows.length === 0 ? (
            // Never scanned. The rescan is the card's only way out — a guest,
            // who may not start one, gets the explanation alone.
            <div className="ag-sec-card">
              <h2 className="ag-sec-h2">{t("sector.empty_title")}</h2>
              <p className="ag-sec-caption">{t("sector.empty_body")}</p>
              <RescanButton rescan={rescan} />
              <Progress rescan={rescan} />
            </div>
          ) : (
            <Refreshable>
              <Freshness asOf={data.as_of} rescan={rescan} />
              <Podium
                data={data}
                lens={lens}
                onLens={(next) =>
                  setParams({ lens: next === "tech" ? "tech" : undefined })
                }
                held={new Set(held.keys())}
              />
              {!guest && (
                <YouHere
                  rows={data.rows}
                  held={held}
                  sectorWeight={sectorWeight(sectorWeights, data.sector)}
                />
              )}
              {data.podium.length > 0 && (
                <Verdict sector={data.sector}>
                  {data.podium.length > 1 ? <TopThree data={data} /> : null}
                </Verdict>
              )}
              <SectorMap
                key={`map-${data.sector}`}
                rows={data.rows}
                positions={book.state === "loading" ? null : positions}
              />
              <Cohort key={data.sector} data={data} held={new Set(held.keys())} />
            </Refreshable>
          )
        }
      </Loaded>
    </>
  );
}

/**
 * How old the cohort is, with the rescan beside it. Quiet while the scan is
 * this week's; a banner once it is older than `STALE_DAYS`, because a ranking
 * on last month's prices reads exactly like one on last night's.
 */
function Freshness({ asOf, rescan }: { asOf: string; rescan: Rescan }) {
  const t = useT();
  const age = ageDays(asOf, new Date());
  const stale = age !== null && age > STALE_DAYS;
  return (
    <div className={stale ? "ag-sec-fresh ag-sec-stale" : "ag-sec-fresh"}>
      <p className={stale ? "ag-sec-fresh-text" : "ag-sec-caption ag-sec-fresh-text"}>
        {stale
          ? t("sector.stale", { date: calendarDay(asOf), n: age })
          : t("sector.as_of", { date: calendarDay(asOf) })}
      </p>
      <RescanButton rescan={rescan} />
      <Progress rescan={rescan} />
    </div>
  );
}

/**
 * A rescan under way. The status the server sends has no progress in it, so
 * the bar says "working" rather than drawing a percentage it would invent.
 */
function Progress({ rescan }: { rescan: Rescan }) {
  if (!rescan.running) return null;
  return <span className="ag-sec-progress" aria-hidden="true" />;
}
