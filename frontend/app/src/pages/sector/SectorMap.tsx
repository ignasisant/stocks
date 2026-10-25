/**
 * The cohort on the Review page's quality against price map.
 *
 * The podium ranks the cohort against itself: a percentile over a basket of
 * KPIs, so somebody always wins, however dear the sector is. The map answers
 * the other question, against fixed bars: the server judges every row the way
 * the Review page judges a name from outside the book (`judged`), so a company
 * sits on the same spot here and there, and the podium's winner can land in
 * the dear half without either being wrong.
 *
 * It is the Review page's own `QualityMap`, not a copy. What it needs from
 * that page's providers it does without: no focus provider (nothing below
 * links to its dots), no returns provider (no trails — they need each name's
 * filings, and this page reads tonight's scan and nothing else).
 *
 * Held names are joined here from the one positions request the cohort table
 * makes too, so they are filled and sized by weight as on Review. Their colour
 * is still the read as a new buy: a held name's own verdict hangs on its
 * weight, which is Review's to draw, and the caption and its details say so.
 */

import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { MAX_ADDED } from "../review/format";
import { QualityMap } from "../review/QualityMap";
import type { ReviewRow } from "../review/types";
import "../review/review.css";
import type { CohortRow } from "./types";

type Held = {
  ticker: string;
  currency: string;
  value: number | null;
  price: number | null;
  weight: number | null;
  pnl: number | null;
  pnl_pct: number | null;
};

/** A cohort row as the map's row type, with the reader's position if any. */
export function asReviewRow(row: CohortRow, held: Held | undefined): ReviewRow | null {
  const judged = row.judged;
  if (!judged) return null;
  return {
    ticker: row.ticker,
    symbol: row.ticker,
    kind: "stock",
    sector: null,
    country: null,
    currency: row.currency ?? held?.currency ?? null,
    held: held !== undefined,
    verdict: judged.verdict,
    reasons: judged.reasons,
    quality: judged.quality,
    cheapness: judged.cheapness,
    metrics: judged.metrics,
    value: held?.value ?? null,
    price: held?.price ?? null,
    weight: held?.weight ?? null,
    risk_share: null,
    pnl: held?.pnl ?? null,
    pnl_pct: held?.pnl_pct ?? null,
    target_weight: null,
    delta: null,
    new_money: null,
    tax: null,
    buy_after: null,
    watched: false,
    favorite: false,
    lists: [],
  };
}

export function SectorMap({ rows }: { rows: CohortRow[] }) {
  const t = useT();
  const book = useApi(() => get<{ positions: Held[] }>("/portfolio/positions"), []);
  const owned = new Map(
    book.state === "loaded"
      ? book.data.positions.map((p) => [p.ticker.toUpperCase(), p] as const)
      : [],
  );
  const judged = rows.flatMap((row) => {
    const one = asReviewRow(row, owned.get(row.ticker.toUpperCase()));
    return one ? [one] : [];
  });
  // An older server judged nothing: no map rather than an empty plane.
  if (judged.length === 0) return null;
  const held = judged.filter((row) => row.held);
  const outside = judged.filter((row) => !row.held);
  // The buys the reader does not own yet, best first: the next step is to
  // weigh them against the book, which is what Review's `?add=` does.
  const buys = outside
    .filter((row) => row.verdict === "buy")
    .sort(
      (a, b) =>
        (b.quality ?? 0) + (b.cheapness ?? 0) - ((a.quality ?? 0) + (a.cheapness ?? 0)),
    )
    .slice(0, MAX_ADDED)
    .map((row) => row.ticker);

  return (
    <QualityMap
      held={held}
      candidates={outside}
      help={t("sector.map_help")}
      outsideLegend={t("sector.map_outside")}
      ruleOf={(row) => (row.held ? t("sector.map_held_rule") : undefined)}
      footer={
        // Not before the book has answered: until then a name the reader
        // owns would be offered as a buy.
        book.state !== "loading" && buys.length > 0 ? (
          <p className="ag-sec-caption ag-sec-map-next">
            <Link page="review" params={{ add: buys.join(",") }}>
              {t("sector.map_to_review", { count: buys.length })}
            </Link>
          </p>
        ) : null
      }
    />
  );
}
