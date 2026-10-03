/**
 * `portfolio_overview`: the book's worth, its result, where the money sits.
 *
 * Three parts, as the Portfolio page opens: the headline figures, a ring of
 * the largest weights, and the holdings largest first. Unpriced rows stay in
 * the table at their cost, labelled, and the note under it says how many —
 * a total that quietly drops part of the book is a lie in smaller print.
 */

import { chipFor, Kpi, KpiGrid, toneOf } from "../ui/Kpi";
import { money, percent } from "./format";
import { TickerLabel } from "./TickerLabel";
import type { Overview as Data, Position, Words } from "./types";

/** Slices the ring draws before the rest becomes one "Other". */
const SLICES = 6;

// `view.css` sets these per theme: the dark tokens, or their deep cousins
// on a light ground, where the pale ones would not show.
const PALETTE = ["--v-c1", "--v-c2", "--v-c3", "--v-c4", "--v-c5", "--v-c6"].map(
  (name) => `var(${name})`,
);

export type Slice = { label: string; weight: number; color: string };

/** The ring's slices: the largest weights, then everything else as one. */
export function slices(positions: Position[], other: string): Slice[] {
  const weighted = positions.filter((p) => (p.weight ?? 0) > 0);
  const top = weighted.slice(0, SLICES).map((p, i) => ({
    label: p.ticker,
    weight: p.weight ?? 0,
    color: PALETTE[i % PALETTE.length] ?? "var(--v-muted)",
  }));
  const shown = top.reduce((sum, s) => sum + s.weight, 0);
  // The rest of the book, including what the payload did not carry: the
  // weights are of the whole book, so whatever they do not reach is "Other".
  const rest = 1 - shown;
  if (rest > 0.005) top.push({ label: other, weight: rest, color: "var(--v-faint)" });
  return top;
}

function Ring({ parts }: { parts: Slice[] }) {
  const radius = 15.915; // circumference 100: a weight is its dash length
  let offset = 25; // start at twelve o'clock
  return (
    <svg className="v-ring" viewBox="0 0 42 42" aria-hidden="true">
      <circle
        cx="21"
        cy="21"
        r={radius}
        fill="none"
        strokeWidth="6"
        style={{ stroke: "var(--v-track)" }}
      />
      {parts.map((part) => {
        const length = Math.max(0, part.weight * 100);
        const arc = (
          <circle
            key={part.label}
            cx="21"
            cy="21"
            r={radius}
            fill="none"
            strokeWidth="6"
            strokeDasharray={`${length} ${100 - length}`}
            strokeDashoffset={offset}
            style={{ stroke: part.color }}
          />
        );
        offset -= length;
        return arc;
      })}
    </svg>
  );
}

export function Overview({ data, words }: { data: Data; words: Words }) {
  const { t, locale } = words;
  const s = data.summary;
  const base = s.base;
  if (data.positions_total === 0) {
    return <p className="v-empty">{t("connector.view_empty")}</p>;
  }
  const parts = slices(data.positions, t("connector.view_other"));

  return (
    <>
      <KpiGrid>
        <Kpi label={t("connector.view_value")} value={money(s.value, base, locale)} />
        <Kpi
          label={t("connector.view_pnl")}
          value={money(s.pnl, base, locale)}
          valueTone={toneOf(s.pnl)}
          chip={chipFor(s.pnl_pct, percent(s.pnl_pct, locale))}
        />
        {s.realized !== null && (
          <Kpi
            label={t("connector.view_realized")}
            value={money(s.realized, base, locale)}
            valueTone={toneOf(s.realized)}
          />
        )}
        <Kpi label={t("connector.view_positions")} value={data.positions_total} />
      </KpiGrid>

      <div className="v-split">
        <figure className="v-ringbox">
          <Ring parts={parts} />
          <ul className="v-legend">
            {parts.map((part) => (
              <li key={part.label}>
                <i style={{ background: part.color }} />
                <span>{part.label}</span>
                <b>{percent(part.weight, locale, false)}</b>
              </li>
            ))}
          </ul>
        </figure>

        <table className="v-table">
          <thead>
            <tr>
              <th>{t("connector.view_ticker")}</th>
              <th className="num">{t("connector.view_value")}</th>
              <th className="num">{t("connector.view_weight")}</th>
              <th className="num">{t("connector.view_return")}</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((p) => (
              <tr key={p.ticker}>
                <td>
                  <TickerLabel ticker={p.ticker} logo={p.logo} words={words} />
                </td>
                <td className="num">
                  {p.value === null ? (
                    <span className="v-muted">{t("connector.view_no_price")}</span>
                  ) : (
                    money(p.value, base, locale)
                  )}
                </td>
                <td className="num">{percent(p.weight, locale, false)}</td>
                <td className={`num ag-tone-${toneOf(p.pnl_pct)}`}>
                  {percent(p.pnl_pct, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.unpriced > 0 && (
        <p className="v-note">
          {t("connector.view_unpriced_note", { n: data.unpriced })}
        </p>
      )}
      {data.positions_total > data.positions.length && (
        <p className="v-note">
          {t("connector.view_more", {
            shown: data.positions.length,
            total: data.positions_total,
          })}
        </p>
      )}
    </>
  );
}
