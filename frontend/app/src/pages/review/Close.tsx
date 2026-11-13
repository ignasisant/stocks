/**
 * The names a few points from a move: what would change the plan next.
 *
 * The server marks them (`close_call`) but holds them still, so a score that
 * wobbles over a line and back does not flip a verdict every morning. Here
 * each says which move it is near and how far: the score with furthest to go,
 * drawn on its 0–100 scale with the line it has to cross. A name whose scores
 * do not say which line keeps its place without a distance (`closeCall`).
 */

import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import { DetailsButton } from "./Explain";
import { score } from "./format";
import type { ReviewRow } from "./types";
import { type CloseCall, closeCalls } from "./verdicts";

export function CloseCalls({
  rows,
  taxCurrency,
}: {
  rows: ReviewRow[];
  taxCurrency: string;
}) {
  const t = useT();
  const calls = closeCalls(rows);
  if (calls.length === 0) return null;
  return (
    <section className="ag-rev-card ag-rev-close" aria-labelledby="ag-rev-close-h">
      <h2 className="ag-rev-h2" id="ag-rev-close-h">
        {t("review.close_title")}
      </h2>
      <p className="ag-rev-caption">{t("review.close_help")}</p>
      <ul className="ag-rev-close-list">
        {calls.map((call) => (
          <Call key={call.row.ticker} call={call} taxCurrency={taxCurrency} />
        ))}
      </ul>
    </section>
  );
}

function Call({ call, taxCurrency }: { call: CloseCall; taxCurrency: string }) {
  const t = useT();
  const { row, side, points, axis, line } = call;
  const value = axis ? row[axis] : null;
  return (
    <li className="ag-rev-close-row ag-row-reach">
      <div className="ag-rev-close-who">
        <TickerCell ticker={row.ticker} />
      </div>
      <p className="ag-rev-close-say">
        <b
          className={
            side ? `ag-rev-tone-${side === "sell" ? "down" : "up"}` : undefined
          }
        >
          {side && points !== null
            ? t(`review.close_${side}`, { points })
            : t("review.close_near")}
        </b>
        {axis && value !== null && line !== null ? (
          <span className="ag-rev-caption">
            {t(`review.close_axis_${axis}`, { score: score(value) ?? "", line })}
          </span>
        ) : null}
      </p>
      {axis && value !== null && line !== null && side ? (
        <Gauge value={value} line={line} side={side} />
      ) : (
        <span aria-hidden="true" />
      )}
      <span className="ag-rev-close-more">
        <DetailsButton
          row={row}
          variant="icon"
          taxCurrency={row.held ? taxCurrency : undefined}
        />
      </span>
    </li>
  );
}

/**
 * A score on 0–100 with the line it is near: the dot is the score, the tick
 * the line, and the stretch between them the way still to go, in the tone of
 * the move at its end. Read out by the sentence beside it.
 */
function Gauge({
  value,
  line,
  side,
}: {
  value: number;
  line: number;
  side: "sell" | "add" | "buy";
}) {
  const at = Math.min(100, Math.max(0, value));
  const from = Math.min(at, line);
  const to = Math.max(at, line);
  return (
    <span className="ag-rev-close-gauge" aria-hidden="true">
      <span
        className={`ag-rev-close-way ag-rev-close-${side === "sell" ? "down" : "up"}`}
        style={{ left: `${from}%`, width: `${to - from}%` }}
      />
      <span className="ag-rev-close-line" style={{ left: `${line}%` }} />
      <span className="ag-rev-close-dot" style={{ left: `${at}%` }} />
    </span>
  );
}
