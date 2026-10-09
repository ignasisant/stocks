/**
 * The moves, one card each: the names the engine says to sell, trim or add to.
 *
 * A card is the whole decision on one line of sight — what, why, from which
 * weight to which, how much money, and what it costs in tax or when it can be
 * done. Holding is not a move, so the quiet rows are the table's, not here.
 * The fold at the foot of each card spells out the rules behind it.
 */

import { useLang, useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { DetailsButton, VerdictChip, PnlChip } from "./Explain";
import { ACTIONS, money, percent, score, verdictTone } from "./format";
import type { Review, ReviewRow } from "./types";

export function Actions({ data }: { data: Review }) {
  const t = useT();
  const moves = data.held.filter((row) => ACTIONS.includes(row.verdict));
  return (
    <section className="ag-rev-card">
      <h2 className="ag-rev-h2">{t("review.moves_title")}</h2>
      {moves.length === 0 ? (
        <p className="ag-rev-caption">{t("review.moves_none")}</p>
      ) : (
        <div className="ag-rev-moves">
          {moves.map((row) => (
            <Move
              key={row.ticker}
              row={row}
              base={data.base}
              taxCurrency={data.plan.tax_currency}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function Move({
  row,
  base,
  taxCurrency,
}: {
  row: ReviewRow;
  base: string;
  taxCurrency: string;
}) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  const tone = verdictTone(row.verdict);
  return (
    <article className={`ag-rev-move ag-rev-move-${tone}`}>
      <div className="ag-rev-move-head">
        <TickerCell ticker={row.ticker} className="ag-rev-move-who" />
        <VerdictChip row={row} />
      </div>
      <div className="ag-rev-move-figs">
        <b className={`ag-rev-tone-${tone}`}>
          {money(row.delta, base, lang, true) ?? na}
        </b>
        <span>
          {percent(row.weight, lang) ?? na}
          <i aria-hidden="true">→</i>
          {percent(row.target_weight, lang) ?? na}
        </span>
      </div>
      <p className="ag-rev-move-scores">
        <span>
          {t("review.col_quality")} <b>{score(row.quality) ?? na}</b>
        </span>
        <span>
          {t("review.col_cheapness")} <b>{score(row.cheapness) ?? na}</b>
        </span>
        <span>
          {t("review.col_pnl")} <PnlChip row={row} />
        </span>
      </p>
      <Reasons reasons={row.reasons} />
      {row.tax !== null && row.tax > 0 ? (
        <p className="ag-rev-caption">
          {t("review.move_tax", { amount: money(row.tax, taxCurrency, lang) ?? na })}
        </p>
      ) : row.verdict !== "add" && row.tax !== null ? (
        <p className="ag-rev-caption">{t("review.move_no_tax")}</p>
      ) : null}
      {row.buy_after ? (
        <p className="ag-rev-caption">
          {t("review.buy_after", { date: row.buy_after })}
        </p>
      ) : null}
      <DetailsButton row={row} />
    </article>
  );
}

/** The engine's reason codes, as the reader's words. */
export function Reasons({ reasons, limit = 4 }: { reasons: string[]; limit?: number }) {
  const t = useT();
  if (reasons.length === 0) return null;
  return (
    <ul className="ag-rev-reasons">
      {reasons.slice(0, limit).map((code) => (
        <li key={code} title={t(`review.reason_${code}_help`)}>
          {t(`review.reason_${code}`)}
        </li>
      ))}
    </ul>
  );
}
