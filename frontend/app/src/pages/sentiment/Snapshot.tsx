/**
 * Readings that only exist as a trend: none of them has a level worth printing.
 *
 * The block's rule is its own subtitle — *a level with no history is no
 * reading*. So a card appears only when the comparison behind it exists, and a
 * figure whose history the API did not send gets no card at all rather than a
 * bare number that looks like one.
 *
 * Three of the four come off `/pulse`, which computes them beside the
 * composite: how broad the uptrend is over the indices and over the sectors,
 * and whether bonds are still cushioning equities. They are **market-wide**,
 * which is the whole reason they are not read off the book card — that one
 * carries this basket's correlation with the long bond, a different pair
 * answering a different question. The fourth, the rates quadrant, is a name
 * for the sign pair of two moves the rates block already publishes; see
 * `logic.ts`.
 *
 * Each card stands or falls on its own. A price burst that failed costs the
 * two breadth counts and leaves the quadrant, because the rates block came
 * from FRED and does not know Yahoo was down.
 */

import type { ReactNode } from "react";

import { useT } from "../../shell/i18n";
import { DownBody, YAHOO } from "./Down";
import { signed } from "./format";
import { quadrant } from "./logic";
import type { Pulse, TrendTables } from "./types";

/** One reading: what it is, what it says, and what that means. */
function Card({
  label,
  value,
  note,
  children,
}: {
  label: string;
  value: string;
  note: string;
  children?: ReactNode;
}) {
  return (
    <div className="sn-tcard sn-tcard-col">
      <span className="sn-tcard-head">
        <span className="sn-tcard-l">{label}</span>
        <span className="sn-tcard-w">{value}</span>
      </span>
      {children}
      <span className="sn-tcard-n">{note}</span>
    </div>
  );
}

export function Snapshot({
  pulse,
  tables,
  onRetry,
}: {
  pulse: Pulse;
  tables: TrendTables;
  onRetry?: () => void;
}) {
  const t = useT();
  const rates = tables.blocks.find((block) => block.block === "rates") ?? null;
  const quad = quadrant(rates);
  const cards: ReactNode[] = [];

  // Trend breadth, twice over. Not today's advance-decline — how many markets
  // are in an uptrend at all. An index at a high with a third of its sectors
  // below trend is a narrowing market, and the index level cannot say so.
  //
  // The window each count used rides in the payload rather than being written
  // here: the indices are measured against a long average and the sectors
  // against a shorter one, and a note naming the wrong one is worse than no
  // note.
  // Both keys are written out rather than built from the pair's name: a
  // composed key is invisible to `test_frontend_i18n_keys`, which is what
  // stands between a renamed string and a dotted slug on a Spanish reader's
  // screen.
  const breadths: [string, string, typeof pulse.breadth_indices][] = [
    [
      "sentiment.breadth_indices",
      "sentiment.breadth_indices_note",
      pulse.breadth_indices,
    ],
    [
      "sentiment.breadth_sectors",
      "sentiment.breadth_sectors_note",
      pulse.breadth_sectors,
    ],
  ];
  for (const [label, note, breadth] of breadths) {
    if (!breadth) continue;
    cards.push(
      <Card
        key={label}
        label={t(label)}
        value={`${breadth.hits}/${breadth.total}`}
        note={t(note, { n: breadth.window })}
      />,
    );
  }

  // Stock/bond correlation: the level IS the story. Negative means bonds
  // cushion an equity drawdown; positive means both legs fall together and the
  // diversification a reader thinks they have is not there.
  if (pulse.stock_bond_correlation !== null) {
    const then = pulse.stock_bond_correlation_then;
    cards.push(
      <Card
        key="corr"
        label={t("sentiment.stock_bond_corr")}
        value={signed(pulse.stock_bond_correlation, 2)}
        note={
          (then === null
            ? ""
            : `${t("sentiment.drift_note", { value: then.toFixed(2) })} · `) +
          t("sentiment.stock_bond_corr_note")
        }
      />,
    );
  }

  if (quad !== null) {
    cards.push(
      <Card
        key="quad"
        label={t("sentiment.rates_regime")}
        value={t(`sentiment.quad_${quad.key}`)}
        note={t(`sentiment.quad_meaning_${quad.key}`)}
      >
        {/* The two moves the label is made of, in the units the rates block
            quotes them in — so the reader can check the name against the
            numbers rather than take it. */}
        <span className="sn-mono">
          {t("sentiment.quad_note", {
            yields: signed(quad.yields, 0, "bp"),
            slope: signed(quad.slope, 0, "bp"),
          })}
        </span>
      </Card>,
    );
  }

  return (
    <>
      <div className="sn-sec-head">
        <h3 className="sn-sec-t" id="ag-snapshot">
          {t("sentiment.snapshot_title")}
        </h3>
        <span className="sn-mono">{t("sentiment.snapshot_hint")}</span>
        <span className="sn-spacer" />
        {/* Every figure on this page names where it came from, and these are
            the only kind that have no source of their own: they are read off
            the numbers above them rather than fetched. */}
        <span className="sn-mono">{t("sentiment.src_derived")}</span>
      </div>

      {cards.length === 0 ? (
        // The block keeps its heading when it has nothing to show. An absent
        // block reads as "nothing is happening here", which is a different and
        // wrong claim from "the series this needs did not arrive". Which feed
        // to blame: Yahoo when the composite's call said so, FRED when only
        // the rates block is down.
        pulse.unavailable ? (
          <DownBody reason={pulse.unavailable} onRetry={onRetry} />
        ) : (
          <DownBody
            reason={rates?.unavailable ?? "no_data"}
            family="macro"
            origin="FRED"
            onRetry={onRetry}
          />
        )
      ) : (
        <>
          <div className="sn-tcards">{cards}</div>
          {/* The quadrant came from FRED and survived; the breadth counts and
              the correlation ride on the Yahoo burst and did not. */}
          {pulse.unavailable && (
            <DownBody reason={pulse.unavailable} origin={YAHOO} onRetry={onRetry} />
          )}
        </>
      )}
    </>
  );
}
